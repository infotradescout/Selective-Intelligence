#!/usr/bin/env python3
"""Initialize and validate Selective Intelligence Start Packs.

The script is intentionally dependency-free so different agents and clients can
apply the same structural rules. It never edits product code. Mutating commands
refuse to overwrite an existing pack or silently reseal locked artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import project_index
import execution_contract
import council


PACK_DIR = ".selective-intelligence"
EXECUTION_CONTRACT_POLICY = "required"
COUNCIL_COMPLETION_POLICY = "required"
COUNCIL_REVIEW_SCHEMA_VERSION = 1
OBSERVATION_RECEIPT_SCHEMA_VERSION = 1
SCHEMA_VERSION = 1
VALIDATOR_VERSION = "0.1.1"
ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
UNRESOLVED_RE = re.compile(r"\b(?:UNRESOLVED|TBD|TO[- ]?DO)\b", re.IGNORECASE)

STANDARD_ARTIFACTS = (
    "intent-contract.md",
    "scope-release.md",
    "experience-surfaces.md",
    "architecture-contract.md",
    "data-contract.md",
    "api-integrations.md",
    "security-operations.md",
    "delivery-map.md",
    "traceability.md",
    "decisions-changes.md",
)
MICRO_ARTIFACTS = (
    "intent-contract.md",
    "scope-release.md",
    "delivery-map.md",
    "decisions-changes.md",
)

INTENT_VERDICTS = {"locked", "supported", "provisional", "conflicted", "unknown"}
DEFINITION_VERDICTS = {"locked", "blocked", "unverified"}
BUILD_VERDICTS = {"aligned", "amendment_required", "blocked", "not_started"}
AS_BUILT_VERDICTS = {
    "reconciled",
    "partial",
    "not_aligned",
    "unverifiable",
    "not_started",
}
RELEASE_VERDICTS = {"closed", "partial", "blocked", "unverifiable", "not_started"}
BUILD_STATUSES = {
    "planned",
    "locked",
    "in_progress",
    "interrupted",
    "reconciled",
    "superseded",
    "abandoned",
}
CHECKPOINT_STATUSES = {"locked", "in_progress", "interrupted"}
CHECKPOINT_STATUS_MOVES = {
    "locked": {"locked", "in_progress", "interrupted"},
    "in_progress": {"in_progress", "interrupted"},
    "interrupted": {"interrupted", "in_progress"},
}
REQUIREMENT_SCOPES = {"mvp", "mandatory", "later", "out"}
FEATURE_STATES = (
    "intended",
    "specified",
    "modeled",
    "implemented",
    "wired",
    "reachable",
    "usable",
    "verified",
    "live",
)
RISK_TRIGGERS = {
    "sensitive_data",
    "multi_tenant",
    "public_mutation",
    "payments_or_entitlements",
    "external_integrations",
    "ai_autonomy",
    "destructive_migration",
    "regulated_domain",
    "production_deployment",
}
DECISION_CLASSES = {
    "product_invariant",
    "release_commitment",
    "hypothesis",
    "reversible_choice",
    "deferred",
}
DECISION_STATUSES = {"accepted", "provisional", "testing", "rejected", "deferred"}
SEMANTIC_CHANGE_KEYS = {"added", "modified", "removed", "renamed", "unchanged"}
TRANSITION_PHASES = {"definition", "build", "as-built", "release"}
INDEPENDENT_REVIEW_STATUSES = {"unverified", "verified", "failed"}
INDEPENDENT_REVIEW_FIELDS = {
    "required",
    "status",
    "evidence",
    "reviewer",
    "reviewed_at",
    "scope",
    "revision",
}
ARTIFACT_ROLES = {"governance", "execution_contract", "council_review", "runner_receipt", "observation"}


@dataclass(frozen=True)
class Diagnostic:
    level: str
    code: str
    message: str
    path: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def control_digest(manifest: dict[str, Any]) -> str:
    canonical = {key: value for key, value in manifest.items() if key != "control_digest"}
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def semantic_contract_digest(manifest: dict[str, Any]) -> str:
    """Digest locked product meaning while excluding observable execution progress.

    Build status, requirement feature state, evidence observations, review result,
    and the active-build pointer may advance without changing the product contract.
    Evidence files have a separate per-seal digest ledger so their contents can be
    checkpointed without weakening the semantic lock.
    """
    evidence_paths = {
        build.get("evidence")
        for build in manifest.get("builds", [])
        if isinstance(build, dict) and isinstance(build.get("evidence"), str)
    }
    active = manifest.get("active_build")
    if isinstance(active, dict) and isinstance(active.get("evidence"), str):
        evidence_paths.add(active["evidence"])
    if isinstance(active, dict) and isinstance(active.get("council_review"), str):
        evidence_paths.add(active["council_review"])
    for key in ("observation_receipt", "observation_output"):
        if isinstance(active, dict) and isinstance(active.get(key), str):
            evidence_paths.add(active[key])

    artifacts: list[Any] = []
    for artifact in manifest.get("artifacts", []):
        if not isinstance(artifact, dict):
            artifacts.append(artifact)
            continue
        projected = dict(artifact)
        if artifact.get("path") in evidence_paths:
            projected.pop("sha256", None)
        artifacts.append(projected)

    requirements = [
        {key: value for key, value in requirement.items() if key != "state"}
        if isinstance(requirement, dict)
        else requirement
        for requirement in manifest.get("requirements", [])
    ]
    builds = [
        {
            key: value
            for key, value in build.items()
            if key not in {"status", "evidence_context"}
        }
        if isinstance(build, dict)
        else build
        for build in manifest.get("builds", [])
    ]
    review = manifest.get("independent_review")
    projected_review = (
        {key: value for key, value in review.items() if key not in {"status", "evidence"}}
        if isinstance(review, dict)
        else review
    )
    canonical = {
        "schema_version": manifest.get("schema_version"),
        "validator_version": manifest.get("validator_version"),
        "project": manifest.get("project"),
        "release": manifest.get("release"),
        "authority": manifest.get("authority"),
        "material_blockers": manifest.get("material_blockers"),
        "artifacts": artifacts,
        "requirements": requirements,
        "builds": builds,
        "external_facts": manifest.get("external_facts"),
        "decisions": manifest.get("decisions"),
        "amendments": manifest.get("amendments"),
        "risk_triggers": manifest.get("risk_triggers"),
        "independent_review": projected_review,
    }
    if "execution_contract_policy" in manifest:
        canonical["execution_contract_policy"] = manifest.get("execution_contract_policy")
    if "council_completion_policy" in manifest:
        canonical["council_completion_policy"] = manifest.get("council_completion_policy")
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("lock.json must contain a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(value, indent=2, sort_keys=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(ID_RE.fullmatch(value))


def meaningful_text(value: Any, minimum: int = 2) -> bool:
    if not isinstance(value, str):
        return False
    cleaned = value.strip()
    return len(cleaned) >= minimum and not UNRESOLVED_RE.search(cleaned) and bool(re.search(r"[A-Za-z0-9]", cleaned))


def valid_unique_text_list(value: Any, allow_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(meaningful_text(item) for item in value)
        and len(value) == len(set(value))
    )


def text_set(value: Any) -> set[str]:
    return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()


def safe_path(root: Path, relative: Any) -> tuple[Path | None, str | None]:
    if not isinstance(relative, str) or not relative.strip():
        return None, "path must be a non-empty string"
    candidate_rel = Path(relative)
    if candidate_rel.is_absolute():
        return None, "absolute paths are not allowed"
    if ".." in candidate_rel.parts:
        return None, "parent traversal is not allowed"
    candidate = root / candidate_rel
    cursor = root
    for part in candidate_rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None, "symlink paths are not allowed"
    try:
        resolved_root = root.resolve()
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        return None, f"path could not be resolved: {exc}"
    if resolved != resolved_root and resolved_root not in resolved.parents:
        return None, "path escapes the Start Pack"
    return candidate, None


def artifact_snapshot(pack: Path, manifest: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    """Read the exact registered artifact state without mutating the manifest."""
    snapshot: dict[str, str] = {}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return {}, "artifacts must be an array"
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            return {}, f"artifact {index} must be an object"
        relative = artifact.get("path")
        if not isinstance(relative, str) or not relative:
            return {}, f"artifact {index} needs a path"
        if relative in snapshot:
            return {}, f"duplicate artifact path: {relative}"
        path, error = safe_path(pack, relative)
        if error or path is None or not path.is_file():
            return {}, f"missing or unsafe artifact {relative}: {error or 'missing'}"
        snapshot[relative] = sha256(path)
    return snapshot, None


def history_artifact_snapshot(entry: Any) -> dict[str, str] | None:
    if not isinstance(entry, dict):
        return None
    value = entry.get("artifact_digests")
    if not isinstance(value, dict):
        return None
    if not all(
        isinstance(path, str)
        and path
        and isinstance(digest, str)
        and bool(re.fullmatch(r"[a-f0-9]{64}", digest))
        for path, digest in value.items()
    ):
        return None
    return value


def parse_calendar_date(value: Any) -> date | None:
    """Parse an ISO date or datetime into a calendar date."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).date()
        except ValueError:
            return None


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def inspect_transition_history(manifest: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    history = manifest.get("seal_history")
    if not isinstance(history, list):
        return None, None, ["seal_history must be an array"]
    last_phase: str | None = None
    last_phase_entry: dict[str, Any] | None = None
    previous_seal_entry: dict[str, Any] | None = None
    errors: list[str] = []
    for index, entry in enumerate(history):
        if not isinstance(entry, dict):
            errors.append(f"seal_history[{index}] must be an object")
            continue
        if parse_timestamp(entry.get("sealed_at")) is None:
            errors.append(f"seal_history[{index}].sealed_at must be an ISO-8601 timestamp with timezone")
        amendment = entry.get("amendment")
        transition = entry.get("transition")
        checkpoint = entry.get("checkpoint")
        if amendment is not None and not valid_id(amendment):
            errors.append(f"seal_history[{index}].amendment has an invalid ID")
        if transition is not None and transition not in TRANSITION_PHASES:
            errors.append(f"seal_history[{index}].transition is invalid")
            continue
        if not isinstance(checkpoint, bool):
            errors.append(f"seal_history[{index}].checkpoint must be boolean")
            checkpoint = False
        semantic = entry.get("semantic_digest")
        if not isinstance(semantic, str) or not re.fullmatch(r"[a-f0-9]{64}", semantic):
            errors.append(f"seal_history[{index}].semantic_digest is invalid")
        if history_artifact_snapshot(entry) is None:
            errors.append(f"seal_history[{index}].artifact_digests is invalid")
        as_built_snapshot = entry.get("as_built_verdict")
        if as_built_snapshot not in AS_BUILT_VERDICTS:
            errors.append(f"seal_history[{index}].as_built_verdict is invalid")
        current_invalidated = entry.get("invalidated_requirements")
        if (
            not isinstance(current_invalidated, list)
            or len(current_invalidated) != len(set(item for item in current_invalidated if isinstance(item, str)))
            or any(not valid_id(item) for item in current_invalidated)
        ):
            errors.append(f"seal_history[{index}].invalidated_requirements must contain unique valid IDs")
        elif previous_seal_entry is not None and amendment is None:
            previous_invalidated = previous_seal_entry.get("invalidated_requirements")
            previous_set = set(previous_invalidated) if isinstance(previous_invalidated, list) else set()
            current_set = set(current_invalidated)
            removed = previous_set - current_set
            removal_is_reconciled = transition == "as-built" and as_built_snapshot == "reconciled"
            if removed and not removal_is_reconciled:
                errors.append(
                    f"seal_history[{index}] removes invalidated requirements outside reconciled as-built: {sorted(removed)}"
                )
            if transition == "release" and current_set != previous_set:
                errors.append(f"seal_history[{index}] changes invalidated requirements during release")
        previous_seal_entry = entry
        if checkpoint and (amendment is not None or transition is not None):
            errors.append(f"seal_history[{index}] checkpoint may not also be a transition or amendment")
            continue
        if amendment is not None and transition not in {None, "definition"}:
            errors.append(f"seal_history[{index}] amendment may transition only to definition")
        if amendment is not None:
            last_phase = None
            last_phase_entry = None
        if checkpoint:
            if last_phase != "build" or last_phase_entry is None:
                errors.append(f"seal_history[{index}] checkpoint requires an active build phase")
                continue
            if entry.get("active_build") != last_phase_entry.get("active_build"):
                errors.append(f"seal_history[{index}] checkpoint changes the active build")
            if entry.get("lock_version") != last_phase_entry.get("lock_version"):
                errors.append(f"seal_history[{index}] checkpoint changes the lock version")
            previous_status = last_phase_entry.get("build_status")
            current_status = entry.get("build_status")
            if current_status not in CHECKPOINT_STATUSES:
                errors.append(f"seal_history[{index}].build_status is not checkpointable")
            elif current_status not in CHECKPOINT_STATUS_MOVES.get(previous_status, set()):
                errors.append(
                    f"seal_history[{index}] cannot checkpoint build status from {previous_status} to {current_status}"
                )
            last_phase_entry = entry
            continue
        if transition is None:
            if amendment is None:
                errors.append(f"seal_history[{index}] reseals controlled state without a transition, amendment, or checkpoint")
            continue
        allowed_previous = {
            "definition": {None},
            "build": {"definition", "as-built"},
            "as-built": {"build"},
            "release": {"as-built"},
        }[transition]
        if last_phase not in allowed_previous:
            errors.append(f"seal_history[{index}] cannot transition from {last_phase or 'unlocked'} to {transition}")
        if not valid_id(entry.get("active_build")):
            errors.append(f"seal_history[{index}].active_build is required for a phase transition")
        if not meaningful_text(entry.get("lock_version")):
            errors.append(f"seal_history[{index}].lock_version is required for a phase transition")
        if entry.get("build_status") not in BUILD_STATUSES:
            errors.append(f"seal_history[{index}].build_status is required for a phase transition")
        must_retain_active = transition in {"as-built", "release"} or (
            transition == "build" and last_phase == "definition"
        )
        if must_retain_active and last_phase_entry is not None:
            if entry.get("active_build") != last_phase_entry.get("active_build"):
                errors.append(f"seal_history[{index}] changes the active build across {last_phase} → {transition}")
            if entry.get("lock_version") != last_phase_entry.get("lock_version"):
                errors.append(f"seal_history[{index}] changes the lock version across {last_phase} → {transition}")
        last_phase = transition
        last_phase_entry = entry
    return last_phase, last_phase_entry, errors


def required_artifacts(manifest: dict[str, Any]) -> set[str]:
    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    profile = project.get("profile", "standard")
    required = set(MICRO_ARTIFACTS if profile == "micro" else STANDARD_ARTIFACTS)
    active = manifest.get("active_build") if isinstance(manifest.get("active_build"), dict) else {}
    for key in (
        "contract", "evidence", "execution_contract", "council_review",
        "observation_receipt", "observation_output",
    ):
        value = active.get(key)
        if isinstance(value, str) and value:
            required.add(value)
    return required


def active_execution_contract_errors(
    pack: Path,
    manifest: dict[str, Any],
    *,
    require: bool,
    validate_decision: bool = True,
) -> list[str]:
    """Validate and identity-bind the active build's execution decision."""
    active = manifest.get("active_build")
    builds = manifest.get("builds")
    if not isinstance(active, dict) or not isinstance(builds, list):
        return ["active build execution contract cannot be resolved"] if require else []

    active_id = active.get("id")
    build = next(
        (item for item in builds if isinstance(item, dict) and item.get("id") == active_id),
        None,
    )
    active_path = active.get("execution_contract")
    build_path = build.get("execution_contract") if isinstance(build, dict) else None
    errors: list[str] = []
    if not isinstance(active_path, str) or not active_path:
        if require:
            errors.append("active_build.execution_contract is required for this contract-aware Start Pack")
        active_path = None
    if not isinstance(build_path, str) or not build_path:
        if require:
            errors.append("the active build record must retain its execution_contract pointer")
        build_path = None
    if active_path is not None and build_path is not None and build_path != active_path:
        errors.append("active_build.execution_contract must match the active build record")

    resolved_path = active_path or build_path
    if resolved_path is None:
        return errors

    path, path_error = safe_path(pack, resolved_path)
    if path_error or path is None:
        errors.append(f"active execution contract path is unsafe: {path_error}")
        return errors
    if path.is_symlink() or not path.is_file():
        errors.append("active execution contract must be a regular registered file")
        return errors

    registered = {
        item.get("path")
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if resolved_path not in registered:
        errors.append("active execution contract must be a registered Start Pack artifact")

    if not validate_decision:
        return errors

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"active execution contract cannot be read: {exc}")
        return errors

    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    release = manifest.get("release") if isinstance(manifest.get("release"), dict) else {}
    expected_binding = {
        "projectId": project.get("id"),
        "releaseId": release.get("id"),
        "releaseVersion": release.get("version"),
        "buildId": active_id,
        "lockVersion": build.get("lock_version") if isinstance(build, dict) else None,
    }
    errors.extend(
        execution_contract.validate_contract(
            payload,
            expected_binding=expected_binding,
            expected_requirement_ids={
                item
                for item in (build.get("requirements", []) if isinstance(build, dict) else [])
                if isinstance(item, str)
            },
        )
    )
    return errors


def execution_contract_aware(manifest: dict[str, Any]) -> bool:
    if manifest.get("execution_contract_policy") == EXECUTION_CONTRACT_POLICY:
        return True
    active = manifest.get("active_build")
    if isinstance(active, dict) and isinstance(active.get("execution_contract"), str):
        return True
    builds = manifest.get("builds")
    if isinstance(builds, list) and any(
        isinstance(item, dict) and isinstance(item.get("execution_contract"), str)
        for item in builds
    ):
        return True
    artifacts = manifest.get("artifacts")
    return isinstance(artifacts, list) and any(
        isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and item["path"].endswith("/execution-contract.json")
        for item in artifacts
    )


def council_completion_aware(manifest: dict[str, Any]) -> bool:
    if manifest.get("council_completion_policy") == COUNCIL_COMPLETION_POLICY:
        return True
    active = manifest.get("active_build")
    if isinstance(active, dict) and isinstance(active.get("council_review"), str):
        return True
    builds = manifest.get("builds")
    if isinstance(builds, list) and any(
        isinstance(item, dict) and isinstance(item.get("council_review"), str)
        for item in builds
    ):
        return True
    artifacts = manifest.get("artifacts")
    return isinstance(artifacts, list) and any(
        isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and item["path"].endswith("/council-review.json")
        for item in artifacts
    )


def council_review_template() -> dict[str, Any]:
    return {
        "schema_version": COUNCIL_REVIEW_SCHEMA_VERSION,
        "status": "pending",
        "binding": None,
        "case_packet_id": None,
        "case_digest": None,
        "alignment_packet_id": None,
        "alignment_digest": None,
        "requirement_proofs": [],
        "case": None,
    }


def observation_receipt_template() -> dict[str, Any]:
    return {"schema_version": OBSERVATION_RECEIPT_SCHEMA_VERSION, "receipts": []}


def resolve_json_pointer(document: Any, fragment: str) -> Any | None:
    """Resolve a local RFC 6901-style fragment without accepting fuzzy anchors."""
    if not fragment.startswith("/"):
        return None
    current = document
    for raw_token in fragment[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return None
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit():
                return None
            index = int(token)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _review_binding(manifest: dict[str, Any], build: dict[str, Any]) -> dict[str, Any]:
    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    release = manifest.get("release") if isinstance(manifest.get("release"), dict) else {}
    context = build.get("evidence_context") if isinstance(build.get("evidence_context"), dict) else {}
    return {
        "project_id": project.get("id"),
        "release_id": release.get("id"),
        "release_version": release.get("version"),
        "build_id": build.get("id"),
        "lock_version": build.get("lock_version"),
        "source_revision": context.get("revision"),
        "semantic_digest": semantic_contract_digest(manifest),
        "validator_version": manifest.get("validator_version"),
        "requirement_ids": sorted(item for item in build.get("requirements", []) if isinstance(item, str)),
    }


def active_council_review_errors(
    pack: Path,
    manifest: dict[str, Any],
    *,
    require_completion: bool,
) -> list[str]:
    """Validate the read-only Council bundle for the active build.

    The wrapper is a Start Pack artifact. Its embedded Council case and every
    implementation-evidence locator are independently recomputed from bytes.
    """
    active = manifest.get("active_build")
    builds = manifest.get("builds")
    if not isinstance(active, dict) or not isinstance(builds, list):
        return ["active build Council review cannot be resolved"] if require_completion else []
    active_id = active.get("id")
    build = next((item for item in builds if isinstance(item, dict) and item.get("id") == active_id), None)
    if not isinstance(build, dict):
        return ["active build Council review cannot be resolved"] if require_completion else []

    errors: list[str] = []
    active_path = active.get("council_review")
    build_path = build.get("council_review")
    if not isinstance(active_path, str) or not active_path:
        errors.append("active_build.council_review is required for this Council-aware Start Pack")
    if not isinstance(build_path, str) or not build_path:
        errors.append("the active build record must retain its council_review pointer")
    if isinstance(active_path, str) and isinstance(build_path, str) and active_path != build_path:
        errors.append("active_build.council_review must match the active build record")
    relative = active_path if isinstance(active_path, str) and active_path else build_path
    if not isinstance(relative, str) or not relative:
        return errors

    registered = {
        item.get("path")
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    artifact_by_path = {
        item.get("path"): item
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if relative not in registered:
        errors.append("active Council review must be a registered Start Pack artifact")
    elif artifact_by_path[relative].get("role") != "council_review":
        errors.append("active Council review artifact must have role council_review")
    review_path, path_error = safe_path(pack, relative)
    if path_error or review_path is None:
        errors.append(f"active Council review path is unsafe: {path_error}")
        return errors
    if review_path.is_symlink() or not review_path.is_file():
        errors.append("active Council review must be a regular non-symlink file")
        return errors
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"active Council review cannot be read: {exc}")
        return errors
    if not isinstance(review, dict):
        errors.append("active Council review must contain a JSON object")
        return errors
    expected_keys = {
        "schema_version", "status", "binding", "case_packet_id", "case_digest",
        "alignment_packet_id", "alignment_digest", "requirement_proofs", "case",
    }
    if set(review) != expected_keys:
        errors.append("active Council review has an invalid field set")
    if review.get("schema_version") != COUNCIL_REVIEW_SCHEMA_VERSION:
        errors.append("active Council review schema_version is unsupported")
    if not require_completion:
        if review.get("status") not in {"pending", "verified", "failed"}:
            errors.append("active Council review status is invalid")
        return errors
    if review.get("status") != "verified":
        errors.append("positive completion requires a verified Council review")
        return errors
    if review.get("binding") != _review_binding(manifest, build):
        errors.append("Council review binding does not match the exact active build")

    case = review.get("case")
    if not isinstance(case, dict):
        errors.append("verified Council review requires an embedded Council case")
        return errors
    case_errors = council.validate_document(case)
    if case_errors:
        errors.append(f"Council case is invalid: {case_errors[0].code} {case_errors[0].message}")
        return errors
    case_binding = case.get("start_pack_binding")
    review_binding = review.get("binding") if isinstance(review.get("binding"), dict) else {}
    if not isinstance(case_binding, dict):
        errors.append("verified Council case requires a non-null Start Pack binding")
    else:
        for case_key, review_key in (
            ("project_id", "project_id"),
            ("release_id", "release_id"),
            ("semantic_digest", "semantic_digest"),
            ("validator_version", "validator_version"),
        ):
            if case_binding.get(case_key) != review_binding.get(review_key):
                errors.append(f"Council case {case_key} does not match the exact Start Pack subject")
    project_boundary = case.get("project_boundary") if isinstance(case.get("project_boundary"), dict) else {}
    if project_boundary.get("project_id") != review_binding.get("project_id"):
        errors.append("Council case project boundary does not match the exact Start Pack subject")
    if case.get("packet_type") != "council_case" or case.get("status") != "verified":
        errors.append("Council case must be an applied verified case")
    if review.get("case_packet_id") != case.get("packet_id"):
        errors.append("Council review case_packet_id does not match its case")
    recomputed_case_digest = council.document_digest(case)
    if review.get("case_digest") != recomputed_case_digest or case.get("canonical_digest") != recomputed_case_digest:
        errors.append("Council review case digest does not match canonical case bytes")

    alignment = case.get("alignment_record")
    if not isinstance(alignment, dict):
        errors.append("verified Council case requires an applied alignment record")
        return errors
    alignment_errors = council.cross_validate_alignment(case, alignment)
    if alignment_errors:
        errors.append(f"Council alignment is invalid: {alignment_errors[0].code} {alignment_errors[0].message}")
    recomputed_alignment_digest = council.document_digest(alignment)
    if review.get("alignment_packet_id") != alignment.get("packet_id"):
        errors.append("Council review alignment_packet_id does not match the applied alignment")
    if review.get("alignment_digest") != recomputed_alignment_digest or alignment.get("canonical_digest") != recomputed_alignment_digest:
        errors.append("Council review alignment digest does not match canonical alignment bytes")
    if alignment.get("workflow_gate") != "pass" or alignment.get("alignment_verdict") != "aligned":
        errors.append("Council completion requires an aligned workflow pass")
    if alignment.get("open_finding_ids"):
        errors.append("Council completion cannot retain open findings")
    if any(not item.get("closed") for item in alignment.get("dispositions", []) if isinstance(item, dict)):
        errors.append("Council completion cannot retain unresolved dispositions")
    if any(
        item.get("status") == "pending"
        for item in alignment.get("corrections", [])
        if isinstance(item, dict)
    ):
        errors.append("Council completion cannot retain pending corrections")
    findings = {
        item.get("finding_id"): item
        for item in case.get("objector_response", {}).get("findings", [])
        if isinstance(item, dict)
    }
    for disposition in alignment.get("dispositions", []):
        if not isinstance(disposition, dict):
            continue
        finding = findings.get(disposition.get("finding_id"), {})
        if finding.get("severity") == "blocking" and disposition.get("resolution") in {"sustained", "unresolved"}:
            errors.append("Council completion cannot retain a sustained or unresolved blocking finding")

    role_runs = [
        case.get("worker_response", {}).get("role_run", {}),
        case.get("objector_response", {}).get("role_run", {}),
        alignment.get("role_run", {}),
    ]
    run_ids = [item.get("run_id") for item in role_runs]
    context_ids = [item.get("context_id") for item in role_runs]
    if len(set(run_ids)) != 3 or any(not valid_id(item) for item in run_ids):
        errors.append("Worker, Objector, and Aligner must use distinct valid run IDs")
    if len(set(context_ids)) != 3 or any(not meaningful_text(item) for item in context_ids):
        errors.append("Worker, Objector, and Aligner must use distinct contexts")

    proof_by_id = {
        item.get("proof_id"): item
        for item in case.get("proofs", [])
        if isinstance(item, dict) and isinstance(item.get("proof_id"), str)
    }
    proof_producers: dict[str, str] = {}
    authoritative_proofs: dict[str, dict[str, Any]] = {}
    ambiguous_producers: set[str] = set()

    def record_producer(proof: Any, run_id: Any) -> None:
        if not isinstance(proof, dict) or not isinstance(proof.get("proof_id"), str) or not isinstance(run_id, str):
            return
        proof_id = proof["proof_id"]
        if proof_id in proof_producers:
            ambiguous_producers.add(proof_id)
            return
        proof_producers[proof_id] = run_id
        authoritative_proofs[proof_id] = proof

    worker_response = case.get("worker_response") if isinstance(case.get("worker_response"), dict) else {}
    worker_run_id = worker_response.get("role_run", {}).get("run_id") if isinstance(worker_response.get("role_run"), dict) else None
    for proof in worker_response.get("proofs", []) if isinstance(worker_response.get("proofs"), list) else []:
        record_producer(proof, worker_run_id)
    aligner_run_id = alignment.get("role_run", {}).get("run_id") if isinstance(alignment.get("role_run"), dict) else None
    for correction in alignment.get("corrections", []) if isinstance(alignment.get("corrections"), list) else []:
        if not isinstance(correction, dict):
            continue
        for proof in correction.get("revalidated_proofs", []) if isinstance(correction.get("revalidated_proofs"), list) else []:
            record_producer(proof, aligner_run_id)
    if ambiguous_producers:
        errors.append(f"Council proof producer lineage is ambiguous: {sorted(ambiguous_producers)}")
    invalidated = set(item for item in case.get("invalidated_proof_ids", []) if isinstance(item, str))
    mappings = review.get("requirement_proofs")
    expected_requirements = set(_review_binding(manifest, build)["requirement_ids"])
    mapped: dict[str, set[str]] = {}
    mapped_receipts: dict[str, set[str]] = {}
    if not isinstance(mappings, list):
        errors.append("Council review requirement_proofs must be an array")
        mappings = []
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict) or set(mapping) != {"requirement_id", "proof_ids", "receipt_ids"}:
            errors.append(f"Council review requirement_proofs[{index}] is invalid")
            continue
        requirement_id = mapping.get("requirement_id")
        proof_ids = mapping.get("proof_ids")
        receipt_ids = mapping.get("receipt_ids")
        if not valid_id(requirement_id) or not isinstance(proof_ids, list) or not proof_ids or len(proof_ids) != len(set(proof_ids)):
            errors.append(f"Council review requirement_proofs[{index}] needs one or more unique proof IDs")
            continue
        if not isinstance(receipt_ids, list) or not receipt_ids or any(not valid_id(item) for item in receipt_ids) or len(receipt_ids) != len(set(receipt_ids)):
            errors.append(f"Council review requirement_proofs[{index}] needs one or more unique receipt IDs")
            continue
        if requirement_id in mapped:
            errors.append(f"Council review maps requirement {requirement_id} more than once")
            continue
        mapped[requirement_id] = set(proof_ids)
        mapped_receipts[requirement_id] = set(receipt_ids)
    if set(mapped) != expected_requirements:
        errors.append("Council review proof mappings must cover exactly the active requirement set")
    mapped_proof_ids = set().union(*mapped.values()) if mapped else set()
    required_proof_ids = {
        item
        for item in case.get("task", {}).get("required_proof_ids", [])
        if isinstance(item, str)
    }
    if mapped_proof_ids != required_proof_ids:
        errors.append("Council review mappings must use exactly the case task's required proof set")

    evidence_by_id = {
        item.get("evidence_id"): item
        for item in case.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)
    }
    all_mapped_receipts = [item for values in mapped_receipts.values() for item in values]
    if len(all_mapped_receipts) != len(set(all_mapped_receipts)):
        errors.append("Council review receipt IDs may map to only one active requirement")
    expected_receipt_path = build.get("observation_receipt")
    expected_output_path = build.get("observation_output")
    if active.get("observation_receipt") != expected_receipt_path:
        errors.append("active_build.observation_receipt must match the active build record")
    if active.get("observation_output") != expected_output_path:
        errors.append("active_build.observation_output must match the active build record")
    if (
        not isinstance(expected_receipt_path, str)
        or artifact_by_path.get(expected_receipt_path, {}).get("role") != "runner_receipt"
    ):
        errors.append("active build requires a registered runner_receipt artifact")
    if (
        not isinstance(expected_output_path, str)
        or artifact_by_path.get(expected_output_path, {}).get("role") != "observation"
    ):
        errors.append("active build requires a registered observation output artifact")
    for requirement_id, proof_ids in mapped.items():
        qualified_for_requirement: set[str] = set()
        for proof_id in proof_ids:
            proof = proof_by_id.get(proof_id)
            if not isinstance(proof, dict) or proof.get("status") != "valid" or proof_id in invalidated:
                errors.append(f"requirement {requirement_id} references a missing, invalid, or invalidated proof {proof_id}")
                continue
            producer_run_id = proof_producers.get(proof_id)
            if (
                proof_id in ambiguous_producers
                or not isinstance(producer_run_id, str)
                or authoritative_proofs.get(proof_id) != proof
            ):
                errors.append(f"proof {proof_id} has no unique authoritative Council producer")
                continue
            if proof.get("revision") != _review_binding(manifest, build)["source_revision"]:
                errors.append(f"proof {proof_id} is stale for the active source revision")
            refs = proof.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                errors.append(f"proof {proof_id} has no implementation evidence")
                continue
            qualified_for_proof: set[str] = set()
            for evidence_id in refs:
                evidence = evidence_by_id.get(evidence_id)
                if not isinstance(evidence, dict) or evidence.get("classification") != "confirmed":
                    errors.append(f"proof {proof_id} requires confirmed evidence {evidence_id}")
                    continue
                locator = evidence.get("locator")
                if not isinstance(locator, str) or "#" not in locator:
                    errors.append(f"evidence {evidence_id} requires an exact JSON Pointer fragment")
                    continue
                locator_path, fragment = locator.split("#", 1)
                artifact = artifact_by_path.get(locator_path)
                if not isinstance(artifact, dict) or artifact.get("role") != "runner_receipt":
                    # Governance may accompany a proof, but it never qualifies it.
                    continue
                if locator_path != expected_receipt_path:
                    errors.append(f"evidence {evidence_id} is not the active build's runner receipt")
                    continue
                resolved, locator_error = safe_path(pack, locator_path)
                if locator_error or resolved is None or resolved.is_symlink() or not resolved.is_file():
                    errors.append(f"evidence {evidence_id} receipt must resolve to a regular non-symlink file")
                    continue
                try:
                    digest = sha256(resolved)
                except OSError as exc:
                    errors.append(f"evidence {evidence_id} cannot be read: {exc}")
                    continue
                if digest != evidence.get("content_digest"):
                    errors.append(f"evidence {evidence_id} content digest does not match its bytes")
                    continue
                try:
                    receipt_document = json.loads(resolved.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"evidence {evidence_id} receipt cannot be parsed: {exc}")
                    continue
                if (
                    not isinstance(receipt_document, dict)
                    or receipt_document.get("schema_version") != OBSERVATION_RECEIPT_SCHEMA_VERSION
                    or not isinstance(receipt_document.get("receipts"), list)
                ):
                    errors.append(f"evidence {evidence_id} receipt document has an invalid schema")
                    continue
                receipt = resolve_json_pointer(receipt_document, fragment)
                receipt_fields = {
                    "receipt_id", "run_id", "proof_id", "requirement_id", "source_revision",
                    "evidence_type", "procedure", "expected", "observed", "verdict",
                    "exit_code", "observed_at", "output_path", "output_digest",
                }
                if not isinstance(receipt, dict) or set(receipt) != receipt_fields:
                    errors.append(f"evidence {evidence_id} fragment does not resolve to an exact runner receipt")
                    continue
                receipt_id = receipt.get("receipt_id")
                if (
                    not valid_id(receipt_id)
                    or receipt_id not in mapped_receipts.get(requirement_id, set())
                    or receipt.get("proof_id") != proof_id
                    or receipt.get("requirement_id") != requirement_id
                ):
                    errors.append(f"evidence {evidence_id} receipt does not match its requirement and proof mapping")
                    continue
                if receipt.get("run_id") != producer_run_id:
                    errors.append(f"receipt {receipt_id} run_id does not match proof {proof_id}'s Council producer")
                if receipt.get("source_revision") != _review_binding(manifest, build)["source_revision"]:
                    errors.append(f"receipt {receipt_id} is stale for the active source revision")
                if receipt.get("evidence_type") not in execution_contract.EVIDENCE_TYPES:
                    errors.append(f"receipt {receipt_id} has an invalid evidence_type")
                for field in ("procedure", "expected", "observed"):
                    if not execution_contract._nonempty(receipt.get(field)):
                        errors.append(f"receipt {receipt_id}.{field} must be a resolved observation")
                receipt_text = " ".join(
                    receipt.get(field, "")
                    for field in ("procedure", "expected", "observed")
                    if isinstance(receipt.get(field), str)
                )
                if execution_contract.SELF_ATTESTATION_RE.search(receipt_text) or any(
                    marker in receipt_text.casefold()
                    for marker in execution_contract.SELF_ATTESTATION_MARKERS
                ):
                    errors.append(f"receipt {receipt_id} is self-attestation, not an observation")
                if receipt.get("verdict") != "passed" or receipt.get("exit_code") != 0:
                    errors.append(f"receipt {receipt_id} must record a passing zero-exit observation")
                if parse_timestamp(receipt.get("observed_at")) is None:
                    errors.append(f"receipt {receipt_id}.observed_at must include a timezone")
                output_path = receipt.get("output_path")
                output_artifact = artifact_by_path.get(output_path)
                if output_path != expected_output_path or not isinstance(output_artifact, dict) or output_artifact.get("role") != "observation":
                    errors.append(f"receipt {receipt_id} must bind the active registered observation output")
                else:
                    output_file, output_error = safe_path(pack, output_path)
                    if output_error or output_file is None or output_file.is_symlink() or not output_file.is_file():
                        errors.append(f"receipt {receipt_id} output must be a regular non-symlink file")
                    else:
                        try:
                            output_digest = sha256(output_file)
                        except OSError as exc:
                            errors.append(f"receipt {receipt_id} output cannot be read: {exc}")
                        else:
                            if output_digest != receipt.get("output_digest"):
                                errors.append(f"receipt {receipt_id} output digest does not match its bytes")
                qualified_for_proof.add(receipt_id)
                qualified_for_requirement.add(receipt_id)
            if not qualified_for_proof:
                errors.append(f"proof {proof_id} lacks a qualifying structured runner receipt")
        if qualified_for_requirement != mapped_receipts.get(requirement_id, set()):
            errors.append(f"requirement {requirement_id} receipt mappings do not exactly match qualifying evidence")
    return errors


def markdown_link_diagnostics(pack: Path, artifact_paths: Iterable[str]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for relative in artifact_paths:
        path, error = safe_path(pack, relative)
        if error or path is None or path.suffix.lower() != ".md" or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for raw_target in LINK_RE.findall(text):
            target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
            parsed = urlparse(target)
            if parsed.scheme or target.startswith(("#", "mailto:")):
                continue
            target_path = target.split("#", 1)[0]
            if not target_path:
                continue
            destination = (path.parent / target_path).resolve(strict=False)
            pack_root = pack.resolve()
            if destination != pack_root and pack_root not in destination.parents:
                # Links into planned product code may not exist yet and are not part
                # of the Start Pack control graph.
                continue
            if not destination.exists():
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "SP031",
                        f"local Start Pack link does not resolve: {target}",
                        relative,
                    )
                )
    return diagnostics


