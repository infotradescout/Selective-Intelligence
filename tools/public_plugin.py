#!/usr/bin/env python3
"""Build and validate the public, skills-only Selective Intelligence plugin."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from xml.etree import ElementTree


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "selective-intelligence"
MANIFEST_PATH = REPO_ROOT / "plugin-submission" / "plugin.json"
SUBMISSION_PATH = REPO_ROOT / "plugin-submission" / "directory-submission.json"
ICON_PATH = REPO_ROOT / "assets" / "icon.svg"
DIST_ROOT = REPO_ROOT / "dist"
MAX_ENTRIES = 5_000
MAX_COMPRESSED = 100 * 1024 * 1024
MAX_UNCOMPRESSED = 512 * 1024 * 1024
MAX_ENTRY = 100 * 1024 * 1024
MAX_SEGMENTS = 20
MAX_PATH_BYTES = 1_024
MAX_RUNTIME_ENTRIES = 55
MAX_RUNTIME_UNCOMPRESSED = 1 * 1024 * 1024
SUPPORTED_CATEGORIES = {
    "Productivity",
    "Creativity",
    "Developer Tools",
    "Business & Operations",
    "Data & Analytics",
    "Communication",
    "Education & Research",
    "Security",
    "Finance",
    "Healthcare",
    "Travel",
    "Entertainment",
    "Other",
}


def load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path.relative_to(REPO_ROOT)}")
    return payload


def https_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password


def supported_text(value: object, *, multiline: bool = False) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    for character in value:
        codepoint = ord(character)
        if character == "\n" and multiline:
            continue
        if codepoint < 32 or codepoint == 127 or character in {"\u2028", "\u2029"}:
            return False
        if unicodedata.category(character) == "Cf":
            return False
    return multiline or "\n" not in value


def normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(value.split())).casefold()


def svg_dimension_errors(content: bytes | str, label: str) -> list[str]:
    """Match the portal's SVG checks, including its viewBox dimension choice."""
    errors: list[str] = []
    try:
        root = ElementTree.fromstring(content)
    except (ElementTree.ParseError, UnicodeError) as exc:
        return [f"{label}: SVG XML is invalid: {exc}"]
    if root.tag.rsplit("}", 1)[-1] != "svg":
        return [f"{label}: SVG root element must be svg"]

    numeric = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")

    def validate_pair(width_text: str, height_text: str, source: str) -> None:
        if not numeric.fullmatch(width_text) or not numeric.fullmatch(height_text):
            errors.append(f"{label}: {source} dimensions must be numeric and omit units")
            return
        width = float(width_text)
        height = float(height_text)
        if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
            errors.append(f"{label}: {source} dimensions must be positive finite numbers")
        elif width != height:
            errors.append(f"{label}: {source} dimensions must be square")
        elif width < 48 or height < 48:
            errors.append(f"{label}: {source} dimensions must be at least 48x48; found {width:g}x{height:g}")
        elif width > 4_096 or height > 4_096:
            errors.append(f"{label}: {source} dimensions must not exceed 4096x4096")

    view_box = root.attrib.get("viewBox")
    width = root.attrib.get("width")
    height = root.attrib.get("height")
    if view_box is not None:
        values = view_box.split()
        if len(values) != 4 or any(not numeric.fullmatch(value) for value in values):
            errors.append(f"{label}: viewBox must contain four numeric values")
        else:
            validate_pair(values[2], values[3], "viewBox")
    if width is not None or height is not None:
        if width is None or height is None:
            errors.append(f"{label}: SVG width and height must be declared together")
        else:
            validate_pair(width, height, "width/height")
    if view_box is None and width is None and height is None:
        errors.append(f"{label}: SVG must define a numeric viewBox or width and height")
    return errors


