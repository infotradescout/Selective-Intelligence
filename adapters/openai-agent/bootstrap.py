#!/usr/bin/env python3
"""Prepare SI's pinned, isolated source; never update a user's installation."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import zipfile

REPOSITORY = "https://github.com/flavorgood/Selective-Intelligence.git"
# Frozen origin recorded in the accepted resource archive; never a fetch URL.
RESOURCE_MANIFEST_REPOSITORY = "https://github.com/infotradescout/Selective-Intelligence.git"
SOURCE_COMMIT = "e194759bb6507f5f651d0d69edd19fdafdbb8b2c"
SOURCE_TREE = "6da6833f5c0703c909ebb4d4df4060857ea48b73"
DESTINATION = Path("/workspace/si-source")
SOURCE_READY_FOR_HOSTED_USE = False
RESOURCE_SHA256 = "af55e8d64536987897409263a43a5483405294f3f825da13b6c6c4207138ccd6"
RESOURCE_PREFIX = "skills/selective-intelligence/"


def require_hosted_source() -> None:
    """Do not treat a local accepted commit as an available hosted resource."""
    if not SOURCE_READY_FOR_HOSTED_USE:
        raise RuntimeError(
            "Corrected e194 SI source is local-only; hosted resource installation "
            "is unverified. Public-fetch bootstrap, registration, and session "
            "preparation remain blocked; offline resource installation is available"
        )


def git_environment() -> dict[str, str]:
    """Anonymous Git only: do not pass application keys or credential helpers."""
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if key in os.environ}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_CONFIG_COUNT="0", GIT_NO_LAZY_FETCH="1")
    return env


def git_bytes(directory: Path, *arguments: str) -> bytes:
    command = ["git", "-c", "core.hooksPath=" + os.devnull,
               "-c", "credential.helper=", "-c", "core.fsmonitor=false",
               "-c", "core.autocrlf=false", "-c", "protocol.file.allow=never",
               "-c", "http.followRedirects=false", "-c", "http.sslVerify=true",
               "-C", str(directory), *arguments]
    result = subprocess.run(command, check=True, capture_output=True,
                            timeout=180, env=git_environment())
    return result.stdout


def git(directory: Path, *arguments: str) -> str:
    return git_bytes(directory, *arguments).decode("utf-8").strip()


def resource_path(name: str) -> str:
    path = PurePosixPath(name)
    if (not name.startswith(RESOURCE_PREFIX) or "\\" in name or ":" in name
            or path.is_absolute() or str(path) != name or ".." in path.parts
            or any(part.rstrip(" .") != part for part in path.parts)):
        raise ValueError("Unsafe canonical resource path")
    reserved = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}
    if any(part.split(".")[0].upper() in reserved for part in path.parts):
        raise ValueError("Aliased canonical resource path")
    return name


def blob_id(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def build_resources(repository: Path, output: Path) -> dict:
    """Package pinned Git objects, never mutable working files or history."""
    repository = repository.absolute()
    trust = ("-c", "safe.directory=" + str(repository))
    if git(repository, *trust, "rev-parse", SOURCE_COMMIT + "^{tree}") != SOURCE_TREE:
        raise ValueError("Pinned source tree mismatch")
    entries = git(repository, *trust, "ls-tree", "-r", "--full-tree", SOURCE_COMMIT, "skills/selective-intelligence")
    expected = {}
    for line in entries.splitlines():
        identity, name = line.split("\t", 1)
        mode, kind, blob = identity.split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("Unsupported canonical Git resource")
        name = resource_path(name)
        if name.casefold() in {key.casefold() for key in expected}:
            raise ValueError("Duplicate canonical resource")
        expected[name] = {"mode": mode, "blob": blob}
    if RESOURCE_PREFIX + "SKILL.md" not in expected:
        raise ValueError("Canonical entrypoint missing")
    raw = git_bytes(repository, *trust, "archive", "--format=zip", SOURCE_COMMIT, "skills/selective-intelligence")
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        for info in source.infolist():
            if info.is_dir():
                continue
            if info.filename not in expected or info.filename in files:
                raise ValueError("Archive differs from pinned canonical tree")
            data = source.read(info)
            if blob_id(data) != expected[info.filename]["blob"]:
                raise ValueError("Archived bytes differ from pinned Git blob")
            files[info.filename] = data
    if set(files) != set(expected):
        raise ValueError("Canonical resources are incomplete")
    manifest = {"repository": RESOURCE_MANIFEST_REPOSITORY, "commit": SOURCE_COMMIT, "tree": SOURCE_TREE, "files": expected}
    encoded = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        for name, data in sorted({**files, "source-manifest.json": encoded}.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = int(expected.get(name, {"mode": "100644"})["mode"], 8) << 16
            bundle.writestr(info, data)
    data = archive.getvalue()
    output = output.absolute()
    if output.parent.resolve() != output.parent or output.is_symlink():
        raise ValueError("Resource output must not redirect")
    with output.open("xb") as handle:
        handle.write(data)
    return {"status": "pinned_resource_input_built", "commit": SOURCE_COMMIT, "tree": SOURCE_TREE,
            "resource_sha256": hashlib.sha256(data).hexdigest(), "files": len(files), "bytes": len(data)}


def read_resources(archive: Path) -> tuple[bytes, dict, dict[str, bytes]]:
    archive = archive.absolute()
    if archive.is_symlink() or archive.parent.resolve() != archive.parent:
        raise ValueError("Resource input must not redirect")
    raw = archive.read_bytes()
    if len(raw) > 32_000_000 or hashlib.sha256(raw).hexdigest() != RESOURCE_SHA256:
        raise ValueError("Resource input differs from the pinned archive")
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        names = source.namelist()
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise ValueError("Duplicate or aliased archive member")
        manifest = json.loads(source.read("source-manifest.json"))
        if any(manifest.get(key) != value for key, value in
               (("repository", RESOURCE_MANIFEST_REPOSITORY), ("commit", SOURCE_COMMIT), ("tree", SOURCE_TREE))):
            raise ValueError("Resource provenance differs from pinned source")
        if set(names) != set(manifest["files"]) | {"source-manifest.json"}:
            raise ValueError("Resource file set differs from pinned manifest")
        files = {}
        for name, expected in manifest["files"].items():
            resource_path(name)
            info = source.getinfo(name)
            if expected["mode"] not in {"100644", "100755"} or info.external_attr >> 16 != int(expected["mode"], 8):
                raise ValueError("Unsupported resource mode or symlink")
            data = source.read(info)
            if blob_id(data) != expected["blob"]:
                raise ValueError("Resource bytes differ from pinned Git blob")
            files[name] = data
    return raw, manifest, files


def install_resources(archive: Path, destination: Path) -> dict:
    """Install verified inputs into an exclusively created local source directory."""
    _, manifest, files = read_resources(archive)
    destination = destination.absolute()
    if destination.parent.resolve() != destination.parent or destination.is_symlink():
        raise ValueError("Resource destination must not redirect")
    # Atomic directory reservation preserves any existing destination. A failed
    # installation remains visible for reconciliation and is never overwritten.
    destination.mkdir()
    for name, data in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.parent.resolve().is_relative_to(destination):
            raise ValueError("Resource destination escaped through a redirect")
        with target.open("xb") as handle:
            handle.write(data)
        target.chmod(int(manifest["files"][name]["mode"], 8) & 0o777)
    for name, data in files.items():
        target = destination / name
        if target.is_symlink() or target.read_bytes() != data:
            raise ValueError("Installed canonical resource differs")
    receipt = {"status": "canonical_resource_inputs_installed_offline", "commit": SOURCE_COMMIT,
               "tree": SOURCE_TREE, "resource_sha256": RESOURCE_SHA256, "files": len(files),
               "entrypoint": str(destination / RESOURCE_PREFIX / "SKILL.md"),
               "full_repository_checkout": False, "hosted_acceptance": False, "api_calls": 0}
    with (destination / "source-resource-receipt.json").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt, indent=2) + "\n")
    return receipt


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
    require_hosted_source()
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
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--build-resources", type=Path)
    actions.add_argument("--install-resources", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    args = parser.parse_args()
    if args.build_resources:
        if args.output is None:
            parser.error("--build-resources requires a new --output")
        result = build_resources(args.build_resources, args.output)
    elif args.install_resources:
        result = install_resources(args.install_resources, args.destination)
    else:
        result = prepare(args.destination)
    print(json.dumps(result, sort_keys=True))
