#!/usr/bin/env python3
"""Build the supported ChatGPT form of the portable Selective Intelligence skill.

The portable Agent Skills package intentionally contains separately runnable
role skills. ChatGPT personal-skill bundles accept exactly one ``SKILL.md``.
This deterministic adapter keeps only runtime instructions and tools, then
converts each nested role entrypoint to a normal reference file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import re
import zipfile
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[1]
PORTABLE_ROOT = REPO_ROOT / "skills" / "selective-intelligence"
ADAPTER_ROOT = REPO_ROOT / "adapters" / "chatgpt" / "selective-intelligence"
ADAPTER_METADATA = REPO_ROOT / "adapters" / "chatgpt" / "metadata" / "chatgpt-adapter.json"
DIST_ROOT = REPO_ROOT / "dist"


def role_path_map(release_files: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for relative in release_files:
        parts = Path(relative).parts
        if len(parts) == 3 and parts[0] == "subskills" and parts[2] == "SKILL.md":
            mapping[relative] = (Path(*parts[:-1]) / "ROLE.md").as_posix()
    return mapping


def rewrite_text(relative: str, text: str, mapping: dict[str, str]) -> str:
    for portable, adapted in mapping.items():
        text = text.replace(portable, adapted)

    if relative == "SKILL.md":
        anchor = "<!-- SELECTIVE_INTELLIGENCE_RUNTIME_PROJECTION -->"
        addition = """

ChatGPT adapter: this bundle has one `SKILL.md`; the seven Council roles are `subskills/*/ROLE.md` references, not independently invocable skills. Read the selected role before assigning it and pass only its bounded packet.
"""
        if anchor not in text:
            raise ValueError("master skill adapter anchor is missing")
        text = text.replace(anchor, anchor + addition, 1)

    if relative == "README.md":
        anchor = "# Selective Intelligence\n"
        version = (PORTABLE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        addition = f"""

