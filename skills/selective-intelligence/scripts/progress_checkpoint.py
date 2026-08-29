#!/usr/bin/env python3
"""Create durable, non-blocking progress checkpoints for Selective Intelligence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "si.progress-checkpoint.v1"
PROTECTED_BRANCHES = {"main", "master", "trunk", "prod", "production", "release"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)


class ProgressCheckpointError(RuntimeError):
    """Raised when a checkpoint cannot be saved safely."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ProgressCheckpointError(f"{' '.join(args)} failed: {detail}")
    return completed


def _git_root(root: Path) -> Path | None:
    completed = _run(root, "git", "rev-parse", "--show-toplevel", check=False)
    if completed.returncode != 0:
        return None
    return Path(completed.stdout.strip()).resolve()


def _git_value(root: Path, *args: str) -> str | None:
    completed = _run(root, "git", *args, check=False)
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _bounded_text(value: str, label: str, maximum: int = 2000) -> str:
    value = value.strip()
    if not value:
        raise ProgressCheckpointError(f"{label} cannot be empty")
    if len(value) > maximum:
        raise ProgressCheckpointError(f"{label} exceeds {maximum} characters")
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise ProgressCheckpointError(f"{label} contains secret-like content")
    return value


def _bounded_list(values: list[str] | None, label: str) -> list[str]:
    return [_bounded_text(value, label) for value in (values or [])]


def _safe_paths(repo_root: Path, values: list[str] | None) -> list[str]:
    safe: list[str] = []
    for raw in values or []:
        relative = Path(raw)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ProgressCheckpointError(f"unsafe checkpoint path: {raw}")
        if relative.parts[0] == ".git":
            raise ProgressCheckpointError("checkpoint paths cannot include .git")
        candidate = (repo_root / relative).resolve(strict=False)
        if candidate != repo_root and repo_root not in candidate.parents:
            raise ProgressCheckpointError(f"checkpoint path escapes repository: {raw}")
        normalized = relative.as_posix()
        if normalized not in safe:
            safe.append(normalized)
    return safe