def find_cycle(builds: dict[str, dict[str, Any]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(build_id: str, chain: list[str]) -> list[str] | None:
        if build_id in visiting:
            start = chain.index(build_id) if build_id in chain else 0
            return chain[start:] + [build_id]
        if build_id in visited:
            return None
        visiting.add(build_id)
        chain.append(build_id)
        for dependency in builds[build_id].get("depends_on", []):
            if isinstance(dependency, str) and dependency in builds:
                cycle = visit(dependency, chain)
                if cycle:
                    return cycle
        chain.pop()
        visiting.remove(build_id)
        visited.add(build_id)
        return None

    for build_id in builds:
        cycle = visit(build_id, [])
        if cycle:
            return cycle
    return None


def validate_manifest(
    project_root: Path,
    manifest_override: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    pack = project_root / PACK_DIR
    manifest_path = pack / "lock.json"
    diagnostics: list[Diagnostic] = []
    if pack.is_symlink():
        return None, [Diagnostic("error", "SP000", "Start Pack directory may not be a symlink", str(pack))]
    if manifest_path.is_symlink():
        return None, [Diagnostic("error", "SP000A", "lock.json may not be a symlink", str(manifest_path))]
    if manifest_override is None:
        try:
            manifest = read_json(manifest_path)
        except ValueError as exc:
            return None, [Diagnostic("error", "SP001", str(exc), str(manifest_path))]
    else:
        manifest = manifest_override

    if manifest.get("schema_version") != SCHEMA_VERSION:
        diagnostics.append(
            Diagnostic(
                "error",
                "SP002",
                f"schema_version must be {SCHEMA_VERSION}",
                "lock.json",
            )
        )
    if manifest.get("validator_version") != VALIDATOR_VERSION:
        diagnostics.append(
            Diagnostic(
                "error",
                "SP002V",
                f"validator_version must be {VALIDATOR_VERSION}; migrate explicitly rather than reinterpreting the pack",
                "lock.json",
            )
        )

    sealed_at = manifest.get("sealed_at")
    digest = manifest.get("control_digest")
    semantic = manifest.get("semantic_digest")
    if sealed_at:
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            diagnostics.append(Diagnostic("error", "SP002A", "sealed manifest requires a control_digest", "lock.json"))
        elif digest != control_digest(manifest):
            diagnostics.append(Diagnostic("error", "SP002B", "sealed manifest control digest does not match; reseal through an authorized transition or amendment", "lock.json"))
        if not isinstance(semantic, str) or not re.fullmatch(r"[a-f0-9]{64}", semantic):
            diagnostics.append(Diagnostic("error", "SP002D", "sealed manifest requires a semantic_digest", "lock.json"))
        elif semantic != semantic_contract_digest(manifest):
            diagnostics.append(Diagnostic("error", "SP002E", "locked product semantics changed; record an authorized amendment", "lock.json"))
    elif digest not in {None, ""}:
        diagnostics.append(Diagnostic("error", "SP002C", "unsealed manifest may not claim a control_digest", "lock.json"))
    elif semantic not in {None, ""}:
        diagnostics.append(Diagnostic("error", "SP002F", "unsealed manifest may not claim a semantic_digest", "lock.json"))

    project = manifest.get("project")
    if not isinstance(project, dict):
        diagnostics.append(Diagnostic("error", "SP003", "project must be an object", "lock.json"))
        project = {}
    for key in ("id", "name", "profile"):
        if not meaningful_text(project.get(key)):
            diagnostics.append(Diagnostic("error", "SP004", f"project.{key} is required", "lock.json"))
    if project.get("profile") not in {"micro", "standard", "high_assurance"}:
        diagnostics.append(
            Diagnostic("error", "SP005", "project.profile must be micro, standard, or high_assurance", "lock.json")
        )
    if project.get("id") and not valid_id(project.get("id")):
        diagnostics.append(Diagnostic("error", "SP006", "project.id has an invalid format", "lock.json"))

    release = manifest.get("release")
    if not isinstance(release, dict):
        diagnostics.append(Diagnostic("error", "SP007", "release must be an object", "lock.json"))
        release = {}
    for key in ("id", "version", "smallest_complete_loop"):
        if not isinstance(release.get(key), str) or not release.get(key):
            diagnostics.append(Diagnostic("error", "SP008", f"release.{key} is required", "lock.json"))

    active_build = manifest.get("active_build")
    if not isinstance(active_build, dict):
        diagnostics.append(Diagnostic("error", "SP009", "active_build must be an object", "lock.json"))
        active_build = {}
    for key in ("id", "contract", "evidence"):
        if not isinstance(active_build.get(key), str) or not active_build.get(key):
            diagnostics.append(Diagnostic("error", "SP010", f"active_build.{key} is required", "lock.json"))

    authority = manifest.get("authority")
    if not isinstance(authority, dict) or not isinstance(authority.get("decision_owners"), dict):
        diagnostics.append(
            Diagnostic("error", "SP011", "authority.decision_owners must define product and technical authority", "lock.json")
        )
        authority = {}
    governing_sources = authority.get("governing_sources") if isinstance(authority, dict) else None
    if not isinstance(governing_sources, list) or any(not isinstance(item, str) for item in governing_sources):
        diagnostics.append(
            Diagnostic("error", "SP011A", "authority.governing_sources must be an array of strings", "lock.json")
        )

    verdicts = manifest.get("verdicts")
    if not isinstance(verdicts, dict):
        diagnostics.append(Diagnostic("error", "SP012", "verdicts must be an object", "lock.json"))
        verdicts = {}
    verdict_contracts = {
        "intent": INTENT_VERDICTS,
        "definition": DEFINITION_VERDICTS,
        "build": BUILD_VERDICTS,
        "as_built": AS_BUILT_VERDICTS,
        "release": RELEASE_VERDICTS,
    }
    for key, allowed in verdict_contracts.items():
        if verdicts.get(key) not in allowed:
            diagnostics.append(
                Diagnostic("error", "SP013", f"verdicts.{key} must be one of {sorted(allowed)}", "lock.json")
            )

    for list_key in (
        "material_blockers",
        "artifacts",
        "requirements",
        "builds",
        "external_facts",
        "amendments",
        "decisions",
        "invalidated_requirements",
        "risk_triggers",
        "seal_history",
    ):
        if not isinstance(manifest.get(list_key), list):
            diagnostics.append(Diagnostic("error", "SP014", f"{list_key} must be an array", "lock.json"))

    artifacts = manifest.get("artifacts", []) if isinstance(manifest.get("artifacts"), list) else []
    artifact_by_path: dict[str, dict[str, Any]] = {}
    lowercase_paths: dict[str, str] = {}
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            diagnostics.append(Diagnostic("error", "SP015", f"artifact {index} must be an object", "lock.json"))
            continue
        relative = artifact.get("path")
        if not isinstance(relative, str) or not relative:
            diagnostics.append(Diagnostic("error", "SP016", f"artifact {index} needs a path", "lock.json"))
            continue
        if relative in artifact_by_path:
            diagnostics.append(Diagnostic("error", "SP017", f"duplicate artifact path: {relative}", "lock.json"))
            continue
        folded = relative.casefold()
        if folded in lowercase_paths and lowercase_paths[folded] != relative:
            diagnostics.append(
                Diagnostic("error", "SP018", f"case-only artifact collision: {lowercase_paths[folded]} and {relative}", "lock.json")
            )
        lowercase_paths[folded] = relative
        artifact_by_path[relative] = artifact
        path, error = safe_path(pack, relative)
        if error or path is None:
            diagnostics.append(Diagnostic("error", "SP019", f"unsafe artifact path {relative}: {error}", "lock.json"))
            continue
        if path.is_symlink():
            diagnostics.append(Diagnostic("error", "SP020", "artifact may not be a symlink", relative))
        if not path.is_file():
            diagnostics.append(Diagnostic("error", "SP021", "artifact file is missing", relative))
            continue
        expected = artifact.get("sha256")
        if expected:
            actual = sha256(path)
            if actual != expected:
                diagnostics.append(
                    Diagnostic("error", "SP022", f"digest mismatch: expected {expected}, got {actual}", relative)
                )
        else:
            diagnostics.append(Diagnostic("warning", "SP023", "artifact has no sha256 digest", relative))
        if not isinstance(artifact.get("version"), str) or not artifact.get("version"):
            diagnostics.append(Diagnostic("error", "SP024", "artifact version is required", relative))
        role = artifact.get("role")
        if role is not None and role not in ARTIFACT_ROLES:
            diagnostics.append(Diagnostic("error", "SP024A", f"artifact role must be one of {sorted(ARTIFACT_ROLES)}", relative))

    for relative in sorted(required_artifacts(manifest)):
        if relative not in artifact_by_path:
            diagnostics.append(Diagnostic("error", "SP025", "required artifact is absent from manifest", relative))

    diagnostics.extend(markdown_link_diagnostics(pack, artifact_by_path))

    requirements = manifest.get("requirements", []) if isinstance(manifest.get("requirements"), list) else []
    requirement_by_id: dict[str, dict[str, Any]] = {}
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            diagnostics.append(Diagnostic("error", "SP040", f"requirement {index} must be an object", "lock.json"))
            continue
        req_id = requirement.get("id")
        if not valid_id(req_id):
            diagnostics.append(Diagnostic("error", "SP041", f"requirement {index} has an invalid id", "lock.json"))
            continue
        if req_id in requirement_by_id:
            diagnostics.append(Diagnostic("error", "SP042", f"duplicate requirement id: {req_id}", "lock.json"))
            continue
        requirement_by_id[req_id] = requirement
        if requirement.get("scope") not in REQUIREMENT_SCOPES:
            diagnostics.append(Diagnostic("error", "SP043", f"{req_id} has an invalid scope", "lock.json"))
        if requirement.get("state") not in FEATURE_STATES:
            diagnostics.append(Diagnostic("error", "SP044", f"{req_id} has an invalid feature state", "lock.json"))
        for key in ("depends_on", "owners"):
            if not isinstance(requirement.get(key, []), list):
                diagnostics.append(Diagnostic("error", "SP045", f"{req_id}.{key} must be an array", "lock.json"))
        owners = requirement.get("owners", [])
        if isinstance(owners, list) and not valid_unique_text_list(owners):
            diagnostics.append(Diagnostic("error", "SP045A", f"{req_id}.owners must contain unique meaningful canonical owner IDs", "lock.json"))
        dependencies = requirement.get("depends_on", [])
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if not valid_id(dependency):
                    diagnostics.append(Diagnostic("error", "SP045B", f"{req_id}.depends_on contains an invalid requirement ID", "lock.json"))

    for req_id, requirement in requirement_by_id.items():
        for dependency in requirement.get("depends_on", []):
            if not valid_id(dependency):
                continue
            if dependency not in requirement_by_id:
                diagnostics.append(Diagnostic("error", "SP046", f"{req_id} depends on unknown requirement {dependency}", "lock.json"))
                continue
            if requirement.get("scope") in {"mvp", "mandatory"} and requirement_by_id[dependency].get("scope") in {"later", "out"}:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "SP047",
                        f"included requirement {req_id} depends on excluded or deferred requirement {dependency}",
                        "lock.json",
                    )
                )

    requirement_cycle = find_cycle(requirement_by_id)
    if requirement_cycle:
        diagnostics.append(
            Diagnostic(
                "error",
                "SP048",
                f"requirement dependency cycle: {' -> '.join(requirement_cycle)}",
                "lock.json",
            )
        )

    builds_list = manifest.get("builds", []) if isinstance(manifest.get("builds"), list) else []
    build_by_id: dict[str, dict[str, Any]] = {}
    for index, build in enumerate(builds_list):
        if not isinstance(build, dict):
            diagnostics.append(Diagnostic("error", "SP050", f"build {index} must be an object", "lock.json"))
            continue
        build_id = build.get("id")
        if not valid_id(build_id):
            diagnostics.append(Diagnostic("error", "SP051", f"build {index} has an invalid id", "lock.json"))
            continue
        if build_id in build_by_id:
            diagnostics.append(Diagnostic("error", "SP052", f"duplicate build id: {build_id}", "lock.json"))
            continue
        build_by_id[build_id] = build
        if build.get("status") not in BUILD_STATUSES:
            diagnostics.append(Diagnostic("error", "SP053", f"{build_id} has an invalid status", "lock.json"))
        for key in ("requirements", "claimed_owners", "depends_on", "overlap_approved_with"):
            if not isinstance(build.get(key), list):
                diagnostics.append(Diagnostic("error", "SP054", f"{build_id}.{key} must be an array", "lock.json"))
        for req_id in build.get("requirements", []):
            if not valid_id(req_id):
                diagnostics.append(Diagnostic("error", "SP054A", f"{build_id}.requirements contains an invalid requirement ID", "lock.json"))
                continue
            if req_id not in requirement_by_id:
                diagnostics.append(Diagnostic("error", "SP055", f"{build_id} references unknown requirement {req_id}", "lock.json"))
        for dependency in build.get("depends_on", []):
            if not valid_id(dependency):
                diagnostics.append(Diagnostic("error", "SP054B", f"{build_id}.depends_on contains an invalid build ID", "lock.json"))
        for key in ("contract", "evidence"):
            relative = build.get(key)
            if not isinstance(relative, str) or relative not in artifact_by_path:
                diagnostics.append(Diagnostic("error", "SP056", f"{build_id}.{key} is not a registered artifact", "lock.json"))
        controlled_status = build.get("status") in {"locked", "in_progress", "interrupted", "reconciled"}
        if controlled_status:
            if not meaningful_text(build.get("base_revision")):
                diagnostics.append(Diagnostic("error", "SP057", f"{build_id} needs a resolved base_revision", "lock.json"))
            if not meaningful_text(build.get("lock_version")):
                diagnostics.append(Diagnostic("error", "SP058", f"{build_id} needs a lock_version", "lock.json"))
            claimed = build.get("claimed_owners", [])
            if not valid_unique_text_list(claimed, allow_empty=False):
                diagnostics.append(Diagnostic("error", "SP058A", f"{build_id} needs unique meaningful claimed_owners", "lock.json"))
            if not build.get("requirements"):
                diagnostics.append(Diagnostic("error", "SP058B", f"{build_id} needs at least one assigned requirement", "lock.json"))
            for req_id in build.get("requirements", []):
                if not valid_id(req_id):
                    continue
                requirement = requirement_by_id.get(req_id, {})
                requirement_owners = text_set(requirement.get("owners", []))
                if requirement_owners and not requirement_owners.intersection(text_set(claimed)):
                    diagnostics.append(Diagnostic("error", "SP058C", f"{build_id} does not claim a canonical owner for requirement {req_id}", "lock.json"))

    active_id = active_build.get("id")
    if active_id not in build_by_id:
        diagnostics.append(Diagnostic("error", "SP059", "active_build.id is not present in builds", "lock.json"))
    elif build_by_id[active_id].get("contract") != active_build.get("contract") or build_by_id[active_id].get("evidence") != active_build.get("evidence"):
        diagnostics.append(Diagnostic("error", "SP060", "active_build paths disagree with the build record", "lock.json"))
    elif verdicts.get("build") == "aligned" and build_by_id[active_id].get("status") not in {"locked", "in_progress", "interrupted", "reconciled"}:
        diagnostics.append(Diagnostic("error", "SP060A", "an aligned Build Lock requires an active locked, in-progress, interrupted, or reconciled build", "lock.json"))
    if verdicts.get("build") == "aligned" and verdicts.get("definition") != "locked":
        diagnostics.append(Diagnostic("error", "SP060B", "Build Lock cannot align before Definition Lock", "lock.json"))

    execution_declared = execution_contract_aware(manifest)
    execution_controls_active = (
        verdicts.get("definition") == "locked" or verdicts.get("build") == "aligned"
    )
    if execution_declared:
        diagnostics.extend(
            Diagnostic("error", "SP060C", message, active_build.get("execution_contract"))
            for message in active_execution_contract_errors(
                pack,
                manifest,
                require=True,
                validate_decision=execution_controls_active,
            )
        )
    policy = manifest.get("execution_contract_policy")
    if policy is not None and policy != EXECUTION_CONTRACT_POLICY:
        diagnostics.append(
            Diagnostic("error", "SP060D", f"execution_contract_policy must be {EXECUTION_CONTRACT_POLICY}", "lock.json")
        )
    council_declared = council_completion_aware(manifest)
    if council_declared:
        diagnostics.extend(
            Diagnostic("error", "SP060E", message, active_build.get("council_review"))
            for message in active_council_review_errors(
                pack,
                manifest,
                require_completion=(
                    verdicts.get("as_built") == "reconciled"
                    or verdicts.get("release") == "closed"
                ),
            )
        )
    council_policy = manifest.get("council_completion_policy")
    if council_policy is not None and council_policy != COUNCIL_COMPLETION_POLICY:
        diagnostics.append(
            Diagnostic("error", "SP060F", f"council_completion_policy must be {COUNCIL_COMPLETION_POLICY}", "lock.json")
        )

    for build_id, build in build_by_id.items():
        for dependency in build.get("depends_on", []):
            if not valid_id(dependency):
                continue
            if dependency not in build_by_id:
                diagnostics.append(Diagnostic("error", "SP061", f"{build_id} depends on unknown build {dependency}", "lock.json"))
    cycle = find_cycle(build_by_id)
    if cycle:
        diagnostics.append(Diagnostic("error", "SP062", f"build dependency cycle: {' -> '.join(cycle)}", "lock.json"))

    active_parallel = [
        build for build in build_by_id.values() if build.get("status") in {"locked", "in_progress"}
    ]
    for left_index, left in enumerate(active_parallel):
        for right in active_parallel[left_index + 1 :]:
            requirement_overlap = text_set(left.get("requirements", [])) & text_set(right.get("requirements", []))
            if requirement_overlap:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "SP063R",
                        f"parallel builds {left.get('id')} and {right.get('id')} claim the same requirements: {sorted(requirement_overlap)}",
                        "lock.json",
                    )
                )
            overlap = text_set(left.get("claimed_owners", [])) & text_set(right.get("claimed_owners", []))
            approved = right.get("id") in text_set(left.get("overlap_approved_with", [])) and left.get("id") in text_set(right.get("overlap_approved_with", []))
            if overlap and not approved:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "SP063",
                        f"parallel builds {left.get('id')} and {right.get('id')} claim the same owners: {sorted(overlap)}",
                        "lock.json",
                    )
                )

    covered_requirements = {
        req_id for build in build_by_id.values() for req_id in build.get("requirements", []) if isinstance(req_id, str)
    }
    for req_id, requirement in requirement_by_id.items():
        if requirement.get("scope") in {"mvp", "mandatory"} and req_id not in covered_requirements:
            diagnostics.append(Diagnostic("error", "SP064", f"included requirement {req_id} is not assigned to any build", "lock.json"))

    for build_id, build in build_by_id.items():
        if build.get("status") != "reconciled":
            continue
        evidence_context = build.get("evidence_context")
        if not isinstance(evidence_context, dict):
            diagnostics.append(Diagnostic("error", "SP067", f"{build_id} needs evidence_context before reconciliation", "lock.json"))
            continue
        evidence_minimums = {
            "revision": 2,
            "environment": 3,
            "configuration": 3,
            "role": 3,
            "fixture": 8,
            "observed_at": 10,
            "expected": 8,
            "actual": 8,
        }
        for key, minimum in evidence_minimums.items():
            value = evidence_context.get(key)
            if not meaningful_text(value, minimum):
                diagnostics.append(Diagnostic("error", "SP068", f"{build_id}.evidence_context.{key} must be resolved", "lock.json"))
        if evidence_context.get("observed_at") and parse_timestamp(evidence_context.get("observed_at")) is None:
            diagnostics.append(Diagnostic("error", "SP068A", f"{build_id}.evidence_context.observed_at must be an ISO-8601 timestamp with timezone", "lock.json"))
        if evidence_context.get("flaky") is not False:
            diagnostics.append(Diagnostic("error", "SP069", f"{build_id} cannot reconcile with flaky or unclassified evidence", "lock.json"))

    invalidated = manifest.get("invalidated_requirements", []) if isinstance(manifest.get("invalidated_requirements"), list) else []
    for req_id in invalidated:
        if not valid_id(req_id):
            diagnostics.append(Diagnostic("error", "SP065A", "invalidated_requirements contains an invalid requirement ID", "lock.json"))
            continue
        if req_id not in requirement_by_id:
            diagnostics.append(Diagnostic("error", "SP065", f"unknown invalidated requirement {req_id}", "lock.json"))
    if invalidated and (verdicts.get("as_built") == "reconciled" or verdicts.get("release") == "closed"):
        diagnostics.append(Diagnostic("error", "SP066", "invalidated evidence blocks reconciled or closed verdicts", "lock.json"))

    risk_triggers = manifest.get("risk_triggers", []) if isinstance(manifest.get("risk_triggers"), list) else []
    for trigger in risk_triggers:
        if not isinstance(trigger, str):
            diagnostics.append(Diagnostic("error", "SP070", "risk trigger must be a string", "lock.json"))
            continue
        if trigger not in RISK_TRIGGERS:
            diagnostics.append(Diagnostic("error", "SP070", f"unknown risk trigger: {trigger}", "lock.json"))
    if risk_triggers and "security-operations.md" not in artifact_by_path:
        diagnostics.append(Diagnostic("error", "SP071", "risk triggers require security-operations.md", "lock.json"))

    decisions = manifest.get("decisions", []) if isinstance(manifest.get("decisions"), list) else []
    decision_ids: set[str] = set()
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            diagnostics.append(Diagnostic("error", "SP072", f"decision {index} must be an object", "lock.json"))
            continue
        decision_id = decision.get("id")
        if not valid_id(decision_id) or decision_id in decision_ids:
            diagnostics.append(Diagnostic("error", "SP073", f"decision {index} needs a unique valid id", "lock.json"))
            continue
        decision_ids.add(decision_id)
        if decision.get("class") not in DECISION_CLASSES:
            diagnostics.append(Diagnostic("error", "SP074", f"{decision_id} has an invalid decision class", "lock.json"))
        if decision.get("status") not in DECISION_STATUSES:
            diagnostics.append(Diagnostic("error", "SP075", f"{decision_id} has an invalid decision status", "lock.json"))
        for key in ("statement", "authority"):
            value = decision.get(key)
            minimum = 12 if key == "statement" else 3
            if not meaningful_text(value, minimum):
                diagnostics.append(Diagnostic("error", "SP076", f"{decision_id}.{key} is required", "lock.json"))
        if decision.get("class") == "hypothesis" and decision.get("status") == "accepted":
            diagnostics.append(Diagnostic("error", "SP077", f"hypothesis {decision_id} may be testing or provisional, not accepted as fact", "lock.json"))
        if decision.get("class") == "deferred" and decision.get("status") != "deferred":
            diagnostics.append(Diagnostic("error", "SP077A", f"deferred decision {decision_id} must use deferred status", "lock.json"))

    amendments = manifest.get("amendments", []) if isinstance(manifest.get("amendments"), list) else []
    amendment_ids: set[str] = set()
    for index, amendment in enumerate(amendments):
        if not isinstance(amendment, dict):
            diagnostics.append(Diagnostic("error", "SP078", f"amendment {index} must be an object", "lock.json"))
            continue
        amendment_id = amendment.get("id")
        if not valid_id(amendment_id) or amendment_id in amendment_ids:
            diagnostics.append(Diagnostic("error", "SP079", f"amendment {index} needs a unique valid id", "lock.json"))
            continue
        amendment_ids.add(amendment_id)
        changes = amendment.get("changes")
        if not isinstance(changes, dict) or set(changes) != SEMANTIC_CHANGE_KEYS:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SP079A",
                    f"{amendment_id}.changes must contain exactly {sorted(SEMANTIC_CHANGE_KEYS)}",
                    "lock.json",
                )
            )
        elif any(not isinstance(changes[key], list) for key in SEMANTIC_CHANGE_KEYS):
            diagnostics.append(Diagnostic("error", "SP079B", f"{amendment_id} semantic change entries must be arrays", "lock.json"))
        for key in ("authority", "reason", "created_at"):
            minimum = 8 if key == "reason" else 3
            if not meaningful_text(amendment.get(key), minimum):
                diagnostics.append(Diagnostic("error", "SP079C", f"{amendment_id}.{key} is required", "lock.json"))
        if amendment.get("created_at") and parse_timestamp(amendment.get("created_at")) is None:
            diagnostics.append(Diagnostic("error", "SP079F", f"{amendment_id}.created_at must be an ISO-8601 timestamp with timezone", "lock.json"))
        impacted = amendment.get("impacted_requirements")
        if not isinstance(impacted, list):
            diagnostics.append(Diagnostic("error", "SP079D", f"{amendment_id}.impacted_requirements must be an array", "lock.json"))
        else:
            for req_id in impacted:
                if not valid_id(req_id):
                    diagnostics.append(Diagnostic("error", "SP079E", f"{amendment_id} has an invalid impacted requirement ID", "lock.json"))
                    continue
                if req_id not in requirement_by_id:
                    diagnostics.append(Diagnostic("error", "SP079E", f"{amendment_id} impacts unknown requirement {req_id}", "lock.json"))
        approval_evidence = amendment.get("approval_evidence")
        if not isinstance(approval_evidence, str) or approval_evidence not in artifact_by_path:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SP079G",
                    f"{amendment_id}.approval_evidence must reference a registered artifact",
                    "lock.json",
                )
            )

    last_phase, last_phase_entry, history_errors = inspect_transition_history(manifest)
    for message in history_errors:
        diagnostics.append(Diagnostic("error", "SP085", message, "lock.json"))
    history_entries = manifest.get("seal_history", []) if isinstance(manifest.get("seal_history"), list) else []
    for index, entry in enumerate(history_entries):
        if not isinstance(entry, dict):
            continue
        decision_authorities = entry.get("decision_authorities")
        if (
            not isinstance(decision_authorities, dict)
            or not decision_authorities
            or any(not isinstance(key, str) or not meaningful_text(value) for key, value in decision_authorities.items())
        ):
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SP085E",
                    f"seal_history[{index}].decision_authorities must preserve the declared authority snapshot",
                    "lock.json",
                )
            )
        amendment = entry.get("amendment")
        if isinstance(amendment, str) and amendment not in amendment_ids:
            diagnostics.append(Diagnostic("error", "SP085A", f"seal_history[{index}] references unknown amendment {amendment}", "lock.json"))
        if isinstance(amendment, str) and amendment in amendment_ids:
            amendment_record = next(
                (item for item in amendments if isinstance(item, dict) and item.get("id") == amendment),
                {},
            )
            prior = history_entries[index - 1] if index > 0 and isinstance(history_entries[index - 1], dict) else {}
            prior_authorities = prior.get("decision_authorities") if isinstance(prior, dict) else None
            authorized_values = {
                value for value in prior_authorities.values() if isinstance(value, str)
            } if isinstance(prior_authorities, dict) else set()
            if amendment_record.get("authority") not in authorized_values:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "SP085F",
                        f"amendment {amendment} authority is not bound to the prior sealed decision owners",
                        "lock.json",
                    )
                )
    history = manifest.get("seal_history") if isinstance(manifest.get("seal_history"), list) else []
    if sealed_at and history:
        latest = history[-1] if isinstance(history[-1], dict) else {}
        if latest.get("semantic_digest") != semantic:
            diagnostics.append(Diagnostic("error", "SP085B", "latest history semantic digest differs from the sealed baseline", "lock.json"))
        registered_digests = {
            item.get("path"): item.get("sha256")
            for item in artifacts
            if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("sha256"), str)
        }
        if history_artifact_snapshot(latest) != registered_digests:
            diagnostics.append(Diagnostic("error", "SP085C", "latest history artifact ledger differs from the sealed manifest", "lock.json"))
        if latest.get("invalidated_requirements") != manifest.get("invalidated_requirements"):
            diagnostics.append(Diagnostic("error", "SP085D", "latest history invalidation ledger differs from the sealed manifest", "lock.json"))
    if verdicts.get("definition") == "locked" and last_phase is None:
        diagnostics.append(Diagnostic("error", "SP086", "Definition Lock requires a sealed definition transition after the latest amendment", "lock.json"))
    active_record = build_by_id.get(active_id, {})
    active_status = active_record.get("status")
    if verdicts.get("build") == "aligned":
        allowed_phases = {"build"} if active_status in {"locked", "in_progress", "interrupted"} else {"as-built", "release"}
        if last_phase not in allowed_phases:
            diagnostics.append(Diagnostic("error", "SP087", f"aligned Build Lock with status {active_status} is inconsistent with last sealed phase {last_phase}", "lock.json"))
    if verdicts.get("as_built") == "reconciled" and last_phase not in {"as-built", "release"}:
        diagnostics.append(Diagnostic("error", "SP088", "reconciled as-built verdict requires an as-built transition", "lock.json"))
    if verdicts.get("release") == "closed" and last_phase != "release":
        diagnostics.append(Diagnostic("error", "SP089", "closed release requires release to be the latest sealed phase", "lock.json"))
    if last_phase_entry is not None and last_phase in {"build", "as-built", "release"}:
        if last_phase_entry.get("active_build") != active_id:
            diagnostics.append(Diagnostic("error", "SP089A", "latest phase transition references a different active build", "lock.json"))
        if last_phase_entry.get("lock_version") != active_record.get("lock_version"):
            diagnostics.append(Diagnostic("error", "SP089B", "latest phase transition lock_version differs from the active build", "lock.json"))

    external_facts = manifest.get("external_facts", []) if isinstance(manifest.get("external_facts"), list) else []
    today = date.today()
    for index, fact in enumerate(external_facts):
        if not isinstance(fact, dict):
            diagnostics.append(Diagnostic("error", "SP080", f"external fact {index} must be an object", "lock.json"))
            continue
        for key in ("id", "claim", "source", "source_version", "applicability", "observed_at"):
            if not meaningful_text(fact.get(key)):
                diagnostics.append(Diagnostic("error", "SP081", f"external fact {index} needs {key}", "lock.json"))
        observed = parse_calendar_date(fact.get("observed_at"))
        if fact.get("observed_at") and observed is None:
            diagnostics.append(Diagnostic("error", "SP081A", f"external fact {fact.get('id', index)} has invalid observed_at", "lock.json"))
        elif observed and observed > today:
            diagnostics.append(Diagnostic("error", "SP081B", f"external fact {fact.get('id', index)} is dated in the future", "lock.json"))
        expiry = fact.get("expires_at")
        trigger = fact.get("revalidate_on")
        if not expiry and not trigger:
            diagnostics.append(Diagnostic("error", "SP082", f"external fact {fact.get('id', index)} needs expires_at or revalidate_on", "lock.json"))
        if expiry:
            expiry_date = parse_calendar_date(expiry)
            if expiry_date is None:
                diagnostics.append(Diagnostic("error", "SP083", f"external fact {fact.get('id', index)} has invalid expires_at", "lock.json"))
            elif expiry_date < today:
                level = "error" if verdicts.get("definition") == "locked" else "warning"
                diagnostics.append(Diagnostic(level, "SP084", f"external fact {fact.get('id', index)} is stale", "lock.json"))

    blockers = manifest.get("material_blockers", []) if isinstance(manifest.get("material_blockers"), list) else []
    blocking = [blocker for blocker in blockers if isinstance(blocker, dict) and blocker.get("blocking") is True]
    if verdicts.get("definition") == "locked":
        if verdicts.get("intent") not in {"locked", "supported"}:
            diagnostics.append(Diagnostic("error", "SP090", "Definition Lock requires locked or supported intent", "lock.json"))
        if blocking:
            diagnostics.append(Diagnostic("error", "SP091", "blocking material decisions prevent Definition Lock", "lock.json"))
        if not manifest.get("sealed_at"):
            diagnostics.append(Diagnostic("error", "SP092", "Definition Lock requires a sealed manifest", "lock.json"))
        loop = release.get("smallest_complete_loop")
        if not meaningful_text(loop, 12):
            diagnostics.append(Diagnostic("error", "SP092A", "Definition Lock requires a resolved smallest complete value loop", "lock.json"))
        decision_owners = authority.get("decision_owners", {}) if isinstance(authority, dict) else {}
        product_owner = decision_owners.get("product") if isinstance(decision_owners, dict) else None
        if not meaningful_text(product_owner):
            diagnostics.append(Diagnostic("error", "SP092B", "Definition Lock requires resolved product decision authority", "lock.json"))
        included = [item for item in requirement_by_id.values() if item.get("scope") in {"mvp", "mandatory"}]
        if not included:
            diagnostics.append(Diagnostic("error", "SP092C", "Definition Lock requires at least one included requirement", "lock.json"))
        governing_decisions = [item for item in decisions if isinstance(item, dict) and item.get("class") in {"product_invariant", "release_commitment"}]
        if not governing_decisions:
            diagnostics.append(Diagnostic("error", "SP092D", "Definition Lock requires at least one product invariant or active-release commitment", "lock.json"))
        for decision in governing_decisions:
            if decision.get("status") != "accepted":
                diagnostics.append(Diagnostic("error", "SP092E", f"governing decision {decision.get('id')} must be accepted before Definition Lock", "lock.json"))
        for req_id, requirement in requirement_by_id.items():
            if requirement.get("scope") in {"mvp", "mandatory"}:
                owners = requirement.get("owners", [])
                if not isinstance(owners, list) or not owners:
                    diagnostics.append(Diagnostic("error", "SP093A", f"{req_id}.owners must name at least one canonical owner before Definition Lock", "lock.json"))
                field_minimums = {
                    "actor": 3,
                    "trigger": 8,
                    "behavior": 12,
                    "constraints": 8,
                    "negative": 12,
                    "unchanged": 12,
                    "acceptance": 12,
                    "owner": 2,
                    "proof": 12,
                }
                for key, minimum in field_minimums.items():
                    value = requirement.get(key)
                    if not meaningful_text(value, minimum):
                        diagnostics.append(Diagnostic("error", "SP093", f"{req_id}.{key} must be resolved before Definition Lock", "lock.json"))
                if isinstance(owners, list) and requirement.get("owner") not in owners:
                    diagnostics.append(Diagnostic("error", "SP093B", f"{req_id}.owner must be one of its canonical owners", "lock.json"))
        for relative, artifact in artifact_by_path.items():
            path, error = safe_path(pack, relative)
            if error or path is None or not path.is_file() or path.suffix.lower() != ".md":
                continue
            if UNRESOLVED_RE.search(path.read_text(encoding="utf-8", errors="replace")):
                diagnostics.append(Diagnostic("error", "SP094", "unresolved marker remains in locked artifact", relative))

    independent = manifest.get("independent_review")
    if not isinstance(independent, dict):
        diagnostics.append(
            Diagnostic("error", "SP094A", "independent_review must be an object", "lock.json")
        )
        independent = {}
    missing_review_fields = sorted(INDEPENDENT_REVIEW_FIELDS - set(independent))
    if missing_review_fields:
        diagnostics.append(
            Diagnostic(
                "error",
                "SP094B",
                f"independent_review is missing required fields: {missing_review_fields}",
                "lock.json",
            )
        )
    if not isinstance(independent.get("required"), bool):
        diagnostics.append(
            Diagnostic("error", "SP094C", "independent_review.required must be a boolean", "lock.json")
        )
    if independent.get("status") not in INDEPENDENT_REVIEW_STATUSES:
        diagnostics.append(
            Diagnostic(
                "error",
                "SP094D",
                f"independent_review.status must be one of {sorted(INDEPENDENT_REVIEW_STATUSES)}",
                "lock.json",
            )
        )
    for key in ("evidence", "reviewer", "reviewed_at", "scope", "revision"):
        if key in independent and independent.get(key) is not None and not isinstance(independent.get(key), str):
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SP094E",
                    f"independent_review.{key} must be a string or null",
                    "lock.json",
                )
            )
    independent_required = project.get("profile") == "high_assurance" or bool(risk_triggers) or (isinstance(independent, dict) and independent.get("required") is True)
    if independent_required:
        if not isinstance(independent, dict) or independent.get("required") is not True:
            diagnostics.append(Diagnostic("error", "SP095", "risk profile requires independent_review.required=true", "lock.json"))
        elif verdicts.get("definition") == "locked" and independent.get("status") != "verified":
            diagnostics.append(Diagnostic("error", "SP096", "Definition Lock requires verified independent review for this risk profile", "lock.json"))
        elif verdicts.get("release") == "closed" and independent.get("status") != "verified":
            diagnostics.append(Diagnostic("error", "SP096A", "release closure requires verified independent review", "lock.json"))
    if isinstance(independent, dict) and independent.get("status") == "verified":
        evidence = independent.get("evidence")
        if not isinstance(evidence, str) or evidence not in artifact_by_path:
            diagnostics.append(
                Diagnostic("error", "SP097", "verified independent review requires a registered evidence artifact", "lock.json")
            )
        reviewer = independent.get("reviewer")
        decision_owners = authority.get("decision_owners", {}) if isinstance(authority, dict) else {}
        owner_values = {
            value for value in decision_owners.values() if isinstance(value, str)
        } if isinstance(decision_owners, dict) else set()
        if not meaningful_text(reviewer) or reviewer in owner_values:
            diagnostics.append(
                Diagnostic("error", "SP097A", "verified independent review requires a named reviewer distinct from decision owners", "lock.json")
            )
        for key, minimum in (("scope", 8), ("revision", 2)):
            if not meaningful_text(independent.get(key), minimum):
                diagnostics.append(
                    Diagnostic("error", "SP097B", f"verified independent review requires a resolved {key}", "lock.json")
                )
        if parse_timestamp(independent.get("reviewed_at")) is None:
            diagnostics.append(
                Diagnostic("error", "SP097C", "verified independent review requires reviewed_at with timezone", "lock.json")
            )

    if verdicts.get("release") == "closed":
        if verdicts.get("as_built") != "reconciled":
            diagnostics.append(Diagnostic("error", "SP100", "release closure requires reconciled as-built evidence", "lock.json"))
        if blocking:
            diagnostics.append(Diagnostic("error", "SP101", "release closure cannot retain blocking decisions", "lock.json"))
        for req_id, requirement in requirement_by_id.items():
            if requirement.get("scope") in {"mvp", "mandatory"} and requirement.get("state") not in {"verified", "live"}:
                diagnostics.append(Diagnostic("error", "SP102", f"release requirement {req_id} is not verified", "lock.json"))
        for build_id, build in build_by_id.items():
            if text_set(build.get("requirements", [])) & {
                req_id for req_id, requirement in requirement_by_id.items() if requirement.get("scope") in {"mvp", "mandatory"}
            } and build.get("status") != "reconciled":
                diagnostics.append(Diagnostic("error", "SP103", f"release build {build_id} is not reconciled", "lock.json"))

    if verdicts.get("as_built") == "reconciled":
        active_record = build_by_id.get(active_id, {})
        if active_record.get("status") != "reconciled":
            diagnostics.append(Diagnostic("error", "SP104", "reconciled as-built verdict requires the active build to be reconciled", "lock.json"))

    return manifest, diagnostics


