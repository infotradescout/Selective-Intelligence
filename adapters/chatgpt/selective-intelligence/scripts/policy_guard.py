#!/usr/bin/env python3
"""Pre-adapter authorization and evidence capture for SI tool execution."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


class PolicyDenied(PermissionError):
    def __init__(self, decision: dict[str, Any]):
        super().__init__(decision["reason"])
        self.decision = decision


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _resolved(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


_MUTATING_GIT = {
    "add", "am", "apply", "branch", "checkout", "cherry-pick", "clean", "commit",
    "fetch", "merge", "mv", "pull", "push", "rebase", "reset", "restore", "revert",
    "rm", "stash", "switch", "tag", "worktree",
}
_INSTALLERS = {
    ("npm", "install"), ("npm", "i"), ("pnpm", "install"), ("pnpm", "add"),
    ("yarn", "add"), ("yarn", "install"), ("pip", "install"), ("pip3", "install"),
    ("poetry", "add"), ("uv", "add"), ("cargo", "install"),
}
_DEPLOY_WORDS = {"deploy", "publish", "release"}
_WINDOWS_EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".com", ".ps1")
_TRANSPARENT_WRAPPERS = {"env", "command", "nice", "nohup", "timeout", "stdbuf", "sudo", "doas"}
_READ_ONLY_GIT = {
    "describe", "diff", "grep", "log", "ls-files", "ls-tree", "rev-parse",
    "shortlog", "show", "status", "version",
}
_ENV_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)


def _command_basename(token: str) -> str:
    """Return a platform-normalized command basename without Windows suffixes."""
    name = str(token).strip()
    while len(name) >= 2 and name[0] == name[-1] and name[0] in {"'", '"'}:
        name = name[1:-1].strip()
    name = re.split(r"[/\\]", name)[-1].lower()
    stripped = True
    while stripped:
        stripped = False
        for suffix in _WINDOWS_EXECUTABLE_SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                stripped = True
                break
    return name


def _redact_argv(argv: Sequence[str]) -> list[str]:
    redacted: list[str] = []
    for value in argv:
        token = str(value)
        unquoted = token
        while len(unquoted) >= 2 and unquoted[0] == unquoted[-1] and unquoted[0] in {"'", '"'}:
            unquoted = unquoted[1:-1]
        match = _ENV_ASSIGNMENT.fullmatch(unquoted)
        redacted.append(f"{match.group(1)}=<redacted>" if match else token)
    return redacted


def _skip_wrapper_prefix(base: str, argv: list[str]) -> tuple[list[str] | None, str | None]:
    """Remove one wrapper, returning an ambiguity reason on malformed input."""
    if not argv or _command_basename(argv[0]) != base:
        return None, "wrapper executable did not match resolver state"
    rest = argv[1:]

    if base == "env":
        index = 0
        while index < len(rest):
            token = rest[index]
            if token == "--":
                return rest[index + 1 :], None
            if (
                token in {"-S", "--split-string"}
                or token.startswith("-S")
                or token.startswith("--split-string=")
            ):
                return None, "env -S command splitting is ambiguous"
            if token in {"-i", "--ignore-environment", "-0", "--null", "-v", "--debug"}:
                index += 1
                continue
            if token in {"-C", "--chdir", "-P"} or token.startswith("--chdir="):
                return None, f"env option {token.split('=', 1)[0]} changes command resolution context"
            if token in {"-u", "--unset"}:
                if index + 1 >= len(rest):
                    return None, f"env option {token} is missing its value"
                index += 2
                continue
            if token.startswith("--unset="):
                if token.endswith("="):
                    return None, f"env option {token.split('=', 1)[0]} is missing its value"
                index += 1
                continue
            if token.startswith("-"):
                return None, f"unsupported env option: {token}"
            if _ENV_ASSIGNMENT.fullmatch(token):
                index += 1
                continue
            return rest[index:], None
        return [], None

    if base == "command":
        index = 0
        while index < len(rest):
            token = rest[index]
            if token in {"-p", "-v", "-V"}:
                index += 1
                continue
            if token == "--":
                return rest[index + 1 :], None
            if token.startswith("-"):
                return None, f"unsupported command option: {token}"
            return rest[index:], None
        return [], None

    if base == "nice":
        index = 0
        if index < len(rest) and rest[index] in {"-n", "--adjustment"}:
            if index + 1 >= len(rest):
                return None, f"nice option {rest[index]} is missing its value"
            if not re.fullmatch(r"-?\d+", rest[index + 1]):
                return None, f"nice option {rest[index]} has an invalid value"
            index += 2
        elif index < len(rest) and rest[index].startswith("--adjustment="):
            if not re.fullmatch(r"-?\d+", rest[index].split("=", 1)[1]):
                return None, "nice option --adjustment has an invalid value"
            index += 1
        elif index < len(rest) and re.fullmatch(r"-?\d+", rest[index] or ""):
            index += 1
        elif index < len(rest) and rest[index].startswith("-"):
            return None, f"unsupported nice option: {rest[index]}"
        return rest[index:], None

    if base == "nohup":
        if rest[:1] == ["--"]:
            rest = rest[1:]
        elif rest[:1] and rest[0].startswith("-"):
            return None, f"unsupported nohup option: {rest[0]}"
        return rest, None

    if base == "timeout":
        index = 0
        while index < len(rest):
            token = rest[index]
            if token in {"-s", "--signal", "-k", "--kill-after"}:
                if index + 1 >= len(rest):
                    return None, f"timeout option {token} is missing its value"
                index += 2
                continue
            if any(token.startswith(prefix) for prefix in ("--signal=", "--kill-after=")):
                if token.endswith("="):
                    return None, f"timeout option {token.split('=', 1)[0]} is missing its value"
                index += 1
                continue
            if token in {"--preserve-status", "--foreground", "-v", "--verbose"}:
                index += 1
                continue
            if token == "--":
                index += 1
                break
            if token.startswith("-"):
                return None, f"unsupported timeout option: {token}"
            break
        if index >= len(rest):
            return None, "timeout is missing its duration"
        if not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)[smhd]?", rest[index], re.IGNORECASE):
            return None, f"timeout has an invalid duration: {rest[index]}"
        if index + 1 >= len(rest):
            return [], None
        return rest[index + 1 :], None

    if base == "stdbuf":
        index = 0
        while index < len(rest):
            token = rest[index]
            if token in {"-i", "-o", "-e", "--input", "--output", "--error"}:
                if index + 1 >= len(rest):
                    return None, f"stdbuf option {token} is missing its value"
                index += 2
                continue
            if re.fullmatch(r"-[ioe].+", token) or any(
                token.startswith(prefix) and not token.endswith("=")
                for prefix in ("--input=", "--output=", "--error=")
            ):
                index += 1
                continue
            if token == "--":
                return rest[index + 1 :], None
            if token.startswith("-"):
                return None, f"unsupported stdbuf option: {token}"
            return rest[index:], None
        return [], None

    if base in {"sudo", "doas"}:
        index = 0
        value_options = {
            "-u", "-g", "-h", "-C", "-p", "-b",
            "--user", "--group", "--host", "--prompt",
        }
        context_options = {"-D", "-R", "--chdir", "--chroot"}
        flag_options = {
            "-A", "-E", "-H", "-K", "-S", "-V", "-n", "-k", "-l", "-s",
            "--askpass", "--preserve-env", "--set-home", "--stdin", "--non-interactive",
        }
        while index < len(rest):
            token = rest[index]
            if token == "--":
                return rest[index + 1 :], None
            if token in context_options or any(
                token.startswith(option + "=") for option in context_options if option.startswith("--")
            ):
                return None, f"{base} option {token.split('=', 1)[0]} changes execution context"
            if token in value_options:
                if index + 1 >= len(rest):
                    return None, f"{base} option {token} is missing its value"
                index += 2
                continue
            if any(token.startswith(option + "=") for option in value_options if option.startswith("--")):
                if token.endswith("="):
                    return None, f"{base} option {token.split('=', 1)[0]} is missing its value"
                index += 1
                continue
            if token in flag_options:
                index += 1
                continue
            if token.startswith("-"):
                return None, f"unsupported {base} option: {token}"
            return rest[index:], None
        return [], None

    return None, f"unsupported wrapper: {base}"


def _resolve_command_argv(argv: Sequence[str] | str) -> dict[str, Any]:
    """Resolve structured argv without invoking a shell.

    This resolver is intentionally lexical. It narrows execution to commands
    the policy can identify, but it is not an OS sandbox and cannot prove that
    an allowed test suite has no filesystem side effects.
    """
    if isinstance(argv, str):
        original = [argv]
        return {
            "originalArgv": original,
            "redactedOriginalArgv": _redact_argv(original),
            "effectiveArgv": [],
            "normalizedExecutable": "",
            "wrapperChain": [],
            "status": "ambiguous",
            "reason": "shell-form string action argv is not allowed",
        }
    if not isinstance(argv, Sequence) or isinstance(argv, (bytes, bytearray)):
        original = []
        return {
            "originalArgv": original,
            "redactedOriginalArgv": original,
            "effectiveArgv": [],
            "normalizedExecutable": "",
            "wrapperChain": [],
            "status": "ambiguous",
            "reason": "action argv is not a sequence",
        }
    if any(not isinstance(token, str) for token in argv):
        original = [str(token) for token in argv]
        return {
            "originalArgv": original,
            "redactedOriginalArgv": _redact_argv(original),
            "effectiveArgv": [],
            "normalizedExecutable": "",
            "wrapperChain": [],
            "status": "ambiguous",
            "reason": "action argv contains a non-string token",
        }
    original = list(argv)

    current = list(original)
    wrappers: list[str] = []
    for _ in range(32):
        if not current:
            return {
                "originalArgv": original,
                "redactedOriginalArgv": _redact_argv(original),
                "effectiveArgv": [],
                "normalizedExecutable": "",
                "wrapperChain": wrappers,
                "status": "no_command",
                "reason": "no effective command remains after wrapper resolution",
            }
        base = _command_basename(current[0])
        if not base:
            return {
                "originalArgv": original,
                "redactedOriginalArgv": _redact_argv(original),
                "effectiveArgv": [],
                "normalizedExecutable": "",
                "wrapperChain": wrappers,
                "status": "no_command",
                "reason": "effective command has an empty executable",
            }
        if base not in _TRANSPARENT_WRAPPERS:
            return {
                "originalArgv": original,
                "redactedOriginalArgv": _redact_argv(original),
                "effectiveArgv": _redact_argv(current),
                "normalizedExecutable": base,
                "wrapperChain": wrappers,
                "status": "resolved",
                "reason": "effective executable resolved from structured argv",
            }
        wrappers.append(base)
        unwrapped, error = _skip_wrapper_prefix(base, current)
        if error is not None or unwrapped is None:
            return {
                "originalArgv": original,
                "redactedOriginalArgv": _redact_argv(original),
                "effectiveArgv": [],
                "normalizedExecutable": "",
                "wrapperChain": wrappers,
                "status": "ambiguous",
                "reason": error or "wrapper resolution failed",
            }
        current = list(unwrapped)
    return {
        "originalArgv": original,
        "redactedOriginalArgv": _redact_argv(original),
        "effectiveArgv": _redact_argv(current),
        "normalizedExecutable": _command_basename(current[0]) if current else "",
        "wrapperChain": wrappers,
        "status": "ambiguous",
        "reason": "transparent wrapper depth limit reached",
    }


def _git_subcommand(argv: list[str]) -> str | None:
    """Return the Git subcommand after global options such as ``-C``/``-c``."""
    index = 1
    options_with_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
    while index < len(argv):
        token = argv[index]
        if token in options_with_value:
            index += 2
            continue
        if any(token.startswith(prefix + "=") for prefix in options_with_value if prefix.startswith("--")):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token.lower()
    return None


def _install_requested(base: str, argv: list[str]) -> bool:
    tokens = [token.lower() for token in argv[1:]]
    if base in {"npm", "pnpm", "yarn", "pip", "pip3", "poetry", "uv", "cargo"}:
        return any(token in {"install", "add", "i"} for token in tokens)
    if base in {"python", "python3", "py"} or base.startswith("python"):
        try:
            module_index = tokens.index("-m")
        except ValueError:
            return False
        return (
            module_index + 1 < len(tokens)
            and tokens[module_index + 1] in {"pip", "pip3"}
            and any(token == "install" for token in tokens[module_index + 2 :])
        )
    return False


def _inline_execution_violation(base: str, argv: list[str]) -> str | None:
    """Reject arbitrary inline programs without inspecting or approving payload text."""
    lowered = [token.lower() for token in argv]
    if base in {"sh", "bash", "zsh", "fish"} and any(
        token == "-c" or (token.startswith("-c") and len(token) > 2) for token in lowered
    ):
        return "arbitrary shell inline execution prohibited"
    if base == "cmd" and any(token == "/c" or token.startswith("/c:") for token in lowered):
        return "arbitrary cmd inline execution prohibited"
    if base in {"powershell", "pwsh"} and any(
        token in {"-command", "-c"} or token.startswith("-command:")
        for token in lowered
    ):
        return "arbitrary PowerShell inline execution prohibited"
    if _is_python(base) and any(
        token == "-c" or (token.startswith("-c") and len(token) > 2) for token in lowered
    ):
        return "arbitrary Python inline execution prohibited"
    if base in {"node", "nodejs"} and any(
        token in {"-e", "--eval"}
        or (token.startswith("-e") and not token.startswith("--"))
        or token.startswith("--eval=")
        for token in lowered
    ):
        return "arbitrary Node inline execution prohibited"
    return None


def _is_python(base: str) -> bool:
    return base in {"python", "python3", "py"} or bool(re.fullmatch(r"python\d+(?:\.\d+)*", base))


def _structured_command_allowed(base: str, argv: list[str]) -> tuple[bool, str]:
    """Allow only the smallest structured read/verification surface in use."""
    lowered = [token.lower() for token in argv]
    if base == "git":
        subcommand = _git_subcommand(argv)
        unsafe_git_options = {
            "-c", "-C", "--config-env", "--exec-path", "--git-dir", "--namespace",
            "--output", "--work-tree", "--ext-diff", "--textconv",
        }
        if any(
            token in unsafe_git_options
            or any(token.startswith(option + "=") for option in unsafe_git_options if option.startswith("--"))
            or token.startswith("--open-files-in-pager")
            for token in argv[1:]
        ):
            return False, "Git option may change context, write output, or invoke an external helper"
        if subcommand in _READ_ONLY_GIT or lowered[1:] in (["--version"], ["-v"]):
            return True, "read-only Git command"
        return False, "Git command is not on the read-only allowlist"
    if _is_python(base):
        if lowered[1:] in (["--version"], ["-v"]):
            return True, "Python version query"
        if len(lowered) >= 3 and lowered[1:3] == ["-m", "unittest"]:
            return True, "structured Python unittest verification"
        return False, "Python command is not on the structured verification allowlist"
    if base in {"node", "nodejs"} and lowered[1:] in (["--version"], ["-v"]):
        return True, "Node version query"
    return False, "executable is not on the structured command allowlist"


class PolicyGuard:
    """Authorizes an action before an adapter is called.

    ``canonical_roots`` are protected. Writes are allowed only inside
    ``writable_roots``. Command execution can occur in a writable root, but
    explicit constraints still deny Git mutation, installs, deploys, or other
    configured operations.
    """

    def __init__(
        self,
        *,
        canonical_roots: Sequence[str | os.PathLike[str]],
        writable_roots: Sequence[str | os.PathLike[str]],
        prohibit_git_mutation: bool = True,
        prohibit_dependency_install: bool = True,
        prohibit_deploy: bool = True,
    ) -> None:
        self.canonical_roots = tuple(_resolved(p) for p in canonical_roots)
        self.writable_roots = tuple(_resolved(p) for p in writable_roots)
        self.prohibit_git_mutation = prohibit_git_mutation
        self.prohibit_dependency_install = prohibit_dependency_install
        self.prohibit_deploy = prohibit_deploy

    def _decision(
        self,
        *,
        session_id: str,
        task_id: str,
        action: dict[str, Any],
        allowed: bool,
        reason: str,
        constraint: str,
        resolution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = {
            "decisionId": _id("policy"),
            "timestamp": _now(),
            "sessionId": session_id,
            "taskId": task_id,
            "requestedOperation": action,
            "relevantConstraint": constraint,
            "matchedConstraint": constraint,
            "decision": "ALLOW" if allowed else "DENY",
            "allowed": allowed,
            "reason": reason,
            "adapterInvocationStatus": "PENDING" if allowed else "NOT_INVOKED",
        }
        if resolution is not None:
            decision.update(
                {
                    "effectiveArgv": resolution["effectiveArgv"],
                    "normalizedExecutable": resolution["normalizedExecutable"],
                    "wrapperChain": resolution["wrapperChain"],
                    "resolutionStatus": resolution["status"],
                    "resolutionReason": resolution["reason"],
                }
            )
        return decision

    def authorize(
        self,
        *,
        session_id: str,
        task_id: str,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        kind = str(action.get("kind", ""))

        if kind == "filesystem.write":
            target = _resolved(str(action.get("path", "")))
            for root in self.canonical_roots:
                if _inside(target, root):
                    return self._decision(
                        session_id=session_id,
                        task_id=task_id,
                        action=action,
                        allowed=False,
                        reason=f"canonical repository write prohibited: {target}",
                        constraint="no canonical repository modifications",
                    )
            if not any(_inside(target, root) for root in self.writable_roots):
                return self._decision(
                    session_id=session_id,
                    task_id=task_id,
                    action=action,
                    allowed=False,
                    reason=f"write target is outside authorized roots: {target}",
                    constraint="writes restricted to declared disposable scope",
                )
            return self._decision(
                session_id=session_id,
                task_id=task_id,
                action=action,
                allowed=True,
                reason="write is within authorized disposable scope",
                constraint="writes restricted to declared disposable scope",
            )

        if kind == "process.run":
            raw_argv = action.get("argv")
            resolution = _resolve_command_argv(raw_argv if raw_argv is not None else [])
            safe_action = dict(action)
            safe_action["argv"] = resolution["redactedOriginalArgv"]
            cwd = _resolved(str(action.get("cwd") or os.getcwd()))
            safe_action["cwd"] = str(cwd)
            effective_argv = list(resolution["effectiveArgv"])
            base = str(resolution["normalizedExecutable"])
            lowered = [v.lower() for v in effective_argv]

            if resolution["status"] != "resolved":
                return self._decision(
                    session_id=session_id,
                    task_id=task_id,
                    action=safe_action,
                    allowed=False,
                    reason=f"command resolution failed closed: {resolution['reason']}",
                    constraint="only unambiguous structured command argv may execute",
                    resolution=resolution,
                )

            # Never execute commands from inside a protected repo in this vertical.
            if any(_inside(cwd, root) for root in self.canonical_roots):
                return self._decision(
                    session_id=session_id,
                    task_id=task_id,
                    action=safe_action,
                    allowed=False,
                    reason=f"process working directory is a protected canonical repository: {cwd}",
                    constraint="no state-changing actions in canonical repositories",
                    resolution=resolution,
                )

            git_subcommand = _git_subcommand(effective_argv) if base == "git" else None
            if self.prohibit_git_mutation and git_subcommand in _MUTATING_GIT:
                return self._decision(
                    session_id=session_id,
                    task_id=task_id,
                    action=safe_action,
                    allowed=False,
                    reason=f"Git mutation prohibited: git {git_subcommand}",
                    constraint="no commit, push, branch, reset, clean, stash, or other Git mutation",
                    resolution=resolution,
                )

            if self.prohibit_dependency_install and _install_requested(base, effective_argv):
                return self._decision(
                    session_id=session_id,
                    task_id=task_id,
                    action=safe_action,
                    allowed=False,
                    reason="dependency installation prohibited",
                    constraint="no dependency installation",
                    resolution=resolution,
                )

            inline_violation = _inline_execution_violation(base, effective_argv)
            if inline_violation and (
                self.prohibit_git_mutation
                or self.prohibit_dependency_install
                or self.prohibit_deploy
            ):
                return self._decision(
                    session_id=session_id,
                    task_id=task_id,
                    action=safe_action,
                    allowed=False,
                    reason=inline_violation,
                    constraint="arbitrary inline execution is denied while prohibitions are active",
                    resolution=resolution,
                )

            if self.prohibit_deploy and (
                any(word in _DEPLOY_WORDS for word in lowered[1:])
                or (base in {"vercel", "wrangler", "render", "netlify", "firebase", "fly"} and len(lowered) > 1)
            ):
                return self._decision(
                    session_id=session_id,
                    task_id=task_id,
                    action=safe_action,
                    allowed=False,
                    reason="deployment or publishing prohibited",
                    constraint="no deploy or publish",
                    resolution=resolution,
                )

            if not any(_inside(cwd, root) or cwd == root for root in self.writable_roots):
                return self._decision(
                    session_id=session_id,
                    task_id=task_id,
                    action=safe_action,
                    allowed=False,
                    reason=f"process cwd outside authorized disposable scope: {cwd}",
                    constraint="process execution restricted to declared disposable scope",
                    resolution=resolution,
                )

            command_allowed, command_reason = _structured_command_allowed(base, effective_argv)
            if not command_allowed:
                return self._decision(
                    session_id=session_id,
                    task_id=task_id,
                    action=safe_action,
                    allowed=False,
                    reason=command_reason,
                    constraint="commands restricted to explicit read-only and verification allowlist",
                    resolution=resolution,
                )

            return self._decision(
                session_id=session_id,
                task_id=task_id,
                action=safe_action,
                allowed=True,
                reason=command_reason,
                constraint="commands restricted to explicit read-only and verification allowlist",
                resolution=resolution,
            )

        return self._decision(
            session_id=session_id,
            task_id=task_id,
            action=action,
            allowed=False,
            reason=f"unknown operation kind: {kind or '<empty>'}",
            constraint="deny unknown operations",
        )


def guarded_write_text(
    path: str | os.PathLike[str],
    content: str,
    *,
    guard: PolicyGuard,
    session_id: str,
    task_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = _resolved(path)
    decision = guard.authorize(
        session_id=session_id,
        task_id=task_id,
        action={"kind": "filesystem.write", "path": str(target)},
    )
    if not decision["allowed"]:
        raise PolicyDenied(decision)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    decision["adapterInvocationStatus"] = "INVOKED"
    evidence = {
        "evidenceId": _id("write"),
        "timestamp": _now(),
        "sessionId": session_id,
        "taskId": task_id,
        "path": str(target),
        "bytes": len(content.encode("utf-8")),
        "sha256": _digest(content),
        "result": "written",
    }
    return decision, evidence


def guarded_run(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    guard: PolicyGuard,
    session_id: str,
    task_id: str,
    timeout: int = 120,
) -> tuple[dict[str, Any], dict[str, Any]]:
    command = [str(v) for v in argv]
    workdir = _resolved(cwd)
    decision = guard.authorize(
        session_id=session_id,
        task_id=task_id,
        action={"kind": "process.run", "argv": command, "cwd": str(workdir)},
    )
    if not decision["allowed"]:
        raise PolicyDenied(decision)
    started = _now()
    proc = subprocess.run(
        command,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    ended = _now()
    decision["adapterInvocationStatus"] = "INVOKED"
    evidence = {
        "evidenceId": _id("command"),
        "sessionId": session_id,
        "taskId": task_id,
        "argv": _redact_argv(command),
        "effectiveArgv": decision["effectiveArgv"],
        "normalizedExecutable": decision["normalizedExecutable"],
        "wrapperChain": decision["wrapperChain"],
        "resolutionStatus": decision["resolutionStatus"],
        "matchedConstraint": decision["matchedConstraint"],
        "adapterInvocationStatus": decision["adapterInvocationStatus"],
        "cwd": str(workdir),
        "startedAt": started,
        "endedAt": ended,
        "exitCode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "stdoutSha256": _digest(proc.stdout),
        "stderrSha256": _digest(proc.stderr),
    }
    return decision, evidence
