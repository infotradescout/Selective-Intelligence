#!/usr/bin/env python3
"""Prepare SI's pinned, isolated source; never update a user's installation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REPOSITORY = "https://github.com/infotradescout/Selective-Intelligence.git"
SOURCE_COMMIT = "3015ede746c84dfb5deac94a622b650701a21e15"
SOURCE_TREE = "51d2ccb7133785685beb08f1ce74616fe4a1ccb7"
DESTINATION = Path("/workspace/si-source")


def git_environment() -> dict[str, str]:
    """Anonymous Git only: do not pass application keys or credential helpers."""
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if key in os.environ}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_CONFIG_COUNT="0")
    return env


def git(directory: Path, *arguments: str) -> str:
    command = ["git", "-c", "core.hooksPath=" + os.devnull,
               "-c", "credential.helper=", "-c", "core.fsmonitor=false",
               "-c", "core.autocrlf=false", "-c", "protocol.file.allow=never",
               "-c", "http.followRedirects=false", "-c", "http.sslVerify=true",
               "-C", str(directory), *arguments]
    result = subprocess.run(command, check=True, capture_output=True, text=True,
                            timeout=180, env=git_environment())
    return result.stdout.strip()


def verify_checkout(directory: Path, commit: str, tree: str) -> dict[str, str]:
    if directory.is_symlink() or not directory.is_dir() or directory.resolve() != directory.absolute():
        raise ValueError("Source must be a real, non-redirected directory")
    if git(directory, "rev-parse", "HEAD") != commit:
        raise ValueError("Source commit mismatch")
    if git(directory, "rev-parse", "HEAD^{tree}") != tree:
        raise ValueError("Source tree mismatch")
    if git(directory, "status", "--porcelain", "--untracked-files=all", "--ignored"):
        raise ValueError("Source checkout was modified or has extra files")
    # Hash actual skill bytes, not merely the index: skip-worktree and
    # assume-unchanged flags must not hide modified executable content.
    entries = git(directory, "ls-tree", "-r", "--full-tree", "HEAD", "skills/selective-intelligence")
    for line in entries.splitlines():
        identity, relative = line.split("\t", 1)
        mode, kind, expected_blob = identity.split()
        path = directory / relative
        if kind != "blob" or mode not in {"100644", "100755"} or path.is_symlink() or not path.is_file():
            raise ValueError("Unsupported canonical skill file")
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Canonical skill file escaped its source directory")
        raw = path.read_bytes()
        actual_blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        if actual_blob != expected_blob:
            raise ValueError("Canonical skill bytes differ from the pinned Git tree")
    for path in (directory / "skills" / "selective-intelligence").rglob("*"):
        if path.is_symlink():
            raise ValueError("The canonical skill must not contain symlinks")
    entry = directory / "skills" / "selective-intelligence" / "SKILL.md"
    if not entry.is_file():
        raise ValueError("Canonical skill entrypoint missing")
    return {"repository": REPOSITORY, "commit": commit, "tree": tree,
            "entrypoint": str(entry), "status": "source_identity_verified"}


def prepare(destination: Path = DESTINATION) -> dict[str, str]:
    destination = destination.absolute()
    if destination != DESTINATION or destination.parent.resolve() != destination.parent:
        raise ValueError("Only the agent's isolated /workspace/si-source is allowed")
    if destination.exists() or destination.is_symlink():
        return verify_checkout(destination, SOURCE_COMMIT, SOURCE_TREE)
    stage = Path(tempfile.mkdtemp(prefix=".si-agent-source-", dir=destination.parent))
    try:
        git(stage, "init", "--template=")
        git(stage, "remote", "add", "origin", REPOSITORY)
        git(stage, "fetch", "--no-tags", "--depth=1", "origin", SOURCE_COMMIT)
        if git(stage, "rev-parse", "FETCH_HEAD") != SOURCE_COMMIT:
            raise ValueError("Fetched revision does not match the fixed source pin")
        git(stage, "checkout", "--detach", SOURCE_COMMIT)
        verify_checkout(stage, SOURCE_COMMIT, SOURCE_TREE)
        if destination.exists() or destination.is_symlink():
            raise ValueError("Destination appeared during setup; refusing replacement")
        stage.rename(destination)
        return verify_checkout(destination, SOURCE_COMMIT, SOURCE_TREE)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


if __name__ == "__main__":
    print(json.dumps(prepare(), sort_keys=True))
