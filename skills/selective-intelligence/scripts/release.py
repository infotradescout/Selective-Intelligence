#!/usr/bin/env python3
"""Validate and package a portable Selective Intelligence release.

This utility has no network or publication behavior. It creates one reproducible
standalone skill archive and a SHA-256 checksum after local release gates pass.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse

# Release validation must not mutate the artifact it is validating.
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
import behavior_eval


SKILL_ROOT = Path(__file__).resolve().parents[1]
TOPIC_RE = re.compile(r"^[a-z0-9-]{1,50}$")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
ALLOWED_TOP_LEVEL_FILES = {
    "SKILL.md",
    "JUMPSTART.md",
    "LICENSE",
    "VERSION",
    "CHANGELOG.md",
    "README.md",
}
ALLOWED_TOP_LEVEL_DIRS = {
    "agents", "assets", "evals", "lanes", "metadata", "references", "schemas", "scripts", "subskills", "tests"
}
FORBIDDEN_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "dist"}
FORBIDDEN_NAMES = {"events.jsonl", "lock.json", ".env", ".env.local", ".env.production"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)
JUMPSTART_MANIFEST_BEGIN = "<!-- SELECTIVE_INTELLIGENCE_JUMPSTART_MANIFEST_BEGIN -->"
JUMPSTART_MANIFEST_END = "<!-- SELECTIVE_INTELLIGENCE_JUMPSTART_MANIFEST_END -->"
PRODUCT_SPECIFIC_BRANDS = tuple(
    re.compile(rf"\b{prefix}{suffix}\b")
    for prefix, suffix in (("Meal", "Scout"), ("Trade", "Scout"))
)
FORBIDDEN_HANDOFF_QUESTION = "What outcome do you want to create or complete?"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def string_list_sha256(values: list[str]) -> str:
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def safe_release_file(root: Path, relative: Path) -> tuple[Path | None, str | None]:
    """Resolve a release file without following any symlink component."""
    if relative.is_absolute() or ".." in relative.parts:
        return None, "path is not a canonical relative path"
    candidate = root / relative
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None, f"symlink component is not allowed: {cursor.relative_to(root)}"
    try:
        release_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        return None, f"file cannot be resolved: {exc}"
    if resolved != release_root and release_root not in resolved.parents:
        return None, "resolved path escapes the skill root"
    if not resolved.is_file():
        return None, "path is not a regular file"
    return candidate, None


def https_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def frontmatter_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*['\"]?([^'\"\n]+)['\"]?\s*$", text)
    return match.group(1).strip() if match else None


def frontmatter_version(text: str) -> str | None:
    frontmatter = text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""
    match = re.search(r'(?ms)^metadata:\s*\n(?:^[ \t]+.*\n)*?^[ \t]+version:\s*["\']?([^"\'\n]+)', frontmatter)
    return match.group(1).strip() if match else None


def read_distribution_metadata(root: Path) -> tuple[dict[str, object] | None, list[str]]:
    metadata_path, path_error = safe_release_file(root, Path("metadata/distribution.json"))
    if path_error or metadata_path is None:
        return None, [f"distribution metadata is missing or unsafe: {path_error}"]
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"invalid distribution metadata: {exc}"]
    if not isinstance(payload, dict):
        return None, ["distribution metadata must be an object"]
    return payload, []


def release_files(root: Path, metadata: dict[str, object]) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    errors: list[str] = []
    declared = metadata.get("release_files")
    if (
        not isinstance(declared, list)
        or not declared
        or any(not isinstance(item, str) or not item for item in declared)
        or len(declared) != len(set(declared))
    ):
        return [], ["distribution release_files must be a non-empty unique string array"]

    declared_set = set(declared)
    for relative_text in sorted(declared_set):
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != relative_text:
            errors.append(f"unsafe release manifest path: {relative_text}")
            continue
        if relative.parts[0] not in ALLOWED_TOP_LEVEL_FILES | ALLOWED_TOP_LEVEL_DIRS:
            errors.append(f"release manifest path is outside the portable skill surface: {relative_text}")
            continue
        if any(part in FORBIDDEN_PARTS for part in relative.parts):
            errors.append(f"generated path must not ship: {relative_text}")
            continue
        path, path_error = safe_release_file(root, relative)
        if path_error or path is None:
            errors.append(f"missing or unsafe declared release file {relative_text}: {path_error}")
            continue
        if path.name in FORBIDDEN_NAMES or path.suffix in {".pyc", ".pyo"} or path.name.startswith(".env"):
            errors.append(f"private or generated file must not ship: {relative_text}")
            continue
        files.append(path)

    actual: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() and not path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part == ".git" for part in relative.parts):
            continue
        actual.add(relative.as_posix())
    for relative_text in sorted(actual - declared_set):
        errors.append(f"unlisted release file requires explicit review: {relative_text}")
    for required in sorted(ALLOWED_TOP_LEVEL_FILES):
        if required not in declared_set:
            errors.append(f"release manifest is missing required file: {required}")
    for required_dir in sorted(ALLOWED_TOP_LEVEL_DIRS):
        if not any(item.startswith(f"{required_dir}/") for item in declared_set):
            errors.append(f"release manifest has no files for required directory: {required_dir}")

    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            errors.append(f"release file is not readable UTF-8 text: {path.relative_to(root)} ({exc})")
            continue
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            errors.append(f"secret-like content must not ship: {path.relative_to(root)}")
    return sorted(set(files)), errors


def public_contract_errors(root: Path, files: list[Path]) -> list[str]:
    """Keep the portable public contract product-neutral and autonomous."""
    errors: list[str] = []
    active_contracts = {
        "SKILL.md",
        "JUMPSTART.md",
        "README.md",
        "references/activation-and-adoption.md",
        "subskills/si-intake/SKILL.md",
    }
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(root).as_posix()
        for pattern in PRODUCT_SPECIFIC_BRANDS:
            if pattern.search(content):
                errors.append(
                    f"product-specific brand is not allowed in the public skill contract: {relative}"
                )
        if relative in active_contracts and FORBIDDEN_HANDOFF_QUESTION in content:
            errors.append(
                f"generic master-trigger handoff question is not allowed in the active public contract: {relative}"
            )
    return errors


def markdown_link_errors(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    included = {item.resolve() for item in files}
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for raw in LINK_RE.findall(text):
            target = raw.strip().strip("<>").split(maxsplit=1)[0]
            parsed = urlparse(target)
            if parsed.scheme or target.startswith(("#", "mailto:")):
                continue
            local = target.split("#", 1)[0]
            if not local:
                continue
            destination = (path.parent / local).resolve(strict=False)
            release_root = root.resolve()
            if destination != release_root and release_root not in destination.parents:
                errors.append(f"off-root local link in {path.relative_to(root)}: {target}")
            elif not destination.exists():
                errors.append(f"broken local link in {path.relative_to(root)}: {target}")
            elif destination.is_file() and destination not in included:
                errors.append(f"link target is not included in the release in {path.relative_to(root)}: {target}")
            elif destination.is_dir() and not any(destination == item.parent or destination in item.parents for item in included):
                errors.append(f"linked directory is empty in the release in {path.relative_to(root)}: {target}")
    return errors


def jumpstart_errors(root: Path, council_version: str | None) -> list[str]:
    path = root / "JUMPSTART.md"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"JUMPSTART.md is missing or unreadable: {exc}"]
    errors: list[str] = []
    if content.count(JUMPSTART_MANIFEST_BEGIN) != 1 or content.count(JUMPSTART_MANIFEST_END) != 1:
        return ["JUMPSTART.md must contain exactly one fixed-marker bootstrap manifest"]
    begin = content.index(JUMPSTART_MANIFEST_BEGIN) + len(JUMPSTART_MANIFEST_BEGIN)
    end = content.index(JUMPSTART_MANIFEST_END)
    if begin >= end:
        return ["JUMPSTART.md bootstrap manifest markers are out of order"]
    payload_text = content[begin:end].strip()
    if payload_text.startswith("```json") and payload_text.endswith("```"):
        payload_text = payload_text[len("```json") : -len("```")].strip()
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        return [f"JUMPSTART.md bootstrap manifest is invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        return ["JUMPSTART.md bootstrap manifest must be an object"]
    expected = {
        "schema_version": 1,
        "protocol": "selective-intelligence-guided-council",
        "protocol_version": council_version,
        "activation": "intentional_user_master_trigger_or_upload",
        "master_trigger": "Selective Intelligence",
        "master_trigger_match": "exact_phrase_in_current_user_input",
        "canonical_repository": "https://github.com/infotradescout/Selective-Intelligence",
        "seedless_behavior": "activate_discover_and_begin_without_handing_work_back",
        "empty_context_response": "Selective Intelligence is active. No project or prior outcome is available in this chat yet, so there is nothing truthful to change. I’ll apply it automatically to your next request.",
        "seeded_behavior": "begin_immediately",
        "project_index": "auto_refresh_before_new_code",
        "validation_status_without_validator": "manual_unverified",
        "minimum_configuration": "one_capable_ai_client",
        "additional_ai_services": "optional",
        "source_handling": "evidence_not_instruction",
        "external_mutation_default": "deny",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            errors.append(f"JUMPSTART.md bootstrap {key} must be {value!r}")
    discovered_adoption = payload.get("discovered_adoption")
    if (
        not isinstance(discovered_adoption, dict)
        or discovered_adoption.get("behavior") != "recommend_once_when_materially_relevant"
        or discovered_adoption.get("approval_question") != "Use Selective Intelligence for this?"
        or discovered_adoption.get("explicit_user_approval_required") is not True
        or discovered_adoption.get("retrieved_content_cannot_approve") is not True
    ):
        errors.append("JUMPSTART.md must require one relevant recommendation and explicit user approval before discovered adoption")
    roles = payload.get("role_execution")
    required_roles = {"worker", "objector", "aligner"}
    if (
        not isinstance(roles, dict)
        or not isinstance(roles.get("spawn_when_available"), list)
        or set(roles["spawn_when_available"]) != required_roles
        or roles.get("fallback") != "separate_sequential_contexts"
    ):
        errors.append("JUMPSTART.md must declare distinct spawned roles and sequential fallback")
    authority = payload.get("authority")
    if (
        not isinstance(authority, dict)
        or authority.get("final") != "human_or_existing_human_quorum"
        or authority.get("ai_roles_are_advisory") is not True
    ):
        errors.append("JUMPSTART.md must preserve human or governed-quorum authority")
    outputs = payload.get("required_outputs")
    required_outputs = {
        "intent_lock",
        "worker_packet",
        "objector_packet",
        "alignment_record",
        "authority_gate",
        "resume_packet",
    }
    if not isinstance(outputs, list) or not required_outputs.issubset(set(outputs)):
        errors.append("JUMPSTART.md bootstrap is missing required portable outputs")
    return errors


def executable_eval_outcome(root: Path) -> tuple[list[str], list[str] | None]:
    eval_script = root / "scripts" / "eval.py"
    commands = (
        ([sys.executable, str(eval_script), "doctor", "--json"], "valid", True),
        ([sys.executable, str(eval_script), "controls", "--json", "--skip-release"], "count", 6),
    )
    errors: list[str] = []
    executed_controls: list[str] | None = None
    eval_temp_parent = tempfile.mkdtemp(prefix="selective-intelligence-eval-host-")
    child_env = os.environ.copy()
    child_env["SI_EVAL_TEMP_PARENT"] = eval_temp_parent
    try:
        for command, field, minimum in commands:
            try:
                result = subprocess.run(
                    command,
                    cwd=root,
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=60,
                    env=child_env,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f"executable eval failed to run: {exc}")
                continue
            if result.returncode != 0:
                errors.append(f"executable eval returned {result.returncode}: {Path(command[1]).name} {' '.join(command[2:])}")
                continue
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                errors.append("executable eval did not return machine-readable JSON")
                continue
            if field == "valid" and payload.get(field) is not minimum:
                errors.append("eval fixture doctor did not report valid=true")
            elif field == "count" and (not isinstance(payload.get(field), int) or payload[field] < minimum):
                errors.append(f"control eval reported fewer than {minimum} passing controls")
            elif field == "count":
                passed = payload.get("passed")
                if (
                    not isinstance(passed, list)
                    or any(not isinstance(item, str) or not item for item in passed)
                    or len(passed) != payload.get("count")
                    or len(set(passed)) != len(passed)
                ):
                    errors.append("control eval returned an inconsistent passing-control list")
                else:
                    executed_controls = passed
    finally:
        shutil.rmtree(eval_temp_parent, ignore_errors=True)
    return errors, executed_controls


def local_schema_reference_errors(schema: dict[str, object], label: str) -> list[str]:
    errors: list[str] = []

    def resolve(reference: str) -> bool:
        if not reference.startswith("#/"):
            return False
        target: object = schema
        for raw_part in reference[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return False
            target = target[part]
        return True

    def visit(node: object, location: str) -> None:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if reference is not None:
                if not isinstance(reference, str) or not resolve(reference):
                    errors.append(f"unresolved or non-local {label} schema reference at {location}: {reference!r}")
            for key, value in node.items():
                visit(value, f"{location}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{location}/{index}")

    visit(schema, "#")
    return errors


def schema_property_consts(schema: object, property_name: str) -> set[object]:
    values: set[object] = set()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                candidate = properties.get(property_name)
                if isinstance(candidate, dict) and "const" in candidate:
                    value = candidate["const"]
                    if isinstance(value, (str, int, bool)) or value is None:
                        values.add(value)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return values


def schema_errors(
    root: Path,
    release_files: list[Path],
    start_pack_version: str | None,
    council_version: str | None,
) -> list[str]:
    schema_paths = sorted(
        path
        for path in release_files
        if path.parent == root / "schemas" and path.suffix == ".json"
    )
    errors: list[str] = []
    if not schema_paths:
        return ["release manifest must include at least one JSON Schema"]

    seen_names = {path.name for path in schema_paths}
    for required_name in ("start-pack.schema.json", "council-packet.schema.json"):
        if required_name not in seen_names:
            errors.append(f"release manifest is missing required schema: {required_name}")

    for path in schema_paths:
        label = "Start Pack" if path.name == "start-pack.schema.json" else path.name
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid {label} JSON Schema: {exc}")
            continue
        if not isinstance(schema, dict):
            errors.append(f"{label} JSON Schema must be an object")
            continue
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{label} schema must declare JSON Schema draft 2020-12")
        errors.extend(local_schema_reference_errors(schema, label))

        if path.name == "start-pack.schema.json":
            properties = schema.get("properties")
            if not isinstance(properties, dict):
                errors.append("Start Pack schema needs a properties object")
                continue
            if properties.get("schema_version") != {"const": 1}:
                errors.append("Start Pack schema_version must be const 1")
            if properties.get("validator_version") != {"const": start_pack_version}:
                errors.append(
                    f"Start Pack schema validator_version must be const {start_pack_version!r}"
                )
            required = schema.get("required")
            required_controls = {
                "schema_version",
                "validator_version",
                "project",
                "release",
                "authority",
                "verdicts",
                "artifacts",
                "requirements",
                "builds",
                "independent_review",
                "seal_history",
            }
            if not isinstance(required, list) or not required_controls.issubset(set(required)):
                errors.append("Start Pack schema is missing required control-graph fields")
            definitions = schema.get("$defs")
            if not isinstance(definitions, dict):
                errors.append("Start Pack schema needs portable $defs")
            elif not {"id", "idArray", "relativePath", "evidenceContext"}.issubset(definitions):
                errors.append("Start Pack schema is missing required portable definitions")
        elif path.name == "council-packet.schema.json":
            protocol_values = schema_property_consts(schema, "protocol_version")
            schema_values = schema_property_consts(schema, "schema_version")
            if council_version not in protocol_values | schema_values:
                errors.append(
                    f"Council packet schema must bind its protocol/schema version to {council_version!r}"
                )
    return errors


def released_result_history_errors(root: Path, release_files: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in release_files:
        if path.parent != root / "evals" or not re.fullmatch(r"results-(.+)\.json", path.name):
            continue
        expected_version = path.name.removeprefix("results-").removesuffix(".json")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid released eval result {path.name}: {exc}")
            continue
        if not isinstance(record, dict):
            errors.append(f"released eval result {path.name} must be an object")
            continue
        if (
            record.get("schema_version") != 1
            or record.get("skill") != "selective-intelligence"
            or record.get("version") != expected_version
        ):
            errors.append(f"released eval result {path.name} has inconsistent identity")
        if "model_client_matrix" in record:
            errors.append(f"released eval result {path.name} uses an ambiguous legacy model_client_matrix claim")
        model_behavior = record.get("model_behavior_evaluation")
        if not isinstance(model_behavior, dict) or model_behavior.get("result") not in {"pass", "not_run", "fail"}:
            errors.append(f"released eval result {path.name} must explicitly classify model behavior execution")
    return errors


def current_eval_case_ids(root: Path) -> tuple[set[str] | None, list[str]]:
    path, path_error = safe_release_file(root, Path("evals/evals.json"))
    if path_error or path is None:
        return None, [f"current eval declarations are missing or unsafe: {path_error}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"current eval declarations are invalid: {exc}"]
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("skill") != "selective-intelligence":
        return None, ["current eval declarations have the wrong schema_version or skill"]
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return None, ["current eval declarations must contain a cases array"]
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(cases) or any(not isinstance(case_id, str) or not case_id for case_id in ids) or len(ids) != len(set(ids)):
        return None, ["current eval declarations need unique non-empty case IDs"]
    return set(ids), []


def model_run_artifact_errors(
    path: Path,
    version: str | None,
    model_client: str,
    observed_at: object,
    expected_case_ids: set[str],
) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"model run artifact is not valid JSON: {exc}"]
    if not isinstance(payload, dict):
        return ["model run artifact must be an object"]
    errors: list[str] = []
    if (
        payload.get("schema_version") != 1
        or payload.get("skill") != "selective-intelligence"
        or payload.get("version") != version
    ):
        errors.append("model run artifact has inconsistent skill/version identity")
    if payload.get("model_client") != model_client:
        errors.append("model run artifact model_client does not match its evidence record")
    if payload.get("observed_at") != observed_at:
        errors.append("model run artifact observed_at does not match its evidence record")
    if payload.get("result") != "pass":
        errors.append("model run artifact must report result=pass")
    case_results = payload.get("cases")
    if not isinstance(case_results, list):
        errors.append("model run artifact must contain case results")
        return errors
    seen: set[str] = set()
    for case_index, case_result in enumerate(case_results):
        if not isinstance(case_result, dict):
            errors.append(f"model run case result {case_index} must be an object")
            continue
        case_id = case_result.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            errors.append(f"model run case result {case_index} needs a unique declared case ID")
            continue
        seen.add(case_id)
        if case_result.get("result") != "pass":
            errors.append(f"model run case {case_id} did not pass")
    missing = sorted(expected_case_ids - seen)
    unexpected = sorted(seen - expected_case_ids)
    if missing:
        errors.append(f"model run artifact is missing declared cases: {missing}")
    if unexpected:
        errors.append(f"model run artifact contains undeclared cases: {unexpected}")
    return errors


def uses_evidence_bearing_behavior_schema(version: str | None) -> bool:
    """Use the stronger behavior artifact contract for 0.3.0 and later."""
    if not isinstance(version, str):
        return False
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", version)
    if match is None:
        return False
    return tuple(int(part) for part in match.groups()) >= (0, 3, 0)


def behavior_model_run_artifact_errors(
    path: Path,
    version: str | None,
    model_client: str,
    observed_at: object,
) -> list[str]:
    """Validate a 0.3.0+ artifact against the hidden-oracle behavior suite."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"behavior model run artifact is not valid JSON: {exc}"]
    if not isinstance(payload, dict):
        return ["behavior model run artifact must be an object"]
    errors: list[str] = []
    if payload.get("version") != version:
        errors.append("behavior model run version does not match the release")
    if payload.get("model_client") != model_client:
        errors.append("behavior model run model_client does not match its evidence record")
    if payload.get("observed_at") != observed_at:
        errors.append("behavior model run observed_at does not match its evidence record")
    if payload.get("result") != "pass":
        errors.append("behavior model run artifact must report result=pass")
    _, cases, case_errors = behavior_eval.load_cases()
    errors.extend(f"behavior suite: {error}" for error in case_errors)
    if not case_errors:
        errors.extend(behavior_eval.validate_run(payload, cases))
    return errors


