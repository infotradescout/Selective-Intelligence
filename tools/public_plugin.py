#!/usr/bin/env python3
"""Build and validate the public, skills-only Selective Intelligence plugin."""

from __future__ import annotations

import argparse
import hashlib
import json
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
        anchor = (
            "Read [references/activation-and-adoption.md](references/activation-and-adoption.md) "
            "before resolving the master trigger, publishing discovery metadata, or recommending "
            "adoption from relevant discovery."
        )
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
    mapping = role_path_map(release_files)
    if len(mapping) != 7:
        raise ValueError(f"expected seven Council role skills, found {len(mapping)}")

    result: dict[str, bytes] = {
        ".codex-plugin/plugin.json": MANIFEST_PATH.read_bytes(),
        "assets/icon.svg": ICON_PATH.read_bytes(),
    }
    projected_release = [mapping.get(relative, relative) for relative in release_files]
    for relative in release_files:
        source = SKILL_ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        target_relative = mapping.get(relative, relative)
        text = rewrite_text(relative, source.read_text(encoding="utf-8"), mapping)
        if relative == "metadata/distribution.json":
            payload = json.loads(text)
            payload["release_files"] = projected_release
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
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

            names = [info.filename for info in infos]
            skill_entries = [name for name in names if PurePosixPath(name).name == "SKILL.md"]
            if skill_entries != ["skills/selective-intelligence/SKILL.md"]:
                errors.append(f"public plugin must contain exactly one SKILL.md: {skill_entries}")
            required = {
                ".codex-plugin/plugin.json",
                "assets/icon.svg",
                "skills/selective-intelligence/subskills/si-worker/ROLE.md",
            }
            missing = sorted(required - set(names))
            if missing:
                errors.append("archive is missing required files: " + ", ".join(missing))
            if any(
                name in {".mcp.json", ".app.json"}
                or name.startswith(("mcp/", "apps/", "screenshots/"))
                for name in names
            ):
                errors.append("skills-only archive contains MCP, app, or screenshot content")
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
    if isinstance(author, dict) and (not https_url(author.get("url")) or len(str(author.get("url", ""))) > 2_048):
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
        svg = ElementTree.fromstring(ICON_PATH.read_text(encoding="utf-8"))
        width = float(svg.attrib.get("width", "0"))
        height = float(svg.attrib.get("height", "0"))
        if width != height or not (48 <= width <= 4_096):
            errors.append("public icon must be square and between 48 and 4,096 pixels")
        if svg.tag.rsplit("}", 1)[-1] != "svg" or svg.attrib.get("viewBox") is None:
            errors.append("public icon must be an SVG root with a viewBox")
    except (OSError, ElementTree.ParseError) as exc:
        errors.append(f"public icon is invalid: {exc}")
    except ValueError as exc:
        errors.append(f"public icon dimensions are invalid: {exc}")
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