def emit(diagnostics: list[Diagnostic], json_output: bool = False) -> None:
    if json_output:
        print(json.dumps([asdict(item) for item in diagnostics], indent=2))
        return
    if not diagnostics:
        print("Start Pack validation passed.")
        return
    for item in diagnostics:
        location = f" ({item.path})" if item.path else ""
        print(f"[{item.level.upper()} {item.code}] {item.message}{location}")


def template_text(name: str, project_name: str, release_id: str, build_id: str) -> str:
    templates = {
        "intent-contract.md": f"""# Actual Intent Lock\n\nProject: {project_name}\nRelease: {release_id}\nStatus: UNRESOLVED\n\n## Outcome and primary value event\n\nUNRESOLVED\n\n## Primary users, jobs, and required actors\n\nUNRESOLVED\n\n## Non-negotiables and prohibitions\n\nUNRESOLVED\n\n## Tradeoffs, authority, scope boundary, and completion proof\n\nUNRESOLVED\n""",
        "scope-release.md": """# Product and Release Scope\n\n## Smallest complete MVP\n\nUNRESOLVED\n\n## Included, mandatory, later, and out\n\nUNRESOLVED\n\n## Requirement quality and acceptance\n\nEach included requirement needs an actor, trigger, behavior, constraint, negative case, owner, and observable proof.\n""",
        "experience-surfaces.md": """# Experience, Journeys, and Surfaces\n\n## Actors and lifecycle journeys\n\nUNRESOLVED\n\n## Routes, navigation, and reachability\n\nUNRESOLVED\n\n## Loading, empty, error, offline, retry, success, and recovery states\n\nUNRESOLVED\n\n## Responsive and accessibility contract\n\nUNRESOLVED\n""",
        "architecture-contract.md": """# Architecture and Canonical Ownership\n\n## Operating envelope and topology\n\nUNRESOLVED\n\n## Feature/module owners, directories, interfaces, and dependency direction\n\nUNRESOLVED\n\n## Reuse, create, migration, and deployment decisions\n\nUNRESOLVED\n""",
        "data-contract.md": """# Data Contract\n\n## Entities, relationships, constraints, indexes, and canonical ownership\n\nUNRESOLVED\n\n## State, concurrency, consistency, ordering, and lifecycle\n\nUNRESOLVED\n\n## Classification, retention, deletion propagation, backup, restore, and migrations\n\nUNRESOLVED\n""",
        "api-integrations.md": """# API and Integration Contract\n\n## Interfaces, schemas, consumers, auth, errors, and versioning\n\nUNRESOLVED\n\n## Idempotency, ordering, retries, timeouts, backpressure, and degradation\n\nUNRESOLVED\n\n## External capability, cost, policy, freshness, and exit path\n\nUNRESOLVED\n""",
        "security-operations.md": """# Security and Operations\n\n## Trust boundaries, threat and abuse cases, access/session lifecycle\n\nUNRESOLVED\n\n## Secrets, dependencies, privacy lifecycle, telemetry, and compliance owner\n\nUNRESOLVED\n\n## Capacity, SLOs, RPO/RTO, deployment, rollback, restore, and incident response\n\nUNRESOLVED\n""",
        "delivery-map.md": """# Delivery and Impact Map\n\n## Dependency-ordered vertical slices\n\nUNRESOLVED\n\n## Cross-build owners, impacts, invalidated evidence, and merge order\n\nUNRESOLVED\n\n## Release reconciliation and closure\n\nUNRESOLVED\n""",
        "traceability.md": """# Traceability\n\nTrace: intent/prohibition → requirement → journey → canonical owner → data/API → acceptance → test → feature state → evidence.\n\nUNRESOLVED\n""",
        "decisions-changes.md": """# Decisions and Semantic Changes\n\nClassify decisions as invariant, active-release commitment, hypothesis, reversible implementation choice, or deferred.\n\nFor each amendment record ADDED, MODIFIED, REMOVED, RENAMED, and deliberately UNCHANGED behavior, authority, impact, compatibility, and proof.\n\nUNRESOLVED\n""",
        f"builds/{build_id}/contract.md": f"""# Build Contract: {build_id}\n\nVerdict: Blocked\nBase revision: UNRESOLVED\nLock version: UNRESOLVED\n\n## Included requirements and protected unchanged behavior\n\nUNRESOLVED\n\n## Claimed canonical owners, dependencies, migrations, and merge order\n\nUNRESOLVED\n\n## Positive, negative, concurrency, recovery, and rollback proof\n\nUNRESOLVED\n""",
        f"builds/{build_id}/evidence.md": f"""# Build Evidence: {build_id}\n\nVerdict: Unverifiable\nSource revision/build/environment/configuration: UNRESOLVED\n\n## Planned versus actual\n\nUNRESOLVED\n\n## Validation results and feature states\n\nUNRESOLVED\n\n## Invalidated prior evidence, remaining gaps, and next baseline\n\nUNRESOLVED\n""",
    }
    return templates[name]