def result_record_errors(
    root: Path,
    version: str | None,
    require_model_behavior: bool,
    release_files: list[Path],
    executed_controls: list[str] | None,
) -> tuple[dict[str, object] | None, list[str]]:
    expected = root / "evals" / f"results-{version}.json"
    try:
        result = json.loads(expected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"invalid current eval result record {expected.name}: {exc}"]
    if not isinstance(result, dict):
        return None, [f"current eval result record {expected.name} must be an object"]
    errors: list[str] = []
    if result.get("schema_version") != 1 or result.get("skill") != "selective-intelligence":
        errors.append("current eval result record has the wrong schema_version or skill")
    if result.get("version") != version:
        errors.append(f"current eval result version must be {version!r}")
    allowed_statuses = {"local_release_candidate_pass", "public_release_candidate_pass"}
    if result.get("status") not in allowed_statuses:
        errors.append("current eval result must use a passing release-candidate status")
    if require_model_behavior and result.get("status") != "public_release_candidate_pass":
        errors.append("public release requires public_release_candidate_pass result status")
    observed_at = result.get("observed_at")
    try:
        observed_timestamp = dt.datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
    except ValueError:
        observed_timestamp = None
    if observed_timestamp is None or observed_timestamp.tzinfo is None:
        errors.append("current eval result observed_at must be an ISO-8601 timestamp with timezone")
    elif observed_timestamp > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        errors.append("current eval result observed_at may not be in the future")
    deterministic = result.get("deterministic_controls")
    if (
        not isinstance(deterministic, dict)
        or deterministic.get("result") != "pass"
        or not isinstance(deterministic.get("passed"), int)
        or deterministic.get("passed", 0) < 1
        or deterministic.get("failed") != 0
    ):
        errors.append("current eval result must record passing deterministic controls with zero failures")
    elif (
        not isinstance(deterministic.get("coverage"), list)
        or not deterministic["coverage"]
        or any(not isinstance(item, str) or not item.strip() for item in deterministic["coverage"])
    ):
        errors.append("current eval result must name deterministic control coverage")
    if isinstance(deterministic, dict) and executed_controls is not None:
        if deterministic.get("passed") != len(executed_controls):
            errors.append(
                "current eval result deterministic pass count does not match the controls executed by release doctor"
            )
        expected_control_digest = string_list_sha256(executed_controls)
        if deterministic.get("executed_controls_sha256") != expected_control_digest:
            errors.append(
                "current eval result deterministic control identity does not match the controls executed by release doctor"
            )
    model_behavior = result.get("model_behavior_evaluation")
    if not isinstance(model_behavior, dict) or model_behavior.get("result") not in {"pass", "not_run", "fail"}:
        errors.append("current eval result must explicitly classify model_behavior_evaluation")
    elif model_behavior.get("result") == "pass":
        evidence_bearing_behavior = uses_evidence_bearing_behavior_schema(version)
        expected_case_ids: set[str] | None = None
        if not evidence_bearing_behavior:
            expected_case_ids, case_id_errors = current_eval_case_ids(root)
            errors.extend(case_id_errors)
        evidence = model_behavior.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append("passing model behavior evaluation requires reproducible evidence records")
        else:
            seen_artifacts: set[str] = set()
            for index, item in enumerate(evidence):
                if not isinstance(item, dict):
                    errors.append(f"model behavior evidence {index} must be an object")
                    continue
                required = {"model_client", "observed_at", "artifact", "sha256"}
                if not required.issubset(item) or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256", ""))):
                    errors.append(f"model behavior evidence {index} lacks reproducible identity")
                    continue
                if not isinstance(item.get("model_client"), str) or not item["model_client"].strip():
                    errors.append(f"model behavior evidence {index} lacks a model/client identity")
                try:
                    evidence_timestamp = dt.datetime.fromisoformat(str(item.get("observed_at")).replace("Z", "+00:00"))
                except ValueError:
                    evidence_timestamp = None
                if evidence_timestamp is None or evidence_timestamp.tzinfo is None:
                    errors.append(f"model behavior evidence {index} needs an ISO-8601 timestamp with timezone")
                elif evidence_timestamp > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
                    errors.append(f"model behavior evidence {index} observed_at may not be in the future")
                artifact_text = item.get("artifact")
                artifact_relative = Path(artifact_text) if isinstance(artifact_text, str) else None
                if (
                    artifact_relative is None
                    or artifact_relative.is_absolute()
                    or ".." in artifact_relative.parts
                    or artifact_relative.as_posix() != artifact_text
                ):
                    errors.append(f"model behavior evidence {index} has an unsafe artifact path")
                    continue
                if (
                    len(artifact_relative.parts) < 3
                    or artifact_relative.parts[:2] != ("evals", "model-runs")
                    or artifact_relative.suffix != ".json"
                ):
                    errors.append(
                        f"model behavior evidence {index} must use a dedicated evals/model-runs JSON artifact"
                    )
                    continue
                if artifact_text in seen_artifacts:
                    errors.append(f"model behavior evidence {index} repeats an artifact")
                seen_artifacts.add(artifact_text)
                artifact_path, artifact_path_error = safe_release_file(root, artifact_relative)
                if artifact_path_error or artifact_path is None:
                    errors.append(
                        f"model behavior evidence {index} artifact is missing or unsafe: {artifact_path_error}"
                    )
                elif artifact_path not in release_files:
                    errors.append(f"model behavior evidence {index} artifact is absent from the release manifest")
                elif sha256(artifact_path) != item["sha256"]:
                    errors.append(f"model behavior evidence {index} artifact digest does not match")
                elif evidence_bearing_behavior:
                    for artifact_error in behavior_model_run_artifact_errors(
                        artifact_path,
                        version,
                        item["model_client"],
                        item.get("observed_at"),
                    ):
                        errors.append(f"model behavior evidence {index}: {artifact_error}")
                elif expected_case_ids is not None:
                    for artifact_error in model_run_artifact_errors(
                        artifact_path,
                        version,
                        item["model_client"],
                        item.get("observed_at"),
                        expected_case_ids,
                    ):
                        errors.append(f"model behavior evidence {index}: {artifact_error}")
    if require_model_behavior and (
        not isinstance(model_behavior, dict) or model_behavior.get("result") != "pass"
    ):
        errors.append("public release requires a passing reproducible model behavior evaluation")
    return result, errors