def _sha256(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _git_status(root: Path, selected_paths: list[str] | None = None) -> list[str]:
    args = ["git", "status", "--porcelain=v1", "--untracked-files=normal"]
    if selected_paths:
        args.extend(["--", *selected_paths])
    return _run(root, *args).stdout.splitlines()


def _private_progress_root(project_root: Path) -> Path:
    git_path = _git_value(project_root, "rev-parse", "--git-path", "selective-intelligence/progress")
    if not git_path:
        raise ProgressCheckpointError("could not resolve the repository-private checkpoint path")
    resolved = Path(git_path)
    if not resolved.is_absolute():
        resolved = project_root / resolved
    return resolved.resolve(strict=False)


def save_checkpoint(
    *,
    root: Path,
    outcome: str,
    next_safe_action: str,
    completed: list[str] | None = None,
    changed_unverified: list[str] | None = None,
    proof: list[str] | None = None,
    external_effects: list[str] | None = None,
    do_not_repeat: list[str] | None = None,
    scope: list[str] | None = None,
    prohibitions: list[str] | None = None,
    paths: list[str] | None = None,
    commit: bool = False,
    push: bool = False,
    remote: str = "origin",
    commit_message: str | None = None,
    protected_branch_authorized: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise ProgressCheckpointError(f"project root does not exist: {root}")
    if push and not commit:
        raise ProgressCheckpointError("--push requires --commit")

    repo_root = _git_root(root)
    if (commit or push) and repo_root is None:
        raise ProgressCheckpointError("Git commit or push requested outside a repository")
    project_root = repo_root or root
    selected_paths = _safe_paths(project_root, paths)

    branch = _git_value(project_root, "rev-parse", "--abbrev-ref", "HEAD") if repo_root else None
    if branch == "HEAD":
        branch = None
    if commit and not branch:
        raise ProgressCheckpointError("cannot checkpoint-commit from a detached HEAD")
    if commit and branch in PROTECTED_BRANCHES and not protected_branch_authorized:
        raise ProgressCheckpointError(
            f"refusing routine checkpoint on protected branch {branch!r}; use a task branch"
        )

    checkpoint_id = f"progress-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    tracked_relative = Path(".selective-intelligence") / "progress" / "latest.json"
    tracked_path = project_root / tracked_relative
    private_root = _private_progress_root(project_root) if repo_root else project_root / ".selective-intelligence" / "progress"

    head_before = _git_value(project_root, "rev-parse", "HEAD") if repo_root else None
    full_status = _git_status(project_root) if repo_root else []
    selected_status = _git_status(project_root, selected_paths) if repo_root and selected_paths else []
    unrelated_change_count = max(0, len(full_status) - len(selected_status))
    file_records = [
        {"path": relative, "sha256": _sha256(project_root / relative)}
        for relative in selected_paths
    ]

    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "checkpointId": checkpoint_id,
        "createdAt": _now(),
        "outcome": _bounded_text(outcome, "outcome"),
        "scope": _bounded_list(scope, "scope"),
        "prohibitions": _bounded_list(prohibitions, "prohibition"),
        "progress": {
            "completedVerified": _bounded_list(completed, "completed item"),
            "changedUnverified": _bounded_list(changed_unverified, "unverified item"),
            "proof": _bounded_list(proof, "proof item"),
            "externalEffects": _bounded_list(external_effects, "external effect"),
            "doNotRepeat": _bounded_list(do_not_repeat, "do-not-repeat item"),
            "nextSafeAction": _bounded_text(next_safe_action, "next safe action"),
        },
        "repository": {
            "root": ".",
            "rootKind": "repository_relative" if repo_root else "project_relative",
            "branch": branch,
            "headBefore": head_before,
            "checkpointCommit": "containing_commit" if commit else None,
            "pushRequested": push,
            "pushRemote": remote if push else None,
            "protectedBranchAuthorized": protected_branch_authorized,
            "selectedStatusBefore": selected_status,
            "unrelatedChangeCountExcluded": unrelated_change_count,
        },
        "savedFiles": file_records,
        "privacyBoundary": (
            "bounded summaries and selected file identities only; absolute project paths, "
            "unrelated file names, raw prompts, and secrets are excluded"
        ),
    }

    if repo_root and commit:
        artifact_path = tracked_path
        artifact_locator = tracked_relative.as_posix()
        _write_json(tracked_path, record)
    else:
        artifact_path = private_root / "checkpoints" / f"{checkpoint_id}.json"
        artifact_locator = str(artifact_path)
        _write_json(artifact_path, record)
        _write_json(private_root / "latest.json", record)

    commit_sha: str | None = None
    pushed = False
    push_error: str | None = None
    if commit:
        checkpoint_paths = selected_paths + [tracked_relative.as_posix()]
        _run(project_root, "git", "add", "--", *checkpoint_paths)
        staged = _run(project_root, "git", "diff", "--cached", "--quiet", check=False)
        if staged.returncode not in {0, 1}:
            raise ProgressCheckpointError("could not inspect staged checkpoint changes")
        if staged.returncode == 1:
            message = commit_message or "checkpoint: preserve authorized work"
            _run(project_root, "git", "commit", "-m", message)
        commit_sha = _git_value(project_root, "rev-parse", "HEAD")
        if push:
            pushed_result = _run(
                project_root,
                "git",
                "push",
                "--set-upstream",
                remote,
                f"HEAD:refs/heads/{branch}",
                check=False,
            )
            pushed = pushed_result.returncode == 0
            if not pushed:
                push_error = (pushed_result.stderr or pushed_result.stdout).strip() or "push failed"

    operation = {
        "schemaVersion": "si.progress-checkpoint-operation.v1",
        "checkpointId": checkpoint_id,
        "observedAt": _now(),
        "artifact": artifact_locator,
        "repository": str(project_root),
        "branch": branch,
        "commitSha": commit_sha,
        "committed": bool(commit_sha) if commit else False,
        "pushRequested": push,
        "pushed": pushed,
        "pushRemote": remote if push else None,
        "pushError": push_error,
        "unrelatedChangesPreserved": True,
        "unrelatedChangeCountExcluded": unrelated_change_count,
    }
    _write_json(private_root / "last-operation.json", operation)
    if push and not pushed:
        raise ProgressCheckpointError(
            f"checkpoint committed locally at {commit_sha}, but push failed: {push_error}"
        )
    return operation


def checkpoint_status(root: Path) -> dict[str, Any]:
    root = root.resolve()
    repo_root = _git_root(root)
    project_root = repo_root or root
    tracked_latest = project_root / ".selective-intelligence" / "progress" / "latest.json"
    if tracked_latest.is_file():
        latest = tracked_latest
    elif repo_root:
        latest = _private_progress_root(project_root) / "latest.json"
    else:
        latest = project_root / ".selective-intelligence" / "progress" / "latest.json"
    record = json.loads(latest.read_text(encoding="utf-8")) if latest.is_file() else None
    return {
        "schemaVersion": "si.progress-checkpoint-status.v1",
        "projectRoot": str(project_root),
        "latestCheckpoint": record,
        "currentBranch": _git_value(project_root, "rev-parse", "--abbrev-ref", "HEAD") if repo_root else None,
        "currentHead": _git_value(project_root, "rev-parse", "HEAD") if repo_root else None,
        "workingTree": _git_status(project_root) if repo_root else [],
    }


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="si-progress-test-") as temporary:
        root = Path(temporary)
        _run(root, "git", "init", "-b", "task/checkpoint-test")
        _run(root, "git", "config", "user.name", "SI Test")
        _run(root, "git", "config", "user.email", "si@example.invalid")
        (root / "owned.txt").write_text("before\n", encoding="utf-8")
        (root / "unrelated.txt").write_text("keep\n", encoding="utf-8")
        _run(root, "git", "add", "owned.txt", "unrelated.txt")
        _run(root, "git", "commit", "-m", "baseline")
        (root / "owned.txt").write_text("after\n", encoding="utf-8")
        (root / "unrelated.txt").write_text("uncommitted unrelated\n", encoding="utf-8")
        result = save_checkpoint(
            root=root,
            outcome="Preserve one owned slice",
            completed=["Owned file updated"],
            next_safe_action="Verify the owned change",
            paths=["owned.txt"],
            commit=True,
        )
        status = _git_status(root)
        if status != [" M unrelated.txt"]:
            raise ProgressCheckpointError(f"self-test left unexpected working changes: {status}")
        artifact_path = root / result["artifact"]
        if not artifact_path.is_file():
            raise ProgressCheckpointError("self-test checkpoint artifact is missing")
        record = json.loads(artifact_path.read_text(encoding="utf-8"))
        serialized = json.dumps(record, ensure_ascii=False)
        if record.get("repository", {}).get("root") != ".":
            raise ProgressCheckpointError("self-test checkpoint leaked the absolute repository root")
        if "unrelated.txt" in serialized:
            raise ProgressCheckpointError("self-test checkpoint leaked an unrelated file name")
        if record.get("repository", {}).get("unrelatedChangeCountExcluded", 0) < 1:
            raise ProgressCheckpointError("self-test did not record excluded unrelated work")
        tracked = _run(root, "git", "ls-files", ".selective-intelligence/progress").stdout.splitlines()
        if tracked != [".selective-intelligence/progress/latest.json"]:
            raise ProgressCheckpointError(f"self-test created checkpoint file sprawl: {tracked}")
        return {"status": "pass", "checkpoint": result, "workingTree": status, "tracked": tracked}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create durable Selective Intelligence progress checkpoints")
    subparsers = parser.add_subparsers(dest="command", required=True)

    save = subparsers.add_parser("save")
    save.add_argument("--root", default=".")
    save.add_argument("--outcome", required=True)
    save.add_argument("--next", dest="next_safe_action", required=True)
    save.add_argument("--completed", action="append")
    save.add_argument("--changed-unverified", action="append")
    save.add_argument("--proof", action="append")
    save.add_argument("--external-effect", action="append")
    save.add_argument("--do-not-repeat", action="append")
    save.add_argument("--scope", action="append")
    save.add_argument("--prohibition", action="append")
    save.add_argument("--path", action="append")
    save.add_argument("--commit", action="store_true")
    save.add_argument("--push", action="store_true")
    save.add_argument("--remote", default="origin")
    save.add_argument("--commit-message")
    save.add_argument("--protected-branch-authorized", action="store_true")

    status = subparsers.add_parser("status")
    status.add_argument("--root", default=".")

    subparsers.add_parser("self-test")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "save":
            result = save_checkpoint(
                root=Path(args.root),
                outcome=args.outcome,
                next_safe_action=args.next_safe_action,
                completed=args.completed,
                changed_unverified=args.changed_unverified,
                proof=args.proof,
                external_effects=args.external_effect,
                do_not_repeat=args.do_not_repeat,
                scope=args.scope,
                prohibitions=args.prohibition,
                paths=args.path,
                commit=args.commit,
                push=args.push,
                remote=args.remote,
                commit_message=args.commit_message,
                protected_branch_authorized=args.protected_branch_authorized,
            )
        elif args.command == "status":
            result = checkpoint_status(Path(args.root))
        else:
            result = self_test()
    except (ProgressCheckpointError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
