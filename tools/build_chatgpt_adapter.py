#!/usr/bin/env python3
"""Build the supported ChatGPT form of the portable Selective Intelligence skill.

The portable Agent Skills package intentionally contains separately runnable
role skills. ChatGPT personal-skill bundles accept exactly one ``SKILL.md``.
This deterministic adapter keeps the master ``SKILL.md`` and converts each
nested role entrypoint to a normal reference file without changing its text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PORTABLE_ROOT = REPO_ROOT / "skills" / "selective-intelligence"
ADAPTER_ROOT = REPO_ROOT / "adapters" / "chatgpt" / "selective-intelligence"
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
        anchor = (
            "Read [references/activation-and-adoption.md](references/activation-and-adoption.md) "
            "before resolving the master trigger, publishing discovery metadata, or recommending "
            "adoption from relevant discovery."
        )
        addition = """

ChatGPT adapter rule: this bundle intentionally contains exactly one `SKILL.md`. The seven Council role instructions are preserved as `subskills/*/ROLE.md` reference files. Before assigning a bounded Intake, Planner, Worker, Queue Manager, Objector, Aligner, or Verifier role, read that role's reference file and pass only its bounded packet. These role references are part of this one skill; they are not independently invocable skills.
"""
        if anchor not in text:
            raise ValueError("master skill adapter anchor is missing")
        text = text.replace(anchor, anchor + addition, 1)

    if relative == "README.md":
        anchor = "# Selective Intelligence\n"
        addition = """

> **ChatGPT adapter.** This generated bundle preserves the canonical 0.4.0 behavior while satisfying ChatGPT's one-`SKILL.md` bundle rule. The portable source remains `skills/selective-intelligence/`; nested Council roles are reference files here so ChatGPT can store and load the complete package.
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


def build_adapter(destination: Path = ADAPTER_ROOT) -> dict[str, object]:
    metadata_path = PORTABLE_ROOT / "metadata" / "distribution.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    release_files = metadata.get("release_files")
    if not isinstance(release_files, list) or not all(isinstance(item, str) for item in release_files):
        raise ValueError("portable release manifest is invalid")

    mapping = role_path_map(release_files)
    if len(mapping) != 7:
        raise ValueError(f"expected seven nested role skills, found {len(mapping)}")

    destination = destination.resolve()
    expected_parent = (REPO_ROOT / "adapters" / "chatgpt").resolve()
    if destination.parent != expected_parent:
        raise ValueError(f"refusing to replace unexpected adapter destination: {destination}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    adapted_release_files = [mapping.get(relative, relative) for relative in release_files]
    adapter_metadata_path = "metadata/chatgpt-adapter.json"
    adapted_release_files.append(adapter_metadata_path)

    for portable_relative in release_files:
        source = PORTABLE_ROOT / portable_relative
        if not source.is_file():
            raise FileNotFoundError(source)
        adapted_relative = mapping.get(portable_relative, portable_relative)
        target = destination / adapted_relative
        text = source.read_text(encoding="utf-8")
        text = rewrite_text(portable_relative, text, mapping)
        if portable_relative == "metadata/distribution.json":
            payload = json.loads(text)
            payload["distribution_status"] = "public_chatgpt_adapter_release_candidate"
            payload["adapter_for"] = "chatgpt_personal_skills"
            payload["adapter_source_path"] = "skills/selective-intelligence"
            payload["chatgpt_adapter_path"] = "adapters/chatgpt/selective-intelligence"
            payload["archive_name"] = f"selective-intelligence-chatgpt-{payload['version']}.zip"
            payload["release_files"] = adapted_release_files
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        mode = stat.S_IMODE(source.stat().st_mode)
        write_text(target, text, mode)

    adapter_metadata = {
        "schema_version": 1,
        "adapter": "chatgpt_personal_skills",
        "skill": metadata["skill"],
        "version": metadata["version"],
        "portable_source_path": "skills/selective-intelligence",
        "adapter_path": "adapters/chatgpt/selective-intelligence",
        "transformation": "nested_role_skill_entrypoints_to_role_references",
        "single_skill_entrypoint": "SKILL.md",
        "role_path_map": mapping,
        "behavioral_contract": "preserved",
    }
    write_text(
        destination / adapter_metadata_path,
        json.dumps(adapter_metadata, ensure_ascii=False, indent=2) + "\n",
        0o644,
    )

    actual_files = sorted(path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file())
    skill_entrypoints = [path for path in actual_files if Path(path).name == "SKILL.md"]
    if actual_files != sorted(adapted_release_files):
        raise ValueError("generated adapter files do not equal the adapted release manifest")
    if skill_entrypoints != ["SKILL.md"]:
        raise ValueError(f"ChatGPT adapter must contain exactly one SKILL.md: {skill_entrypoints}")

    return {
        "destination": str(destination),
        "files": len(actual_files),
        "skill_entrypoints": skill_entrypoints,
        "role_path_map": mapping,
    }


def build_archive(adapter_root: Path = ADAPTER_ROOT, dist_root: Path = DIST_ROOT) -> dict[str, object]:
    metadata = json.loads((adapter_root / "metadata" / "distribution.json").read_text(encoding="utf-8"))
    archive_path = dist_root / str(metadata["archive_name"])
    dist_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in adapter_root.rglob("*") if item.is_file()):
            relative = Path("selective-intelligence") / path.relative_to(adapter_root)
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IMODE(path.stat().st_mode) & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes())
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