def skill_frontmatter_errors(text: str, label: str) -> list[str]:
    """Reject interface metadata that the portal ignores in SKILL.md."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return [f"{label}: SKILL.md must start with YAML frontmatter"]
    parts = text.split("---", 2)
    if len(parts) < 3:
        return [f"{label}: SKILL.md frontmatter is not closed"]
    keys = re.findall(r"(?m)^([A-Za-z_][A-Za-z0-9_-]*):(?:\s|$)", parts[1])
    errors: list[str] = []
    if len(keys) != len(set(keys)):
        errors.append(f"{label}: SKILL.md frontmatter has duplicate top-level keys")
    if set(keys) != {"name", "description"}:
        errors.append(
            f"{label}: SKILL.md frontmatter must contain only name and description; found {', '.join(keys) or 'none'}"
        )
    return errors


def openai_agent_errors(text: str, label: str) -> list[str]:
    """Validate the supported skill interface fields used by the portal."""
    errors: list[str] = []
    if not re.search(r"(?m)^interface:\s*$", text):
        return [f"{label}: agents/openai.yaml must contain interface"]
    values: dict[str, str] = {}
    for key in ("display_name", "short_description", "default_prompt"):
        match = re.search(rf'(?m)^  {key}:\s+"([^"\n]+)"\s*$', text)
        if not match:
            errors.append(f"{label}: interface.{key} must be a quoted, non-empty string")
        else:
            values[key] = match.group(1)
    short_description = values.get("short_description")
    if short_description is not None and not 25 <= len(short_description) <= 64:
        errors.append(f"{label}: interface.short_description must contain 25 to 64 characters")
    default_prompt = values.get("default_prompt")
    if default_prompt is not None and "$selective-intelligence" not in default_prompt:
        errors.append(f"{label}: interface.default_prompt must mention $selective-intelligence")
    return errors


def contrast_against_white(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return 1.05 / (luminance + 0.05)


def role_path_map(release_files: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for relative in release_files:
        parts = PurePosixPath(relative).parts
        if len(parts) == 3 and parts[0] == "subskills" and parts[2] == "SKILL.md":
            mapping[relative] = PurePosixPath(*parts[:-1], "ROLE.md").as_posix()
    return mapping


def rewrite_text(relative: str, text: str, mapping: dict[str, str]) -> str:
    for portable, projected in mapping.items():
        text = text.replace(portable, projected)

    if relative == "SKILL.md":
        anchor = "<!-- SELECTIVE_INTELLIGENCE_RUNTIME_PROJECTION -->"
        addition = """

Public plugin rule: this package intentionally contains exactly one `SKILL.md`. The seven Council role instructions are preserved as `subskills/*/ROLE.md` reference files. Before assigning a bounded Intake, Planner, Worker, Queue Manager, Objector, Aligner, or Verifier role, read that role's reference file and pass only its bounded packet. These role references are part of this one public skill; they are not independently invocable skills.
"""
        if anchor not in text:
            raise ValueError("master skill public-plugin anchor is missing")
        text = text.replace(anchor, anchor + addition, 1)

    if relative == "README.md":
        anchor = "# Selective Intelligence\n"
        version = (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        addition = f"""

