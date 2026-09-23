#!/usr/bin/env python3
"""Preserve work and bound evidence use for Selective Intelligence."""

from __future__ import annotations

import argparse
import copy
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

PROGRESS_SCHEMA = "si.progress-checkpoint.v1"
USAGE_SCHEMA = "si.usage-governor.v1"
PROTECTED_BRANCHES = {"main", "master", "trunk", "prod", "production", "release"}
MAX_BATCH_FILES = 12
MAX_BATCH_BYTES = 65_536
MAX_BATCHES_BEFORE_DECISION = 3
MAX_USAGE_EVENTS = 20
HANDOFF_USAGE_SCHEMA = "si.worker-handoff-usage.v1"
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)


class ProgressCheckpointError(RuntimeError):
    """Raised when preservation or usage control cannot proceed safely."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args), cwd=root, capture_output=True, text=True, check=False
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ProgressCheckpointError(f"{' '.join(args)} failed: {detail}")
    return completed


def _git_root(root: Path) -> Path | None:
    completed = _run(root, "git", "rev-parse", "--show-toplevel", check=False)
    return Path(completed.stdout.strip()).resolve() if completed.returncode == 0 else None


def _git_value(root: Path, *args: str) -> str | None:
    completed = _run(root, "git", *args, check=False)
    value = completed.stdout.strip() if completed.returncode == 0 else ""
    return value or None


def _private_root(project_root: Path, leaf: str) -> Path:
    git_path = _git_value(
        project_root, "rev-parse", "--git-path", f"selective-intelligence/{leaf}"
    )
    if git_path:
        candidate = Path(git_path)
        return (
            candidate if candidate.is_absolute() else project_root / candidate
        ).resolve(strict=False)
    return project_root / ".selective-intelligence" / leaf


def _bounded_text(value: str, label: str, maximum: int = 2000) -> str:
    value = " ".join(value.split())
    if not value:
        raise ProgressCheckpointError(f"{label} cannot be empty")
    if len(value) > maximum:
        raise ProgressCheckpointError(f"{label} exceeds {maximum} characters")
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        raise ProgressCheckpointError(f"{label} contains secret-like content")
    return value


def _bounded_list(values: list[str] | None, label: str) -> list[str]:
    return [_bounded_text(value, label) for value in (values or [])]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".si-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path, schema: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProgressCheckpointError(f"state is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != schema:
        raise ProgressCheckpointError("state has an unsupported schema")
    return payload


def _git_status(root: Path, paths: list[str] | None = None) -> list[str]:
    args = ["git", "--literal-pathspecs", "status", "--porcelain=v1", "--untracked-files=normal"]
    if paths:
        args.extend(["--", *paths])
    return _run(root, *args).stdout.splitlines()


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
        if candidate.is_dir():
            raise ProgressCheckpointError("checkpoint paths must name individual task-owned files")
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


def _protected_branch(branch: str | None) -> bool:
    if not branch:
        return False
    lower = branch.casefold()
    return lower in PROTECTED_BRANCHES or any(
        lower.startswith(prefix) for prefix in ("release/", "prod/", "production/")
    )


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
    if not root.is_dir():
        raise ProgressCheckpointError(f"project root does not exist: {root}")
    if push and not commit:
        raise ProgressCheckpointError("--push requires --commit")

    repo_root = _git_root(root)
    if (commit or push) and repo_root is None:
        raise ProgressCheckpointError("Git commit or push requested outside a repository")
    project_root = repo_root or root
    selected_paths = _safe_paths(project_root, paths)
    branch = (
        _git_value(project_root, "rev-parse", "--abbrev-ref", "HEAD")
        if repo_root
        else None
    )
    if branch == "HEAD":
        branch = None
    if commit and not branch:
        raise ProgressCheckpointError("cannot checkpoint-commit from detached HEAD")
    if commit and _protected_branch(branch) and not protected_branch_authorized:
        raise ProgressCheckpointError(
            f"refusing routine checkpoint on protected branch {branch!r}; use a task branch"
        )

    checkpoint_id = (
        f"progress-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    )
    tracked_relative = Path(".selective-intelligence/progress/latest.json")
    tracked_path = project_root / tracked_relative
    _safe_paths(project_root, [tracked_relative.as_posix()])
    private_root = _private_root(project_root, "progress")
    full_status = _git_status(project_root) if repo_root else []
    selected_status = (
        _git_status(project_root, selected_paths)
        if repo_root and selected_paths
        else []
    )
    record = {
        "schemaVersion": PROGRESS_SCHEMA,
        "checkpointId": checkpoint_id,
        "createdAt": _now(),
        "outcome": _bounded_text(outcome, "outcome"),
        "scope": _bounded_list(scope, "scope"),
        "prohibitions": _bounded_list(prohibitions, "prohibition"),
        "progress": {
            "completedVerified": _bounded_list(completed, "completed item"),
            "changedUnverified": _bounded_list(
                changed_unverified, "unverified item"
            ),
            "proof": _bounded_list(proof, "proof item"),
            "externalEffects": _bounded_list(
                external_effects, "external effect"
            ),
            "doNotRepeat": _bounded_list(do_not_repeat, "do-not-repeat item"),
            "nextSafeAction": _bounded_text(
                next_safe_action, "next safe action"
            ),
        },
        "repository": {
            "root": ".",
            "rootKind": "repository_relative" if repo_root else "project_relative",
            "branch": branch,
            "headBefore": (
                _git_value(project_root, "rev-parse", "HEAD") if repo_root else None
            ),
            "checkpointCommit": "containing_commit" if commit else None,
            "pushRequested": push,
            "pushRemote": remote if push else None,
            "protectedBranchAuthorized": protected_branch_authorized,
            "selectedStatusBefore": selected_status,
            "unrelatedChangeCountExcluded": max(
                0, len(full_status) - len(selected_status)
            ),
        },
        "savedFiles": [
            {"path": relative, "sha256": _sha256(project_root / relative)}
            for relative in selected_paths
        ],
        "privacyBoundary": (
            "bounded summaries and selected file identities only; absolute paths, "
            "unrelated file names, raw prompts, and secrets are excluded"
        ),
    }

    if repo_root and commit:
        artifact_path = tracked_path
        artifact_locator = tracked_relative.as_posix()
        _write_json(artifact_path, record)
    else:
        artifact_path = (
            private_root / "checkpoints" / f"{checkpoint_id}.json"
        )
        artifact_locator = str(artifact_path)
        _write_json(artifact_path, record)
        _write_json(private_root / "latest.json", record)

    commit_sha: str | None = None
    pushed = False
    push_accepted = False
    remote_head: str | None = None
    push_error: str | None = None
    if commit:
        if selected_paths:
            _run(project_root, "git", "--literal-pathspecs", "add", "--", *selected_paths)
        # The project may ignore local SI state. Only the bounded recovery
        # record is deliberately tracked; never force-add selected user files.
        _run(project_root, "git", "--literal-pathspecs", "add", "--force", "--", tracked_relative.as_posix())
        staged = _run(
            project_root, "git", "--literal-pathspecs", "diff", "--cached", "--quiet",
            "--", *selected_paths, tracked_relative.as_posix(), check=False
        )
        if staged.returncode not in {0, 1}:
            raise ProgressCheckpointError(
                "could not inspect staged checkpoint changes"
            )
        if staged.returncode == 1:
            _run(
                project_root,
                "git",
                "--literal-pathspecs",
                "commit",
                "--only",
                "-m",
                commit_message or "checkpoint: preserve authorized work",
                "--",
                *selected_paths,
                tracked_relative.as_posix(),
            )
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
            push_accepted = pushed_result.returncode == 0
            if push_accepted:
                verified = _run(
                    project_root, "git", "ls-remote", "--exit-code", "--refs",
                    remote, f"refs/heads/{branch}", check=False,
                )
                if verified.returncode == 0:
                    heads = [line.split()[0] for line in verified.stdout.splitlines()
                             if len(line.split()) == 2 and line.split()[1] == f"refs/heads/{branch}"]
                    remote_head = heads[0] if len(heads) == 1 else None
                pushed = remote_head == commit_sha
                if not pushed:
                    push_error = "push was accepted, but the remote checkpoint revision could not be verified; inspect remote state before retrying"
            else:
                push_error = (
                    pushed_result.stderr or pushed_result.stdout
                ).strip() or "push failed"

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
        "pushAccepted": push_accepted,
        "pushed": pushed,
        "remoteVerified": pushed,
        "remoteHead": remote_head,
        "pushRemote": remote if push else None,
        "pushError": push_error,
        "unrelatedChangesPreserved": True,
        "unrelatedChangeCountExcluded": record["repository"][
            "unrelatedChangeCountExcluded"
        ],
    }
    _write_json(private_root / "last-operation.json", operation)
    if push and not pushed:
        raise ProgressCheckpointError(
            f"checkpoint committed locally at {commit_sha}, but remote preservation is unverified: {push_error}"
        )
    return operation


def checkpoint_status(root: Path) -> dict[str, Any]:
    root = root.resolve()
    repo_root = _git_root(root)
    project_root = repo_root or root
    tracked = project_root / ".selective-intelligence/progress/latest.json"
    private = _private_root(project_root, "progress") / "latest.json"
    latest = tracked if tracked.is_file() else private
    return {
        "schemaVersion": "si.progress-checkpoint-status.v1",
        "projectRoot": str(project_root),
        "latestCheckpoint": (
            _read_json(latest, PROGRESS_SCHEMA) if latest.is_file() else None
        ),
        "currentBranch": (
            _git_value(project_root, "rev-parse", "--abbrev-ref", "HEAD")
            if repo_root
            else None
        ),
        "currentHead": (
            _git_value(project_root, "rev-parse", "HEAD") if repo_root else None
        ),
        "workingTree": _git_status(project_root) if repo_root else [],
    }


def _resume_git(root: Path, *args: str, allow_not_repo: bool = False) -> str | None:
    """Bound local observations; no fetch, hooks, or changes are requested."""
    try:
        result = subprocess.run(["git", "--no-optional-locks", *args], cwd=root, capture_output=True,
                                text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProgressCheckpointError("Git observation unavailable") from exc
    if result.returncode:
        if allow_not_repo and result.returncode == 128 and "not a git repository" in result.stderr.lower():
            if not any((parent / ".git").exists() for parent in (root, *root.parents)):
                return None
        raise ProgressCheckpointError("Git observation failed")
    if len(result.stdout.encode("utf-8")) > MAX_BATCH_BYTES:
        raise ProgressCheckpointError("Git observation exceeds resume budget")
    return result.stdout.strip()


def _resume_path(path: Path, boundary: Path) -> None:
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise ProgressCheckpointError("resume path escaped its owning store") from exc
    if not path.resolve(strict=False).is_relative_to(boundary.resolve()):
        raise ProgressCheckpointError("resolved state escaped its owning store")
    current = boundary
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ProgressCheckpointError("symlinked resume state is not accepted")

def _resume_record(path: Path, boundary: Path) -> tuple[dict[str, Any], datetime] | None:
    _resume_path(path, boundary)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_BATCH_BYTES // 2:
        raise ProgressCheckpointError("checkpoint is not bounded regular text")
    before = path.stat()
    with path.open("rb") as stream:
        raw = stream.read(MAX_BATCH_BYTES // 2 + 1)
    after = path.stat()
    if len(raw) > MAX_BATCH_BYTES // 2 or (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise ProgressCheckpointError("checkpoint changed during bounded read")
    record = json.loads(raw.decode("utf-8"))
    if not isinstance(record, dict) or record.get("schemaVersion") != PROGRESS_SCHEMA:
        raise ProgressCheckpointError("checkpoint schema is unknown")
    for key in ("checkpointId", "createdAt", "outcome"):
        if not isinstance(record.get(key), str):
            raise ProgressCheckpointError("checkpoint text identity is malformed")
        _bounded_text(record[key], key)
    timestamp = datetime.fromisoformat(record["createdAt"].replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp > datetime.now(UTC):
        raise ProgressCheckpointError("checkpoint timestamp is not an observed UTC instant")
    for key in ("scope", "prohibitions", "savedFiles"):
        if not isinstance(record.get(key), list) or len(record[key]) > 128:
            raise ProgressCheckpointError("checkpoint list is malformed or unbounded")
    if not isinstance(record.get("progress"), dict) or not isinstance(record.get("repository"), dict):
        raise ProgressCheckpointError("checkpoint requires progress and repository identity")
    _bounded_text(record["progress"].get("nextSafeAction", ""), "next safe action")
    if any(pattern.search(raw.decode("utf-8")) for pattern in SECRET_PATTERNS):
        raise ProgressCheckpointError("checkpoint contains secret-like material")
    return record, timestamp

def resume_checkpoint(root: Path) -> dict[str, Any]:
    """Return a current project packet, never permission to execute its contents."""
    packet: dict[str, Any] = {"schemaVersion": "si.project-resume.v1",
        "state": "reconciliation_required", "executionAuthorized": False,
        "releaseAuthorized": False, "nextSafeAction": None, "issues": []}
    try:
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise ProgressCheckpointError("resume requires an existing workspace directory")
        observed_root = _resume_git(root, "rev-parse", "--show-toplevel", allow_not_repo=True)
        project = Path(observed_root).resolve() if observed_root else root
        head = _resume_git(project, "rev-parse", "HEAD") if observed_root else None
        branch = _resume_git(project, "rev-parse", "--abbrev-ref", "HEAD") if observed_root else None
        branch = None if branch == "HEAD" else branch
        git_dir = Path(_resume_git(project, "rev-parse", "--absolute-git-dir")) if observed_root else project
        tracked = project / ".selective-intelligence/progress/latest.json"
        private = git_dir / "selective-intelligence/progress/latest.json" if observed_root else tracked
        packet.update(projectRoot=str(project), currentHead=head, currentBranch=branch)
        candidates = []
        store_observations = []
        for source, path, boundary in (("tracked", tracked, project), ("private", private, git_dir)):
            if source == "private" and private == tracked:
                continue
            loaded = _resume_record(path, boundary)
            observed = path.stat() if path.exists() else None
            signature = (observed.st_mtime_ns, observed.st_size) if observed else None
            store_observations.append((path, boundary, signature))
            if loaded:
                candidates.append((loaded[1], source, path, loaded[0]))
        if not candidates:
            packet["state"] = "no_checkpoint"
            return packet
        candidates.sort(key=lambda item: item[0], reverse=True)
        timestamp, source, path, record = candidates[0]
        if len(candidates) > 1 and candidates[1][0] == timestamp and candidates[1][3] != record:
            raise ProgressCheckpointError("different checkpoints claim the same latest instant")
        repository = record["repository"]
        if repository.get("root") != "." or repository.get("rootKind") != ("repository_relative" if observed_root else "project_relative"):
            raise ProgressCheckpointError("checkpoint owner format does not match this workspace")
        expected = repository.get("headBefore")
        if observed_root and (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{40,64}", expected)):
            raise ProgressCheckpointError("checkpoint has no valid source revision")
        if repository.get("checkpointCommit") == "containing_commit":
            if source != "tracked" or not observed_root:
                raise ProgressCheckpointError("containing-commit identity requires a tracked checkpoint")
            relative = path.relative_to(project).as_posix()
            expected = _resume_git(project, "log", "-1", "--format=%H", "--", relative)
            stored = _resume_git(project, "show", f"{expected}:{relative}")
            if not expected or json.loads(stored) != record:
                raise ProgressCheckpointError("tracked checkpoint differs from its containing commit")
        elif repository.get("checkpointCommit") is not None:
            raise ProgressCheckpointError("unknown checkpoint commit binding")
        issues = []
        if head != expected:
            issues.append("source_revision_changed")
        if branch != repository.get("branch"):
            issues.append("source_branch_changed")
        hash_bytes = 0
        for item in record["savedFiles"]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ProgressCheckpointError("saved-file identity is malformed")
            relative = _safe_paths(project, [item["path"]])[0]
            target = project / relative
            _resume_path(target, project)
            digest = item.get("sha256")
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise ProgressCheckpointError("saved-file hash is invalid")
            hash_bytes += target.stat().st_size if target.exists() else 0
            if hash_bytes > 16 * 1024 * 1024:
                raise ProgressCheckpointError("saved file needs separate bounded verification")
            if _sha256(target) != digest:
                issues.append("saved_file_changed:" + relative)
        for observed_path, boundary, signature in store_observations:
            _resume_path(observed_path, boundary)
            current = observed_path.stat() if observed_path.exists() else None
            if ((current.st_mtime_ns, current.st_size) if current else None) != signature:
                raise ProgressCheckpointError("checkpoint changed during resume")
        if observed_root and _resume_git(project, "rev-parse", "HEAD") != head:
            issues.append("source_changed_during_resume")
        safe_progress = {}
        for key in ("completedVerified", "changedUnverified", "proof", "externalEffects", "doNotRepeat"):
            value = record["progress"].get(key, [])
            if not isinstance(value, list) or len(value) > 128 or any(not isinstance(item, str) for item in value):
                raise ProgressCheckpointError("progress summaries are malformed")
            safe_progress[key] = _bounded_list(value, key)
        packet.update(state="reconciliation_required" if issues else "ready",
            checkpointId=record["checkpointId"], checkpointSource=source,
            outcome=record["outcome"], expectedHead=expected, issues=issues,
            scope=_bounded_list(record["scope"], "scope"),
            prohibitions=_bounded_list(record["prohibitions"], "prohibition"),
            progress=safe_progress,
            nextSafeAction=record["progress"]["nextSafeAction"] if not issues else None)
        if len(json.dumps(packet, ensure_ascii=False).encode("utf-8")) > MAX_BATCH_BYTES:
            raise ProgressCheckpointError("resume packet exceeds the complete output budget")
    except (ProgressCheckpointError, OSError, ValueError, TypeError, AttributeError) as exc:
        packet = {"schemaVersion": "si.project-resume.v1", "state": "reconciliation_required",
            "executionAuthorized": False, "releaseAuthorized": False, "nextSafeAction": None,
            "projectRoot": packet.get("projectRoot"), "issues": [str(exc)[:500]]}
    return packet


def _usage_path(root: Path) -> Path:
    root = root.resolve()
    repo_root = _git_root(root)
    project_root = repo_root or root
    return _private_root(project_root, "usage") / "current.json"


def _usage_status(state: dict[str, Any]) -> dict[str, Any]:
    questions = state.get("questions", {})
    window = state.get("window", {})
    return {
        "schemaVersion": USAGE_SCHEMA,
        "runId": state.get("runId"),
        "outcome": state.get("outcome"),
        "phase": state.get("phase"),
        "batchCount": window.get("batchCount", 0),
        "batchLimit": MAX_BATCHES_BEFORE_DECISION,
        "decisionRequired": window.get("decisionRequired", False),
        "questionCount": len(questions) if isinstance(questions, dict) else 0,
        "lastDecision": state.get("lastDecision"),
        "requiredAction": (
            "act, narrow, checkpoint, or stop before another search or inspection batch"
            if window.get("decisionRequired")
            else None
        ),
    }


def usage_start(root: Path, outcome: str) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ProgressCheckpointError(f"project root does not exist: {root}")
    state = {
        "schemaVersion": USAGE_SCHEMA,
        "runId": f"usage-{uuid.uuid4().hex}",
        "createdAt": _now(),
        "updatedAt": _now(),
        "outcome": _bounded_text(outcome, "outcome", 600),
        "phase": "research",
        "window": {
            "batchCount": 0,
            "decisionRequired": False,
            "limit": MAX_BATCHES_BEFORE_DECISION,
        },
        "questions": {},
        "events": [],
        "lastDecision": None,
    }
    _write_json(_usage_path(root), state)
    return _usage_status(state)


def _usage_load(root: Path) -> dict[str, Any]:
    path = _usage_path(root)
    if not path.is_file():
        raise ProgressCheckpointError(
            "no active usage-governor run; start one first"
        )
    return _read_json(path, USAGE_SCHEMA)


def usage_record(
    root: Path,
    *,
    kind: str,
    question: str,
    owner: str,
    file_count: int,
    byte_count: int,
    impact: str,
    result: str,
) -> dict[str, Any]:
    if kind not in {"search", "inspection"}:
        raise ProgressCheckpointError("kind must be search or inspection")
    if impact not in {"decision", "risk", "proof"}:
        raise ProgressCheckpointError("impact must be decision, risk, or proof")
    if (
        isinstance(file_count, bool)
        or not isinstance(file_count, int)
        or file_count < 0
    ):
        raise ProgressCheckpointError(
            "file_count must be a non-negative integer"
        )
    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count < 0
    ):
        raise ProgressCheckpointError(
            "byte_count must be a non-negative integer"
        )
    if file_count > MAX_BATCH_FILES:
        raise ProgressCheckpointError(
            f"batch has {file_count} files; maximum is {MAX_BATCH_FILES}"
        )
    if byte_count > MAX_BATCH_BYTES:
        raise ProgressCheckpointError(
            f"batch has {byte_count} bytes; maximum is {MAX_BATCH_BYTES}; use targeted ranges"
        )

    state = _usage_load(root)
    if state.get("phase") != "research":
        raise ProgressCheckpointError(
            f"run phase is {state.get('phase')!r}; start a new run before more research"
        )
    window = state.setdefault("window", {})
    if window.get("decisionRequired"):
        raise ProgressCheckpointError(
            "three search or inspection batches are complete; act, narrow, checkpoint, or stop"
        )

    clean_question = _bounded_text(question, "question", 600)
    clean_owner = _bounded_text(owner, "owner", 120)
    clean_result = _bounded_text(result, "result", 600)
    key = hashlib.sha256(
        clean_question.casefold().encode("utf-8")
    ).hexdigest()[:16]
    questions = state.setdefault("questions", {})
    existing = questions.get(key)
    if existing and existing.get("owner") != clean_owner:
        raise ProgressCheckpointError(
            f"question already belongs to {existing.get('owner')!r}; overlapping ownership is blocked"
        )
    question_state = existing or {
        "question": clean_question,
        "owner": clean_owner,
        "batchCount": 0,
    }
    question_state["batchCount"] += 1
    question_state["lastImpact"] = impact
    question_state["lastResult"] = clean_result
    questions[key] = question_state

    event = {
        "recordedAt": _now(),
        "kind": kind,
        "questionKey": key,
        "owner": clean_owner,
        "files": file_count,
        "bytes": byte_count,
        "estimatedTokensUpperBound": (byte_count + 3) // 4,
        "impact": impact,
        "result": clean_result,
    }
    events = state.setdefault("events", [])
    events.append(event)
    state["events"] = events[-MAX_USAGE_EVENTS:]
    window["batchCount"] = int(window.get("batchCount", 0)) + 1
    window["decisionRequired"] = (
        window["batchCount"] >= MAX_BATCHES_BEFORE_DECISION
    )
    state["updatedAt"] = _now()
    _write_json(_usage_path(root), state)
    response = _usage_status(state)
    response["recorded"] = event
    return response


def usage_decide(root: Path, *, action: str, summary: str) -> dict[str, Any]:
    if action not in {"act", "narrow", "checkpoint", "stop"}:
        raise ProgressCheckpointError(
            "action must be act, narrow, checkpoint, or stop"
        )
    state = _usage_load(root)
    state["lastDecision"] = {
        "decidedAt": _now(),
        "action": action,
        "summary": _bounded_text(summary, "decision summary", 600),
        "batchesClosed": state.get("window", {}).get("batchCount", 0),
    }
    if action == "narrow":
        state["phase"] = "research"
        state["window"] = {
            "batchCount": 0,
            "decisionRequired": False,
            "limit": MAX_BATCHES_BEFORE_DECISION,
        }
    else:
        state["phase"] = action
        state["window"]["decisionRequired"] = False
    state["updatedAt"] = _now()
    _write_json(_usage_path(root), state)
    return _usage_status(state)


def usage_status(root: Path) -> dict[str, Any]:
    return _usage_status(_usage_load(root))


def validate_worker_handoff_size(*, file_count: int, byte_count: int) -> None:
    for value, maximum, label in (
        (file_count, MAX_BATCH_FILES, "files"),
        (byte_count, MAX_BATCH_BYTES, "UTF-8 payload bytes"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
            raise ProgressCheckpointError(f"worker handoff exceeds {maximum} {label}; narrow the complete task or context")


def admit_worker_handoff(
    state: dict[str, Any] | None,
    *,
    task_id: str,
    checkpoint_id: str,
    intent_hash: str,
    progress_id: str,
) -> dict[str, Any]:
    """Reserve retrieval using engine-observed progress, before reading context.

    The engine stores the returned ledger in its locked session transaction.
    Failed retrievals consume the window; successful exports are counted by the
    engine after size/coverage checks. This does not govern unrelated tool use.
    """
    for value in (task_id, checkpoint_id, intent_hash, progress_id):
        if not isinstance(value, str) or not value.strip():
            raise ProgressCheckpointError("handoff requires current task, checkpoint, intent and progress identities")
    if state is None:
        state = {"schemaVersion": HANDOFF_USAGE_SCHEMA, "tasks": {}, "totalRetrievals": 0,
                 "totalExports": 0, "totalPayloadBytes": 0}
    if not isinstance(state, dict) or state.get("schemaVersion") != HANDOFF_USAGE_SCHEMA:
        raise ProgressCheckpointError("invalid worker handoff usage ledger")
    ledger = copy.deepcopy(state)
    if not isinstance(ledger.get("tasks"), dict):
        raise ProgressCheckpointError("invalid worker handoff task ledger")
    for field in ("totalRetrievals", "totalExports", "totalPayloadBytes"):
        if type(ledger.get(field)) is not int or ledger[field] < 0:
            raise ProgressCheckpointError("invalid worker handoff usage totals")
    binding = {"checkpointId": checkpoint_id, "intentHash": intent_hash, "progressId": progress_id}
    previous = ledger["tasks"].get(task_id)
    if previous is not None and (not isinstance(previous, dict)
            or type(previous.get("retrievals")) is not int or previous["retrievals"] < 0):
        raise ProgressCheckpointError("invalid worker handoff progress window")
    window = previous if previous and all(previous.get(k) == v for k, v in binding.items()) else {**binding, "retrievals": 0}
    if window["retrievals"] >= MAX_BATCHES_BEFORE_DECISION:
        raise ProgressCheckpointError(
            "three worker handoff retrievals for this task have no accepted progress; "
            "apply the result, verify work, or correct the task before another export"
        )
    ledger["tasks"][task_id] = {**window, "retrievals": window["retrievals"] + 1}
    ledger["totalRetrievals"] += 1
    return ledger


def _checkpoint_self_test(base: Path) -> dict[str, Any]:
    root = base / "workspace"
    remote = base / "remote.git"
    root.mkdir()
    _run(base, "git", "init", "--bare", str(remote))
    _run(root, "git", "init", "-b", "task/checkpoint-test")
    _run(root, "git", "config", "user.name", "SI Test")
    _run(root, "git", "config", "user.email", "si@example.invalid")
    _run(root, "git", "remote", "add", "origin", str(remote))
    (root / "owned.txt").write_text("before\n", encoding="utf-8")
    (root / "unrelated.txt").write_text("keep\n", encoding="utf-8")
    _run(root, "git", "add", "owned.txt", "unrelated.txt")
    _run(root, "git", "commit", "-m", "baseline")
    (root / "owned.txt").write_text("after\n", encoding="utf-8")
    (root / "unrelated.txt").write_text(
        "uncommitted unrelated\n", encoding="utf-8"
    )
    operation = save_checkpoint(
        root=root,
        outcome="Preserve one owned slice",
        completed=["Owned file updated"],
        next_safe_action="Verify the owned change",
        paths=["owned.txt"],
        commit=True,
        push=True,
    )
    working_tree = _git_status(root)
    if working_tree != [" M unrelated.txt"]:
        raise ProgressCheckpointError(
            f"self-test left unexpected working changes: {working_tree}"
        )
    artifact = root / operation["artifact"]
    record = _read_json(artifact, PROGRESS_SCHEMA)
    serialized = json.dumps(record, ensure_ascii=False)
    if record["repository"]["root"] != "." or "unrelated.txt" in serialized:
        raise ProgressCheckpointError("checkpoint leaked private path data")
    tracked = _run(
        root, "git", "ls-files", ".selective-intelligence/progress"
    ).stdout.splitlines()
    if tracked != [".selective-intelligence/progress/latest.json"]:
        raise ProgressCheckpointError(
            f"checkpoint created tracked file sprawl: {tracked}"
        )
    remote_head = _run(
        root,
        "git",
        "--git-dir",
        str(remote),
        "rev-parse",
        "refs/heads/task/checkpoint-test",
    ).stdout.strip()
    if not operation["pushed"] or remote_head != operation["commitSha"]:
        raise ProgressCheckpointError(
            "checkpoint task branch was not verified remotely"
        )
    return {
        "checkpoint": operation,
        "workingTree": working_tree,
        "tracked": tracked,
        "remoteHead": remote_head,
        "root": root,
    }


def _usage_self_test(root: Path) -> dict[str, Any]:
    usage_start(root, "Bound the evidence work")
    for index in range(3):
        response = usage_record(
            root,
            kind="inspection",
            question="Which files own checkout totals?",
            owner="worker-1",
            file_count=4,
            byte_count=8192,
            impact="decision" if index == 2 else "risk",
            result=f"Batch {index + 1} removed one candidate",
        )
    if not response["decisionRequired"]:
        raise ProgressCheckpointError(
            "usage self-test did not stop after three batches"
        )
    try:
        usage_record(
            root,
            kind="search",
            question="Which files own checkout totals?",
            owner="worker-1",
            file_count=1,
            byte_count=100,
            impact="proof",
            result="must be rejected",
        )
    except ProgressCheckpointError:
        pass
    else:
        raise ProgressCheckpointError(
            "usage self-test allowed a fourth batch"
        )
    usage_decide(
        root,
        action="narrow",
        summary="Inspect only the selected owner",
    )
    try:
        usage_record(
            root,
            kind="inspection",
            question="Which files own checkout totals?",
            owner="worker-2",
            file_count=1,
            byte_count=100,
            impact="proof",
            result="must be rejected",
        )
    except ProgressCheckpointError:
        pass
    else:
        raise ProgressCheckpointError(
            "usage self-test allowed overlapping ownership"
        )
    for files, bytes_ in (
        (MAX_BATCH_FILES + 1, 100),
        (1, MAX_BATCH_BYTES + 1),
    ):
        try:
            usage_record(
                root,
                kind="inspection",
                question="A bounded second question",
                owner="worker-1",
                file_count=files,
                byte_count=bytes_,
                impact="proof",
                result="must be rejected",
            )
        except ProgressCheckpointError:
            pass
        else:
            raise ProgressCheckpointError(
                "usage self-test allowed an oversized batch"
            )
    state = _usage_path(root)
    if state.stat().st_size > 32_768:
        raise ProgressCheckpointError("usage state exceeded its size limit")
    if _git_status(root) != [" M unrelated.txt"]:
        raise ProgressCheckpointError("usage ledger dirtied the worktree")
    return {
        "limits": {
            "filesPerBatch": MAX_BATCH_FILES,
            "bytesPerBatch": MAX_BATCH_BYTES,
            "batchesBeforeDecision": MAX_BATCHES_BEFORE_DECISION,
        },
        "stateBytes": state.stat().st_size,
        "status": usage_status(root),
    }


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="si-work-guard-test-") as temporary:
        proof = _checkpoint_self_test(Path(temporary))
        usage = _usage_self_test(proof["root"])
        return {
            "status": "pass",
            "checkpoint": proof["checkpoint"],
            "workingTree": proof["workingTree"],
            "tracked": proof["tracked"],
            "remoteHead": proof["remoteHead"],
            "usage": usage,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preserve work and bound Selective Intelligence evidence use"
    )
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

    checkpoint_status_parser = subparsers.add_parser("status")
    checkpoint_status_parser.add_argument("--root", default=".")

    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--root", default=".")

    usage_start_parser = subparsers.add_parser("usage-start")
    usage_start_parser.add_argument("--root", default=".")
    usage_start_parser.add_argument("--outcome", required=True)

    usage_record_parser = subparsers.add_parser("usage-record")
    usage_record_parser.add_argument("--root", default=".")
    usage_record_parser.add_argument(
        "--kind", choices=("search", "inspection"), required=True
    )
    usage_record_parser.add_argument("--question", required=True)
    usage_record_parser.add_argument("--owner", required=True)
    usage_record_parser.add_argument("--files", type=int, default=0)
    usage_record_parser.add_argument("--bytes", type=int, default=0)
    usage_record_parser.add_argument(
        "--impact", choices=("decision", "risk", "proof"), required=True
    )
    usage_record_parser.add_argument("--result", required=True)

    usage_decide_parser = subparsers.add_parser("usage-decide")
    usage_decide_parser.add_argument("--root", default=".")
    usage_decide_parser.add_argument(
        "--action",
        choices=("act", "narrow", "checkpoint", "stop"),
        required=True,
    )
    usage_decide_parser.add_argument("--summary", required=True)

    usage_status_parser = subparsers.add_parser("usage-status")
    usage_status_parser.add_argument("--root", default=".")

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
        elif args.command == "resume":
            result = resume_checkpoint(Path(args.root))
        elif args.command == "usage-start":
            result = usage_start(Path(args.root), args.outcome)
        elif args.command == "usage-record":
            result = usage_record(
                Path(args.root),
                kind=args.kind,
                question=args.question,
                owner=args.owner,
                file_count=args.files,
                byte_count=args.bytes,
                impact=args.impact,
                result=args.result,
            )
        elif args.command == "usage-decide":
            result = usage_decide(
                Path(args.root), action=args.action, summary=args.summary
            )
        elif args.command == "usage-status":
            result = usage_status(Path(args.root))
        else:
            result = self_test()
    except (ProgressCheckpointError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if args.command == "resume" and result["state"] == "reconciliation_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