> **ChatGPT adapter.** This generated bundle preserves the canonical {version} behavior while satisfying ChatGPT's one-`SKILL.md` bundle rule. The portable source remains `skills/selective-intelligence/`; nested Council roles are reference files here so ChatGPT can store and load the complete package.
"""
        if not text.startswith(anchor):
            raise ValueError("adapter README heading is missing")
        text = text.replace(anchor, anchor + addition, 1)

    if relative == "subskills/README.md":
        text = text.replace(
            "Selective Intelligence is now split into small, separately runnable modules so one agent can do one job at a time.",
            "Selective Intelligence keeps each Council role in a small reference module so one agent can do one bounded job at a time.",
        )
        text = text.replace(
            "Each sub-skill is built in plain, easy-to-understand language:",
            "Each role reference is built in plain, easy-to-understand language:",
        )
        text = text.replace(
            "The parent `selective-intelligence` skill can still run the same full flow, but this split lets you hand each phase to a separate agent/context.",
            "The parent `selective-intelligence` skill runs the full flow and may hand each phase to a separate agent/context after reading the matching `ROLE.md` reference.",
        )
    if relative == "scripts/release.py":
        portable_archive = 'expected_archive = f"selective-intelligence-{version}.zip" if version else None'
        adapter_archive = 'expected_archive = f"selective-intelligence-chatgpt-{version}.zip" if version else None'
        if portable_archive not in text:
            raise ValueError("release archive adapter anchor is missing")
        text = text.replace(portable_archive, adapter_archive, 1)
    if relative == "scripts/eval.py":
        text = text.replace(
            'f"selective-intelligence-{version}.zip"',
            'f"selective-intelligence-chatgpt-{version}.zip"',
        )
    return text


def write_text(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    path.chmod(mode)


# These are shipped dependencies, not instructions to activate tools without
# permission. The package must carry the same execution owners that tests use.
EXECUTION_RUNTIME_FILES = frozenset({
    "scripts/build_engine.py", "scripts/capabilities.py", "scripts/checkpoint.py",
    "scripts/context_budget.py", "scripts/feedback.py", "scripts/intent_contract.py",
    "scripts/lane_registry.py", "scripts/lane_session.py", "scripts/policy_guard.py",
    "scripts/text_gate.py", "lanes/si.execution.json", "lanes/si.planning.json",
    "schemas/lane.schema.json",
})


def _safe_member(relative: str) -> None:
    parts = PurePosixPath(relative).parts
    if (not relative or "\\" in relative or ":" in relative
            or relative.startswith("/") or ".." in parts
            or PurePosixPath(relative).as_posix() != relative
            or any(ord(char) < 32 for char in relative)):
        raise ValueError(f"unsafe runtime path: {relative!r}")


def _source(relative: str) -> Path:
    _safe_member(relative)
    source = PORTABLE_ROOT / relative
    current = source
    while current != PORTABLE_ROOT:
        if current.is_symlink():
            raise ValueError(f"runtime sources must not be symlinks: {relative}")
        current = current.parent
    if not source.is_file():
        raise FileNotFoundError(source)
    return source


def _prepare_projection() -> tuple[dict[str, tuple[bytes, int]], dict[str, object]]:
    """Read and validate everything before replacing a previously usable copy.

    Content hashes identify source/projection drift. They are not signatures,
    installed-client evidence, or proof of behavior across running models.
    """
    if PORTABLE_ROOT.resolve() != PORTABLE_ROOT.absolute():
        raise ValueError("portable source root must not redirect through symlinks")
    metadata_bytes = _source("metadata/distribution.json").read_bytes()
    metadata = json.loads(metadata_bytes)
    release_files = metadata.get("release_files")
    runtime_files = metadata.get("runtime_files")
    for name, values in (("portable release", release_files), ("runtime file", runtime_files)):
        if not isinstance(values, list) or not values or not all(isinstance(x, str) for x in values):
            raise ValueError(f"{name} manifest is invalid")
        if len(values) != len(set(values)):
            raise ValueError(f"{name} manifest contains duplicates")
        for value in values:
            _safe_member(value)
    if not set(runtime_files).issubset(release_files):
        raise ValueError("runtime file manifest contains files outside the portable release")
    missing = sorted(EXECUTION_RUNTIME_FILES - set(runtime_files))
    if missing:
        raise ValueError("runtime manifest omits execution dependencies: " + ", ".join(missing))
    version = metadata.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("distribution version must be a safe semantic version")
    if _source("VERSION").read_text(encoding="utf-8").strip() != version:
        raise ValueError("distribution and VERSION disagree")
    mapping = role_path_map(runtime_files)
    if len(mapping) != 7:
        raise ValueError(f"expected seven nested role skills, found {len(mapping)}")
    prepared: dict[str, tuple[bytes, int]] = {}
    source_hashes: dict[str, str] = {}
    for relative in runtime_files:
        source = _source(relative)
        raw = source.read_bytes()
        text = rewrite_text(relative, raw.decode("utf-8"), mapping)
        adapted = mapping.get(relative, relative)
        if adapted in prepared:
            raise ValueError("runtime projection has colliding target paths")
        prepared[adapted] = (text.encode("utf-8"), stat.S_IMODE(source.stat().st_mode))
        source_hashes[relative] = hashlib.sha256(raw).hexdigest()
    for relative in prepared:
        if any(parent.as_posix() in prepared for parent in PurePosixPath(relative).parents):
            raise ValueError("runtime files conflict with a parent directory")
    entrypoints = sorted(name for name in prepared if PurePosixPath(name).name == "SKILL.md")
    if entrypoints != ["SKILL.md"]:
        raise ValueError(f"ChatGPT adapter must contain exactly one SKILL.md: {entrypoints}")
    projection = {
        "schema_version": 2,
        "adapter": "chatgpt_personal_skills",
        "skill": "selective-intelligence",
        "version": version,
        "portable_source_path": "skills/selective-intelligence",
        "adapter_path": "adapters/chatgpt/selective-intelligence",
        "transformation": "runtime_only_with_nested_role_entrypoints_as_role_references",
        "single_skill_entrypoint": "SKILL.md",
        "runtime_file_count": len(prepared),
        "role_path_map": mapping,
        "behavioral_contract": "source_preserved_not_installed_behavior_proof",
        "source_manifest_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "source_file_sha256": source_hashes,
        "projected_file_sha256": {name: hashlib.sha256(raw).hexdigest() for name, (raw, _) in prepared.items()},
        "execution_entrypoint": "scripts/build_engine.py",
        "execution_dependencies": sorted(EXECUTION_RUNTIME_FILES),
    }
    return prepared, projection


def _validate_output(root: Path, prepared: dict[str, tuple[bytes, int]]) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("adapter must be a real directory")
    actual = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("adapter must not contain symlinks")
        if path.is_file():
            actual.append(path.relative_to(root).as_posix())
    if sorted(actual) != sorted(prepared):
        raise ValueError("generated adapter files do not equal the adapted runtime manifest")
    for relative, (raw, mode) in prepared.items():
        path = root / relative
        if path.read_bytes() != raw or stat.S_IMODE(path.stat().st_mode) != mode:
            raise ValueError(f"adapter content or mode differs from source projection: {relative}")


def build_adapter(destination: Path = ADAPTER_ROOT) -> dict[str, object]:
    destination = Path(destination).absolute()
    expected_parent = (REPO_ROOT / "adapters" / "chatgpt").absolute()
    if (destination.parent != expected_parent or destination.name != "selective-intelligence"
            or destination.is_symlink() or expected_parent.resolve() != expected_parent):
        raise ValueError(f"refusing to replace unexpected adapter destination: {destination}")
    if destination.exists() and not destination.is_dir():
        raise ValueError("existing adapter destination is not a directory")
    # This call has no write effects. Missing sources, bad paths, stale versions
    # and bad rewrite anchors cannot delete the preceding generated package.
    prepared, projection = _prepare_projection()
    metadata = Path(ADAPTER_METADATA).absolute()
    if (metadata != expected_parent / "metadata" / "chatgpt-adapter.json"
            or metadata.is_symlink() or metadata.parent.resolve() != metadata.parent):
        raise ValueError("unexpected adapter metadata destination")
    expected_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".si-adapter-stage-", dir=expected_parent))
    cleanup_allowed = True
    try:
        staged = temporary / "new"
        staged.mkdir()
        for relative, (raw, mode) in prepared.items():
            write_text(staged / relative, raw.decode("utf-8"), mode)
        _validate_output(staged, prepared)
        staged_metadata = temporary / "metadata.json"
        write_text(staged_metadata, json.dumps(projection, ensure_ascii=False, indent=2) + "\n", 0o644)
        backup = temporary / "previous"
        backup_metadata = temporary / "previous-metadata.json"
        old_metadata = metadata.read_bytes() if metadata.exists() else None
        if old_metadata is not None:
            backup_metadata.write_bytes(old_metadata)
            backup_metadata.chmod(stat.S_IMODE(metadata.stat().st_mode))
        had_old = destination.exists()
        replaced = False
        moved_old = False
        # Retain recovery material if interruption or restoration itself fails.
        # A hard process kill is not claimed to be a completed transaction.
        cleanup_allowed = False
        try:
            metadata.parent.mkdir(parents=True, exist_ok=True)
            if had_old:
                os.replace(destination, backup)
                moved_old = True
            os.replace(staged, destination)
            replaced = True
            os.replace(staged_metadata, metadata)
            cleanup_allowed = True
        except BaseException as failure:
            recovery_errors = []
            try:
                if replaced:
                    shutil.rmtree(destination)
                if moved_old:
                    os.replace(backup, destination)
            except OSError as exc:
                recovery_errors.append(str(exc))
            try:
                if old_metadata is not None:
                    os.replace(backup_metadata, metadata)
                else:
                    metadata.unlink(missing_ok=True)
            except OSError as exc:
                recovery_errors.append(str(exc))
            if recovery_errors:
                raise RuntimeError(f"adapter build failed; recovery retained at {temporary}: "
                                   + "; ".join(recovery_errors)) from failure
            cleanup_allowed = True
            raise
    finally:
        if cleanup_allowed:
            shutil.rmtree(temporary)
    return {
        "destination": str(destination), "files": len(prepared),
        "version": projection["version"], "skill_entrypoints": ["SKILL.md"],
        "role_path_map": projection["role_path_map"],
        "execution_entrypoint": projection["execution_entrypoint"],
        "source_manifest_sha256": projection["source_manifest_sha256"],
    }


def validate_adapter(adapter_root: Path = ADAPTER_ROOT) -> dict[str, object]:
    prepared, projection = _prepare_projection()
    _validate_output(Path(adapter_root), prepared)
    metadata = Path(ADAPTER_METADATA)
    if metadata.is_symlink() or json.loads(metadata.read_text(encoding="utf-8")) != projection:
        raise ValueError("adapter metadata is missing or stale; rebuild from current source")
    return projection


def build_archive(adapter_root: Path = ADAPTER_ROOT, dist_root: Path = DIST_ROOT) -> dict[str, object]:
    projection = validate_adapter(adapter_root)
    version = projection["version"]
    archive_path = dist_root / f"selective-intelligence-chatgpt-{version}.zip"
    dist_root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".si-archive-", dir=dist_root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(item for item in adapter_root.rglob("*") if item.is_file()):
                relative = Path("selective-intelligence") / path.relative_to(adapter_root)
                info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IMODE(path.stat().st_mode) & 0xFFFF) << 16
                if path.is_symlink() or not path.resolve().is_relative_to(adapter_root.resolve()):
                    raise ValueError("archive source redirected outside the adapter")
                raw = path.read_bytes()
                expected = projection["projected_file_sha256"].get(path.relative_to(adapter_root).as_posix())
                if hashlib.sha256(raw).hexdigest() != expected:
                    raise ValueError("archive bytes differ from the validated source projection")
                archive.writestr(info, raw)
        # Recheck after archive creation so source/output drift during this
        # build cannot be published as a matching package.
        if validate_adapter(adapter_root) != projection:
            raise ValueError("source projection changed while building archive")
        os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    return {"archive": str(archive_path), "sha256": digest}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", action="store_true", help="also build the deterministic ChatGPT ZIP")
    args = parser.parse_args()
    result = build_adapter()
    if args.archive:
        result.update(build_archive())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