def doctor(root: Path, require_public: bool, require_support: bool) -> tuple[dict[str, object] | None, list[str], list[Path]]:
    errors: list[str] = []
    metadata, metadata_errors = read_distribution_metadata(root)
    errors.extend(metadata_errors)
    if metadata is None:
        return None, errors, []
    files, file_errors = release_files(root, metadata)
    errors.extend(file_errors)
    errors.extend(public_contract_errors(root, files))

    version = (root / "VERSION").read_text(encoding="utf-8").strip() if (root / "VERSION").is_file() else None
    skill_text = (root / "SKILL.md").read_text(encoding="utf-8") if (root / "SKILL.md").is_file() else ""
    versions = {version, metadata.get("version"), frontmatter_version(skill_text)}
    if None in versions or len(versions) != 1:
        errors.append(f"version mismatch: VERSION={version!r}, metadata={metadata.get('version')!r}, SKILL={frontmatter_version(skill_text)!r}")
    components = metadata.get("component_versions")
    required_components = {
        "skill",
        "start_pack_validator",
        "start_pack_schema",
        "council_protocol",
    }
    if not isinstance(components, dict) or set(components) != required_components:
        errors.append(
            "component_versions must declare exactly skill, start_pack_validator, "
            "start_pack_schema, and council_protocol"
        )
        components = {}
    elif any(not isinstance(value, str) or not value.strip() for value in components.values()):
        errors.append("every component version must be a non-empty string")
    if components.get("skill") != version:
        errors.append(f"component skill version must be {version!r}")
    if components.get("start_pack_schema") != components.get("start_pack_validator"):
        errors.append("Start Pack schema and validator component versions must match")
    validator_text = (root / "scripts" / "start_pack.py").read_text(encoding="utf-8") if (root / "scripts" / "start_pack.py").is_file() else ""
    validator_match = re.search(r'(?m)^VALIDATOR_VERSION\s*=\s*["\']([^"\']+)["\']', validator_text)
    validator_version = validator_match.group(1) if validator_match else None
    expected_start_pack_version = components.get("start_pack_validator")
    if validator_version != expected_start_pack_version:
        errors.append(
            "Start Pack validator component mismatch: "
            f"expected {expected_start_pack_version!r}, found {validator_version!r}"
        )
    errors.extend(
        schema_errors(
            root,
            files,
            components.get("start_pack_schema"),
            components.get("council_protocol"),
        )
    )
    errors.extend(jumpstart_errors(root, components.get("council_protocol")))
    errors.extend(released_result_history_errors(root, files))
    executable_errors, executed_controls = executable_eval_outcome(root)
    errors.extend(executable_errors)
    result_record, result_errors = result_record_errors(
        root,
        version,
        require_public,
        files,
        executed_controls,
    )
    errors.extend(result_errors)
    licenses = {metadata.get("license"), frontmatter_value(skill_text, "license")}
    if None in licenses or len(licenses) != 1:
        errors.append("license mismatch between SKILL.md and distribution metadata")
    if metadata.get("skill") != "selective-intelligence":
        errors.append("distribution metadata has the wrong skill name")
    expected_archive = f"selective-intelligence-{version}.zip" if version else None
    if metadata.get("archive_name") != expected_archive:
        errors.append(f"archive_name must be {expected_archive}")

    topics = metadata.get("topics")
    if not isinstance(topics, list) or not 1 <= len(topics) <= 20:
        errors.append("topics must contain between 1 and 20 values")
    elif len(set(topics)) != len(topics) or any(not TOPIC_RE.fullmatch(item or "") for item in topics if isinstance(item, str)) or any(not isinstance(item, str) for item in topics):
        errors.append("topics must be unique lowercase letters, numbers, and hyphens, at most 50 characters")

    if metadata.get("master_trigger") != "Selective Intelligence":
        errors.append("distribution metadata must preserve Selective Intelligence as the exact master trigger")
    if metadata.get("direct_activation") != "exact_phrase_in_current_user_input":
        errors.append("distribution metadata must bind direct activation to the exact phrase in current user input")
    if metadata.get("discovered_adoption") != "explicit_user_approval_required":
        errors.append("distribution metadata must require explicit user approval for discovered adoption")
    agent_config = root / "agents" / "openai.yaml"
    agent_config_text = (
        agent_config.read_text(encoding="utf-8") if agent_config.is_file() else ""
    )
    if not re.search(r"(?m)^\s*allow_implicit_invocation:\s*true\s*$", agent_config_text):
        errors.append(
            "OpenAI agent metadata must allow implicit invocation so canonical discovery triggers can be evaluated"
        )
    if metadata.get("seedless_behavior") != "automatic_context_discovery_and_begin":
        errors.append("distribution metadata must require automatic context discovery for seedless activation")
    if metadata.get("project_index") != "auto_refresh_before_new_code":
        errors.append("distribution metadata must require the project index before new code")
    repository_description = metadata.get("repository_description")
    if not isinstance(repository_description, str) or not repository_description.startswith("Selective Intelligence"):
        errors.append("repository description must begin with the Selective Intelligence wordmark")

    canonical = metadata.get("canonical_repository")
    publisher = metadata.get("publisher_identity")
    chatgpt_skill = metadata.get("chatgpt_skill_url")
    support = metadata.get("support_url")
    if canonical is not None and not https_url(canonical):
        errors.append("canonical_repository must be null or an HTTPS URL")
    if not https_url(chatgpt_skill):
        errors.append("chatgpt_skill_url must be an HTTPS URL")
    elif chatgpt_skill not in ((root / "README.md").read_text(encoding="utf-8") if (root / "README.md").is_file() else ""):
        errors.append("README must link to chatgpt_skill_url")
    if support is not None and not https_url(support):
        errors.append("support_url must be null or an HTTPS URL")
    if require_public and not https_url(canonical):
        errors.append("public release requires the owner-supplied canonical_repository HTTPS URL")
    if require_public and (not isinstance(publisher, str) or not publisher.strip()):
        errors.append("public release requires the owner-supplied publisher_identity")
    if require_public and metadata.get("distribution_status") != "public":
        errors.append("public release requires distribution_status=public")
    if require_public and isinstance(canonical, str):
        readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").is_file() else ""
        if canonical not in readme:
            errors.append("public README must link to the canonical_repository")
        if "has not been assigned yet" in readme:
            errors.append("public README still says the canonical repository is unassigned")
    if require_support and not https_url(support):
        errors.append("donation configuration requires the owner-supplied support_url HTTPS URL")
    if require_support and isinstance(support, str):
        readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").is_file() else ""
        if support not in readme:
            errors.append("README must contain the verified support_url before donations are configured")
    if support and metadata.get("support_is_optional") is not True:
        errors.append("support_url may be configured only when support_is_optional is true")

    errors.extend(markdown_link_errors(root, files))
    metadata["model_behavior_ready"] = bool(
        not result_errors
        and isinstance(result_record, dict)
        and isinstance(result_record.get("model_behavior_evaluation"), dict)
        and result_record["model_behavior_evaluation"].get("result") == "pass"
    )
    return metadata, errors, files


