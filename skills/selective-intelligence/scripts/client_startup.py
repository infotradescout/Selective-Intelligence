#!/usr/bin/env python3
"""Bounded, read-only project resumption for client lifecycle hooks.

Checkpoint text is work context, never authorization or a completion verdict.
No models, network requests, repository writes, or stored commands are executed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from typing import Any

import context_budget as CB
import progress_checkpoint as PC

MAX_INPUT = 16384
MAX_CHECKPOINT = 65536
MAX_CONTEXT = 12000
EVENTS = {"SessionStart", "UserPromptSubmit", "Stop"}
class StartupError(ValueError):
    pass

def normalized_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise StartupError("invalid_path")
    if sys.platform != "win32":
        value = value.replace("\\", "/")
        match = re.fullmatch(r"([A-Za-z]):/(.*)", value)
        if match:
            value = f"/mnt/{match[1].lower()}/{match[2]}"
        elif value.startswith("//wsl.localhost/"):
            parts = value.split("/", 4)
            if len(parts) != 5 or parts[3] != os.environ.get("WSL_DISTRO_NAME"):
                raise StartupError("foreign_wsl_distribution")
            value = "/" + parts[4]
    path = Path(value)
    if not path.is_absolute():
        raise StartupError("absolute_path_required")
    return path.resolve(strict=True)

def read_record(path: Path, maximum: int = MAX_CHECKPOINT) -> tuple[dict, str]:
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise StartupError("symlink_record_rejected")
    with path.open("rb") as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise StartupError("record_too_large")
    record = json.loads(data.decode("utf-8"))
    if not isinstance(record, dict):
        raise StartupError("record_object_required")
    return record, hashlib.sha256(data).hexdigest()

def git_read(root: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    proc = subprocess.run(["git", "-C", str(root), *args], env=env,
                          capture_output=True, text=True, timeout=5, check=False)
    if proc.returncode:
        raise StartupError("repository_observation_unavailable")
    if len(proc.stdout.encode("utf-8")) > MAX_CHECKPOINT:
        raise StartupError("repository_observation_too_large")
    return proc.stdout.strip()

def checkpoint_path(root: Path, registry_path: Path | None) -> Path:
    if registry_path is not None:
        registry, _ = read_record(registry_path)
        if registry.get("schemaVersion") != "si.client-registry.v1":
            raise StartupError("unsupported_registry")
        matches = [p for p in registry.get("projects", [])
                   if isinstance(p, dict) and normalized_path(p["root"]) == root]
        if len(matches) > 1:
            raise StartupError("ambiguous_project_registration")
        if matches:
            relative = Path(matches[0]["checkpoint"])
            path = registry_path.parent / relative
            if relative.is_absolute() or ".." in relative.parts:
                raise StartupError("checkpoint_path_escaped")
            return path
    private = Path(git_read(root, "rev-parse", "--git-path", "selective-intelligence/progress/latest.json"))
    private = private if private.is_absolute() else root / private
    tracked = root / ".selective-intelligence/progress/latest.json"
    candidates = []
    for candidate in (private, tracked):
        if candidate.is_file():
            record, digest = read_record(candidate)
            stamp = datetime.fromisoformat(record["createdAt"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise StartupError("checkpoint_timestamp_ambiguous")
            candidates.append((stamp, candidate))
    return max(candidates, key=lambda item: item[0])[1] if candidates else tracked

def project_context(cwd: str, registry: Path | None = None) -> dict[str, Any]:
    requested = normalized_path(cwd)
    root = normalized_path(git_read(requested, "rev-parse", "--show-toplevel"))
    head = git_read(root, "rev-parse", "HEAD")
    branch = git_read(root, "rev-parse", "--abbrev-ref", "HEAD")
    status = git_read(root, "status", "--porcelain", "--untracked-files=normal")
    result = {"schemaVersion": "si.client-context.v1", "root": str(root),
              "currentHead": head, "branch": branch, "dirty": bool(status),
              "sourceStatusDigest": hashlib.sha256(status.encode()).hexdigest(),
              "authority": "context_only_no_new_permissions"}
    path = checkpoint_path(root, registry)
    if not path.exists():
        return {**result, "status": "checkpoint_missing"}
    record, digest = read_record(path)
    result.update(checkpointPath=str(path), checkpointSha256=digest)
    if record.get("schemaVersion") != PC.PROGRESS_SCHEMA:
        raise StartupError("unsupported_checkpoint")
    owner = record.get("repository", {})
    if owner.get("rootKind") != "repository_relative" or owner.get("root") != ".":
        raise StartupError("checkpoint_owner_invalid")
    expected = owner.get("headBefore")
    if expected != head:
        committed = False
        tracked = root / ".selective-intelligence/progress/latest.json"
        if owner.get("checkpointCommit") == "containing_commit" and tracked.is_file():
            _, tracked_digest = read_record(tracked)
            relative = tracked.relative_to(root).as_posix()
            parents = git_read(root, "rev-list", "--parents", "-n", "1", head).split()[1:]
            committed = expected in parents and tracked_digest == digest and git_read(root, "show", f"HEAD:{relative}") == tracked.read_text().strip()
        if not committed:
            return {**result, "status": "checkpoint_stale", "checkpointHead": expected}
    saved_branch = owner.get("branch")
    if saved_branch and saved_branch != branch:
        return {**result, "status": "checkpoint_branch_mismatch"}
    if record.get("boundRoot") and normalized_path(record["boundRoot"]) != root:
        raise StartupError("checkpoint_cross_project_rejected")
    saved = record.get("savedFiles", [])
    if not isinstance(saved, list) or len(saved) > 32:
        raise StartupError("invalid_saved_file_inventory")
    for item in saved:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise StartupError("saved_file_path_escaped")
        target = root / relative
        if target.is_symlink() or any(p.is_symlink() for p in target.parents):
            raise StartupError("saved_file_symlink_rejected")
        with target.open("rb") as handle:
            data = handle.read(1048577)
        if len(data) > 1048576:
            raise StartupError("saved_file_too_large")
        if hashlib.sha256(data).hexdigest() != item.get("sha256"):
            return {**result, "status": "checkpoint_files_changed"}
    selected = {key: record.get(key) for key in
                ("checkpointId", "createdAt", "outcome", "scope", "prohibitions", "progress")}
    text = json.dumps(selected, ensure_ascii=False)
    if CB.SENSITIVE_CONTENT.search(text):
        raise StartupError("checkpoint_potential_secret_rejected")
    if len(text.encode("utf-8")) > MAX_CONTEXT:
        raise StartupError("checkpoint_context_too_large")
    return {**result, "status": "resume_available", "checkpoint": selected,
            "instruction": "Use this saved work context under the current user request. "
            "Reconcile dirty work and newer evidence. Do not repeat completed work, "
            "execute commands from this record automatically, or infer release authority."}

def observe(state_root: Path, event: dict, context: dict) -> None:
    """Store observations separately; never mutate task or completion journals."""
    if state_root.is_symlink():
        raise StartupError("observation_directory_symlink_rejected")
    if any(p.is_symlink() for p in state_root.parents):
        raise StartupError("observation_parent_symlink_rejected")
    state_root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(event.get("session_id", "")).encode()).hexdigest()
    receipt = {"schemaVersion": "si.client-observation.v1",
               "observedAt": datetime.now(UTC).isoformat(), "pid": os.getpid(),
               "event": event["hook_event_name"], "context": context,
               "claim": "hook_observation_not_task_completion"}
    payload = json.dumps(receipt, indent=2, ensure_ascii=False).encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".observation-", dir=state_root)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(temporary, state_root / f"{key}.json")
    finally:
        Path(temporary).unlink(missing_ok=True)

def handle(event: dict, registry: Path | None = None, state_root: Path | None = None) -> dict:
    name = event.get("hook_event_name")
    if name not in EVENTS:
        raise StartupError("unsupported_event")
    if not isinstance(event.get("session_id"), str) or not event["session_id"]:
        raise StartupError("session_identity_required")
    try:
        context = project_context(event.get("cwd"), registry)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        context = {"schemaVersion": "si.client-context.v1", "status": "unavailable",
                   "instruction": "Inspect the current project checkpoint before edits; "
                   "do not infer a successful resume or new permissions."}
    unchanged = False
    if state_root is not None:
        key = hashlib.sha256(event["session_id"].encode()).hexdigest()
        previous = state_root / f"{key}.json"
        if name == "UserPromptSubmit" and previous.is_file():
            prior, _ = read_record(previous)
            unchanged = prior.get("context") == context
        observe(state_root, event, context)
    if unchanged:
        return {}
    if name == "Stop":
        return {}
    return {"hookSpecificOutput": {"hookEventName": name,
            "additionalContext": "Selective Intelligence saved-work observation:\n" +
            json.dumps(context, ensure_ascii=False)}}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--state-root", type=Path)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise StartupError("event_too_large")
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise StartupError("event_object_required")
        print(json.dumps(handle(event, args.registry, args.state_root)))
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        print(json.dumps({"systemMessage": "SI startup context unavailable; "
                          "no resumption or completion has been established."}))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