> **Public plugin projection.** This generated skills-only package preserves canonical {version} behavior while satisfying the public directory's one-`SKILL.md` rule. The seven Council roles are complete `ROLE.md` references inside the one skill. The repository remains the canonical source; this package is a submission candidate until OpenAI review and publisher publication are complete.
"""
        if not text.startswith(anchor):
            raise ValueError("public-plugin README heading is missing")
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

    if relative == "scripts/eval.py":
        text = text.replace(
            'copied / "subskills" / "si-queue-manager" / "SKILL.md"',
            'copied / "subskills" / "si-queue-manager" / "ROLE.md"',
        )
    return text


def projected_files() -> dict[str, bytes]:
    distribution = load_json(SKILL_ROOT / "metadata" / "distribution.json")
    release_files = distribution.get("release_files")
    if not isinstance(release_files, list) or not all(isinstance(item, str) for item in release_files):
        raise ValueError("canonical release manifest is invalid")
    runtime_files = distribution.get("runtime_files")
    if not isinstance(runtime_files, list) or not runtime_files or not all(isinstance(item, str) for item in runtime_files):
        raise ValueError("runtime file manifest is invalid")
    if len(runtime_files) != len(set(runtime_files)):
        raise ValueError("runtime file manifest contains duplicates")
    if not set(runtime_files).issubset(set(release_files)):
        raise ValueError("runtime file manifest contains files outside the canonical release")
    mapping = role_path_map(runtime_files)
    if len(mapping) != 7:
        raise ValueError(f"expected seven Council role skills, found {len(mapping)}")

    result: dict[str, bytes] = {
        ".codex-plugin/plugin.json": MANIFEST_PATH.read_bytes(),
        "assets/icon.svg": ICON_PATH.read_bytes(),
    }
    for relative in runtime_files:
        source = SKILL_ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        target_relative = mapping.get(relative, relative)
        text = rewrite_text(relative, source.read_text(encoding="utf-8"), mapping)
        result[f"skills/selective-intelligence/{target_relative}"] = text.encode("utf-8")
    return result


def archive_name() -> str:
    distribution = load_json(SKILL_ROOT / "metadata" / "distribution.json")
    public = distribution.get("public_plugin")
    if not isinstance(public, dict) or not isinstance(public.get("archive_name"), str):
        raise ValueError("public_plugin.archive_name is missing")
    return public["archive_name"]


def write_archive(path: Path) -> dict[str, object]:
    files = projected_files()
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in sorted(files):
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, files[relative])
    return {
        "archive": str(path),
        "files": len(files),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "compressed_bytes": path.stat().st_size,
    }


def zip_errors(path: Path) -> list[str]:
    errors: list[str] = []
    if path.stat().st_size > MAX_COMPRESSED:
        errors.append("archive exceeds the 100 MB compressed limit")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                errors.append("archive exceeds the 5,000-entry limit")
            if len(infos) > MAX_RUNTIME_ENTRIES:
                errors.append(f"public runtime archive exceeds the {MAX_RUNTIME_ENTRIES}-file lean limit")
            total = 0
            normalized: dict[str, str] = {}
            regular_paths: set[str] = set()
            normalized_regular_paths: dict[str, str] = {}
            for info in infos:
                name = info.filename
                pure = PurePosixPath(name)
                parts = pure.parts
                total += info.file_size
                if not name or name != name.strip() or "\\" in name:
                    errors.append(f"unsafe archive path: {name!r}")
                raw_parts = name.split("/")
                if (
                    pure.is_absolute()
                    or re.match(r"^[A-Za-z]:", name)
                    or not parts
                    or any(part in {"", ".", ".."} for part in raw_parts)
                ):
                    errors.append(f"unsafe archive path: {name!r}")
                if name != pure.as_posix() or any(part != part.strip() for part in parts):
                    errors.append(f"non-normalized archive path: {name!r}")
                if len(parts) > MAX_SEGMENTS:
                    errors.append(f"archive path is too deep: {name}")
                if len(name.encode("utf-8")) > MAX_PATH_BYTES:
                    errors.append(f"archive path exceeds {MAX_PATH_BYTES} UTF-8 bytes: {name}")
                normalized_name = unicodedata.normalize("NFKC", pure.as_posix()).casefold()
                if normalized_name in normalized:
                    errors.append(
                        f"case or Unicode-normalized archive path collision: {normalized[normalized_name]} and {name}"
                    )
                normalized[normalized_name] = name
                if info.file_size > MAX_ENTRY:
                    errors.append(f"archive entry exceeds the 100 MB limit: {name}")
                if info.flag_bits & 0x1:
                    errors.append(f"encrypted archive entry is not allowed: {name}")
                mode = (info.external_attr >> 16) & 0xFFFF
                if info.is_dir() or not stat.S_ISREG(mode):
                    errors.append(f"archive entry is not a regular file: {name}")
                else:
                    regular_paths.add(pure.as_posix())
                    normalized_regular_paths[normalized_name] = pure.as_posix()
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    errors.append(f"archive entry uses unsupported compression: {name}")
                try:
                    archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    errors.append(f"archive entry is unreadable: {name}: {exc}")
            for file_path in sorted(regular_paths):
                parts = PurePosixPath(file_path).parts
                for index in range(1, len(parts)):
                    parent = PurePosixPath(*parts[:index]).as_posix()
                    normalized_parent = unicodedata.normalize("NFKC", parent).casefold()
                    if normalized_parent in normalized_regular_paths:
                        errors.append(
                            "archive file/directory path conflict: "
                            f"{normalized_regular_paths[normalized_parent]} and {file_path}"
                        )
            if total > MAX_UNCOMPRESSED:
                errors.append("archive exceeds the 512 MiB uncompressed limit")
            if total > MAX_RUNTIME_UNCOMPRESSED:
                errors.append("public runtime archive exceeds the 1 MiB lean limit")

            names = [info.filename for info in infos]
            skill_entries = [name for name in names if PurePosixPath(name).name == "SKILL.md"]
            if skill_entries != ["skills/selective-intelligence/SKILL.md"]:
                errors.append(f"public plugin must contain exactly one SKILL.md: {skill_entries}")
            required = {
                ".codex-plugin/plugin.json",
                "assets/icon.svg",
                "skills/selective-intelligence/agents/openai.yaml",
                "skills/selective-intelligence/assets/icon.svg",
                "skills/selective-intelligence/SKILL.md",
                "skills/selective-intelligence/subskills/si-worker/ROLE.md",
            }
            missing = sorted(required - set(names))
            if missing:
                errors.append("archive is missing required files: " + ", ".join(missing))
            for icon_name in (
                "assets/icon.svg",
                "skills/selective-intelligence/assets/icon.svg",
            ):
                if icon_name in names:
                    errors.extend(svg_dimension_errors(archive.read(icon_name), icon_name))
            skill_name = "skills/selective-intelligence/SKILL.md"
            if skill_name in names:
                try:
                    skill_text = archive.read(skill_name).decode("utf-8")
                except UnicodeDecodeError as exc:
                    errors.append(f"{skill_name}: invalid UTF-8: {exc}")
                else:
                    errors.extend(skill_frontmatter_errors(skill_text, skill_name))
            agent_name = "skills/selective-intelligence/agents/openai.yaml"
            if agent_name in names:
                try:
                    agent_text = archive.read(agent_name).decode("utf-8")
                except UnicodeDecodeError as exc:
                    errors.append(f"{agent_name}: invalid UTF-8: {exc}")
                else:
                    errors.extend(openai_agent_errors(agent_text, agent_name))
            if any(
                name in {".mcp.json", ".app.json"}
                or name.startswith(("mcp/", "apps/", "screenshots/"))
                for name in names
            ):
                errors.append("skills-only archive contains MCP, app, or screenshot content")
            runtime_prefix = "skills/selective-intelligence/"
            forbidden_runtime = {
                f"{runtime_prefix}AI-GUIDE.md",
                f"{runtime_prefix}CHANGELOG.md",
                f"{runtime_prefix}JUMPSTART.md",
                f"{runtime_prefix}LICENSE",
                f"{runtime_prefix}README.md",
                f"{runtime_prefix}scripts/behavior_eval.py",
                f"{runtime_prefix}scripts/eval.py",
                f"{runtime_prefix}scripts/eval_runner.py",
                f"{runtime_prefix}scripts/quality_gate.py",
                f"{runtime_prefix}scripts/release.py",
                f"{runtime_prefix}scripts/site_quality.py",
                f"{runtime_prefix}scripts/site_review_gate.py",
            }
            if any(
                name in forbidden_runtime
                or name.startswith(f"{runtime_prefix}tests/")
                or name.startswith(f"{runtime_prefix}evals/results-")
                for name in names
            ):
                errors.append("public runtime archive contains repository-only development files")
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid plugin archive: {exc}")
    return errors


def collect_ids(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        identifier = value.get("id")
        if isinstance(identifier, str):
            result.add(identifier)
        for child in value.values():
            result.update(collect_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(collect_ids(child))
    return result


def manifest_errors() -> list[str]:
    errors: list[str] = []
    try:
        manifest = load_json(MANIFEST_PATH)
        submission = load_json(SUBMISSION_PATH)
        distribution = load_json(SKILL_ROOT / "metadata" / "distribution.json")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [str(exc)]

    required_strings = ("name", "version", "description", "homepage", "repository", "license", "skills")
    for key in required_strings:
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            errors.append(f"plugin manifest field is missing: {key}")
    if manifest.get("name") != "selective-intelligence":
        errors.append("plugin name must be selective-intelligence")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", str(manifest.get("name", ""))):
        errors.append("plugin name must meet the public directory format and length limit")
    if manifest.get("version") != distribution.get("version"):
        errors.append("plugin, skill, and distribution versions must agree")
    runtime_files = distribution.get("runtime_files")
    release_files = distribution.get("release_files")
    if (
        not isinstance(runtime_files, list)
        or not runtime_files
        or any(not isinstance(item, str) or not item for item in runtime_files)
        or len(runtime_files) != len(set(runtime_files))
    ):
        errors.append("runtime_files must be a non-empty unique string array")
        runtime_files = []
    if not isinstance(release_files, list) or not set(runtime_files).issubset(set(release_files)):
        errors.append("runtime_files must be a subset of release_files")
    if len(runtime_files) + 2 > MAX_RUNTIME_ENTRIES:
        errors.append(f"runtime_files exceed the {MAX_RUNTIME_ENTRIES}-file public package limit")
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", str(manifest.get("version", ""))):
        errors.append("plugin version must be semantic versioning")
    if manifest.get("skills") != "./skills/":
        errors.append("skills-only manifest must use ./skills/")
    if len(str(manifest.get("description", ""))) > 1_024 or not supported_text(manifest.get("description"), multiline=True):
        errors.append("plugin description exceeds 1,024 characters or uses unsupported text")
    if not https_url(manifest.get("homepage")) or not https_url(manifest.get("repository")):
        errors.append("plugin homepage and repository must be HTTPS URLs")
    author = manifest.get("author")
    if not isinstance(author, dict) or not supported_text(author.get("name")) or len(str(author.get("name", ""))) > 120:
        errors.append("plugin author name is missing, unsupported, or too long")
    if (
        isinstance(author, dict)
        and author.get("url") is not None
        and (not https_url(author.get("url")) or len(str(author.get("url", ""))) > 2_048)
    ):
        errors.append("plugin author URL is invalid or too long")

    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        errors.append("plugin interface is missing")
        interface = {}
    if isinstance(author, dict) and author.get("name") != interface.get("developerName"):
        errors.append("plugin author and developer names must match for the final listing")
    limits = {"displayName": 30, "shortDescription": 30, "longDescription": 4_000, "developerName": 80}
    for key, limit in limits.items():
        value = interface.get(key)
        multiline = key == "longDescription"
        if not supported_text(value, multiline=multiline):
            errors.append(f"plugin interface field is missing: {key}")
        elif len(value) > limit:
            errors.append(f"plugin interface field exceeds {limit} characters: {key}")
    if interface.get("category") not in SUPPORTED_CATEGORIES:
        errors.append("plugin category is not supported")
    capabilities = interface.get("capabilities")
    if not isinstance(capabilities, list) or len(capabilities) > 20:
        errors.append("plugin capabilities must contain at most 20 entries")
    else:
        for capability in capabilities:
            if not supported_text(capability) or len(capability) > 120:
                errors.append("plugin capability is empty, unsupported, multiline, or too long")
    for key in ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL"):
        if not https_url(interface.get(key)) or len(str(interface.get(key, ""))) > 1_024:
            errors.append(f"plugin interface URL is invalid: {key}")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(interface.get("brandColor", ""))):
        errors.append("brandColor must be a six-digit hex color")
    elif contrast_against_white(str(interface["brandColor"])) < 2:
        errors.append("brandColor must have at least 2:1 contrast against white")
    if interface.get("composerIcon") != "./assets/icon.svg" or interface.get("logo") != "./assets/icon.svg":
        errors.append("plugin icons must resolve to ./assets/icon.svg")
    prompts = interface.get("defaultPrompt")
    if not isinstance(prompts, list) or not (1 <= len(prompts) <= 3):
        errors.append("defaultPrompt must contain one to three prompts")
    else:
        normalized_prompts: set[str] = set()
        for prompt in prompts:
            if not supported_text(prompt) or len(prompt) > 128 or re.search(r"(?:^|\s)@[A-Za-z0-9_]", str(prompt)):
                errors.append("defaultPrompt entry is unsupported, multiline, too long, or contains an app mention")
                continue
            normalized = normalized_text(prompt)
            if normalized in normalized_prompts:
                errors.append("defaultPrompt entries must be unique after Unicode and whitespace normalization")
            normalized_prompts.add(normalized)
    if "mcpServers" in manifest or "apps" in manifest or "screenshots" in interface:
        errors.append("skills-only manifest cannot declare MCP servers, apps, or screenshots")

    public = distribution.get("public_plugin")
    if not isinstance(public, dict):
        errors.append("distribution public_plugin metadata is missing")
    else:
        expected = {
            "status": "submission_candidate",
            "submission_type": "skills_only",
            "manifest_source": "plugin-submission/plugin.json",
            "archive_manifest_path": ".codex-plugin/plugin.json",
            "submission_manifest": "plugin-submission/directory-submission.json",
        }
        for key, value in expected.items():
            if public.get(key) != value:
                errors.append(f"public_plugin.{key} must be {value}")
        url_pairs = {
            "website_url": "websiteURL",
            "support_url": "supportURL",
            "privacy_policy_url": "privacyPolicyURL",
            "terms_of_service_url": "termsOfServiceURL",
        }
        for public_key, interface_key in url_pairs.items():
            if public.get(public_key) != interface.get(interface_key):
                errors.append(f"public_plugin.{public_key} differs from the listing interface")

    if submission.get("plugin") != manifest.get("name") or submission.get("version") != manifest.get("version"):
        errors.append("directory submission identity differs from the plugin manifest")
    if submission.get("submission_type") != "skills_only":
        errors.append("directory submission must be skills_only")
    availability = submission.get("availability")
    if not isinstance(availability, dict) or availability.get("audience") != "public" or availability.get("regions") != "global":
        errors.append("directory submission availability must be public and global")
    if not supported_text(submission.get("release_notes"), multiline=True):
        errors.append("directory submission release notes are missing or use unsupported text")
    positive = submission.get("positive_test_cases")
    negative = submission.get("negative_test_cases")
    if not isinstance(positive, list) or len(positive) != 5:
        errors.append("directory submission must include exactly five positive test cases")
        positive = []
    if not isinstance(negative, list) or len(negative) != 3:
        errors.append("directory submission must include exactly three negative test cases")
        negative = []
    canonical_ids = collect_ids(load_json(SKILL_ROOT / "evals" / "evals.json"))
    seen: set[str] = set()
    for kind, cases, fields in (
        ("positive", positive, ("id", "user_prompt", "expected_behavior", "expected_result_shape", "fixture_data")),
        ("negative", negative, ("id", "scenario", "expected_safe_behavior", "why_not_complete", "fixture_data")),
    ):
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                errors.append(f"{kind} test case {index} is not an object")
                continue
            for field in fields:
                value = case.get(field)
                if field == "expected_behavior":
                    valid = (
                        isinstance(value, list)
                        and bool(value)
                        and all(supported_text(item, multiline=True) for item in value)
                    )
                else:
                    valid = supported_text(value, multiline=True)
                if not valid:
                    errors.append(f"{kind} test case {index} has invalid {field}")
            identifier = case.get("id")
            if isinstance(identifier, str):
                if identifier not in canonical_ids:
                    errors.append(f"directory test case is not backed by canonical evals: {identifier}")
                if identifier in seen:
                    errors.append(f"duplicate directory test case: {identifier}")
                seen.add(identifier)

    try:
        errors.extend(svg_dimension_errors(ICON_PATH.read_bytes(), "assets/icon.svg"))
        errors.extend(
            svg_dimension_errors(
                (SKILL_ROOT / "assets" / "icon.svg").read_bytes(),
                "skills/selective-intelligence/assets/icon.svg",
            )
        )
        errors.extend(
            skill_frontmatter_errors(
                (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"),
                "skills/selective-intelligence/SKILL.md",
            )
        )
        errors.extend(
            openai_agent_errors(
                (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"),
                "skills/selective-intelligence/agents/openai.yaml",
            )
        )
    except OSError as exc:
        errors.append(f"public skill branding or interface file is unreadable: {exc}")
    if ICON_PATH.stat().st_size > 5 * 1024 * 1024:
        errors.append("public icon exceeds 5 MiB")
    if ICON_PATH.read_bytes() != (SKILL_ROOT / "assets" / "icon.svg").read_bytes():
        errors.append("public and canonical icons differ")
    if (REPO_ROOT / ".codex-plugin" / "plugin.json").exists():
        errors.append("repository must keep the archive manifest source under plugin-submission, not a root .codex-plugin")
    for required in (REPO_ROOT / "PRIVACY.md", REPO_ROOT / "TERMS.md"):
        if not required.is_file():
            errors.append(f"public policy file is missing: {required.name}")
    return errors


def canonical_doctor_errors() -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-B", str(SKILL_ROOT / "scripts" / "release.py"), "doctor", "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        return []
    try:
        payload = json.loads(completed.stdout)
        errors = payload.get("errors")
        if isinstance(errors, list):
            return [f"canonical release doctor: {item}" for item in errors]
    except json.JSONDecodeError:
        pass
    return [f"canonical release doctor failed: {completed.stderr.strip() or completed.stdout.strip()}"]


def doctor() -> dict[str, object]:
    errors = manifest_errors()
    errors.extend(canonical_doctor_errors())
    files = 0
    temporary = Path(tempfile.mkdtemp(prefix="si-public-plugin-doctor-", dir=REPO_ROOT))
    try:
        archive_path = temporary / archive_name()
        result = write_archive(archive_path)
        files = int(result["files"])
        errors.extend(zip_errors(archive_path))
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read(".codex-plugin/plugin.json"))
            if manifest != load_json(MANIFEST_PATH):
                errors.append("archive manifest differs from its canonical submission source")
            master = archive.read("skills/selective-intelligence/SKILL.md").decode("utf-8")
            if "Public plugin rule:" not in master:
                errors.append("projected master skill is missing the public plugin rule")
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        errors.append(str(exc))
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "files": files,
        "skill_entrypoints": ["skills/selective-intelligence/SKILL.md"] if not errors else [],
    }


def command_doctor(args: argparse.Namespace) -> int:
    result = doctor()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["status"] == "pass":
        print(f"Public plugin is ready to package ({result['files']} files).")
    else:
        for error in result["errors"]:
            print(f"ERROR: {error}")
    return 0 if result["status"] == "pass" else 1


def command_package(args: argparse.Namespace) -> int:
    validation = doctor()
    if validation["status"] != "pass":
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 1
    destination = Path(args.output_dir).resolve() / archive_name()
    if destination.exists() and not args.force:
        print(f"refusing to replace existing archive without --force: {destination}", file=sys.stderr)
        return 1
    result = write_archive(destination)
    errors = zip_errors(destination)
    if errors:
        print(json.dumps({"status": "fail", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "pass", **result}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(handler=command_doctor)
    package_parser = subparsers.add_parser("package")
    package_parser.add_argument("--output-dir", default=str(DIST_ROOT))
    package_parser.add_argument("--force", action="store_true")
    package_parser.set_defaults(handler=command_package)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
