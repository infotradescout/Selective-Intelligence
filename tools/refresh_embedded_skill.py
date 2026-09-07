#!/usr/bin/env python3
"""Refresh an existing SI installation from one verified public source revision.

Check is the default. --apply replaces only the named skill directory, retains
its old contents outside skill discovery, and never edits project state.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
import uuid
import zipfile

SOURCE_COMMIT = "26606d51cffec17607802ded4d758b35d0086058"
SOURCE_TREE = "818a5cddd3fa082922b4b551083041fc64a70429"
SOURCE_PREFIX = f"Selective-Intelligence-{SOURCE_COMMIT}/skills/selective-intelligence/"
SOURCE_URL = f"https://codeload.github.com/infotradescout/Selective-Intelligence/zip/{SOURCE_COMMIT}"
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_CONTENT = 128 * 1024 * 1024
ALLOWED_CLIENTS = {".agents", ".claude", ".codex", ".cursor", ".gemini", ".kiro"}


def object_hash(kind: str, data: bytes) -> str:
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def directory_hash(root: Path) -> str:
    """Compute the real Git tree identity; ignore only Python-generated caches."""
    entries = []
    for path in root.iterdir():
        if path.name == "__pycache__" and path.is_dir() and not path.is_symlink():
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Refusing a symbolic link inside an installed skill")
        if stat.S_ISDIR(info.st_mode):
            mode, digest, key = "40000", directory_hash(path), path.name.encode() + b"/"
        elif stat.S_ISREG(info.st_mode):
            mode = "100755" if info.st_mode & 0o111 else "100644"
            digest, key = object_hash("blob", path.read_bytes()), path.name.encode()
        else:
            raise ValueError("Refusing a special file inside an installed skill")
        entry = mode.encode() + b" " + path.name.encode() + b"\0" + bytes.fromhex(digest)
        entries.append((key, entry))
    return object_hash("tree", b"".join(entry for _, entry in sorted(entries)))


def validate_destination(destination: Path) -> Path:
    destination = Path(os.path.abspath(destination))
    if destination.name != "selective-intelligence" or destination.parent.name != "skills":
        raise ValueError("Destination must be an existing selective-intelligence skill directory")
    if destination.parent.parent.name not in ALLOWED_CLIENTS:
        raise ValueError("Destination is not a supported installed-skill location")
    for part in (destination, *destination.parents):
        if part.is_symlink():
            raise ValueError("Refusing a symbolic-link destination or ancestor")
    if not destination.is_dir() or not (destination / "SKILL.md").is_file():
        raise ValueError("This updater never creates a previously absent installation")
    return destination


def download_source() -> bytes:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "Selective-Intelligence-Refresh/1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(MAX_ARCHIVE + 1)
    if len(data) > MAX_ARCHIVE:
        raise ValueError("Source archive exceeds the download limit")
    return data


def stage_source(data: bytes, stage: Path) -> None:
    if len(data) > MAX_ARCHIVE:
        raise ValueError("Source archive exceeds the download limit")
    total, seen, case_names = 0, set(), set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            if not item.filename.startswith(SOURCE_PREFIX):
                continue
            name = item.filename[len(SOURCE_PREFIX):]
            if not name or item.is_dir():
                continue
            parts = PurePosixPath(name).parts
            if name.startswith("/") or "\\" in name or any(p in {"", ".", ".."} or ":" in p for p in parts):
                raise ValueError("Unsafe path in source archive")
            if name in seen or name.casefold() in case_names:
                raise ValueError("Duplicate or case-colliding source path")
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG}):
                raise ValueError("Only regular source files may be installed")
            total += item.file_size
            if total > MAX_CONTENT or len(seen) >= 2000:
                raise ValueError("Unpacked source exceeds its limit")
            seen.add(name)
            case_names.add(name.casefold())
            target = stage.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as handle:
                content = handle.read(min(item.file_size, MAX_CONTENT) + 1)
            if len(content) != item.file_size:
                raise ValueError("Incomplete source file")
            target.write_bytes(content)
            target.chmod(0o755 if mode & 0o111 else 0o644)
    if not seen or not (stage / "SKILL.md").is_file():
        raise ValueError("Source does not contain the complete named skill")
    if directory_hash(stage) != SOURCE_TREE:
        raise ValueError("Source files do not match the approved complete skill tree")


def refresh(destination: Path, *, apply: bool = False, source: bytes | None = None) -> dict:
    destination = validate_destination(destination)
    current = directory_hash(destination)
    report = {"source_commit": SOURCE_COMMIT, "expected_tree": SOURCE_TREE, "observed_tree": current}
    if current == SOURCE_TREE:
        return {**report, "status": "current", "changed": False}
    if not apply:
        return {**report, "status": "outdated", "changed": False}
    lock = destination.parent / ".selective-intelligence-refresh.lock"
    lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(lock_fd, str(os.getpid()).encode())
    os.close(lock_fd)
    stage = None
    backup = None
    old_moved = False
    new_installed = False
    try:
        backup_parent = destination.parent.parent / ".si-refresh-backups"
        if backup_parent.is_symlink():
            raise ValueError("Refusing a symbolic-link backup location")
        backup_parent.mkdir(exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="stage-", dir=backup_parent))
        stage_source(download_source() if source is None else source, stage)
        if directory_hash(destination) != current:
            raise ValueError("Installation changed during preparation; no replacement was made")
        backup = backup_parent / ("previous-" + uuid.uuid4().hex)
        os.replace(destination, backup)
        old_moved = True
        os.replace(stage, destination)
        stage = None
        new_installed = True
        if directory_hash(destination) != SOURCE_TREE:
            raise ValueError("Installed files failed read-back verification")
        return {**report, "status": "updated", "changed": True,
                "observed_tree": SOURCE_TREE, "previous_copy_retained": True}
    except BaseException:
        if old_moved:
            if new_installed:
                failed = backup.parent / ("failed-" + uuid.uuid4().hex)
                os.replace(destination, failed)
            try:
                os.replace(backup, destination)
            except OSError as restore_error:
                raise RuntimeError("Restore failed; previous skill remains in the retained backup") from restore_error
        raise
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path(__file__).absolute().parent)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        report = refresh(args.destination, apply=args.apply)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] in {"current", "updated"} else 2
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "not_updated", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