def execution_contract_template(
    project_id: str,
    release_id: str,
    release_version: str,
    build_id: str,
) -> dict[str, Any]:
    """Create a registered but deliberately blocked execution decision."""
    return {
        "schemaVersion": execution_contract.SCHEMA_VERSION,
        "binding": {
            "projectId": project_id,
            "releaseId": release_id,
            "releaseVersion": release_version,
            "buildId": build_id,
            "lockVersion": release_version,
        },
        "phase": "first_delivery",
        "wholeProduct": {
            "preserved": True,
            "summary": "UNRESOLVED",
            "complexity": "multi_deliverable",
        },
        "deliverables": [
            {
                "id": "D1",
                "active": True,
                "outcome": "UNRESOLVED",
                "entry": "UNRESOLVED",
                "ending": "UNRESOLVED",
                "proof": [],
                "journeySteps": [],
                "constraints": [],
                "requirementIds": [],
                "completionScope": "active_deliverable",
                "completionClaims": [],
                "excludedFromActive": [],
                "informationComplete": False,
                "fitsExecutionWindow": False,
                "endToEnd": False,
            },
            {"id": "D2", "active": False, "outcome": "UNRESOLVED later deliverable"},
        ],
        "executionTarget": {
            "kind": "other",
            "productionIntent": False,
            "establishedApplicationAvailable": False,
            "repositoryFit": "unknown",
            "sitesRole": "none",
            "rationale": "UNRESOLVED",
            "constraintsConsidered": [],
            "coreValueDependsOn": {
                name: False for name in execution_contract.OPERATIONAL_DEPENDENCIES
            },
        },
    }