def command_doctor(args: argparse.Namespace) -> int:
    metadata, errors, files = doctor(SKILL_ROOT, args.public, args.donations)
    result = {
        "ready": not errors,
        "mode": "public" if args.public else "local_package",
        "donations_checked": bool(args.donations),
        "file_count": len(files),
        "canonical_repository": metadata.get("canonical_repository") if metadata else None,
        "support_url_configured": bool(metadata and metadata.get("support_url")),
        "model_behavior_ready": bool(metadata and metadata.get("model_behavior_ready")),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    elif errors:
        print(f"release doctor: {len(errors)} issue(s)")
        for error in errors:
            print(f"- {error}")
    else:
        print(f"release doctor: ready ({len(files)} files)")
    return 1 if errors else 0


def command_package(args: argparse.Namespace) -> int:
    metadata, errors, files = doctor(SKILL_ROOT, args.public, False)
    if errors or metadata is None:
        print("release gates failed; run release.py doctor", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / str(metadata["archive_name"])
    checksum = output_dir / "SHA256SUMS"
    if (archive.exists() or checksum.exists()) and not args.force:
        print("refusing to overwrite release output without --force", file=sys.stderr)
        return 2
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            relative = path.relative_to(SKILL_ROOT).as_posix()
            info = zipfile.ZipInfo(f"selective-intelligence/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.parent.name == "scripts" and path.suffix == ".py" else 0o644) << 16
            bundle.writestr(info, path.read_bytes())
    digest = sha256(archive)
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"created {archive}")
    print(f"sha256 {digest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and package Selective Intelligence without publishing")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("doctor")
    check.add_argument("--public", action="store_true", help="require the canonical public repository URL")
    check.add_argument("--donations", action="store_true", help="require the optional owner-supplied support URL")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=command_doctor)

    package = commands.add_parser("package")
    package.add_argument("--output-dir", required=True)
    package.add_argument("--public", action="store_true", help="require public-release metadata before packaging")
    package.add_argument("--force", action="store_true")
    package.set_defaults(func=command_package)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