def command_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        project_index_payload = project_index.build_index(root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Unable to build the project index: {exc}", file=sys.stderr)
        return 2
    pack = root / PACK_DIR
    if pack.is_symlink():
        print(f"Refusing symlinked Start Pack path: {pack}", file=sys.stderr)
        return 2
    if pack.exists() and any(pack.iterdir()):
        print(f"Refusing to overwrite existing Start Pack: {pack}", file=sys.stderr)
        return 2
    if not valid_id(args.project_id) or not valid_id(args.release_id) or not valid_id(args.build_id):
        print("project, release, and build IDs must use letters, digits, dot, underscore, or hyphen", file=sys.stderr)
        return 2
    pack.mkdir(parents=True, exist_ok=True)
    artifact_names = list(MICRO_ARTIFACTS if args.profile == "micro" else STANDARD_ARTIFACTS)
    build_contract = f"builds/{args.build_id}/contract.md"
    build_evidence = f"builds/{args.build_id}/evidence.md"
    build_execution_contract = f"builds/{args.build_id}/execution-contract.json"
    build_council_review = f"builds/{args.build_id}/council-review.json"
    build_observation_receipt = f"builds/{args.build_id}/observation-receipts.json"
    build_observation_output = f"builds/{args.build_id}/observation-output.log"
    artifact_names.extend((build_contract, build_evidence))
    for relative in artifact_names:
        path = pack / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            template_text(relative, args.project_name, args.release_id, args.build_id),
            encoding="utf-8",
        )
    write_json(
        pack / build_execution_contract,
        execution_contract_template(
            args.project_id,
            args.release_id,
            args.release_version,
            args.build_id,
        ),
    )
    artifact_names.append(build_execution_contract)
    write_json(pack / build_council_review, council_review_template())
    artifact_names.append(build_council_review)
    write_json(pack / build_observation_receipt, observation_receipt_template())
    artifact_names.append(build_observation_receipt)
    (pack / build_observation_output).write_text("", encoding="utf-8")
    artifact_names.append(build_observation_output)
    artifact_roles = {
        build_execution_contract: "execution_contract",
        build_council_review: "council_review",
        build_observation_receipt: "runner_receipt",
        build_observation_output: "observation",
    }
    artifacts = [
        {
            "path": relative,
            "version": args.release_version,
            "sha256": sha256(pack / relative),
            "role": artifact_roles.get(relative, "governance"),
        }
        for relative in artifact_names
    ]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "execution_contract_policy": EXECUTION_CONTRACT_POLICY,
        "council_completion_policy": COUNCIL_COMPLETION_POLICY,
        "project": {"id": args.project_id, "name": args.project_name, "profile": args.profile},
        "release": {
            "id": args.release_id,
            "version": args.release_version,
            "smallest_complete_loop": "UNRESOLVED",
        },
        "active_build": {
            "id": args.build_id,
            "contract": build_contract,
            "evidence": build_evidence,
            "execution_contract": build_execution_contract,
            "council_review": build_council_review,
            "observation_receipt": build_observation_receipt,
            "observation_output": build_observation_output,
        },
        "authority": {
            "governing_sources": [],
            "decision_owners": {
                "product": "UNRESOLVED",
                "technical": "Delegated to the implementing agent within locked product boundaries",
                "legal_or_regulated": "External accountable owner when applicable",
            },
        },
        "verdicts": {
            "intent": "unknown",
            "definition": "blocked",
            "build": "not_started",
            "as_built": "not_started",
            "release": "not_started",
        },
        "material_blockers": [],
        "artifacts": artifacts,
        "requirements": [],
        "builds": [
            {
                "id": args.build_id,
                "status": "planned",
                "base_revision": "UNRESOLVED",
                "lock_version": args.release_version,
                "requirements": [],
                "claimed_owners": [],
                "depends_on": [],
                "overlap_approved_with": [],
                "contract": build_contract,
                "evidence": build_evidence,
                "execution_contract": build_execution_contract,
                "council_review": build_council_review,
                "observation_receipt": build_observation_receipt,
                "observation_output": build_observation_output,
            }
        ],
        "external_facts": [],
        "decisions": [],
        "amendments": [],
        "invalidated_requirements": [],
        "risk_triggers": [],
        "independent_review": {
            "required": args.profile == "high_assurance",
            "status": "unverified",
            "evidence": None,
            "reviewer": None,
            "reviewed_at": None,
            "scope": None,
            "revision": None,
        },
        "sealed_at": None,
        "semantic_digest": None,
        "control_digest": None,
        "seal_history": [],
    }
    write_json(pack / "lock.json", manifest)
    write_json(pack / "project-index.json", project_index_payload)
    print(f"Initialized blocked Start Pack at {pack}")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    _, diagnostics = validate_manifest(Path(args.root).resolve())
    emit(diagnostics, args.json)
    return 1 if any(item.level == "error" for item in diagnostics) else 0


def command_seal(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    pack = root / PACK_DIR
    manifest_path = pack / "lock.json"
    try:
        manifest = read_json(manifest_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    verdicts = manifest.get("verdicts", {}) if isinstance(manifest.get("verdicts"), dict) else {}
    already_sealed = bool(manifest.get("control_digest"))
    if args.checkpoint and (args.amendment or args.transition):
        print("A checkpoint may not also be a transition or amendment", file=sys.stderr)
        return 2
    if args.amendment and args.transition and args.transition != "definition":
        print("An amendment may be combined only with a definition transition", file=sys.stderr)
        return 2
    if not (args.amendment or args.transition or args.checkpoint):
        print("Seal requires --transition phase, --amendment ID, or --checkpoint", file=sys.stderr)
        return 2
    if not already_sealed and (args.transition != "definition" or args.amendment or args.checkpoint):
        print("The first controlled seal must be --transition definition", file=sys.stderr)
        return 2
    if args.amendment:
        amendment_records = manifest.get("amendments")
        amendment_record = next(
            (
                item
                for item in amendment_records
                if isinstance(item, dict) and item.get("id") == args.amendment
            ),
            None,
        ) if isinstance(amendment_records, list) else None
        if amendment_record is None:
            print(f"Unknown amendment ID: {args.amendment}", file=sys.stderr)
            return 2
        history = manifest.get("seal_history")
        latest = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else None
        prior_authorities = latest.get("decision_authorities") if isinstance(latest, dict) else None
        authorized_values = {
            value for value in prior_authorities.values() if isinstance(value, str)
        } if isinstance(prior_authorities, dict) else set()
        if amendment_record.get("authority") not in authorized_values:
            print("Amendment authority must match a decision owner from the prior sealed baseline", file=sys.stderr)
            return 2
        if not args.transition and (
            verdicts.get("definition") == "locked"
            or verdicts.get("build") == "aligned"
            or verdicts.get("as_built") == "reconciled"
            or verdicts.get("release") == "closed"
        ):
            print("Reopen affected verdicts before sealing an amendment, or combine it with --transition definition", file=sys.stderr)
            return 2

    last_phase, last_phase_entry, history_errors = inspect_transition_history(manifest)
    if history_errors:
        print(f"Cannot seal invalid transition history: {history_errors[0]}", file=sys.stderr)
        return 2
    if args.amendment:
        last_phase = None
    active_build = manifest.get("active_build")
    active_id = active_build.get("id") if isinstance(active_build, dict) else None
    builds = manifest.get("builds")
    active = (
        next(
            (item for item in builds if isinstance(item, dict) and item.get("id") == active_id),
            {},
        )
        if isinstance(builds, list)
        else {}
    )
    if (args.transition or args.checkpoint) and (not valid_id(active_id) or not meaningful_text(active.get("lock_version"))):
        print("Phase transitions and checkpoints require a valid active build and lock_version", file=sys.stderr)
        return 2
    contract_aware = execution_contract_aware(manifest)
    if (args.transition or args.checkpoint) and not contract_aware:
        print(
            "Execution contract migration required before any transition or checkpoint seal",
            file=sys.stderr,
        )
        return 2
    if contract_aware and (args.transition or args.checkpoint):
        execution_errors = active_execution_contract_errors(pack, manifest, require=True)
        if execution_errors:
            print(
                f"Execution contract blocks sealing: {execution_errors[0]}",
                file=sys.stderr,
            )
            return 2
    if args.checkpoint:
        if last_phase != "build" or last_phase_entry is None:
            print("Checkpoint requires an active Build phase", file=sys.stderr)
            return 2
        if active_id != last_phase_entry.get("active_build") or active.get("lock_version") != last_phase_entry.get("lock_version"):
            print("Checkpoint may not change the active build or lock_version", file=sys.stderr)
            return 2
        previous_status = last_phase_entry.get("build_status")
        current_status = active.get("status")
        if current_status not in CHECKPOINT_STATUSES or current_status not in CHECKPOINT_STATUS_MOVES.get(previous_status, set()):
            print(f"Cannot checkpoint build status from {previous_status} to {current_status}", file=sys.stderr)
            return 2
        if (
            verdicts.get("definition") != "locked"
            or verdicts.get("build") != "aligned"
            or verdicts.get("as_built") == "reconciled"
            or verdicts.get("release") == "closed"
        ):
            print("Checkpoint requires an aligned active build before as-built reconciliation or release closure", file=sys.stderr)
            return 2
    if args.transition:
        allowed_previous = {
            "definition": {None},
            "build": {"definition", "as-built"},
            "as-built": {"build"},
            "release": {"as-built"},
        }[args.transition]
        if last_phase not in allowed_previous:
            print(f"Cannot transition from {last_phase or 'unlocked'} to {args.transition}", file=sys.stderr)
            return 2
        if args.transition == "definition":
            if verdicts.get("definition") != "locked" or verdicts.get("release") == "closed":
                print("Definition transition requires definition=locked and a release that is not closed", file=sys.stderr)
                return 2
        elif args.transition == "build":
            if verdicts.get("definition") != "locked" or verdicts.get("build") != "aligned" or active.get("status") not in {"locked", "in_progress"}:
                print("Build transition requires a locked definition, aligned build verdict, and active locked or in-progress build", file=sys.stderr)
                return 2
        elif args.transition == "as-built":
            if verdicts.get("definition") != "locked" or verdicts.get("as_built") == "not_started":
                print("As-built transition requires a locked definition and an observed as-built verdict", file=sys.stderr)
                return 2
            if verdicts.get("as_built") == "reconciled" and active.get("status") != "reconciled":
                print("Reconciled as-built transition requires a reconciled active build", file=sys.stderr)
                return 2
        elif args.transition == "release":
            if verdicts.get("release") != "closed" or verdicts.get("as_built") != "reconciled" or active.get("status") != "reconciled":
                print("Release transition requires closed release, reconciled as-built verdict, and reconciled active build", file=sys.stderr)
                return 2
    positive_completion = (
        (args.transition == "as-built" and verdicts.get("as_built") == "reconciled")
        or (args.transition == "release" and verdicts.get("release") == "closed")
    )
    if positive_completion:
        if not council_completion_aware(manifest):
            print(
                "Council completion evidence migration required before a positive completion seal",
                file=sys.stderr,
            )
            return 2
        council_errors = active_council_review_errors(pack, manifest, require_completion=True)
        if council_errors:
            print(f"Council completion evidence blocks sealing: {council_errors[0]}", file=sys.stderr)
            return 2
    current_snapshot, snapshot_error = artifact_snapshot(pack, manifest)
    if snapshot_error:
        print(f"Cannot seal: {snapshot_error}", file=sys.stderr)
        return 2
    baseline_semantic: str | None = None
    removed_invalidated: set[str] = set()
    if already_sealed and not args.amendment:
        history = manifest.get("seal_history")
        latest = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else None
        if latest is None:
            print("Cannot reseal without a valid prior seal history entry", file=sys.stderr)
            return 2
        baseline_semantic = latest.get("semantic_digest")
        if (
            not isinstance(baseline_semantic, str)
            or manifest.get("semantic_digest") != baseline_semantic
            or semantic_contract_digest(manifest) != baseline_semantic
        ):
            print("Locked product semantics changed; record an authorized amendment", file=sys.stderr)
            return 2
        previous_snapshot = history_artifact_snapshot(latest)
        if previous_snapshot is None:
            print("Prior seal has no valid artifact digest ledger", file=sys.stderr)
            return 2
        previous_invalidated = latest.get("invalidated_requirements")
        current_invalidated = manifest.get("invalidated_requirements")
        if not isinstance(previous_invalidated, list) or not isinstance(current_invalidated, list):
            print("Invalidated requirement state is missing from the operational ledger", file=sys.stderr)
            return 2
        previous_invalidated_set = set(item for item in previous_invalidated if isinstance(item, str))
        current_invalidated_set = set(item for item in current_invalidated if isinstance(item, str))
        removed_invalidated = previous_invalidated_set - current_invalidated_set
        removal_is_reconciled = args.transition == "as-built" and verdicts.get("as_built") == "reconciled"
        if removed_invalidated and not removal_is_reconciled:
            print(
                f"Invalidated requirements may be cleared only by reconciled as-built evidence: {', '.join(sorted(removed_invalidated))}",
                file=sys.stderr,
            )
            return 2
        if args.transition == "release" and current_invalidated_set != previous_invalidated_set:
            print("Release transition may not change invalidated requirements", file=sys.stderr)
            return 2
        declared_snapshot = {
            artifact.get("path"): artifact.get("sha256")
            for artifact in manifest.get("artifacts", [])
            if isinstance(artifact, dict) and isinstance(artifact.get("path"), str)
        }
        changed_paths = {
            path
            for path in set(previous_snapshot) | set(current_snapshot) | set(declared_snapshot)
            if previous_snapshot.get(path) != current_snapshot.get(path)
            or previous_snapshot.get(path) != declared_snapshot.get(path)
        }
        allowed_changes = {active.get("evidence")} if args.checkpoint or args.transition == "as-built" else set()
        if args.transition == "as-built":
            allowed_changes.update(
                {
                    active.get("council_review"),
                    active.get("observation_receipt"),
                    active.get("observation_output"),
                }
            )
        disallowed = sorted(path for path in changed_paths if path not in allowed_changes)
        if disallowed:
            print(
                f"Artifact drift requires an amendment before sealing: {', '.join(disallowed)}",
                file=sys.stderr,
            )
            return 2
        if removed_invalidated and active.get("evidence") not in changed_paths:
            print("Clearing invalidated requirements requires updated active-build reconciliation evidence", file=sys.stderr)
            return 2
    for artifact in manifest.get("artifacts", []):
        if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
            artifact["sha256"] = current_snapshot[artifact["path"]]
    current_invalidated = manifest.get("invalidated_requirements")
    if not isinstance(current_invalidated, list) or any(not valid_id(item) for item in current_invalidated):
        print("Invalidated requirements must be an array of valid requirement IDs", file=sys.stderr)
        return 2
    new_semantic = semantic_contract_digest(manifest)
    if baseline_semantic is not None and new_semantic != baseline_semantic:
        print("Operational seal changed locked product semantics; record an authorized amendment", file=sys.stderr)
        return 2
    manifest["semantic_digest"] = new_semantic
    timestamp = utc_now()
    manifest["sealed_at"] = timestamp
    history = manifest.setdefault("seal_history", [])
    history.append(
        {
            "sealed_at": timestamp,
            "amendment": args.amendment,
            "transition": args.transition,
            "checkpoint": args.checkpoint,
            "active_build": active_id if args.transition or args.checkpoint else None,
            "lock_version": active.get("lock_version") if args.transition or args.checkpoint else None,
            "build_status": active.get("status") if args.transition or args.checkpoint else None,
            "as_built_verdict": verdicts.get("as_built"),
            "invalidated_requirements": list(current_invalidated),
            "semantic_digest": new_semantic,
            "artifact_digests": current_snapshot,
            "decision_authorities": dict(
                manifest.get("authority", {}).get("decision_owners", {})
                if isinstance(manifest.get("authority"), dict)
                and isinstance(manifest.get("authority", {}).get("decision_owners"), dict)
                else {}
            ),
        }
    )
    _, _, prospective_errors = inspect_transition_history(manifest)
    if prospective_errors:
        print(f"Refusing invalid transition history: {prospective_errors[0]}", file=sys.stderr)
        return 2
    manifest["control_digest"] = control_digest(manifest)
    _, prospective_diagnostics = validate_manifest(root, manifest_override=manifest)
    prospective_errors = [item for item in prospective_diagnostics if item.level == "error"]
    if prospective_errors:
        first = prospective_errors[0]
        location = f" ({first.path})" if first.path else ""
        print(
            f"Refusing to seal an invalid Start Pack: [{first.code}] {first.message}{location}",
            file=sys.stderr,
        )
        return 2
    write_json(manifest_path, manifest)
    print(f"Sealed Start Pack at {timestamp}")
    return 0


def command_diff(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    pack = root / PACK_DIR
    try:
        manifest = read_json(pack / "lock.json")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    changes: list[dict[str, str]] = []
    registered: set[str] = set()
    for artifact in manifest.get("artifacts", []):
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            continue
        relative = artifact["path"]
        registered.add(relative)
        path, error = safe_path(pack, relative)
        if error or path is None or not path.is_file():
            changes.append({"path": relative, "status": "missing"})
            continue
        actual = sha256(path)
        if actual != artifact.get("sha256"):
            changes.append({"path": relative, "status": "changed", "sha256": actual})
    for path in pack.rglob("*"):
        if not path.is_file() or path.name == "lock.json":
            continue
        relative = path.relative_to(pack).as_posix()
        if relative not in registered:
            changes.append({"path": relative, "status": "unregistered"})
    if args.json:
        print(json.dumps(changes, indent=2))
    elif changes:
        for item in changes:
            print(f"{item['status']}: {item['path']}")
    else:
        print("No artifact drift detected.")
    return 1 if changes else 0


def command_status(args: argparse.Namespace, resume: bool = False) -> int:
    root = Path(args.root).resolve()
    manifest, diagnostics = validate_manifest(root)
    if manifest is None:
        emit(diagnostics, args.json)
        return 1
    errors = [item for item in diagnostics if item.level == "error"]
    active_id = manifest.get("active_build", {}).get("id")
    active = next((item for item in manifest.get("builds", []) if isinstance(item, dict) and item.get("id") == active_id), {})
    result = {
        "project": manifest.get("project", {}).get("name"),
        "release": manifest.get("release", {}).get("id"),
        "verdicts": manifest.get("verdicts"),
        "active_build": active,
        "material_blockers": manifest.get("material_blockers"),
        "invalidated_requirements": manifest.get("invalidated_requirements"),
        "validation_errors": len(errors),
    }
    if resume:
        if errors:
            result["next_action"] = "Repair Start Pack validation errors before implementation."
        elif manifest.get("verdicts", {}).get("definition") != "locked":
            result["next_action"] = "Resolve blocking decisions and obtain Definition Lock."
        elif active.get("status") == "interrupted":
            result["next_action"] = "Compare the current revision with the build contract, classify partial effects, then resume or roll back."
        elif active.get("status") in {"locked", "in_progress"}:
            result["next_action"] = "Continue only the active build contract from its recorded base revision and revalidate before merge."
        else:
            result["next_action"] = "Lock the next build contract or perform release reconciliation."
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Project: {result['project']}")
        print(f"Release: {result['release']}")
        print(f"Verdicts: {json.dumps(result['verdicts'], sort_keys=True)}")
        print(f"Active build: {active_id} ({active.get('status', 'missing')})")
        print(f"Validation errors: {len(errors)}")
        if resume:
            print(f"Next action: {result['next_action']}")
    return 1 if errors else 0


def command_converge(args: argparse.Namespace) -> int:
    """Emit a deterministic repair queue without changing authoritative artifacts."""
    _, diagnostics = validate_manifest(Path(args.root).resolve())
    errors = [item for item in diagnostics if item.level == "error"]
    warnings = [item for item in diagnostics if item.level == "warning"]
    queue = [
        {
            "order": index,
            "code": item.code,
            "path": item.path,
            "repair": item.message,
        }
        for index, item in enumerate(errors, start=1)
    ]
    result = {
        "converged": not errors,
        "repair_queue": queue,
        "warnings": [asdict(item) for item in warnings],
        "rule": "Repair the control graph, reseal through an authorized amendment when locked, then rerun validate.",
    }
    if args.json:
        print(json.dumps(result, indent=2))
    elif errors:
        print("Convergence required:")
        for item in queue:
            location = f" ({item['path']})" if item["path"] else ""
            print(f"{item['order']}. [{item['code']}] {item['repair']}{location}")
    else:
        print("Start Pack control graph is structurally converged.")
        if warnings:
            print(f"Warnings: {len(warnings)}")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Selective Intelligence Start Pack controls")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a blocked Start Pack without overwriting existing work")
    init_parser.add_argument("--root", required=True)
    init_parser.add_argument("--project-id", required=True)
    init_parser.add_argument("--project-name", required=True)
    init_parser.add_argument("--release-id", required=True)
    init_parser.add_argument("--release-version", default="0.1.1")
    init_parser.add_argument("--build-id", default="b001-foundation")
    init_parser.add_argument("--profile", choices=("micro", "standard", "high_assurance"), default="standard")

    for name in ("validate", "doctor", "status", "resume", "diff", "converge"):
        child = subparsers.add_parser(name)
        child.add_argument("--root", required=True)
        child.add_argument("--json", action="store_true")

    seal_parser = subparsers.add_parser("seal", help="refresh control digests through an ordered phase transition, operational checkpoint, or authorized amendment")
    seal_parser.add_argument("--root", required=True)
    seal_parser.add_argument("--amendment")
    seal_parser.add_argument("--transition", choices=("definition", "build", "as-built", "release"))
    seal_parser.add_argument("--checkpoint", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        return command_init(args)
    if args.command in {"validate", "doctor"}:
        return command_validate(args)
    if args.command == "seal":
        return command_seal(args)
    if args.command == "diff":
        return command_diff(args)
    if args.command == "status":
        return command_status(args)
    if args.command == "resume":
        return command_status(args, resume=True)
    if args.command == "converge":
        return command_converge(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
