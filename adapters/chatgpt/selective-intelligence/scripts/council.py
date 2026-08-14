#!/usr/bin/env python3
"""Deterministic Guided Council packet controls.

This dependency-free utility validates portable council cases and packets.  It
does not call models, connectors, or external services and never claims that a
model behavior was tested.  JSON Schema provides ecosystem compatibility;
this module is authoritative for cross-document bindings and state invariants.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import uuid
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlparse


SCHEMA_VERSION = "0.3.0"
PACKET_TYPES = {
    "council_case",
    "worker_packet",
    "worker_response",
    "objector_packet",
    "objector_response",
    "alignment_packet",
    "alignment_record",
    "resume_packet",
}
ROLES = {"orchestrator", "intent_objector", "worker", "objector", "aligner", "reserve"}
INDEPENDENCE_GRADES = {
    "not_applicable",
    "separate_context_same_model",
    "independent_model",
    "independent_human",
}
MUTATING_ACTIONS = {
    "write_file",
    "modify_drive",
    "send_email",
    "push_code",
    "open_pr",
    "merge_pr",
    "delete",
    "publish",
    "spend",
    "change_permissions",
    "export_sensitive_data",
}
ACTIONS = MUTATING_ACTIONS | {"read_source", "read_repository"}
OBJECTOR_CATEGORIES = {
    "unsupported_claim",
    "missing_evidence",
    "unsafe_permission",
    "scope_drift",
    "unnecessary_complexity",
    "duplication",
    "failure_case",
    "provenance",
    "continuity",
}
SEVERITIES = {"advisory", "material", "blocking"}
HEX64 = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SECRET_KEY_RE = re.compile(
    r"(?:^|_)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential|authorization|private[_-]?key)(?:$|_)",
    re.I,
)
PROHIBITED_KEY_RE = re.compile(
    r"(?:^|_)(?:raw[_-]?prompt|prompt|chain[_-]?of[_-]?thought|hidden[_-]?reasoning|scratchpad|internal[_-]?monologue)(?:$|_)",
    re.I,
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*\b", re.I),
    re.compile(r"(?:api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]{8,}", re.I),
)
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "key",
    "password",
    "secret",
    "sig",
    "signature",
    "token",
}


@dataclass(frozen=True)
class Diagnostic:
    level: str
    code: str
    message: str
    path: str = "$"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def document_digest(document: dict[str, Any]) -> str:
    payload = copy.deepcopy(document)
    payload.pop("canonical_digest", None)
    return sha256_value(payload)


def stamp_document(document: dict[str, Any]) -> dict[str, Any]:
    document["canonical_digest"] = document_digest(document)
    return document


def ledger_entry_digest(entry: dict[str, Any]) -> str:
    payload = copy.deepcopy(entry)
    payload.pop("entry_digest", None)
    return sha256_value(payload)


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError(f"refusing symlinked JSON path: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing symlinked output path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def add_error(errors: list[Diagnostic], code: str, message: str, path: str = "$") -> None:
    errors.append(Diagnostic("error", code, message, path))


def exact_keys(
    value: Any,
    required: Iterable[str],
    optional: Iterable[str],
    path: str,
    errors: list[Diagnostic],
) -> bool:
    if not isinstance(value, dict):
        add_error(errors, "GC001", "must be an object", path)
        return False
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(value))
    extras = sorted(set(value) - allowed)
    if missing:
        add_error(errors, "GC002", f"missing required keys: {missing}", path)
    if extras:
        add_error(errors, "GC003", f"unknown keys are prohibited: {extras}", path)
    return not missing and not extras


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(ID_RE.fullmatch(value))


def meaningful(value: Any, minimum: int = 1) -> bool:
    return isinstance(value, str) and len(value.strip()) >= minimum and "TBD" not in value.upper() and "UNRESOLVED" not in value.upper()


def valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def unique_strings(value: Any, allow_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(meaningful(item) for item in value)
        and len(value) == len(set(value))
    )


def scan_prohibited(value: Any, path: str, errors: list[Diagnostic]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if SECRET_KEY_RE.search(key):
                add_error(errors, "GC010", "secret-bearing keys are prohibited", child_path)
            if PROHIBITED_KEY_RE.search(key):
                add_error(errors, "GC011", "raw prompts and hidden reasoning fields are prohibited", child_path)
            scan_prohibited(child, child_path, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_prohibited(child, f"{path}[{index}]", errors)
    elif isinstance(value, str):
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                add_error(errors, "GC012", "secret-like content is prohibited", path)
                break
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.query:
            keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
            if keys & SENSITIVE_QUERY_KEYS:
                add_error(errors, "GC013", "URLs with sensitive query parameters are prohibited", path)


def validate_common(document: dict[str, Any], expected: str, errors: list[Diagnostic]) -> None:
    if document.get("schema_version") != SCHEMA_VERSION:
        add_error(errors, "GC020", f"schema_version must be {SCHEMA_VERSION}", "$.schema_version")
    if document.get("packet_type") != expected:
        add_error(errors, "GC021", f"packet_type must be {expected}", "$.packet_type")
    if not valid_id(document.get("packet_id")):
        add_error(errors, "GC022", "packet_id has an invalid format", "$.packet_id")
    if not valid_timestamp(document.get("created_at")):
        add_error(errors, "GC023", "created_at must be a timezone-aware ISO-8601 timestamp", "$.created_at")
    digest = document.get("canonical_digest")
    if not isinstance(digest, str) or not HEX64.fullmatch(digest):
        add_error(errors, "GC024", "canonical_digest must be a lowercase SHA-256 digest", "$.canonical_digest")
    elif digest != document_digest(document):
        add_error(errors, "GC025", "canonical_digest does not match canonical packet content", "$.canonical_digest")


def validate_parent(parent: Any, path: str, errors: list[Diagnostic]) -> None:
    if not exact_keys(parent, {"packet_id", "packet_type", "digest"}, set(), path, errors):
        return
    if not valid_id(parent.get("packet_id")):
        add_error(errors, "GC026", "parent packet_id is invalid", f"{path}.packet_id")
    if parent.get("packet_type") not in PACKET_TYPES:
        add_error(errors, "GC027", "parent packet_type is invalid", f"{path}.packet_type")
    if not isinstance(parent.get("digest"), str) or not HEX64.fullmatch(parent["digest"]):
        add_error(errors, "GC028", "parent digest must be SHA-256", f"{path}.digest")


def validate_start_pack_binding(binding: Any, path: str, errors: list[Diagnostic]) -> None:
    if binding is None:
        return
    required = {
        "project_id",
        "release_id",
        "validator_version",
        "control_digest",
        "semantic_digest",
        "bound_at",
    }
    if not exact_keys(binding, required, set(), path, errors):
        return
    for key in ("project_id", "release_id", "validator_version"):
        if not meaningful(binding.get(key)):
            add_error(errors, "GC030", f"{key} is required", f"{path}.{key}")
    for key in ("control_digest", "semantic_digest"):
        if not isinstance(binding.get(key), str) or not HEX64.fullmatch(binding[key]):
            add_error(errors, "GC031", f"{key} must be SHA-256", f"{path}.{key}")
    if not valid_timestamp(binding.get("bound_at")):
        add_error(errors, "GC032", "bound_at must be timezone-aware", f"{path}.bound_at")


def verify_start_pack_binding(binding: Any, root: Path, errors: list[Diagnostic]) -> None:
    if binding is None:
        add_error(errors, "GC033", "a Start Pack binding is required for this check", "$.start_pack_binding")
        return
    try:
        lock = read_json(root / ".selective-intelligence" / "lock.json")
    except ValueError as exc:
        add_error(errors, "GC034", str(exc), "$.start_pack_binding")
        return
    comparisons = {
        "project_id": lock.get("project", {}).get("id"),
        "release_id": lock.get("release", {}).get("id"),
        "validator_version": lock.get("validator_version"),
        "control_digest": lock.get("control_digest"),
        "semantic_digest": lock.get("semantic_digest"),
    }
    for key, actual in comparisons.items():
        if binding.get(key) != actual:
            add_error(errors, "GC035", f"Start Pack {key} binding mismatch", f"$.start_pack_binding.{key}")


def validate_role_run(run: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "run_id",
        "role",
        "provider",
        "model",
        "surface",
        "context_id",
        "billing_pool_id",
        "allowed_data_classes",
        "started_at",
        "completed_at",
    }
    if not exact_keys(run, required, {"parent_run_id"}, path, errors):
        return
    for key in ("run_id", "provider", "model", "surface", "context_id", "billing_pool_id"):
        if not meaningful(run.get(key)):
            add_error(errors, "GC040", f"{key} is required", f"{path}.{key}")
    if run.get("role") not in ROLES:
        add_error(errors, "GC041", "role is invalid", f"{path}.role")
    if not unique_strings(run.get("allowed_data_classes")):
        add_error(errors, "GC042", "allowed_data_classes must be unique strings", f"{path}.allowed_data_classes")
    if not valid_timestamp(run.get("started_at")):
        add_error(errors, "GC043", "started_at must be timezone-aware", f"{path}.started_at")
    if run.get("completed_at") is not None and not valid_timestamp(run.get("completed_at")):
        add_error(errors, "GC044", "completed_at must be null or timezone-aware", f"{path}.completed_at")
    if "parent_run_id" in run and run["parent_run_id"] is not None and not meaningful(run["parent_run_id"]):
        add_error(errors, "GC045", "parent_run_id must be null or a run ID", f"{path}.parent_run_id")


def independence_grade(worker: dict[str, Any], objector: dict[str, Any]) -> str:
    if objector.get("provider") == "human":
        return "independent_human"
    if worker.get("context_id") == objector.get("context_id"):
        return "not_applicable"
    if worker.get("provider") == objector.get("provider") and worker.get("model") == objector.get("model"):
        return "separate_context_same_model"
    return "independent_model"


def append_ledger(
    case: dict[str, Any],
    actor_run_id: str,
    event_type: str,
    subject_id: str,
    subject_digest: str,
    *,
    material: bool = False,
    subject_revision: str = "not_applicable",
    validation_status: str = "not_applicable",
    approval_status: str = "not_required",
    correction_status: str = "not_applicable",
) -> None:
    ledger = case["provenance_ledger"]
    previous = ledger[-1]["entry_digest"] if ledger else "0" * 64
    run = next((item for item in case["role_runs"] if item.get("run_id") == actor_run_id), None)
    if run is None:
        raise ValueError("ledger actor run is not registered")
    entry = {
        "sequence": len(ledger) + 1,
        "entry_id": new_id("ledger"),
        "occurred_at": utc_now(),
        "actor_run_id": actor_run_id,
        "provider": run["provider"],
        "surface": run["surface"],
        "role": run["role"],
        "event_type": event_type,
        "subject_id": subject_id,
        "subject_digest": subject_digest,
        "subject_revision": subject_revision,
        "material": material,
        "validation_status": validation_status,
        "approval_status": approval_status,
        "correction_status": correction_status,
        "previous_entry_digest": previous,
        "entry_digest": "",
    }
    entry["entry_digest"] = ledger_entry_digest(entry)
    ledger.append(entry)


def validate_ledger(
    ledger: Any,
    runs_by_id: dict[str, dict[str, Any]],
    path: str,
    errors: list[Diagnostic],
) -> None:
    if not isinstance(ledger, list) or not ledger:
        add_error(errors, "GC050", "provenance ledger must contain a genesis entry", path)
        return
    previous = "0" * 64
    seen_ids: set[str] = set()
    allowed_events = {
        "case_initialized",
        "intent_challenge_recorded",
        "packet_exported",
        "worker_response_imported",
        "objector_response_imported",
        "alignment_applied",
        "resume_exported",
    }
    for index, entry in enumerate(ledger):
        item_path = f"{path}[{index}]"
        required = {
            "sequence",
            "entry_id",
            "occurred_at",
            "actor_run_id",
            "provider",
            "surface",
            "role",
            "event_type",
            "subject_id",
            "subject_digest",
            "subject_revision",
            "material",
            "validation_status",
            "approval_status",
            "correction_status",
            "previous_entry_digest",
            "entry_digest",
        }
        if not exact_keys(entry, required, set(), item_path, errors):
            continue
        if type(entry.get("sequence")) is not int or entry["sequence"] != index + 1:
            add_error(errors, "GC051", "ledger sequence must be contiguous from 1", f"{item_path}.sequence")
        if not valid_id(entry.get("entry_id")) or entry["entry_id"] in seen_ids:
            add_error(errors, "GC052", "ledger entry_id must be unique", f"{item_path}.entry_id")
        else:
            seen_ids.add(entry["entry_id"])
        if not valid_timestamp(entry.get("occurred_at")):
            add_error(errors, "GC053", "ledger timestamp is invalid", f"{item_path}.occurred_at")
        actor_run = runs_by_id.get(entry.get("actor_run_id"))
        if actor_run is None:
            add_error(errors, "GC054", "ledger actor_run_id is not a registered role run", f"{item_path}.actor_run_id")
        for key in ("provider", "surface"):
            if not meaningful(entry.get(key)):
                add_error(errors, "GC054A", f"ledger {key} is required", f"{item_path}.{key}")
            elif actor_run is not None and entry.get(key) != actor_run.get(key):
                add_error(errors, "GC054C", f"ledger {key} does not identify the actor run", f"{item_path}.{key}")
        if entry.get("role") not in ROLES:
            add_error(errors, "GC054B", "ledger role is invalid", f"{item_path}.role")
        elif actor_run is not None and entry.get("role") != actor_run.get("role"):
            add_error(errors, "GC054D", "ledger role does not identify the actor run", f"{item_path}.role")
        if entry.get("event_type") not in allowed_events:
            add_error(errors, "GC055", "ledger event_type is invalid", f"{item_path}.event_type")
        if not valid_id(entry.get("subject_id")):
            add_error(errors, "GC056", "ledger subject_id is invalid", f"{item_path}.subject_id")
        for key in ("subject_digest", "previous_entry_digest", "entry_digest"):
            if not isinstance(entry.get(key), str) or not HEX64.fullmatch(entry[key]):
                add_error(errors, "GC057", f"{key} must be SHA-256", f"{item_path}.{key}")
        if not meaningful(entry.get("subject_revision")):
            add_error(errors, "GC057A", "ledger subject_revision is required", f"{item_path}.subject_revision")
        if type(entry.get("material")) is not bool:
            add_error(errors, "GC057B", "ledger material must be boolean", f"{item_path}.material")
        if entry.get("validation_status") not in {"unverified", "passed", "failed", "not_applicable"}:
            add_error(errors, "GC057C", "ledger validation_status is invalid", f"{item_path}.validation_status")
        if entry.get("approval_status") not in {"not_required", "approved", "denied", "pending"}:
            add_error(errors, "GC057D", "ledger approval_status is invalid", f"{item_path}.approval_status")
        if entry.get("correction_status") not in {"not_applicable", "pending", "applied", "revalidated"}:
            add_error(errors, "GC057E", "ledger correction_status is invalid", f"{item_path}.correction_status")
        if entry.get("previous_entry_digest") != previous:
            add_error(errors, "GC058", "ledger hash chain is broken", f"{item_path}.previous_entry_digest")
        if entry.get("entry_digest") != ledger_entry_digest(entry):
            add_error(errors, "GC059", "ledger entry digest is invalid", f"{item_path}.entry_digest")
        previous = entry.get("entry_digest", previous)


def validate_intent_lock(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "outcome",
        "reason",
        "primary_user",
        "job",
        "non_negotiables",
        "prohibitions",
        "tradeoff_rules",
        "included_scope",
        "excluded_scope",
        "material_open_decisions",
        "confidence",
        "source_precedence",
        "success_criteria",
        "authority_owner",
        "permission_boundaries",
        "permission_policy_id",
        "permission_policy_digest",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    for key in ("outcome", "reason", "primary_user", "job", "authority_owner", "permission_policy_id"):
        if not meaningful(value.get(key), 3):
            add_error(errors, "GC060", f"{key} must be resolved", f"{path}.{key}")
    for key in (
        "non_negotiables", "tradeoff_rules", "included_scope", "source_precedence",
        "success_criteria", "permission_boundaries",
    ):
        if not unique_strings(value.get(key), allow_empty=False):
            add_error(errors, "GC061", f"{key} must contain unique resolved statements", f"{path}.{key}")
    for key in ("prohibitions", "excluded_scope", "material_open_decisions"):
        if not unique_strings(value.get(key)):
            add_error(errors, "GC062", f"{key} must be unique statements", f"{path}.{key}")
    if value.get("confidence") not in {"locked", "supported", "provisional", "conflicted", "unknown"}:
        add_error(errors, "GC062A", "intent confidence is invalid", f"{path}.confidence")
    if value.get("confidence") in {"locked", "supported"} and value.get("material_open_decisions"):
        add_error(errors, "GC062B", "locked or supported intent cannot retain material open decisions", f"{path}.material_open_decisions")
    if not isinstance(value.get("permission_policy_digest"), str) or not HEX64.fullmatch(value["permission_policy_digest"]):
        add_error(errors, "GC062C", "permission_policy_digest must be SHA-256", f"{path}.permission_policy_digest")


def validate_intent_challenge(value: Any, path: str, errors: list[Diagnostic]) -> None:
    if value is None:
        return
    required = {
        "candidate_digest",
        "authoritative_source_id",
        "challenger_run",
        "independence_grade",
        "competing_interpretation",
        "consequence_difference",
        "resolution",
        "evidence_refs",
        "challenged_at",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    if not isinstance(value.get("candidate_digest"), str) or not HEX64.fullmatch(value["candidate_digest"]):
        add_error(errors, "GC062D", "candidate_digest must be SHA-256", f"{path}.candidate_digest")
    if not valid_id(value.get("authoritative_source_id")):
        add_error(errors, "GC062E", "authoritative_source_id is invalid", f"{path}.authoritative_source_id")
    validate_role_run(value.get("challenger_run"), f"{path}.challenger_run", errors)
    if isinstance(value.get("challenger_run"), dict) and value["challenger_run"].get("role") != "intent_objector":
        add_error(errors, "GC062F", "intent challenge requires an intent_objector run", f"{path}.challenger_run.role")
    if value.get("independence_grade") not in INDEPENDENCE_GRADES - {"not_applicable"}:
        add_error(errors, "GC062G", "intent challenge independence is invalid", f"{path}.independence_grade")
    for key in ("competing_interpretation", "consequence_difference"):
        if not meaningful(value.get(key), 20):
            add_error(errors, "GC062H", f"{key} must record a substantive challenge", f"{path}.{key}")
    if value.get("resolution") not in {"candidate_supported", "candidate_revised"}:
        add_error(errors, "GC062I", "intent challenge must record a resolved candidate verdict", f"{path}.resolution")
    if not unique_strings(value.get("evidence_refs"), allow_empty=False):
        add_error(errors, "GC062J", "intent challenge needs evidence references", f"{path}.evidence_refs")
    if not valid_timestamp(value.get("challenged_at")):
        add_error(errors, "GC062K", "intent challenge timestamp is invalid", f"{path}.challenged_at")


def validate_intent_challenge_binding(
    challenge: Any,
    intent_lock: Any,
    path: str,
    errors: list[Diagnostic],
) -> None:
    validate_intent_challenge(challenge, path, errors)
    if isinstance(challenge, dict) and isinstance(intent_lock, dict):
        if challenge.get("candidate_digest") != sha256_value(intent_lock):
            add_error(errors, "GC062L", "intent challenge is not bound to the current candidate", f"{path}.candidate_digest")


def validate_project_boundary(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "project_id",
        "adapter_id",
        "adapter_version",
        "adapter_digest",
        "allowed_destinations",
        "allowed_data_classes",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    for key in ("project_id", "adapter_id", "adapter_version"):
        if not meaningful(value.get(key)):
            add_error(errors, "GC063", f"{key} is required", f"{path}.{key}")
    if not isinstance(value.get("adapter_digest"), str) or not HEX64.fullmatch(value["adapter_digest"]):
        add_error(errors, "GC064", "adapter_digest must be SHA-256", f"{path}.adapter_digest")
    for key in ("allowed_destinations", "allowed_data_classes"):
        if not unique_strings(value.get(key), allow_empty=False):
            add_error(errors, "GC065", f"{key} must be a non-empty unique list", f"{path}.{key}")


def validate_grant(grant: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "approval_id",
        "action",
        "destination",
        "project_id",
        "data_classes",
        "approved_by",
        "approved_at",
        "expires_at",
        "max_minor_units",
        "billing_pool_id",
        "price_evidence_ids",
    }
    if not exact_keys(grant, required, set(), path, errors):
        return
    if not valid_id(grant.get("approval_id")):
        add_error(errors, "GC070", "approval_id is invalid", f"{path}.approval_id")
    if grant.get("action") not in ACTIONS:
        add_error(errors, "GC071", "approval action is invalid", f"{path}.action")
    for key in ("destination", "project_id", "approved_by"):
        if not meaningful(grant.get(key)):
            add_error(errors, "GC072", f"{key} is required", f"{path}.{key}")
    if not unique_strings(grant.get("data_classes")):
        add_error(errors, "GC073", "data_classes must be unique strings", f"{path}.data_classes")
    if not valid_timestamp(grant.get("approved_at")):
        add_error(errors, "GC074", "approved_at must be timezone-aware", f"{path}.approved_at")
    if grant.get("expires_at") is not None and not valid_timestamp(grant.get("expires_at")):
        add_error(errors, "GC075", "expires_at must be null or timezone-aware", f"{path}.expires_at")
    amount = grant.get("max_minor_units")
    if amount is not None and (type(amount) is not int or amount < 0):
        add_error(errors, "GC076", "max_minor_units must be a non-negative integer or null", f"{path}.max_minor_units")
    if grant.get("action") == "spend":
        if amount is None or not meaningful(grant.get("billing_pool_id")) or not unique_strings(grant.get("price_evidence_ids"), allow_empty=False):
            add_error(errors, "GC077", "spend approval needs max_minor_units, billing_pool_id, and price evidence", path)
    elif amount is not None or grant.get("billing_pool_id") is not None or grant.get("price_evidence_ids") != []:
        add_error(errors, "GC078", "non-spend approvals cannot carry budget fields", path)


def permission_policy_digest(value: dict[str, Any]) -> str:
    return sha256_value(
        {
            "policy_id": value.get("policy_id"),
            "default": value.get("default"),
            "rules": value.get("rules"),
        }
    )


def validate_permission_rule(rule: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {"rule_id", "action", "effect", "destination", "project_id", "data_classes"}
    if not exact_keys(rule, required, set(), path, errors):
        return
    if not valid_id(rule.get("rule_id")):
        add_error(errors, "GC078A", "permission rule_id is invalid", f"{path}.rule_id")
    if rule.get("action") not in ACTIONS:
        add_error(errors, "GC078B", "unknown permission actions deny and cannot be registered", f"{path}.action")
    if rule.get("effect") not in {"allow", "approval_required", "deny"}:
        add_error(errors, "GC078C", "permission effect is invalid", f"{path}.effect")
    if rule.get("action") in MUTATING_ACTIONS and rule.get("effect") == "allow":
        add_error(errors, "GC078I", "mutating actions cannot bypass explicit approval", f"{path}.effect")
    for key in ("destination", "project_id"):
        if not meaningful(rule.get(key)):
            add_error(errors, "GC078D", f"{key} is required", f"{path}.{key}")
    if not unique_strings(rule.get("data_classes")):
        add_error(errors, "GC078E", "rule data_classes must be unique", f"{path}.data_classes")


def validate_permissions(value: Any, path: str, errors: list[Diagnostic]) -> None:
    if not exact_keys(value, {"policy_id", "policy_digest", "default", "rules", "approval_receipts"}, set(), path, errors):
        return
    if not valid_id(value.get("policy_id")):
        add_error(errors, "GC078F", "permission policy_id is invalid", f"{path}.policy_id")
    if not isinstance(value.get("policy_digest"), str) or not HEX64.fullmatch(value["policy_digest"]):
        add_error(errors, "GC078G", "policy_digest must be SHA-256", f"{path}.policy_digest")
    elif value["policy_digest"] != permission_policy_digest(value):
        add_error(errors, "GC078H", "permission policy_digest does not match policy rules", f"{path}.policy_digest")
    if value.get("default") != "deny":
        add_error(errors, "GC079", "permission default must be deny", f"{path}.default")
    rules = value.get("rules")
    if not isinstance(rules, list):
        add_error(errors, "GC079A", "permission rules must be an array", f"{path}.rules")
        rules = []
    seen_rules: set[str] = set()
    for index, rule in enumerate(rules):
        validate_permission_rule(rule, f"{path}.rules[{index}]", errors)
        rule_id = rule.get("rule_id") if isinstance(rule, dict) else None
        if rule_id in seen_rules:
            add_error(errors, "GC079B", "permission rule_id must be unique", f"{path}.rules[{index}].rule_id")
        if isinstance(rule_id, str):
            seen_rules.add(rule_id)
    grants = value.get("approval_receipts")
    if not isinstance(grants, list):
        add_error(errors, "GC080", "approval_receipts must be an array", f"{path}.approval_receipts")
        return
    seen: set[str] = set()
    for index, grant in enumerate(grants):
        validate_grant(grant, f"{path}.approval_receipts[{index}]", errors)
        approval_id = grant.get("approval_id") if isinstance(grant, dict) else None
        if approval_id in seen:
            add_error(errors, "GC081", "approval receipt IDs must be unique", f"{path}.approval_receipts[{index}].approval_id")
        if isinstance(approval_id, str):
            seen.add(approval_id)


def validate_budget(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "currency",
        "shared_fixed_minor_units",
        "per_project_fixed_minor_units",
        "metered_planning_minor_units",
        "expected_increment_minor_units",
        "expected_total_minor_units",
        "pools",
        "price_evidence",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    currency = value.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        add_error(errors, "GC090", "currency must be an ISO-style three-letter code", f"{path}.currency")
    amount_keys = (
        "shared_fixed_minor_units", "per_project_fixed_minor_units", "metered_planning_minor_units",
        "expected_increment_minor_units", "expected_total_minor_units",
    )
    for key in amount_keys:
        amount = value.get(key)
        if type(amount) is not int or amount < 0:
            add_error(errors, "GC091", f"{key} must be a non-negative integer", f"{path}.{key}")
    if all(type(value.get(key)) is int for key in amount_keys):
        expected_increment = value["per_project_fixed_minor_units"] + value["metered_planning_minor_units"]
        expected_total = value["shared_fixed_minor_units"] + expected_increment
        if value["expected_increment_minor_units"] != expected_increment:
            add_error(errors, "GC091A", "expected increment does not recompute from per-project fixed plus metered", f"{path}.expected_increment_minor_units")
        if value["expected_total_minor_units"] != expected_total:
            add_error(errors, "GC091B", "expected total does not recompute from shared fixed plus increment", f"{path}.expected_total_minor_units")
    pools = value.get("pools")
    if not isinstance(pools, list):
        add_error(errors, "GC092", "pools must be an array", f"{path}.pools")
        pools = []
    pool_ids: set[str] = set()
    for index, pool in enumerate(pools):
        item_path = f"{path}.pools[{index}]"
        required_pool = {
            "pool_id",
            "kind",
            "enabled",
            "hard_limit_minor_units",
            "spent_minor_units",
            "overage_allowed",
        }
        if not exact_keys(pool, required_pool, set(), item_path, errors):
            continue
        if not valid_id(pool.get("pool_id")) or pool["pool_id"] in pool_ids:
            add_error(errors, "GC093", "pool_id must be unique", f"{item_path}.pool_id")
        else:
            pool_ids.add(pool["pool_id"])
        if pool.get("kind") not in {"fixed", "metered", "credits"}:
            add_error(errors, "GC094", "pool kind is invalid", f"{item_path}.kind")
        if type(pool.get("enabled")) is not bool or pool.get("overage_allowed") is not False:
            add_error(errors, "GC095", "enabled must be boolean and overage_allowed must be false", item_path)
        limit = pool.get("hard_limit_minor_units")
        spent = pool.get("spent_minor_units")
        if type(limit) is not int or limit < 0 or type(spent) is not int or spent < 0:
            add_error(errors, "GC096", "pool limits and spend must be non-negative integer minor units", item_path)
        elif spent > limit:
            add_error(errors, "GC097", "spent amount exceeds hard limit", item_path)
        if pool.get("kind") == "metered" and pool.get("enabled") is True and (type(limit) is not int or limit <= 0):
            add_error(errors, "GC097A", "enabled metered pools require a positive hard limit", item_path)
    evidence = value.get("price_evidence")
    if not isinstance(evidence, list):
        add_error(errors, "GC098", "price_evidence must be an array", f"{path}.price_evidence")
        return
    seen_evidence: set[str] = set()
    for index, item in enumerate(evidence):
        item_path = f"{path}.price_evidence[{index}]"
        required_evidence = {
            "evidence_id",
            "service",
            "amount_minor_units",
            "currency",
            "region",
            "source_url",
            "observed_on",
            "expires_on",
            "revalidate_on",
        }
        if not exact_keys(item, required_evidence, set(), item_path, errors):
            continue
        if not valid_id(item.get("evidence_id")) or item["evidence_id"] in seen_evidence:
            add_error(errors, "GC099", "price evidence_id must be unique", f"{item_path}.evidence_id")
        else:
            seen_evidence.add(item["evidence_id"])
        if type(item.get("amount_minor_units")) is not int or item["amount_minor_units"] < 0:
            add_error(errors, "GC100", "price amount must be integer minor units", f"{item_path}.amount_minor_units")
        if item.get("currency") != currency:
            add_error(errors, "GC101", "price evidence currency must match budget currency", f"{item_path}.currency")
        for key in ("service", "region", "source_url"):
            if not meaningful(item.get(key)):
                add_error(errors, "GC102", f"{key} is required", f"{item_path}.{key}")
        if not valid_date(item.get("observed_on")):
            add_error(errors, "GC103", "observed_on must be an ISO date", f"{item_path}.observed_on")
        expiry = item.get("expires_on")
        trigger = item.get("revalidate_on")
        if expiry is None and not meaningful(trigger):
            add_error(errors, "GC104", "price evidence needs expires_on or revalidate_on", item_path)
        if expiry is not None and not valid_date(expiry):
            add_error(errors, "GC105", "expires_on must be null or an ISO date", f"{item_path}.expires_on")
        if trigger is not None and not meaningful(trigger):
            add_error(errors, "GC106", "revalidate_on must be null or a meaningful trigger", f"{item_path}.revalidate_on")
        observed = item.get("observed_on")
        if valid_date(observed) and valid_date(expiry) and date.fromisoformat(expiry) < date.fromisoformat(observed):
            add_error(errors, "GC107", "expires_on cannot precede observed_on", f"{item_path}.expires_on")


def validate_capability(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {"capability_id", "disposition", "canonical_owner", "evidence_refs"}
    if not exact_keys(value, required, set(), path, errors):
        return
    if not valid_id(value.get("capability_id")) or not meaningful(value.get("canonical_owner")):
        add_error(errors, "GC110", "capability identity and owner are required", path)
    if value.get("disposition") not in {"reuse", "extend", "extract", "consolidate", "create", "remove"}:
        add_error(errors, "GC111", "capability disposition is invalid", f"{path}.disposition")
    if not unique_strings(value.get("evidence_refs"), allow_empty=False):
        add_error(errors, "GC112", "capability decision needs evidence_refs", f"{path}.evidence_refs")


def validate_source(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "source_id",
        "provider",
        "immutable_id",
        "title",
        "source_type",
        "project_id",
        "authority",
        "sensitivity",
        "data_classes",
        "version",
        "modified_at",
        "validated_at",
        "summary",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    for key in ("source_id", "provider", "immutable_id", "title", "source_type", "project_id", "version", "summary"):
        if not meaningful(value.get(key)):
            add_error(errors, "GC120", f"{key} is required", f"{path}.{key}")
    if value.get("authority") not in {"authoritative", "supporting", "draft", "unknown"}:
        add_error(errors, "GC121", "source authority is invalid", f"{path}.authority")
    if value.get("sensitivity") not in {"public", "internal", "confidential", "restricted"}:
        add_error(errors, "GC122", "source sensitivity is invalid", f"{path}.sensitivity")
    if not unique_strings(value.get("data_classes"), allow_empty=False):
        add_error(errors, "GC123", "source data_classes are required", f"{path}.data_classes")
    for key in ("modified_at", "validated_at"):
        if not valid_timestamp(value.get(key)):
            add_error(errors, "GC124", f"{key} must be timezone-aware", f"{path}.{key}")


def validate_evidence(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "evidence_id",
        "source_id",
        "locator",
        "summary",
        "classification",
        "observed_at",
        "content_digest",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    for key in ("evidence_id", "source_id", "locator", "summary"):
        if not meaningful(value.get(key)):
            add_error(errors, "GC130", f"{key} is required", f"{path}.{key}")
    if value.get("classification") not in {"confirmed", "inferred", "created", "unknown", "conflicted"}:
        add_error(errors, "GC131", "evidence classification is invalid", f"{path}.classification")
    if not valid_timestamp(value.get("observed_at")):
        add_error(errors, "GC132", "observed_at must be timezone-aware", f"{path}.observed_at")
    if not isinstance(value.get("content_digest"), str) or not HEX64.fullmatch(value["content_digest"]):
        add_error(errors, "GC133", "content_digest must be SHA-256", f"{path}.content_digest")


def validate_action(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "action_id",
        "action",
        "destination",
        "project_id",
        "data_classes",
        "approval_id",
        "amount_minor_units",
        "billing_pool_id",
        "price_evidence_ids",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    if not valid_id(value.get("action_id")):
        add_error(errors, "GC140", "action_id is invalid", f"{path}.action_id")
    if value.get("action") not in ACTIONS:
        add_error(errors, "GC141", "action is invalid", f"{path}.action")
    for key in ("destination", "project_id"):
        if not meaningful(value.get(key)):
            add_error(errors, "GC142", f"{key} is required", f"{path}.{key}")
    if value.get("approval_id") is not None and not valid_id(value.get("approval_id")):
        add_error(errors, "GC142A", "approval_id must be null or a valid approval receipt ID", f"{path}.approval_id")
    if not unique_strings(value.get("data_classes")):
        add_error(errors, "GC143", "action data_classes must be unique", f"{path}.data_classes")
    amount = value.get("amount_minor_units")
    if amount is not None and (type(amount) is not int or amount < 0):
        add_error(errors, "GC144", "amount_minor_units must be a non-negative integer or null", f"{path}.amount_minor_units")
    if value.get("action") == "spend":
        if amount is None or not meaningful(value.get("billing_pool_id")) or not unique_strings(value.get("price_evidence_ids"), allow_empty=False):
            add_error(errors, "GC145", "spend action needs integer amount, billing pool, and price evidence", path)
    elif amount is not None or value.get("billing_pool_id") is not None or value.get("price_evidence_ids") != []:
        add_error(errors, "GC146", "non-spend actions cannot carry budget fields", path)


def grant_matches_action(grant: dict[str, Any], action: dict[str, Any]) -> bool:
    return (
        grant.get("approval_id") == action.get("approval_id")
        and grant.get("action") == action.get("action")
        and grant.get("destination") == action.get("destination")
        and grant.get("project_id") == action.get("project_id")
        and set(grant.get("data_classes", [])) == set(action.get("data_classes", []))
        and grant.get("billing_pool_id") == action.get("billing_pool_id")
        and grant.get("price_evidence_ids") == action.get("price_evidence_ids")
    )


def rule_matches_action(rule: dict[str, Any], action: dict[str, Any]) -> bool:
    return (
        rule.get("action") == action.get("action")
        and rule.get("destination") == action.get("destination")
        and rule.get("project_id") == action.get("project_id")
        and set(rule.get("data_classes", [])) == set(action.get("data_classes", []))
    )


def check_actions_authorized(
    actions: list[dict[str, Any]],
    permissions: dict[str, Any],
    project: dict[str, Any],
    budget: dict[str, Any],
    path: str,
    errors: list[Diagnostic],
) -> None:
    receipts = permissions.get("approval_receipts", [])
    rules = permissions.get("rules", [])
    pools = {pool.get("pool_id"): pool for pool in budget.get("pools", []) if isinstance(pool, dict)}
    price_records = {
        item.get("evidence_id"): item for item in budget.get("price_evidence", []) if isinstance(item, dict)
    }
    now = datetime.now(timezone.utc)
    for index, action in enumerate(actions):
        item_path = f"{path}[{index}]"
        matching_rules = [rule for rule in rules if isinstance(rule, dict) and rule_matches_action(rule, action)]
        effects = {rule.get("effect") for rule in matching_rules}
        if "deny" in effects:
            add_error(errors, "GC147A", "deny rule takes precedence for this action", item_path)
            continue
        if not effects:
            add_error(errors, "GC147B", "unknown or unruled actions deny by default", item_path)
            continue
        if action.get("action") in MUTATING_ACTIONS and "approval_required" not in effects:
            add_error(errors, "GC147C", "mutating actions always require an explicit scoped approval receipt", item_path)
            continue
        receipt: dict[str, Any] | None = None
        if "approval_required" in effects:
            matches = [item for item in receipts if isinstance(item, dict) and grant_matches_action(item, action)]
            if len(matches) != 1:
                add_error(errors, "GC147", "approval_required action needs exactly one scoped approval receipt", item_path)
                continue
            receipt = matches[0]
        elif "allow" not in effects:
            add_error(errors, "GC147B", "action is not allowed by policy", item_path)
            continue
        elif action.get("approval_id") is not None:
            add_error(errors, "GC147D", "allow actions must not imply an unused approval receipt", f"{item_path}.approval_id")
            continue
        if action.get("destination") not in project.get("allowed_destinations", []):
            add_error(errors, "GC148", "action destination is outside the project boundary", f"{item_path}.destination")
        if action.get("project_id") != project.get("project_id"):
            add_error(errors, "GC149", "action project does not match the case", f"{item_path}.project_id")
        if not set(action.get("data_classes", [])).issubset(set(project.get("allowed_data_classes", []))):
            add_error(errors, "GC150", "action data crosses the project boundary", f"{item_path}.data_classes")
        expiry = receipt.get("expires_at") if receipt else None
        if isinstance(expiry, str) and valid_timestamp(expiry):
            parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if parsed < now:
                add_error(errors, "GC151", "approval has expired", item_path)
        if action.get("action") == "spend":
            amount = action.get("amount_minor_units")
            maximum = receipt.get("max_minor_units") if receipt else None
            if type(amount) is int and type(maximum) is int and amount > maximum:
                add_error(errors, "GC152", "spend exceeds its exact approval", item_path)
            pool = pools.get(action.get("billing_pool_id"))
            if not pool or pool.get("enabled") is not True:
                add_error(errors, "GC153", "billing pool is missing or disabled", item_path)
            elif type(amount) is int and pool.get("spent_minor_units", 0) + amount > pool.get("hard_limit_minor_units", -1):
                add_error(errors, "GC154", "spend would exceed the hard budget limit", item_path)
            for evidence_id in action.get("price_evidence_ids", []):
                record = price_records.get(evidence_id)
                if record is None:
                    add_error(errors, "GC155", "spend references unknown price evidence", item_path)
                    continue
                expiry_on = record.get("expires_on")
                trigger = record.get("revalidate_on")
                stale = isinstance(expiry_on, str) and valid_date(expiry_on) and date.fromisoformat(expiry_on) < date.today()
                if isinstance(trigger, str) and valid_date(trigger) and date.fromisoformat(trigger) <= date.today():
                    stale = True
                if expiry_on is None and (not isinstance(trigger, str) or not valid_date(trigger)):
                    stale = True
                if stale:
                    add_error(errors, "GC156", "stale price evidence blocks purchase", item_path)


def validate_task(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "task_id",
        "exact_task",
        "output_contract",
        "success_criteria",
        "prohibitions",
        "source_ids",
        "capability_ids",
        "requested_actions",
        "required_proof_ids",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    for key in ("task_id", "exact_task", "output_contract"):
        if not meaningful(value.get(key), 3):
            add_error(errors, "GC160", f"{key} must be resolved", f"{path}.{key}")
    for key in ("success_criteria", "source_ids", "capability_ids", "required_proof_ids"):
        if not unique_strings(value.get(key), allow_empty=False):
            add_error(errors, "GC161", f"{key} must be non-empty and unique", f"{path}.{key}")
    if not unique_strings(value.get("prohibitions")):
        add_error(errors, "GC162", "task prohibitions must be unique", f"{path}.prohibitions")
    actions = value.get("requested_actions")
    if not isinstance(actions, list):
        add_error(errors, "GC163", "requested_actions must be an array", f"{path}.requested_actions")
    else:
        seen: set[str] = set()
        for index, action in enumerate(actions):
            validate_action(action, f"{path}.requested_actions[{index}]", errors)
            action_id = action.get("action_id") if isinstance(action, dict) else None
            if action_id in seen:
                add_error(errors, "GC164", "task action_id must be unique", f"{path}.requested_actions[{index}].action_id")
            if isinstance(action_id, str):
                seen.add(action_id)


def validate_proof(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "proof_id",
        "status",
        "claim",
        "evidence_refs",
        "revision",
        "observed_at",
        "supersedes",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    if not valid_id(value.get("proof_id")) or not meaningful(value.get("claim"), 3) or not meaningful(value.get("revision")):
        add_error(errors, "GC170", "proof identity, claim, and revision are required", path)
    if value.get("status") not in {"valid", "invalidated"}:
        add_error(errors, "GC171", "proof status is invalid", f"{path}.status")
    if not unique_strings(value.get("evidence_refs"), allow_empty=False):
        add_error(errors, "GC172", "proof needs evidence_refs", f"{path}.evidence_refs")
    if not valid_timestamp(value.get("observed_at")):
        add_error(errors, "GC173", "proof observed_at must be timezone-aware", f"{path}.observed_at")
    if value.get("supersedes") is not None and not valid_id(value.get("supersedes")):
        add_error(errors, "GC174", "supersedes must be null or a proof ID", f"{path}.supersedes")


def validate_continuity(value: Any, path: str, errors: list[Diagnostic], require_resume: bool = False) -> None:
    required = {
        "current_state_summary",
        "repository",
        "uncommitted_changes",
        "migrations",
        "external_actions",
        "completed_steps",
        "next_safe_action",
        "checkpointed_at",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    if not meaningful(value.get("current_state_summary"), 3) or not meaningful(value.get("next_safe_action"), 3):
        add_error(errors, "GC180", "continuity summary and next safe action are required", path)
    if not valid_timestamp(value.get("checkpointed_at")):
        add_error(errors, "GC181", "checkpointed_at must be timezone-aware", f"{path}.checkpointed_at")
    repository = value.get("repository")
    if repository is not None:
        if exact_keys(repository, {"repository_id", "branch", "commit", "dirty"}, set(), f"{path}.repository", errors):
            for key in ("repository_id", "branch", "commit"):
                if not meaningful(repository.get(key)):
                    add_error(errors, "GC182", f"repository {key} is required", f"{path}.repository.{key}")
            if type(repository.get("dirty")) is not bool:
                add_error(errors, "GC183", "repository dirty must be boolean", f"{path}.repository.dirty")
    for key in ("uncommitted_changes", "migrations", "completed_steps"):
        if not unique_strings(value.get(key)):
            add_error(errors, "GC184", f"{key} must be unique strings", f"{path}.{key}")
    actions = value.get("external_actions")
    if not isinstance(actions, list):
        add_error(errors, "GC185", "external_actions must be an array", f"{path}.external_actions")
        return
    seen: set[str] = set()
    for index, action in enumerate(actions):
        item_path = f"{path}.external_actions[{index}]"
        required_action = {
            "action_id",
            "kind",
            "destination",
            "status",
            "idempotency_key",
            "receipt_ref",
            "retry_safe",
        }
        if not exact_keys(action, required_action, set(), item_path, errors):
            continue
        if not valid_id(action.get("action_id")) or action["action_id"] in seen:
            add_error(errors, "GC186", "external action_id must be unique", f"{item_path}.action_id")
        else:
            seen.add(action["action_id"])
        for key in ("kind", "destination", "idempotency_key"):
            if not meaningful(action.get(key)):
                add_error(errors, "GC187", f"{key} is required", f"{item_path}.{key}")
        if action.get("status") not in {"not_started", "attempted", "confirmed", "failed", "compensated"}:
            add_error(errors, "GC188", "external action status is invalid", f"{item_path}.status")
        if action.get("status") in {"attempted", "confirmed", "failed", "compensated"} and not meaningful(action.get("receipt_ref")):
            add_error(errors, "GC189", "attempted external action needs a receipt reference", f"{item_path}.receipt_ref")
        if action.get("status") == "not_started" and action.get("receipt_ref") is not None:
            add_error(errors, "GC190", "not-started action cannot claim a receipt", f"{item_path}.receipt_ref")
        if type(action.get("retry_safe")) is not bool:
            add_error(errors, "GC191", "retry_safe must be boolean", f"{item_path}.retry_safe")
        if require_resume and action.get("status") == "attempted" and action.get("retry_safe") is True:
            add_error(errors, "GC192", "an attempted action cannot be marked retry-safe without confirmation or compensation", item_path)


def validate_export_record(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "packet_id",
        "packet_type",
        "digest",
        "parent_case_digest",
        "run_id",
        "created_at",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    if not valid_id(value.get("packet_id")) or not valid_id(value.get("run_id")):
        add_error(errors, "GC193", "export packet and run IDs are invalid", path)
    if value.get("packet_type") not in {"worker_packet", "objector_packet", "alignment_packet", "resume_packet"}:
        add_error(errors, "GC194", "export packet_type is invalid", f"{path}.packet_type")
    for key in ("digest", "parent_case_digest"):
        if not isinstance(value.get(key), str) or not HEX64.fullmatch(value[key]):
            add_error(errors, "GC195", f"{key} must be SHA-256", f"{path}.{key}")
    if not valid_timestamp(value.get("created_at")):
        add_error(errors, "GC196", "export created_at is invalid", f"{path}.created_at")


def validate_case(case: dict[str, Any], errors: list[Diagnostic]) -> None:
    required = {
        "schema_version",
        "packet_type",
        "packet_id",
        "created_at",
        "updated_at",
        "revision",
        "canonical_digest",
        "start_pack_binding",
        "intent_lock",
        "intent_challenge",
        "project_boundary",
        "council_mode",
        "required_independence",
        "role_runs",
        "permissions",
        "budget_lock",
        "capabilities",
        "sources",
        "evidence",
        "task",
        "exports",
        "worker_response",
        "objector_response",
        "alignment_record",
        "proofs",
        "invalidated_proof_ids",
        "continuity",
        "status",
        "provenance_ledger",
    }
    if not exact_keys(case, required, set(), "$", errors):
        return
    validate_common(case, "council_case", errors)
    if not valid_timestamp(case.get("updated_at")):
        add_error(errors, "GC200", "updated_at must be timezone-aware", "$.updated_at")
    if type(case.get("revision")) is not int or case["revision"] < 1:
        add_error(errors, "GC201", "revision must be a positive integer", "$.revision")
    validate_start_pack_binding(case.get("start_pack_binding"), "$.start_pack_binding", errors)
    validate_intent_lock(case.get("intent_lock"), "$.intent_lock", errors)
    validate_intent_challenge_binding(case.get("intent_challenge"), case.get("intent_lock"), "$.intent_challenge", errors)
    validate_project_boundary(case.get("project_boundary"), "$.project_boundary", errors)
    if case.get("council_mode") not in {"single_model", "multi_provider"}:
        add_error(errors, "GC202", "council_mode is invalid", "$.council_mode")
    if case.get("required_independence") not in INDEPENDENCE_GRADES - {"not_applicable"}:
        add_error(errors, "GC203", "required_independence is invalid", "$.required_independence")

    runs = case.get("role_runs")
    run_ids: set[str] = set()
    contexts: set[str] = set()
    if not isinstance(runs, list) or not runs:
        add_error(errors, "GC204", "at least one role run is required", "$.role_runs")
        runs = []
    for index, run in enumerate(runs):
        validate_role_run(run, f"$.role_runs[{index}]", errors)
        if not isinstance(run, dict):
            continue
        run_id = run.get("run_id")
        context = run.get("context_id")
        if run_id in run_ids:
            add_error(errors, "GC205", "role run IDs must be unique", f"$.role_runs[{index}].run_id")
        if isinstance(run_id, str):
            run_ids.add(run_id)
        if context in contexts:
            add_error(errors, "GC206", "every council role run must use a distinct context", f"$.role_runs[{index}].context_id")
        if isinstance(context, str):
            contexts.add(context)
        parent_run = run.get("parent_run_id")
        if parent_run is not None and parent_run not in run_ids:
            add_error(errors, "GC207", "parent_run_id must reference an earlier run", f"$.role_runs[{index}].parent_run_id")

    validate_permissions(case.get("permissions"), "$.permissions", errors)
    if isinstance(case.get("intent_lock"), dict) and isinstance(case.get("permissions"), dict):
        if case["intent_lock"].get("permission_policy_id") != case["permissions"].get("policy_id"):
            add_error(errors, "GC207A", "Intent Lock permission policy ID does not match the active policy", "$.intent_lock.permission_policy_id")
        if case["intent_lock"].get("permission_policy_digest") != case["permissions"].get("policy_digest"):
            add_error(errors, "GC207B", "Intent Lock permission policy digest does not match the active policy", "$.intent_lock.permission_policy_digest")
    validate_budget(case.get("budget_lock"), "$.budget_lock", errors)

    capabilities = case.get("capabilities")
    capability_ids: set[str] = set()
    if not isinstance(capabilities, list) or not capabilities:
        add_error(errors, "GC208", "at least one capability decision is required", "$.capabilities")
        capabilities = []
    for index, item in enumerate(capabilities):
        validate_capability(item, f"$.capabilities[{index}]", errors)
        capability_id = item.get("capability_id") if isinstance(item, dict) else None
        if capability_id in capability_ids:
            add_error(errors, "GC209", "capability_id must be unique", f"$.capabilities[{index}].capability_id")
        if isinstance(capability_id, str):
            capability_ids.add(capability_id)

    sources = case.get("sources")
    source_ids: set[str] = set()
    if not isinstance(sources, list):
        add_error(errors, "GC210", "sources must be an array", "$.sources")
        sources = []
    for index, item in enumerate(sources):
        validate_source(item, f"$.sources[{index}]", errors)
        source_id = item.get("source_id") if isinstance(item, dict) else None
        if source_id in source_ids:
            add_error(errors, "GC211", "source_id must be unique", f"$.sources[{index}].source_id")
        if isinstance(source_id, str):
            source_ids.add(source_id)
        if isinstance(item, dict) and item.get("project_id") != case.get("project_boundary", {}).get("project_id"):
            add_error(errors, "GC212", "source belongs to a different project", f"$.sources[{index}].project_id")

    evidence = case.get("evidence")
    evidence_ids: set[str] = set()
    if not isinstance(evidence, list):
        add_error(errors, "GC213", "evidence must be an array", "$.evidence")
        evidence = []
    for index, item in enumerate(evidence):
        validate_evidence(item, f"$.evidence[{index}]", errors)
        evidence_id = item.get("evidence_id") if isinstance(item, dict) else None
        if evidence_id in evidence_ids:
            add_error(errors, "GC214", "evidence_id must be unique", f"$.evidence[{index}].evidence_id")
        if isinstance(evidence_id, str):
            evidence_ids.add(evidence_id)
        if isinstance(item, dict) and item.get("source_id") not in source_ids:
            add_error(errors, "GC215", "evidence references an unknown source", f"$.evidence[{index}].source_id")

    challenge = case.get("intent_challenge")
    if case.get("status") != "draft" and challenge is None:
        add_error(errors, "GC213A", "non-draft Council work requires a bound intent challenge", "$.intent_challenge")
    if isinstance(challenge, dict):
        source = next(
            (item for item in sources if isinstance(item, dict) and item.get("source_id") == challenge.get("authoritative_source_id")),
            None,
        )
        if source is None or source.get("authority") != "authoritative":
            add_error(errors, "GC213B", "intent challenge must bind an authoritative source", "$.intent_challenge.authoritative_source_id")
        if not set(challenge.get("evidence_refs", [])).issubset(evidence_ids):
            add_error(errors, "GC213C", "intent challenge references unknown evidence", "$.intent_challenge.evidence_refs")
        challenger = challenge.get("challenger_run")
        registered = next(
            (item for item in runs if isinstance(item, dict) and isinstance(challenger, dict) and item.get("run_id") == challenger.get("run_id")),
            None,
        )
        if registered != challenger:
            add_error(errors, "GC213D", "intent challenge run is not exactly registered in role history", "$.intent_challenge.challenger_run")
        orchestrator = next((item for item in runs if isinstance(item, dict) and item.get("role") == "orchestrator"), None)
        if isinstance(orchestrator, dict) and isinstance(challenger, dict):
            if challenge.get("independence_grade") != independence_grade(orchestrator, challenger):
                add_error(errors, "GC213E", "intent challenge independence grade is inaccurate", "$.intent_challenge.independence_grade")
    validate_task(case.get("task"), "$.task", errors)
    task = case.get("task", {}) if isinstance(case.get("task"), dict) else {}
    if not set(task.get("source_ids", [])).issubset(source_ids):
        add_error(errors, "GC216", "task references unknown sources", "$.task.source_ids")
    if not set(task.get("capability_ids", [])).issubset(capability_ids):
        add_error(errors, "GC217", "task references unknown capabilities", "$.task.capability_ids")
    actions = task.get("requested_actions", [])
    if isinstance(actions, list):
        check_actions_authorized(
            [action for action in actions if isinstance(action, dict)],
            case.get("permissions", {}) if isinstance(case.get("permissions"), dict) else {},
            case.get("project_boundary", {}) if isinstance(case.get("project_boundary"), dict) else {},
            case.get("budget_lock", {}) if isinstance(case.get("budget_lock"), dict) else {},
            "$.task.requested_actions",
            errors,
        )

    exports = case.get("exports")
    export_ids: set[str] = set()
    if not isinstance(exports, list):
        add_error(errors, "GC218", "exports must be an array", "$.exports")
        exports = []
    for index, item in enumerate(exports):
        validate_export_record(item, f"$.exports[{index}]", errors)
        packet_id = item.get("packet_id") if isinstance(item, dict) else None
        if packet_id in export_ids:
            add_error(errors, "GC219", "export packet_id must be unique", f"$.exports[{index}].packet_id")
        if isinstance(packet_id, str):
            export_ids.add(packet_id)
        if isinstance(item, dict) and item.get("run_id") not in run_ids:
            add_error(errors, "GC220", "export references an unknown run", f"$.exports[{index}].run_id")

    stored_documents = (
        ("worker_response", "worker_packet"),
        ("objector_response", "objector_packet"),
        ("alignment_record", "alignment_packet"),
    )
    for key, expected_parent_type in stored_documents:
        stored = case.get(key)
        if stored is None:
            continue
        if not isinstance(stored, dict):
            add_error(errors, "GC220A", f"{key} must be null or a typed packet", f"$.{key}")
            continue
        nested = validate_document(stored)
        for item in nested:
            errors.append(Diagnostic(item.level, item.code, item.message, f"$.{key}{item.path[1:]}"))
        parent = stored.get("parent") if isinstance(stored.get("parent"), dict) else {}
        if find_export(case, parent.get("packet_id"), parent.get("digest"), expected_parent_type) is None:
            add_error(errors, "GC220B", f"{key} is not bound to a recorded {expected_parent_type}", f"$.{key}.parent")
        stored_run = stored.get("role_run") if isinstance(stored.get("role_run"), dict) else {}
        if stored_run.get("run_id") not in run_ids:
            add_error(errors, "GC220C", f"{key} references an unknown role run", f"$.{key}.role_run.run_id")
    if isinstance(case.get("worker_response"), dict):
        worker_check: list[Diagnostic] = []
        check_actions_authorized(
            case["worker_response"].get("attempted_actions", []),
            case.get("permissions", {}),
            case.get("project_boundary", {}),
            case.get("budget_lock", {}),
            "$.worker_response.attempted_actions",
            worker_check,
        )
        errors.extend(worker_check)
    if isinstance(case.get("worker_response"), dict) and isinstance(case.get("objector_response"), dict):
        actual = independence_grade(case["worker_response"].get("role_run", {}), case["objector_response"].get("role_run", {}))
        if case["objector_response"].get("independence_grade") != actual:
            add_error(errors, "GC220D", "stored objector independence grade does not match its role contexts", "$.objector_response.independence_grade")

    proofs = case.get("proofs")
    proof_ids: set[str] = set()
    proof_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(proofs, list):
        add_error(errors, "GC221", "proofs must be an array", "$.proofs")
        proofs = []
    for index, proof in enumerate(proofs):
        validate_proof(proof, f"$.proofs[{index}]", errors)
        proof_id = proof.get("proof_id") if isinstance(proof, dict) else None
        if proof_id in proof_ids:
            add_error(errors, "GC222", "proof_id must be unique", f"$.proofs[{index}].proof_id")
        if isinstance(proof_id, str):
            proof_ids.add(proof_id)
            proof_by_id[proof_id] = proof
        if isinstance(proof, dict) and not set(proof.get("evidence_refs", [])).issubset(evidence_ids):
            add_error(errors, "GC223", "proof references unknown evidence", f"$.proofs[{index}].evidence_refs")
        if isinstance(proof, dict) and proof.get("supersedes") is not None and proof["supersedes"] not in proof_ids:
            add_error(errors, "GC224", "proof supersedes must reference an earlier proof", f"$.proofs[{index}].supersedes")
    invalidated = case.get("invalidated_proof_ids")
    if not unique_strings(invalidated):
        add_error(errors, "GC225", "invalidated_proof_ids must be unique proof IDs", "$.invalidated_proof_ids")
        invalidated = []
    for proof_id in invalidated:
        if proof_id not in proof_by_id or proof_by_id[proof_id].get("status") != "invalidated":
            add_error(errors, "GC226", "invalidated proof ledger disagrees with proof status", "$.invalidated_proof_ids")
    required_proofs = set(task.get("required_proof_ids", []))
    if case.get("worker_response") is not None and not required_proofs.issubset(proof_ids):
        add_error(errors, "GC227", "worker result does not supply every required proof ID", "$.proofs")

    validate_continuity(case.get("continuity"), "$.continuity", errors)
    if case.get("status") not in {
        "draft",
        "ready_for_worker",
        "worker_complete",
        "objection_open",
        "alignment_required",
        "correction_required",
        "verified",
        "blocked",
        "interrupted",
    }:
        add_error(errors, "GC228", "case status is invalid", "$.status")
    runs_by_id = {
        item.get("run_id"): item
        for item in runs
        if isinstance(item, dict) and isinstance(item.get("run_id"), str)
    }
    validate_ledger(case.get("provenance_ledger"), runs_by_id, "$.provenance_ledger", errors)


def validate_worker_packet(document: dict[str, Any], errors: list[Diagnostic]) -> None:
    required = {
        "schema_version", "packet_type", "packet_id", "created_at", "parent", "canonical_digest",
        "start_pack_binding", "intent_lock", "intent_challenge", "project_boundary", "role_run", "permissions",
        "budget_lock", "capabilities", "sources", "evidence", "task", "prior_objections", "continuity",
    }
    if not exact_keys(document, required, set(), "$", errors):
        return
    validate_common(document, "worker_packet", errors)
    validate_parent(document.get("parent"), "$.parent", errors)
    if isinstance(document.get("parent"), dict) and document["parent"].get("packet_type") != "council_case":
        add_error(errors, "GC230", "worker packet parent must be a council case", "$.parent.packet_type")
    validate_start_pack_binding(document.get("start_pack_binding"), "$.start_pack_binding", errors)
    validate_intent_lock(document.get("intent_lock"), "$.intent_lock", errors)
    validate_intent_challenge_binding(document.get("intent_challenge"), document.get("intent_lock"), "$.intent_challenge", errors)
    if document.get("intent_challenge") is None:
        add_error(errors, "GC230A", "worker packet requires a bound intent challenge", "$.intent_challenge")
    validate_project_boundary(document.get("project_boundary"), "$.project_boundary", errors)
    validate_role_run(document.get("role_run"), "$.role_run", errors)
    if isinstance(document.get("role_run"), dict) and document["role_run"].get("role") != "worker":
        add_error(errors, "GC231", "worker packet requires a worker run", "$.role_run.role")
    validate_permissions(document.get("permissions"), "$.permissions", errors)
    if isinstance(document.get("intent_lock"), dict) and isinstance(document.get("permissions"), dict):
        if document["intent_lock"].get("permission_policy_id") != document["permissions"].get("policy_id"):
            add_error(errors, "GC231A", "worker packet policy ID disagrees with Intent Lock", "$.permissions.policy_id")
        if document["intent_lock"].get("permission_policy_digest") != document["permissions"].get("policy_digest"):
            add_error(errors, "GC231B", "worker packet policy digest disagrees with Intent Lock", "$.permissions.policy_digest")
    validate_budget(document.get("budget_lock"), "$.budget_lock", errors)
    for index, item in enumerate(document.get("capabilities", []) if isinstance(document.get("capabilities"), list) else []):
        validate_capability(item, f"$.capabilities[{index}]", errors)
    for index, item in enumerate(document.get("sources", []) if isinstance(document.get("sources"), list) else []):
        validate_source(item, f"$.sources[{index}]", errors)
    for index, item in enumerate(document.get("evidence", []) if isinstance(document.get("evidence"), list) else []):
        validate_evidence(item, f"$.evidence[{index}]", errors)
    validate_task(document.get("task"), "$.task", errors)
    if not isinstance(document.get("prior_objections"), list):
        add_error(errors, "GC232", "prior_objections must be an array", "$.prior_objections")
    validate_continuity(document.get("continuity"), "$.continuity", errors)
    if isinstance(document.get("role_run"), dict):
        allowed = set(document["role_run"].get("allowed_data_classes", []))
        for index, source in enumerate(document.get("sources", [])):
            if isinstance(source, dict) and not set(source.get("data_classes", [])).issubset(allowed):
                add_error(errors, "GC233", "worker packet exceeds the run data boundary", f"$.sources[{index}].data_classes")


def validate_worker_response(document: dict[str, Any], errors: list[Diagnostic]) -> None:
    required = {
        "schema_version", "packet_type", "packet_id", "created_at", "parent", "canonical_digest",
        "role_run", "attempted_actions", "summary", "artifact_refs", "assumptions", "unknowns", "proofs",
    }
    if not exact_keys(document, required, set(), "$", errors):
        return
    validate_common(document, "worker_response", errors)
    validate_parent(document.get("parent"), "$.parent", errors)
    if isinstance(document.get("parent"), dict) and document["parent"].get("packet_type") != "worker_packet":
        add_error(errors, "GC234", "worker response parent must be a worker packet", "$.parent.packet_type")
    validate_role_run(document.get("role_run"), "$.role_run", errors)
    if isinstance(document.get("role_run"), dict) and document["role_run"].get("role") != "worker":
        add_error(errors, "GC235", "worker response requires a worker run", "$.role_run.role")
    actions = document.get("attempted_actions")
    if not isinstance(actions, list):
        add_error(errors, "GC236", "attempted_actions must be an array", "$.attempted_actions")
    else:
        for index, action in enumerate(actions):
            validate_action(action, f"$.attempted_actions[{index}]", errors)
    if not meaningful(document.get("summary"), 3):
        add_error(errors, "GC237", "worker summary is required", "$.summary")
    for key in ("artifact_refs", "assumptions", "unknowns"):
        if not unique_strings(document.get(key)):
            add_error(errors, "GC238", f"{key} must be unique strings", f"$.{key}")
    proofs = document.get("proofs")
    if not isinstance(proofs, list) or not proofs:
        add_error(errors, "GC239", "worker response needs proof", "$.proofs")
    else:
        for index, proof in enumerate(proofs):
            validate_proof(proof, f"$.proofs[{index}]", errors)


def validate_finding(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "finding_id",
        "target_kind",
        "target_ref",
        "category",
        "statement",
        "evidence_refs",
        "counterexample_or_failed_test",
        "recommended_correction",
        "severity",
        "material",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    if not valid_id(value.get("finding_id")):
        add_error(errors, "GC240", "finding_id is invalid", f"{path}.finding_id")
    if value.get("target_kind") not in {"claim", "artifact", "permission", "scope", "capability", "proof", "continuity"}:
        add_error(errors, "GC241", "finding target_kind is invalid", f"{path}.target_kind")
    if not meaningful(value.get("target_ref"), 3) or not meaningful(value.get("statement"), 12):
        add_error(errors, "GC242", "finding must identify a specific target and objection", path)
    if not meaningful(value.get("counterexample_or_failed_test"), 12):
        add_error(errors, "GC242A", "finding needs a reproducible counterexample or failed test", f"{path}.counterexample_or_failed_test")
    if not meaningful(value.get("recommended_correction"), 8):
        add_error(errors, "GC242B", "finding needs a bounded recommended correction", f"{path}.recommended_correction")
    if value.get("category") not in OBJECTOR_CATEGORIES:
        add_error(errors, "GC243", "finding category is invalid", f"{path}.category")
    if not unique_strings(value.get("evidence_refs"), allow_empty=False):
        add_error(errors, "GC244", "finding requires specific evidence refs", f"{path}.evidence_refs")
    if value.get("severity") not in SEVERITIES:
        add_error(errors, "GC245", "finding severity is invalid", f"{path}.severity")
    if type(value.get("material")) is not bool:
        add_error(errors, "GC246", "finding material must be boolean", f"{path}.material")
    elif value.get("severity") in {"material", "blocking"} and value.get("material") is not True:
        add_error(errors, "GC247", "material or blocking severity must be marked material", path)


def validate_objector_packet(document: dict[str, Any], errors: list[Diagnostic]) -> None:
    required = {
        "schema_version", "packet_type", "packet_id", "created_at", "parent", "canonical_digest",
        "start_pack_binding", "intent_lock", "intent_challenge", "project_boundary", "role_run", "independence_grade",
        "permitted_actions", "sources", "evidence", "task", "worker_response_digest", "worker_summary", "proofs",
    }
    if not exact_keys(document, required, set(), "$", errors):
        return
    validate_common(document, "objector_packet", errors)
    validate_parent(document.get("parent"), "$.parent", errors)
    if isinstance(document.get("parent"), dict) and document["parent"].get("packet_type") != "council_case":
        add_error(errors, "GC248", "objector packet parent must be a council case", "$.parent.packet_type")
    validate_start_pack_binding(document.get("start_pack_binding"), "$.start_pack_binding", errors)
    validate_intent_lock(document.get("intent_lock"), "$.intent_lock", errors)
    validate_intent_challenge_binding(document.get("intent_challenge"), document.get("intent_lock"), "$.intent_challenge", errors)
    validate_project_boundary(document.get("project_boundary"), "$.project_boundary", errors)
    validate_role_run(document.get("role_run"), "$.role_run", errors)
    if isinstance(document.get("role_run"), dict) and document["role_run"].get("role") != "objector":
        add_error(errors, "GC249", "objector packet requires an objector run", "$.role_run.role")
    if document.get("independence_grade") not in INDEPENDENCE_GRADES - {"not_applicable"}:
        add_error(errors, "GC250", "objector independence grade is invalid", "$.independence_grade")
    if document.get("permitted_actions") != []:
        add_error(errors, "GC251", "objector is read-only and cannot receive tool actions", "$.permitted_actions")
    for index, source in enumerate(document.get("sources", []) if isinstance(document.get("sources"), list) else []):
        validate_source(source, f"$.sources[{index}]", errors)
    for index, item in enumerate(document.get("evidence", []) if isinstance(document.get("evidence"), list) else []):
        validate_evidence(item, f"$.evidence[{index}]", errors)
    validate_task(document.get("task"), "$.task", errors)
    if isinstance(document.get("task"), dict) and document["task"].get("requested_actions") != []:
        add_error(errors, "GC251A", "objector packet task actions must be minimized to an empty review-only list", "$.task.requested_actions")
    if not isinstance(document.get("worker_response_digest"), str) or not HEX64.fullmatch(document["worker_response_digest"]):
        add_error(errors, "GC252", "worker_response_digest must be SHA-256", "$.worker_response_digest")
    if not meaningful(document.get("worker_summary"), 3):
        add_error(errors, "GC253", "worker summary is required", "$.worker_summary")
    proofs = document.get("proofs")
    if not isinstance(proofs, list) or not proofs:
        add_error(errors, "GC254", "objector packet needs worker proof", "$.proofs")
    else:
        for index, proof in enumerate(proofs):
            validate_proof(proof, f"$.proofs[{index}]", errors)


def validate_objector_response(document: dict[str, Any], errors: list[Diagnostic]) -> None:
    required = {
        "schema_version", "packet_type", "packet_id", "created_at", "parent", "canonical_digest",
        "role_run", "independence_grade", "attempted_actions", "findings",
    }
    if not exact_keys(document, required, set(), "$", errors):
        return
    validate_common(document, "objector_response", errors)
    validate_parent(document.get("parent"), "$.parent", errors)
    if isinstance(document.get("parent"), dict) and document["parent"].get("packet_type") != "objector_packet":
        add_error(errors, "GC255", "objector response parent must be an objector packet", "$.parent.packet_type")
    validate_role_run(document.get("role_run"), "$.role_run", errors)
    if isinstance(document.get("role_run"), dict) and document["role_run"].get("role") != "objector":
        add_error(errors, "GC256", "objector response requires an objector run", "$.role_run.role")
    if document.get("independence_grade") not in INDEPENDENCE_GRADES - {"not_applicable"}:
        add_error(errors, "GC257", "objector independence grade is invalid", "$.independence_grade")
    if document.get("attempted_actions") != []:
        add_error(errors, "GC258", "objector response must record no tool or mutation actions", "$.attempted_actions")
    findings = document.get("findings")
    if not isinstance(findings, list):
        add_error(errors, "GC259", "findings must be an array", "$.findings")
        return
    seen: set[str] = set()
    for index, finding in enumerate(findings):
        validate_finding(finding, f"$.findings[{index}]", errors)
        finding_id = finding.get("finding_id") if isinstance(finding, dict) else None
        if finding_id in seen:
            add_error(errors, "GC260", "finding_id must be unique", f"$.findings[{index}].finding_id")
        if isinstance(finding_id, str):
            seen.add(finding_id)


def validate_alignment_packet(document: dict[str, Any], errors: list[Diagnostic]) -> None:
    required = {
        "schema_version", "packet_type", "packet_id", "created_at", "parent", "canonical_digest",
        "start_pack_binding", "intent_lock", "intent_challenge", "project_boundary", "role_run", "sources", "evidence",
        "task", "worker_response_digest", "proofs", "objector_response_digest", "findings",
    }
    if not exact_keys(document, required, set(), "$", errors):
        return
    validate_common(document, "alignment_packet", errors)
    validate_parent(document.get("parent"), "$.parent", errors)
    if isinstance(document.get("parent"), dict) and document["parent"].get("packet_type") != "council_case":
        add_error(errors, "GC261", "alignment packet parent must be a council case", "$.parent.packet_type")
    validate_start_pack_binding(document.get("start_pack_binding"), "$.start_pack_binding", errors)
    validate_intent_lock(document.get("intent_lock"), "$.intent_lock", errors)
    validate_intent_challenge_binding(document.get("intent_challenge"), document.get("intent_lock"), "$.intent_challenge", errors)
    validate_project_boundary(document.get("project_boundary"), "$.project_boundary", errors)
    validate_role_run(document.get("role_run"), "$.role_run", errors)
    if isinstance(document.get("role_run"), dict) and document["role_run"].get("role") != "aligner":
        add_error(errors, "GC262", "alignment packet requires an aligner run", "$.role_run.role")
    for key in ("worker_response_digest", "objector_response_digest"):
        if not isinstance(document.get(key), str) or not HEX64.fullmatch(document[key]):
            add_error(errors, "GC263", f"{key} must be SHA-256", f"$.{key}")
    validate_task(document.get("task"), "$.task", errors)
    for index, proof in enumerate(document.get("proofs", []) if isinstance(document.get("proofs"), list) else []):
        validate_proof(proof, f"$.proofs[{index}]", errors)
    for index, finding in enumerate(document.get("findings", []) if isinstance(document.get("findings"), list) else []):
        validate_finding(finding, f"$.findings[{index}]", errors)


def validate_disposition(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {"finding_id", "resolution", "evidence_refs", "rationale", "correction_id", "closed"}
    if not exact_keys(value, required, set(), path, errors):
        return
    if not valid_id(value.get("finding_id")):
        add_error(errors, "GC270", "disposition finding_id is invalid", f"{path}.finding_id")
    if value.get("resolution") not in {"sustained", "rejected", "unresolved", "superseded"}:
        add_error(errors, "GC271", "disposition resolution is invalid", f"{path}.resolution")
    if not unique_strings(value.get("evidence_refs"), allow_empty=False):
        add_error(errors, "GC272", "disposition requires evidence refs", f"{path}.evidence_refs")
    if not meaningful(value.get("rationale"), 8):
        add_error(errors, "GC273", "disposition needs a concise evidence-based rationale", f"{path}.rationale")
    if type(value.get("closed")) is not bool:
        add_error(errors, "GC274", "closed must be boolean", f"{path}.closed")
    if value.get("correction_id") is not None and not valid_id(value.get("correction_id")):
        add_error(errors, "GC275", "correction_id must be null or a valid correction ID", f"{path}.correction_id")
    if value.get("resolution") == "unresolved" and value.get("closed") is not False:
        add_error(errors, "GC274A", "unresolved findings must remain open", f"{path}.closed")
    if value.get("resolution") in {"rejected", "superseded", "unresolved"} and value.get("correction_id") is not None:
        add_error(errors, "GC276", "only sustained findings may reference a correction", f"{path}.correction_id")


def validate_correction(value: Any, path: str, errors: list[Diagnostic]) -> None:
    required = {
        "correction_id", "finding_ids", "material", "status", "invalidated_proof_ids", "revalidated_proofs",
    }
    if not exact_keys(value, required, set(), path, errors):
        return
    if not valid_id(value.get("correction_id")) or not unique_strings(value.get("finding_ids"), allow_empty=False):
        add_error(errors, "GC277", "correction identity and finding_ids are required", path)
    if type(value.get("material")) is not bool:
        add_error(errors, "GC278", "correction material must be boolean", f"{path}.material")
    if value.get("status") not in {"pending", "revalidated", "not_required"}:
        add_error(errors, "GC279", "correction status is invalid", f"{path}.status")
    if not unique_strings(value.get("invalidated_proof_ids")):
        add_error(errors, "GC280", "invalidated_proof_ids must be unique", f"{path}.invalidated_proof_ids")
    proofs = value.get("revalidated_proofs")
    if not isinstance(proofs, list):
        add_error(errors, "GC281", "revalidated_proofs must be an array", f"{path}.revalidated_proofs")
        proofs = []
    for index, proof in enumerate(proofs):
        validate_proof(proof, f"{path}.revalidated_proofs[{index}]", errors)
    if value.get("material") is True:
        if value.get("status") != "revalidated" or not value.get("invalidated_proof_ids") or not proofs:
            add_error(errors, "GC282", "material correction must invalidate old proof and provide revalidated proof", path)
    elif value.get("status") == "revalidated" and not proofs:
        add_error(errors, "GC283", "revalidated correction needs replacement proof", path)


def validate_alignment_record(document: dict[str, Any], errors: list[Diagnostic]) -> None:
    required = {
        "schema_version", "packet_type", "packet_id", "created_at", "parent", "canonical_digest",
        "role_run", "objector_response_digest", "dispositions", "corrections", "alignment_verdict",
        "workflow_gate", "open_finding_ids",
    }
    if not exact_keys(document, required, set(), "$", errors):
        return
    validate_common(document, "alignment_record", errors)
    validate_parent(document.get("parent"), "$.parent", errors)
    if isinstance(document.get("parent"), dict) and document["parent"].get("packet_type") != "alignment_packet":
        add_error(errors, "GC284", "alignment record parent must be an alignment packet", "$.parent.packet_type")
    validate_role_run(document.get("role_run"), "$.role_run", errors)
    if isinstance(document.get("role_run"), dict) and document["role_run"].get("role") != "aligner":
        add_error(errors, "GC285", "alignment record requires an aligner run", "$.role_run.role")
    if not isinstance(document.get("objector_response_digest"), str) or not HEX64.fullmatch(document["objector_response_digest"]):
        add_error(errors, "GC286", "objector_response_digest must be SHA-256", "$.objector_response_digest")
    dispositions = document.get("dispositions")
    if not isinstance(dispositions, list):
        add_error(errors, "GC287", "dispositions must be an array", "$.dispositions")
        dispositions = []
    seen: set[str] = set()
    for index, item in enumerate(dispositions):
        validate_disposition(item, f"$.dispositions[{index}]", errors)
        finding_id = item.get("finding_id") if isinstance(item, dict) else None
        if finding_id in seen:
            add_error(errors, "GC288", "every finding may be disposed only once", f"$.dispositions[{index}].finding_id")
        if isinstance(finding_id, str):
            seen.add(finding_id)
    corrections = document.get("corrections")
    if not isinstance(corrections, list):
        add_error(errors, "GC289", "corrections must be an array", "$.corrections")
    else:
        for index, correction in enumerate(corrections):
            validate_correction(correction, f"$.corrections[{index}]", errors)
    if document.get("alignment_verdict") not in {
        "aligned", "provisionally_aligned", "partially_aligned", "not_aligned", "unverifiable",
    }:
        add_error(errors, "GC290", "alignment_verdict is invalid", "$.alignment_verdict")
    if document.get("workflow_gate") not in {"pass", "return_to_worker", "human_decision_required", "blocked"}:
        add_error(errors, "GC290A", "workflow_gate is invalid", "$.workflow_gate")
    if not unique_strings(document.get("open_finding_ids")):
        add_error(errors, "GC291", "open_finding_ids must be unique", "$.open_finding_ids")
    if document.get("workflow_gate") == "pass" and document.get("open_finding_ids"):
        add_error(errors, "GC292", "a pass verdict cannot contain open findings", "$.open_finding_ids")
    if document.get("workflow_gate") == "pass" and document.get("alignment_verdict") != "aligned":
        add_error(errors, "GC292A", "workflow pass requires an aligned verdict", "$.workflow_gate")


def validate_resume_packet(document: dict[str, Any], errors: list[Diagnostic]) -> None:
    required = {
        "schema_version", "packet_type", "packet_id", "created_at", "parent", "canonical_digest",
        "start_pack_binding", "intent_lock", "intent_challenge", "project_boundary", "case_status", "role_runs", "task",
        "worker_response", "objector_response", "alignment_record", "proofs", "invalidated_proof_ids",
        "continuity", "next_required_role", "provenance_head",
    }
    if not exact_keys(document, required, set(), "$", errors):
        return
    validate_common(document, "resume_packet", errors)
    validate_parent(document.get("parent"), "$.parent", errors)
    if isinstance(document.get("parent"), dict) and document["parent"].get("packet_type") != "council_case":
        add_error(errors, "GC293", "resume parent must be a council case", "$.parent.packet_type")
    validate_start_pack_binding(document.get("start_pack_binding"), "$.start_pack_binding", errors)
    validate_intent_lock(document.get("intent_lock"), "$.intent_lock", errors)
    validate_intent_challenge_binding(document.get("intent_challenge"), document.get("intent_lock"), "$.intent_challenge", errors)
    validate_project_boundary(document.get("project_boundary"), "$.project_boundary", errors)
    runs = document.get("role_runs")
    if not isinstance(runs, list) or not runs:
        add_error(errors, "GC294", "resume packet needs role run history", "$.role_runs")
    else:
        for index, run in enumerate(runs):
            validate_role_run(run, f"$.role_runs[{index}]", errors)
    validate_task(document.get("task"), "$.task", errors)
    for index, proof in enumerate(document.get("proofs", []) if isinstance(document.get("proofs"), list) else []):
        validate_proof(proof, f"$.proofs[{index}]", errors)
    if not unique_strings(document.get("invalidated_proof_ids")):
        add_error(errors, "GC295", "invalidated proof IDs must be unique", "$.invalidated_proof_ids")
    validate_continuity(document.get("continuity"), "$.continuity", errors, require_resume=True)
    if document.get("next_required_role") not in ROLES | {"human_authority", "none"}:
        add_error(errors, "GC296", "next_required_role is invalid", "$.next_required_role")
    if not isinstance(document.get("provenance_head"), str) or not HEX64.fullmatch(document["provenance_head"]):
        add_error(errors, "GC297", "provenance_head must be SHA-256", "$.provenance_head")


def validate_document(document: dict[str, Any], start_pack_root: Path | None = None) -> list[Diagnostic]:
    errors: list[Diagnostic] = []
    scan_prohibited(document, "$", errors)
    packet_type = document.get("packet_type")
    validators = {
        "council_case": validate_case,
        "worker_packet": validate_worker_packet,
        "worker_response": validate_worker_response,
        "objector_packet": validate_objector_packet,
        "objector_response": validate_objector_response,
        "alignment_packet": validate_alignment_packet,
        "alignment_record": validate_alignment_record,
        "resume_packet": validate_resume_packet,
    }
    validator = validators.get(packet_type)
    if validator is None:
        add_error(errors, "GC298", f"unknown packet_type: {packet_type!r}", "$.packet_type")
        return errors
    validator(document, errors)
    if start_pack_root is not None:
        verify_start_pack_binding(document.get("start_pack_binding"), start_pack_root, errors)
    return errors


def diagnostics_json(errors: list[Diagnostic]) -> list[dict[str, Any]]:
    return [asdict(item) for item in errors]


def emit_diagnostics(errors: list[Diagnostic], json_output: bool) -> int:
    if json_output:
        print(json.dumps({"valid": not errors, "errors": diagnostics_json(errors)}, indent=2, sort_keys=True))
    elif errors:
        for item in errors:
            print(f"[{item.code}] {item.message} ({item.path})")
    else:
        print("Guided Council validation passed.")
    return 1 if errors else 0


def load_start_pack_binding(root: Path) -> dict[str, Any]:
    lock = read_json(root / ".selective-intelligence" / "lock.json")
    binding = {
        "project_id": lock.get("project", {}).get("id"),
        "release_id": lock.get("release", {}).get("id"),
        "validator_version": lock.get("validator_version"),
        "control_digest": lock.get("control_digest"),
        "semantic_digest": lock.get("semantic_digest"),
        "bound_at": utc_now(),
    }
    errors: list[Diagnostic] = []
    validate_start_pack_binding(binding, "$.start_pack_binding", errors)
    if errors:
        raise ValueError("Start Pack is not sealed and bindable: " + errors[0].message)
    return binding


def finish_case_update(case: dict[str, Any]) -> None:
    case["revision"] += 1
    case["updated_at"] = utc_now()
    case["continuity"]["checkpointed_at"] = case["updated_at"]
    stamp_document(case)


def make_run(
    role: str,
    run_id: str,
    provider: str,
    model: str,
    surface: str,
    context_id: str,
    billing_pool_id: str,
    data_classes: list[str],
    parent_run_id: str | None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "role": role,
        "provider": provider,
        "model": model,
        "surface": surface,
        "context_id": context_id,
        "billing_pool_id": billing_pool_id,
        "allowed_data_classes": sorted(set(data_classes)),
        "started_at": utc_now(),
        "completed_at": None,
        "parent_run_id": parent_run_id,
    }


def add_run(case: dict[str, Any], run: dict[str, Any]) -> None:
    if any(item.get("run_id") == run["run_id"] for item in case["role_runs"]):
        raise ValueError(f"run_id already exists: {run['run_id']}")
    if any(item.get("context_id") == run["context_id"] for item in case["role_runs"]):
        raise ValueError("every role pass requires a distinct context_id")
    if run.get("parent_run_id") and not any(item.get("run_id") == run["parent_run_id"] for item in case["role_runs"]):
        raise ValueError("parent_run_id is not registered")
    case["role_runs"].append(run)


def update_run_completion(case: dict[str, Any], completed_run: dict[str, Any]) -> None:
    current = next((item for item in case["role_runs"] if item.get("run_id") == completed_run.get("run_id")), None)
    if current is None:
        raise ValueError("response role run is not registered")
    identity_keys = {
        "run_id", "role", "provider", "model", "surface", "context_id", "billing_pool_id",
        "allowed_data_classes", "started_at", "parent_run_id",
    }
    if any(current.get(key) != completed_run.get(key) for key in identity_keys):
        raise ValueError("response role run does not match the exported run")
    if not valid_timestamp(completed_run.get("completed_at")):
        raise ValueError("response must record a completed_at timestamp")
    current["completed_at"] = completed_run["completed_at"]


def find_export(case: dict[str, Any], packet_id: str, digest: str, packet_type: str) -> dict[str, Any] | None:
    return next(
        (
            item for item in case["exports"]
            if item.get("packet_id") == packet_id
            and item.get("digest") == digest
            and item.get("packet_type") == packet_type
        ),
        None,
    )


def record_export(case: dict[str, Any], packet: dict[str, Any], run_id: str, parent_case_digest: str) -> None:
    case["exports"].append(
        {
            "packet_id": packet["packet_id"],
            "packet_type": packet["packet_type"],
            "digest": packet["canonical_digest"],
            "parent_case_digest": parent_case_digest,
            "run_id": run_id,
            "created_at": packet["created_at"],
        }
    )
    append_ledger(
        case,
        run_id,
        "packet_exported",
        packet["packet_id"],
        packet["canonical_digest"],
        subject_revision=f"case-revision-{case['revision']}",
        validation_status="passed",
    )


def selected_case_material(case: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    task = case["task"]
    sources = [copy.deepcopy(item) for item in case["sources"] if item["source_id"] in task["source_ids"]]
    source_ids = {item["source_id"] for item in sources}
    evidence = [copy.deepcopy(item) for item in case["evidence"] if item["source_id"] in source_ids]
    capabilities = [copy.deepcopy(item) for item in case["capabilities"] if item["capability_id"] in task["capability_ids"]]
    return sources, evidence, capabilities


def filtered_permissions(case: dict[str, Any]) -> dict[str, Any]:
    approvals = {item["approval_id"] for item in case["task"]["requested_actions"]}
    return {
        "policy_id": case["permissions"]["policy_id"],
        "policy_digest": case["permissions"]["policy_digest"],
        "default": "deny",
        "rules": copy.deepcopy(case["permissions"]["rules"]),
        "approval_receipts": [
            copy.deepcopy(item) for item in case["permissions"]["approval_receipts"]
            if item["approval_id"] in approvals
        ],
    }


def packet_parent(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_id": case["packet_id"],
        "packet_type": "council_case",
        "digest": case["canonical_digest"],
    }


def required_grade_met(actual: str, required: str) -> bool:
    rank = {
        "not_applicable": 0,
        "separate_context_same_model": 1,
        "independent_model": 2,
        "independent_human": 3,
    }
    return rank[actual] >= rank[required]


def import_worker_response(case: dict[str, Any], response: dict[str, Any]) -> None:
    errors = validate_document(response)
    if errors:
        raise ValueError(f"invalid worker response: [{errors[0].code}] {errors[0].message}")
    parent = response["parent"]
    export = find_export(case, parent["packet_id"], parent["digest"], "worker_packet")
    if export is None:
        raise ValueError("worker response is not bound to a recorded worker packet")
    if response["role_run"]["run_id"] != export["run_id"]:
        raise ValueError("worker response run does not match its packet")
    update_run_completion(case, response["role_run"])
    check_errors: list[Diagnostic] = []
    check_actions_authorized(
        response["attempted_actions"], case["permissions"], case["project_boundary"], case["budget_lock"],
        "$.attempted_actions", check_errors,
    )
    requested_ids = {item["action_id"] for item in case["task"]["requested_actions"]}
    attempted_ids = {item["action_id"] for item in response["attempted_actions"]}
    if not attempted_ids.issubset(requested_ids):
        raise ValueError("worker attempted an action absent from the task packet")
    if check_errors:
        raise ValueError(f"unauthorized worker action: [{check_errors[0].code}] {check_errors[0].message}")
    evidence_ids = {item["evidence_id"] for item in case["evidence"]}
    proof_ids: set[str] = set()
    for proof in response["proofs"]:
        if proof["proof_id"] in proof_ids:
            raise ValueError("worker proof IDs must be unique")
        proof_ids.add(proof["proof_id"])
        if not set(proof["evidence_refs"]).issubset(evidence_ids):
            raise ValueError("worker proof references unknown evidence")
    if not set(case["task"]["required_proof_ids"]).issubset(proof_ids):
        raise ValueError("worker response omits required proof")
    case["worker_response"] = copy.deepcopy(response)
    case["proofs"] = copy.deepcopy(response["proofs"])
    case["status"] = "worker_complete"
    case["continuity"]["current_state_summary"] = "Worker result imported with bound proof; independent objection is next."
    case["continuity"]["completed_steps"].append("worker_response_imported")
    case["continuity"]["completed_steps"] = sorted(set(case["continuity"]["completed_steps"]))
    case["continuity"]["next_safe_action"] = "Export an objector packet into a distinct review context."
    append_ledger(
        case,
        response["role_run"]["run_id"],
        "worker_response_imported",
        response["packet_id"],
        response["canonical_digest"],
        material=bool(response["artifact_refs"] or response["proofs"]),
        subject_revision=",".join(sorted(proof["revision"] for proof in response["proofs"])),
        validation_status="passed",
        approval_status="approved" if response["attempted_actions"] else "not_required",
    )


def make_worker_packet(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    sources, evidence, capabilities = selected_case_material(case)
    prior = case["objector_response"]["findings"] if case.get("objector_response") else []
    packet = {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "worker_packet",
        "packet_id": new_id("worker-packet"),
        "created_at": utc_now(),
        "parent": packet_parent(case),
        "canonical_digest": "",
        "start_pack_binding": copy.deepcopy(case["start_pack_binding"]),
        "intent_lock": copy.deepcopy(case["intent_lock"]),
        "intent_challenge": copy.deepcopy(case["intent_challenge"]),
        "project_boundary": copy.deepcopy(case["project_boundary"]),
        "role_run": copy.deepcopy(run),
        "permissions": filtered_permissions(case),
        "budget_lock": copy.deepcopy(case["budget_lock"]),
        "capabilities": capabilities,
        "sources": sources,
        "evidence": evidence,
        "task": copy.deepcopy(case["task"]),
        "prior_objections": copy.deepcopy(prior),
        "continuity": copy.deepcopy(case["continuity"]),
    }
    return stamp_document(packet)


def make_objector_packet(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    worker_run = case["worker_response"]["role_run"]
    grade = independence_grade(worker_run, run)
    if grade == "not_applicable":
        raise ValueError("objector must run in a distinct context")
    if not required_grade_met(grade, case["required_independence"]):
        raise ValueError(f"objector independence {grade} is below required {case['required_independence']}")
    sources, evidence, _ = selected_case_material(case)
    allowed = set(run["allowed_data_classes"])
    if any(not set(item["data_classes"]).issubset(allowed) for item in sources):
        raise ValueError("objector route is not allowed to receive all selected source data classes")
    review_task = copy.deepcopy(case["task"])
    review_task["requested_actions"] = []
    packet = {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "objector_packet",
        "packet_id": new_id("objector-packet"),
        "created_at": utc_now(),
        "parent": packet_parent(case),
        "canonical_digest": "",
        "start_pack_binding": copy.deepcopy(case["start_pack_binding"]),
        "intent_lock": copy.deepcopy(case["intent_lock"]),
        "intent_challenge": copy.deepcopy(case["intent_challenge"]),
        "project_boundary": copy.deepcopy(case["project_boundary"]),
        "role_run": copy.deepcopy(run),
        "independence_grade": grade,
        "permitted_actions": [],
        "sources": sources,
        "evidence": evidence,
        "task": review_task,
        "worker_response_digest": case["worker_response"]["canonical_digest"],
        "worker_summary": case["worker_response"]["summary"],
        "proofs": copy.deepcopy(case["proofs"]),
    }
    return stamp_document(packet)


def make_alignment_packet(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    sources, evidence, _ = selected_case_material(case)
    packet = {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "alignment_packet",
        "packet_id": new_id("alignment-packet"),
        "created_at": utc_now(),
        "parent": packet_parent(case),
        "canonical_digest": "",
        "start_pack_binding": copy.deepcopy(case["start_pack_binding"]),
        "intent_lock": copy.deepcopy(case["intent_lock"]),
        "intent_challenge": copy.deepcopy(case["intent_challenge"]),
        "project_boundary": copy.deepcopy(case["project_boundary"]),
        "role_run": copy.deepcopy(run),
        "sources": sources,
        "evidence": evidence,
        "task": copy.deepcopy(case["task"]),
        "worker_response_digest": case["worker_response"]["canonical_digest"],
        "proofs": copy.deepcopy(case["proofs"]),
        "objector_response_digest": case["objector_response"]["canonical_digest"],
        "findings": copy.deepcopy(case["objector_response"]["findings"]),
    }
    return stamp_document(packet)


def import_objector_response(case: dict[str, Any], response: dict[str, Any]) -> None:
    errors = validate_document(response)
    if errors:
        raise ValueError(f"invalid objector response: [{errors[0].code}] {errors[0].message}")
    parent = response["parent"]
    export = find_export(case, parent["packet_id"], parent["digest"], "objector_packet")
    if export is None:
        raise ValueError("objector response is not bound to a recorded objector packet")
    if response["role_run"]["run_id"] != export["run_id"]:
        raise ValueError("objector response run does not match its packet")
    update_run_completion(case, response["role_run"])
    worker_run = case["worker_response"]["role_run"]
    actual_grade = independence_grade(worker_run, response["role_run"])
    if response["independence_grade"] != actual_grade:
        raise ValueError(
            f"objector independence overclaim: declared {response['independence_grade']}, actual {actual_grade}"
        )
    if not required_grade_met(actual_grade, case["required_independence"]):
        raise ValueError("objector response does not meet the locked independence grade")
    allowed_refs = (
        {item["evidence_id"] for item in case["evidence"]}
        | {item["proof_id"] for item in case["proofs"]}
        | set(case["worker_response"]["artifact_refs"])
    )
    for finding in response["findings"]:
        if not set(finding["evidence_refs"]).issubset(allowed_refs):
            raise ValueError(f"finding {finding['finding_id']} references evidence absent from the packet")
    case["objector_response"] = copy.deepcopy(response)
    case["status"] = "alignment_required" if response["findings"] else "alignment_required"
    case["continuity"]["current_state_summary"] = "Independent objection imported; every finding requires an evidence-based disposition."
    case["continuity"]["completed_steps"].append("objector_response_imported")
    case["continuity"]["completed_steps"] = sorted(set(case["continuity"]["completed_steps"]))
    case["continuity"]["next_safe_action"] = "Export an alignment packet and dispose every finding exactly once."
    append_ledger(
        case,
        response["role_run"]["run_id"],
        "objector_response_imported",
        response["packet_id"],
        response["canonical_digest"],
        material=any(finding["material"] for finding in response["findings"]),
        subject_revision=f"case-revision-{case['revision']}",
        validation_status="passed",
    )


def cross_validate_alignment(case: dict[str, Any], alignment: dict[str, Any]) -> list[Diagnostic]:
    errors = validate_document(alignment)
    if errors:
        return errors
    parent = alignment["parent"]
    export = find_export(case, parent["packet_id"], parent["digest"], "alignment_packet")
    if export is None:
        add_error(errors, "GC300", "alignment is not bound to a recorded alignment packet", "$.parent")
        return errors
    if alignment["role_run"]["run_id"] != export["run_id"]:
        add_error(errors, "GC301", "alignment run does not match its packet", "$.role_run.run_id")
    objector_run = case["objector_response"]["role_run"]
    if (
        alignment["role_run"]["run_id"] == objector_run.get("run_id")
        or alignment["role_run"]["context_id"] == objector_run.get("context_id")
        or alignment["role_run"].get("role") == "objector"
    ):
        add_error(errors, "GC301A", "the Objector cannot also serve as the Aligner run", "$.role_run")
    if alignment["objector_response_digest"] != case["objector_response"]["canonical_digest"]:
        add_error(errors, "GC302", "alignment binds the wrong objector response", "$.objector_response_digest")
    findings = {item["finding_id"]: item for item in case["objector_response"]["findings"]}
    dispositions = {item["finding_id"]: item for item in alignment["dispositions"]}
    if set(dispositions) != set(findings):
        missing = sorted(set(findings) - set(dispositions))
        extra = sorted(set(dispositions) - set(findings))
        add_error(errors, "GC303", f"every finding must be disposed exactly once; missing={missing}, extra={extra}", "$.dispositions")
    open_ids = {item["finding_id"] for item in alignment["dispositions"] if not item["closed"]}
    if set(alignment["open_finding_ids"]) != open_ids:
        add_error(errors, "GC304", "open_finding_ids must exactly match non-closed dispositions", "$.open_finding_ids")
    corrections = {item["correction_id"]: item for item in alignment["corrections"]}
    evidence_ids = {item["evidence_id"] for item in case["evidence"]}
    proof_ids = {item["proof_id"] for item in case["proofs"]}
    allowed_refs = evidence_ids | proof_ids | set(case["worker_response"]["artifact_refs"])
    referenced_corrections: set[str] = set()
    for finding_id, disposition in dispositions.items():
        if not set(disposition["evidence_refs"]).issubset(allowed_refs):
            add_error(errors, "GC305", "disposition references unknown evidence", f"$.dispositions[{finding_id}].evidence_refs")
        correction_id = disposition["correction_id"]
        finding = findings.get(finding_id, {})
        if disposition["resolution"] == "sustained" and finding.get("material") and correction_id is None:
            add_error(errors, "GC305A", "sustained material finding requires a correction", f"$.dispositions[{finding_id}].correction_id")
        if correction_id is not None:
            referenced_corrections.add(correction_id)
            if correction_id not in corrections:
                add_error(errors, "GC306", "disposition references an unknown correction", f"$.dispositions[{finding_id}].correction_id")
    if set(corrections) != referenced_corrections:
        add_error(errors, "GC307", "every correction must be referenced by a sustained finding", "$.corrections")
    current_proofs = {item["proof_id"]: item for item in case["proofs"]}
    new_proof_ids: set[str] = set()
    for correction_id, correction in corrections.items():
        if not set(correction["finding_ids"]).issubset(findings):
            add_error(errors, "GC308", "correction references an unknown finding", f"$.corrections[{correction_id}].finding_ids")
        expected_finding_ids = {
            finding_id
            for finding_id, disposition in dispositions.items()
            if disposition.get("resolution") == "sustained" and disposition.get("correction_id") == correction_id
        }
        if set(correction["finding_ids"]) != expected_finding_ids:
            add_error(
                errors,
                "GC308A",
                "correction finding_ids must exactly match sustained dispositions that reference it",
                f"$.corrections[{correction_id}].finding_ids",
            )
        expected_material = any(findings[item]["material"] for item in correction["finding_ids"])
        if correction["material"] != expected_material:
            add_error(errors, "GC309", "correction material flag must match its findings", f"$.corrections[{correction_id}].material")
        invalidated = correction["invalidated_proof_ids"]
        for proof_id in invalidated:
            if proof_id not in current_proofs or current_proofs[proof_id]["status"] != "valid":
                add_error(errors, "GC310", "correction can invalidate only current valid proof", f"$.corrections[{correction_id}].invalidated_proof_ids")
        for proof in correction["revalidated_proofs"]:
            if proof["proof_id"] in current_proofs or proof["proof_id"] in new_proof_ids:
                add_error(errors, "GC311", "revalidated proof ID must be new", f"$.corrections[{correction_id}].revalidated_proofs")
            new_proof_ids.add(proof["proof_id"])
            if proof["supersedes"] not in invalidated:
                add_error(errors, "GC312", "revalidated proof must supersede an invalidated proof", f"$.corrections[{correction_id}].revalidated_proofs")
            if not set(proof["evidence_refs"]).issubset(evidence_ids):
                add_error(errors, "GC313", "revalidated proof references unknown evidence", f"$.corrections[{correction_id}].revalidated_proofs")
    if alignment["alignment_verdict"] == "aligned" and case["intent_lock"]["confidence"] not in {"locked", "supported"}:
        add_error(errors, "GC313A", "aligned verdict requires locked or supported intent", "$.alignment_verdict")
    if alignment["workflow_gate"] == "pass":
        if open_ids:
            add_error(errors, "GC314", "open findings block workflow pass", "$.workflow_gate")
        if any(not item["closed"] for item in alignment["dispositions"]):
            add_error(errors, "GC315", "every finding must be closed before pass", "$.workflow_gate")
        if any(item["status"] == "pending" for item in alignment["corrections"]):
            add_error(errors, "GC316", "pending corrections block a pass verdict", "$.workflow_gate")
        for finding_id, finding in findings.items():
            disposition = dispositions.get(finding_id)
            if disposition and finding["severity"] == "blocking" and disposition["resolution"] in {"sustained", "unresolved"}:
                add_error(errors, "GC317", "blocking sustained or unresolved finding blocks workflow pass", "$.workflow_gate")
    return errors


def apply_alignment(case: dict[str, Any], alignment: dict[str, Any]) -> None:
    update_run_completion(case, alignment["role_run"])
    proofs = {item["proof_id"]: item for item in case["proofs"]}
    for correction in alignment["corrections"]:
        for proof_id in correction["invalidated_proof_ids"]:
            proofs[proof_id]["status"] = "invalidated"
            if proof_id not in case["invalidated_proof_ids"]:
                case["invalidated_proof_ids"].append(proof_id)
        for proof in correction["revalidated_proofs"]:
            case["proofs"].append(copy.deepcopy(proof))
    case["invalidated_proof_ids"] = sorted(set(case["invalidated_proof_ids"]))
    case["alignment_record"] = copy.deepcopy(alignment)
    case["status"] = {
        "pass": "verified",
        "return_to_worker": "correction_required",
        "human_decision_required": "blocked",
        "blocked": "blocked",
    }[alignment["workflow_gate"]]
    case["continuity"]["current_state_summary"] = (
        f"Alignment verdict recorded: {alignment['alignment_verdict']}; workflow gate: {alignment['workflow_gate']}."
    )
    case["continuity"]["completed_steps"].append("alignment_applied")
    case["continuity"]["completed_steps"] = sorted(set(case["continuity"]["completed_steps"]))
    case["continuity"]["next_safe_action"] = (
        "Present the verified result to the human authority."
        if alignment["workflow_gate"] == "pass"
        else "Return valid objections and corrections to a new worker run."
    )
    correction_status = "not_applicable"
    if alignment["corrections"]:
        correction_status = (
            "pending"
            if any(item["status"] == "pending" for item in alignment["corrections"])
            else "revalidated"
            if any(item["status"] == "revalidated" for item in alignment["corrections"])
            else "not_applicable"
        )
    append_ledger(
        case,
        alignment["role_run"]["run_id"],
        "alignment_applied",
        alignment["packet_id"],
        alignment["canonical_digest"],
        material=any(item["material"] for item in alignment["corrections"]),
        subject_revision=f"case-revision-{case['revision']}",
        validation_status="passed",
        approval_status="pending" if alignment["workflow_gate"] == "human_decision_required" else "not_required",
        correction_status=correction_status,
    )


def next_required_role(case: dict[str, Any]) -> str:
    return {
        "draft": "intent_objector",
        "ready_for_worker": "worker",
        "worker_complete": "objector",
        "objection_open": "aligner",
        "alignment_required": "aligner",
        "correction_required": "worker",
        "verified": "human_authority",
        "blocked": "human_authority",
        "interrupted": "reserve",
    }[case["status"]]


def make_resume_packet(case: dict[str, Any]) -> dict[str, Any]:
    validate_errors: list[Diagnostic] = []
    validate_continuity(case["continuity"], "$.continuity", validate_errors, require_resume=True)
    if validate_errors:
        raise ValueError(f"resume state is not idempotent: [{validate_errors[0].code}] {validate_errors[0].message}")
    packet = {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "resume_packet",
        "packet_id": new_id("resume-packet"),
        "created_at": utc_now(),
        "parent": packet_parent(case),
        "canonical_digest": "",
        "start_pack_binding": copy.deepcopy(case["start_pack_binding"]),
        "intent_lock": copy.deepcopy(case["intent_lock"]),
        "intent_challenge": copy.deepcopy(case["intent_challenge"]),
        "project_boundary": copy.deepcopy(case["project_boundary"]),
        "case_status": case["status"],
        "role_runs": copy.deepcopy(case["role_runs"]),
        "task": copy.deepcopy(case["task"]),
        "worker_response": copy.deepcopy(case["worker_response"]),
        "objector_response": copy.deepcopy(case["objector_response"]),
        "alignment_record": copy.deepcopy(case["alignment_record"]),
        "proofs": copy.deepcopy(case["proofs"]),
        "invalidated_proof_ids": copy.deepcopy(case["invalidated_proof_ids"]),
        "continuity": copy.deepcopy(case["continuity"]),
        "next_required_role": next_required_role(case),
        "provenance_head": case["provenance_ledger"][-1]["entry_digest"],
    }
    return stamp_document(packet)


def command_init(args: argparse.Namespace) -> int:
    output = Path(args.output)
    if output.exists():
        print(f"refusing to overwrite existing case: {output}", file=sys.stderr)
        return 2
    now = utc_now()
    case_id = args.case_id or new_id("case")
    orchestrator_run = make_run(
        "orchestrator", args.run_id or new_id("run-orchestrator"), args.provider, args.model,
        args.surface, args.context_id, args.billing_pool_id, args.data_class, None,
    )
    orchestrator_run["completed_at"] = now
    source_id = "source-intent-seed"
    evidence_id = "evidence-intent-seed"
    capability_id = "intent-reconstruction"
    authoritative_seed = getattr(args, "authoritative_seed_summary", None)
    challenge_fields = {
        "context_id": getattr(args, "intent_challenger_context_id", None),
        "competing_interpretation": getattr(args, "intent_competing_interpretation", None),
        "consequence_difference": getattr(args, "intent_consequence_difference", None),
        "resolution": getattr(args, "intent_challenge_resolution", None),
    }
    challenge_supplied = [value is not None for value in challenge_fields.values()]
    if any(challenge_supplied) and not all(challenge_supplied):
        print(
            "intent challenge requires a distinct context, competing interpretation, "
            "consequence difference, and resolved verdict",
            file=sys.stderr,
        )
        return 2
    challenge_complete = all(challenge_supplied)
    if args.confidence in {"locked", "supported"} and not authoritative_seed:
        print(
            "locked or supported intent requires --authoritative-seed-summary; "
            "a candidate outcome summary cannot authorize itself",
            file=sys.stderr,
        )
        return 2
    if challenge_complete and not authoritative_seed:
        print("intent challenge requires a separately preserved authoritative seed", file=sys.stderr)
        return 2
    if challenge_complete and args.confidence in {"conflicted", "unknown"}:
        print("intent challenge cannot clear conflicted or unknown material intent", file=sys.stderr)
        return 2
    if challenge_complete and challenge_fields["context_id"] == args.context_id:
        print("intent challenge requires a context distinct from the orchestrator", file=sys.stderr)
        return 2
    adapter_digest = sha256_value(
        {"adapter_id": args.adapter_id, "adapter_version": args.adapter_version, "project_id": args.project_id}
    )
    permission_policy = {
        "policy_id": args.permission_policy_id,
        "policy_digest": "",
        "default": "deny",
        "rules": [],
        "approval_receipts": [],
    }
    permission_policy["policy_digest"] = permission_policy_digest(permission_policy)
    start_binding = load_start_pack_binding(Path(args.start_pack_root)) if args.start_pack_root else None
    intent_lock = {
        "outcome": args.outcome,
        "reason": args.reason,
        "primary_user": args.primary_user,
        "job": args.job,
        "non_negotiables": list(dict.fromkeys(args.non_negotiable or ["Preserve truthful evidence and human authority."])),
        "prohibitions": list(dict.fromkeys(args.prohibition or [])),
        "tradeoff_rules": list(dict.fromkeys(args.tradeoff_rule or ["Truth and safety outrank speed."])),
        "included_scope": list(dict.fromkeys(args.included_scope)),
        "excluded_scope": list(dict.fromkeys(args.excluded_scope or [])),
        "material_open_decisions": list(dict.fromkeys(args.open_decision or [])),
        "confidence": args.confidence,
        "source_precedence": ["current user authority", "sealed project authority", "approved evidence"],
        "success_criteria": list(dict.fromkeys(args.success_criterion)),
        "authority_owner": args.authority_owner,
        "permission_boundaries": ["All external and mutating actions require an exact recorded approval."],
        "permission_policy_id": permission_policy["policy_id"],
        "permission_policy_digest": permission_policy["policy_digest"],
    }
    challenge_run: dict[str, Any] | None = None
    intent_challenge: dict[str, Any] | None = None
    role_runs = [orchestrator_run]
    if challenge_complete:
        challenge_run = make_run(
            "intent_objector",
            getattr(args, "intent_challenger_run_id", None) or new_id("run-intent-objector"),
            getattr(args, "intent_challenger_provider", None) or args.provider,
            getattr(args, "intent_challenger_model", None) or args.model,
            getattr(args, "intent_challenger_surface", None) or args.surface,
            challenge_fields["context_id"],
            args.billing_pool_id,
            args.data_class,
            orchestrator_run["run_id"],
        )
        challenge_run["completed_at"] = now
        grade = independence_grade(orchestrator_run, challenge_run)
        if grade == "not_applicable":
            print("intent challenge did not achieve a distinct review context", file=sys.stderr)
            return 2
        role_runs.append(challenge_run)
        intent_challenge = {
            "candidate_digest": sha256_value(intent_lock),
            "authoritative_source_id": source_id,
            "challenger_run": copy.deepcopy(challenge_run),
            "independence_grade": grade,
            "competing_interpretation": challenge_fields["competing_interpretation"],
            "consequence_difference": challenge_fields["consequence_difference"],
            "resolution": challenge_fields["resolution"],
            "evidence_refs": [evidence_id],
            "challenged_at": now,
        }
    case: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "council_case",
        "packet_id": case_id,
        "created_at": now,
        "updated_at": now,
        "revision": 1,
        "canonical_digest": "",
        "start_pack_binding": start_binding,
        "intent_lock": intent_lock,
        "intent_challenge": intent_challenge,
        "project_boundary": {
            "project_id": args.project_id,
            "adapter_id": args.adapter_id,
            "adapter_version": args.adapter_version,
            "adapter_digest": adapter_digest,
            "allowed_destinations": list(dict.fromkeys(args.destination)),
            "allowed_data_classes": list(dict.fromkeys(args.data_class)),
        },
        "council_mode": args.mode,
        "required_independence": args.required_independence,
        "role_runs": role_runs,
        "permissions": permission_policy,
        "budget_lock": {
            "currency": args.currency,
            "shared_fixed_minor_units": 0,
            "per_project_fixed_minor_units": 0,
            "metered_planning_minor_units": 0,
            "expected_increment_minor_units": 0,
            "expected_total_minor_units": 0,
            "pools": [
                {
                    "pool_id": args.billing_pool_id,
                    "kind": "fixed",
                    "enabled": True,
                    "hard_limit_minor_units": 0,
                    "spent_minor_units": 0,
                    "overage_allowed": False,
                }
            ],
            "price_evidence": [],
        },
        "capabilities": [
            {
                "capability_id": capability_id,
                "disposition": "reuse",
                "canonical_owner": "Selective Intelligence intent reconstruction",
                "evidence_refs": [evidence_id],
            }
        ],
        "sources": [
            {
                "source_id": source_id,
                "provider": "user",
                "immutable_id": sha256_value({"case": case_id, "seed": authoritative_seed or args.outcome}),
                "title": "Authoritative intent seed" if authoritative_seed else "Candidate intake summary",
                "source_type": "user_intent_seed" if authoritative_seed else "candidate_intent_summary",
                "project_id": args.project_id,
                "authority": "authoritative" if authoritative_seed else "draft",
                "sensitivity": args.sensitivity,
                "data_classes": list(dict.fromkeys(args.data_class)),
                "version": "1",
                "modified_at": now,
                "validated_at": now,
                "summary": authoritative_seed or args.outcome,
            }
        ],
        "evidence": [
            {
                "evidence_id": evidence_id,
                "source_id": source_id,
                "locator": "authoritative seed summary" if authoritative_seed else "machine candidate intake",
                "summary": authoritative_seed or args.outcome,
                "classification": "confirmed" if authoritative_seed else "inferred",
                "observed_at": now,
                "content_digest": sha256_value({"seed": authoritative_seed or args.outcome, "candidate_job": args.job}),
            }
        ],
        "task": {
            "task_id": args.task_id or new_id("task"),
            "exact_task": args.exact_task,
            "output_contract": args.output_contract,
            "success_criteria": list(dict.fromkeys(args.success_criterion)),
            "prohibitions": list(dict.fromkeys(args.prohibition or [])),
            "source_ids": [source_id],
            "capability_ids": [capability_id],
            "requested_actions": [],
            "required_proof_ids": ["proof-outcome"],
        },
        "exports": [],
        "worker_response": None,
        "objector_response": None,
        "alignment_record": None,
        "proofs": [],
        "invalidated_proof_ids": [],
        "continuity": {
            "current_state_summary": (
                "Intent reconstruction challenged and sufficient for a bounded worker packet."
                if challenge_complete
                else "Candidate intent reconstructed; pre-lock challenge remains required."
            ),
            "repository": None,
            "uncommitted_changes": [],
            "migrations": [],
            "external_actions": [],
            "completed_steps": ["intent_reconstructed", "intent_challenged"] if challenge_complete else ["intent_reconstructed"],
            "next_safe_action": (
                "Export a bounded worker packet into a distinct context."
                if challenge_complete
                else "Challenge the candidate meaning against the authoritative seed before material work."
            ),
            "checkpointed_at": now,
        },
        "status": "ready_for_worker" if challenge_complete else "draft",
        "provenance_ledger": [],
    }
    append_ledger(
        case,
        orchestrator_run["run_id"],
        "case_initialized",
        case_id,
        sha256_value(case["intent_lock"]),
        material=True,
        subject_revision="case-revision-1",
        validation_status="passed",
    )
    if challenge_run is not None and intent_challenge is not None:
        append_ledger(
            case,
            challenge_run["run_id"],
            "intent_challenge_recorded",
            f"{case_id}:intent-challenge",
            sha256_value(intent_challenge),
            material=True,
            subject_revision="case-revision-1",
            validation_status="passed",
        )
    stamp_document(case)
    errors = validate_document(case, Path(args.start_pack_root) if args.start_pack_root else None)
    if errors:
        print(f"cannot initialize invalid case: [{errors[0].code}] {errors[0].message}", file=sys.stderr)
        return 2
    write_json_atomic(output, case)
    print(f"Initialized Guided Council case at {output}")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    try:
        document = read_json(Path(args.path))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    errors = validate_document(document, Path(args.start_pack_root) if args.start_pack_root else None)
    return emit_diagnostics(errors, args.json)


def command_status(args: argparse.Namespace) -> int:
    try:
        case = read_json(Path(args.case))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    errors = validate_document(case)
    result = {
        "valid": not errors,
        "case_id": case.get("packet_id"),
        "status": case.get("status"),
        "revision": case.get("revision"),
        "next_required_role": next_required_role(case) if not errors else None,
        "next_safe_action": case.get("continuity", {}).get("next_safe_action"),
        "proofs_valid": sum(item.get("status") == "valid" for item in case.get("proofs", [])),
        "proofs_invalidated": len(case.get("invalidated_proof_ids", [])),
        "open_findings": len(case.get("alignment_record", {}).get("open_finding_ids", [])) if case.get("alignment_record") else len(case.get("objector_response", {}).get("findings", [])) if case.get("objector_response") else 0,
        "errors": diagnostics_json(errors),
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Case: {result['case_id']}")
        print(f"Status: {result['status']}")
        print(f"Next role: {result['next_required_role']}")
        print(f"Next action: {result['next_safe_action']}")
        print(f"Validation errors: {len(errors)}")
    return 1 if errors else 0


def command_export(args: argparse.Namespace) -> int:
    case_path = Path(args.case)
    try:
        case = read_json(case_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    case_errors = validate_document(case)
    if case_errors:
        print(f"refusing invalid case: [{case_errors[0].code}] {case_errors[0].message}", file=sys.stderr)
        return 2
    if args.role == "worker" and case["status"] not in {"ready_for_worker", "correction_required"}:
        print("case is not ready for a worker export", file=sys.stderr)
        return 2
    if args.role == "objector":
        if not args.worker_response:
            print("objector export requires --worker-response", file=sys.stderr)
            return 2
        try:
            import_worker_response(case, read_json(Path(args.worker_response)))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if args.role == "aligner" and case.get("objector_response") is None:
        print("aligner export requires an imported objector response", file=sys.stderr)
        return 2
    parent_run = case["role_runs"][-1]["run_id"]
    run = make_run(
        args.role, args.run_id, args.provider, args.model, args.surface, args.context_id,
        args.billing_pool_id, args.data_class, parent_run,
    )
    try:
        add_run(case, run)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finish_case_update(case)
    parent_digest = case["canonical_digest"]
    try:
        if args.role == "worker":
            packet = make_worker_packet(case, run)
        elif args.role == "objector":
            packet = make_objector_packet(case, run)
        else:
            packet = make_alignment_packet(case, run)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    packet_errors = validate_document(packet)
    if packet_errors:
        print(f"refusing invalid export: [{packet_errors[0].code}] {packet_errors[0].message}", file=sys.stderr)
        return 2
    record_export(case, packet, run["run_id"], parent_digest)
    finish_case_update(case)
    final_errors = validate_document(case)
    if final_errors:
        print(f"refusing invalid case update: [{final_errors[0].code}] {final_errors[0].message}", file=sys.stderr)
        return 2
    write_json_atomic(case_path, case)
    write_json_atomic(Path(args.output), packet)
    print(f"Exported {args.role} packet to {args.output}")
    return 0


def command_import_objector(args: argparse.Namespace) -> int:
    case_path = Path(args.case)
    try:
        case = read_json(case_path)
        response = read_json(Path(args.response))
        import_objector_response(case, response)
        finish_case_update(case)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    errors = validate_document(case)
    if errors:
        print(f"refusing invalid case update: [{errors[0].code}] {errors[0].message}", file=sys.stderr)
        return 2
    write_json_atomic(case_path, case)
    print(f"Imported {len(response['findings'])} objector finding(s)")
    return 0


def command_validate_alignment(args: argparse.Namespace) -> int:
    case_path = Path(args.case)
    try:
        case = read_json(case_path)
        alignment = read_json(Path(args.alignment))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    errors = validate_document(case)
    if not errors:
        errors = cross_validate_alignment(case, alignment)
    if errors:
        return emit_diagnostics(errors, args.json)
    if args.apply:
        try:
            apply_alignment(case, alignment)
            finish_case_update(case)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        case_errors = validate_document(case)
        if case_errors:
            print(f"refusing invalid case update: [{case_errors[0].code}] {case_errors[0].message}", file=sys.stderr)
            return 2
        write_json_atomic(case_path, case)
    if args.json:
        print(json.dumps({
            "valid": True,
            "applied": bool(args.apply),
            "alignment_verdict": alignment["alignment_verdict"],
            "workflow_gate": alignment["workflow_gate"],
            "errors": [],
        }, indent=2, sort_keys=True))
    else:
        print(
            f"Alignment validation passed; alignment={alignment['alignment_verdict']}; "
            f"gate={alignment['workflow_gate']}; applied={bool(args.apply)}"
        )
    return 0


def command_export_resume(args: argparse.Namespace) -> int:
    case_path = Path(args.case)
    try:
        case = read_json(case_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    errors = validate_document(case)
    if errors:
        print(f"refusing invalid case: [{errors[0].code}] {errors[0].message}", file=sys.stderr)
        return 2
    try:
        packet = make_resume_packet(case)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    packet_errors = validate_document(packet)
    if packet_errors:
        print(f"refusing invalid resume packet: [{packet_errors[0].code}] {packet_errors[0].message}", file=sys.stderr)
        return 2
    actor_run_id = case["role_runs"][-1]["run_id"]
    parent_digest = case["canonical_digest"]
    record_export(case, packet, actor_run_id, parent_digest)
    append_ledger(
        case,
        actor_run_id,
        "resume_exported",
        packet["packet_id"],
        packet["canonical_digest"],
        subject_revision=f"case-revision-{case['revision']}",
        validation_status="passed",
    )
    finish_case_update(case)
    write_json_atomic(case_path, case)
    write_json_atomic(Path(args.output), packet)
    print(f"Exported idempotent resume packet to {args.output}")
    return 0


def command_ledger_doctor(args: argparse.Namespace) -> int:
    try:
        case = read_json(Path(args.case))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    errors: list[Diagnostic] = []
    runs = case.get("role_runs", [])
    runs_by_id = {
        item.get("run_id"): item
        for item in runs
        if isinstance(item, dict) and isinstance(item.get("run_id"), str)
    }
    validate_ledger(case.get("provenance_ledger"), runs_by_id, "$.provenance_ledger", errors)
    if args.json:
        print(json.dumps({"healthy": not errors, "entries": len(case.get("provenance_ledger", [])), "errors": diagnostics_json(errors)}, indent=2, sort_keys=True))
    elif errors:
        for item in errors:
            print(f"[{item.code}] {item.message} ({item.path})")
    else:
        print(f"Provenance ledger healthy: {len(case['provenance_ledger'])} hash-chained entries")
    return 1 if errors else 0


def self_test() -> tuple[list[str], list[str]]:
    passed: list[str] = []
    failed: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        if condition:
            passed.append(name)
        else:
            failed.append(f"{name}: {detail or 'condition failed'}")

    def error_codes(document: dict[str, Any]) -> set[str]:
        return {item.code for item in validate_document(document)}

    with tempfile.TemporaryDirectory(prefix="selective-intelligence-council-") as temporary:
        root = Path(temporary)
        start_root = root / "project"
        pack = start_root / ".selective-intelligence"
        pack.mkdir(parents=True)
        start_lock = {
            "validator_version": "0.1.1",
            "project": {"id": "project-a"},
            "release": {"id": "release-a"},
            "control_digest": "a" * 64,
            "semantic_digest": "b" * 64,
        }
        write_json_atomic(pack / "lock.json", start_lock)
        case_path = root / "case.json"
        init_args = argparse.Namespace(
            output=str(case_path), case_id="case-a", run_id="run-orchestrator", provider="openai",
            model="model-a", surface="chat", context_id="ctx-orchestrator", billing_pool_id="pool-free",
            data_class=["public"], start_pack_root=str(start_root), outcome="Produce a verified council result.",
            reason="The beginner needs a trustworthy completed outcome.",
            primary_user="A beginner", job="Complete one bounded outcome", non_negotiable=[], prohibition=[],
            tradeoff_rule=[], included_scope=["One bounded Guided Council result"], excluded_scope=[],
            open_decision=[], confidence="locked", permission_policy_id="policy-default-deny",
            authoritative_seed_summary="Produce a verified council result.",
            intent_challenger_run_id="run-intent-objector", intent_challenger_provider="openai",
            intent_challenger_model="model-a", intent_challenger_surface="chat",
            intent_challenger_context_id="ctx-intent-objector",
            intent_competing_interpretation="The request could mean producing a persuasive plan without executing or proving the outcome.",
            intent_consequence_difference="That reading would stop at prose while the intended reading requires an observed bounded result.",
            intent_challenge_resolution="candidate_supported",
            success_criterion=["The result has evidence and an alignment pass."], authority_owner="human-owner",
            project_id="project-a", adapter_id="generic", adapter_version="1", destination=["local"],
            mode="single_model", required_independence="separate_context_same_model", currency="USD",
            sensitivity="public", task_id="task-a", exact_task="Build and verify the requested result.",
            output_contract="Return the completed result and exact proof.",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            init_code = command_init(init_args)
        case = read_json(case_path)
        check("init creates a valid Start-Pack-bound case", init_code == 0 and not validate_document(case, start_root))

        candidate_args = copy.deepcopy(init_args)
        candidate_path = root / "candidate-case.json"
        candidate_args.output = str(candidate_path)
        candidate_args.case_id = "case-candidate"
        candidate_args.confidence = "provisional"
        candidate_args.authoritative_seed_summary = None
        candidate_args.intent_challenger_run_id = None
        candidate_args.intent_challenger_provider = None
        candidate_args.intent_challenger_model = None
        candidate_args.intent_challenger_surface = None
        candidate_args.intent_challenger_context_id = None
        candidate_args.intent_competing_interpretation = None
        candidate_args.intent_consequence_difference = None
        candidate_args.intent_challenge_resolution = None
        with contextlib.redirect_stdout(io.StringIO()):
            candidate_code = command_init(candidate_args)
        candidate_case = read_json(candidate_path)
        check(
            "machine candidate defaults to provisional draft before intent challenge",
            candidate_code == 0
            and candidate_case["status"] == "draft"
            and candidate_case["intent_lock"]["confidence"] == "provisional"
            and candidate_case["sources"][0]["authority"] == "draft"
            and candidate_case["evidence"][0]["classification"] == "inferred",
        )

        unauthorized_lock_args = copy.deepcopy(init_args)
        unauthorized_lock_path = root / "unauthorized-lock.json"
        unauthorized_lock_args.output = str(unauthorized_lock_path)
        unauthorized_lock_args.case_id = "case-unauthorized-lock"
        unauthorized_lock_args.authoritative_seed_summary = None
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            unauthorized_lock_code = command_init(unauthorized_lock_args)
        check(
            "candidate paraphrase cannot authorize a locked intent",
            unauthorized_lock_code == 2 and not unauthorized_lock_path.exists(),
        )

        ceremonial_args = copy.deepcopy(candidate_args)
        ceremonial_path = root / "ceremonial-challenge.json"
        ceremonial_args.output = str(ceremonial_path)
        ceremonial_args.case_id = "case-ceremonial-challenge"
        ceremonial_args.authoritative_seed_summary = "Produce a verified council result."
        ceremonial_args.intent_challenger_context_id = "ctx-claim-only"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            ceremonial_code = command_init(ceremonial_args)
        check(
            "intent challenge cannot be asserted as a context-only checkbox",
            ceremonial_code == 2 and not ceremonial_path.exists(),
        )

        stale_challenge = copy.deepcopy(case)
        stale_challenge["intent_challenge"]["candidate_digest"] = "0" * 64
        stamp_document(stale_challenge)
        check(
            "intent challenge stays bound to the exact candidate meaning",
            "GC062L" in error_codes(stale_challenge),
        )

        tampered = copy.deepcopy(case)
        tampered["intent_lock"]["outcome"] = "tampered"
        check("canonical digest detects tampering", "GC025" in error_codes(tampered))
        extra = copy.deepcopy(case)
        extra["unexpected"] = True
        stamp_document(extra)
        check("strict top-level keys reject extras", "GC003" in error_codes(extra))
        duplicate_context = copy.deepcopy(case)
        second_run = make_run(
            "worker", "run-duplicate-context", "openai", "model-a", "work", "ctx-orchestrator",
            "pool-free", ["public"], "run-orchestrator",
        )
        duplicate_context["role_runs"].append(second_run)
        stamp_document(duplicate_context)
        check("role passes require distinct contexts", "GC206" in error_codes(duplicate_context))
        hidden = copy.deepcopy(case)
        hidden["intent_lock"]["raw_prompt"] = "do not store this"
        stamp_document(hidden)
        check("raw prompts are prohibited", "GC011" in error_codes(hidden))
        secret = copy.deepcopy(case)
        secret["intent_lock"]["outcome"] = "api_key=abcdefghijk12345"
        stamp_document(secret)
        check("secret-like content is prohibited", "GC012" in error_codes(secret))
        open_locked = copy.deepcopy(case)
        open_locked["intent_lock"]["material_open_decisions"] = ["Choose the authoritative deployment region."]
        stamp_document(open_locked)
        check("locked intent cannot retain material open decisions", "GC062B" in error_codes(open_locked))

        unauthorized = copy.deepcopy(case)
        unauthorized["task"]["requested_actions"] = [
            {
                "action_id": "action-write", "action": "write_file", "destination": "local",
                "project_id": "project-a", "data_classes": ["public"], "approval_id": "approval-missing",
                "amount_minor_units": None, "billing_pool_id": None, "price_evidence_ids": [],
            }
        ]
        stamp_document(unauthorized)
        check("default-deny rejects an unknown or unruled action", "GC147B" in error_codes(unauthorized))
        approval_missing = copy.deepcopy(case)
        approval_missing["permissions"]["rules"] = [
            {
                "rule_id": "rule-write", "action": "write_file", "effect": "approval_required",
                "destination": "local", "project_id": "project-a", "data_classes": ["public"],
            }
        ]
        approval_missing["permissions"]["policy_digest"] = permission_policy_digest(approval_missing["permissions"])
        approval_missing["intent_lock"]["permission_policy_digest"] = approval_missing["permissions"]["policy_digest"]
        approval_missing["task"]["requested_actions"] = copy.deepcopy(unauthorized["task"]["requested_actions"])
        stamp_document(approval_missing)
        check("approval-required action blocks without an exact receipt", "GC147" in error_codes(approval_missing))
        deny_precedence = copy.deepcopy(approval_missing)
        deny_precedence["permissions"]["rules"].append(
            {
                "rule_id": "rule-write-deny", "action": "write_file", "effect": "deny",
                "destination": "local", "project_id": "project-a", "data_classes": ["public"],
            }
        )
        deny_precedence["permissions"]["approval_receipts"] = [
            {
                "approval_id": "approval-missing", "action": "write_file", "destination": "local",
                "project_id": "project-a", "data_classes": ["public"], "approved_by": "human-owner",
                "approved_at": utc_now(), "expires_at": None, "max_minor_units": None,
                "billing_pool_id": None, "price_evidence_ids": [],
            }
        ]
        deny_precedence["permissions"]["policy_digest"] = permission_policy_digest(deny_precedence["permissions"])
        deny_precedence["intent_lock"]["permission_policy_digest"] = deny_precedence["permissions"]["policy_digest"]
        stamp_document(deny_precedence)
        check("deny rules take precedence over approvals", "GC147A" in error_codes(deny_precedence))
        allowed_read = copy.deepcopy(case)
        allowed_read["permissions"]["rules"] = [
            {
                "rule_id": "rule-read", "action": "read_source", "effect": "allow",
                "destination": "local", "project_id": "project-a", "data_classes": ["public"],
            }
        ]
        allowed_read["permissions"]["policy_digest"] = permission_policy_digest(allowed_read["permissions"])
        allowed_read["intent_lock"]["permission_policy_digest"] = allowed_read["permissions"]["policy_digest"]
        allowed_read["task"]["requested_actions"] = [
            {
                "action_id": "action-read", "action": "read_source", "destination": "local",
                "project_id": "project-a", "data_classes": ["public"], "approval_id": None,
                "amount_minor_units": None, "billing_pool_id": None, "price_evidence_ids": [],
            }
        ]
        allowed_read["intent_challenge"]["candidate_digest"] = sha256_value(allowed_read["intent_lock"])
        stamp_document(allowed_read)
        check("read allow remains separate from write authority", not error_codes(allowed_read))
        write_allow = copy.deepcopy(approval_missing)
        write_allow["permissions"]["rules"][0]["effect"] = "allow"
        write_allow["permissions"]["policy_digest"] = permission_policy_digest(write_allow["permissions"])
        write_allow["intent_lock"]["permission_policy_digest"] = write_allow["permissions"]["policy_digest"]
        stamp_document(write_allow)
        write_allow_codes = error_codes(write_allow)
        check("mutating allow rules cannot bypass approval", bool(write_allow_codes & {"GC078I", "GC147C"}))
        wrong_destination = copy.deepcopy(case)
        wrong_destination["permissions"]["rules"] = [
            {
                "rule_id": "rule-outside", "action": "write_file", "effect": "approval_required",
                "destination": "outside", "project_id": "project-a", "data_classes": ["public"],
            }
        ]
        wrong_destination["permissions"]["approval_receipts"] = [
            {
                "approval_id": "approval-outside", "action": "write_file", "destination": "outside",
                "project_id": "project-a", "data_classes": ["public"], "approved_by": "human-owner",
                "approved_at": utc_now(), "expires_at": None, "max_minor_units": None, "billing_pool_id": None,
                "price_evidence_ids": [],
            }
        ]
        wrong_destination["permissions"]["policy_digest"] = permission_policy_digest(wrong_destination["permissions"])
        wrong_destination["intent_lock"]["permission_policy_digest"] = wrong_destination["permissions"]["policy_digest"]
        wrong_destination["task"]["requested_actions"] = [
            {
                "action_id": "action-outside", "action": "write_file", "destination": "outside",
                "project_id": "project-a", "data_classes": ["public"], "approval_id": "approval-outside",
                "amount_minor_units": None, "billing_pool_id": None, "price_evidence_ids": [],
            }
        ]
        stamp_document(wrong_destination)
        check("approved actions still cannot cross destination boundaries", "GC148" in error_codes(wrong_destination))
        float_budget = copy.deepcopy(case)
        float_budget["budget_lock"]["shared_fixed_minor_units"] = 1.5
        stamp_document(float_budget)
        check("budgets require integer minor units", "GC091" in error_codes(float_budget))
        miscomputed_budget = copy.deepcopy(case)
        miscomputed_budget["budget_lock"]["expected_total_minor_units"] = 1
        stamp_document(miscomputed_budget)
        check("budget expected total must recompute exactly", "GC091B" in error_codes(miscomputed_budget))
        unbounded_metered = copy.deepcopy(case)
        unbounded_metered["budget_lock"]["pools"] = [
            {
                "pool_id": "pool-metered", "kind": "metered", "enabled": True,
                "hard_limit_minor_units": 0, "spent_minor_units": 0, "overage_allowed": False,
            }
        ]
        stamp_document(unbounded_metered)
        check("enabled metered pools require a positive hard limit", "GC097A" in error_codes(unbounded_metered))
        stale_price = copy.deepcopy(case)
        stale_price["budget_lock"]["price_evidence"] = [
            {
                "evidence_id": "price-a", "service": "service", "amount_minor_units": 700,
                "currency": "USD", "region": "US", "source_url": "https://example.com/pricing",
                "observed_on": "not-a-date", "expires_on": None, "revalidate_on": "provider price changes",
            }
        ]
        stamp_document(stale_price)
        check("price evidence requires an observed date", "GC103" in error_codes(stale_price))
        stale_purchase = copy.deepcopy(case)
        stale_purchase["budget_lock"]["pools"] = [
            {
                "pool_id": "pool-metered", "kind": "metered", "enabled": True,
                "hard_limit_minor_units": 1000, "spent_minor_units": 0, "overage_allowed": False,
            }
        ]
        stale_purchase["budget_lock"]["price_evidence"] = [
            {
                "evidence_id": "price-expired", "service": "service", "amount_minor_units": 100,
                "currency": "USD", "region": "US", "source_url": "https://example.com/pricing",
                "observed_on": "2000-01-01", "expires_on": "2000-01-02", "revalidate_on": None,
            }
        ]
        stale_purchase["permissions"]["rules"] = [
            {
                "rule_id": "rule-spend", "action": "spend", "effect": "approval_required",
                "destination": "local", "project_id": "project-a", "data_classes": ["public"],
            }
        ]
        stale_purchase["permissions"]["approval_receipts"] = [
            {
                "approval_id": "approval-spend", "action": "spend", "destination": "local",
                "project_id": "project-a", "data_classes": ["public"], "approved_by": "human-owner",
                "approved_at": utc_now(), "expires_at": None, "max_minor_units": 500,
                "billing_pool_id": "pool-metered", "price_evidence_ids": ["price-expired"],
            }
        ]
        stale_purchase["permissions"]["policy_digest"] = permission_policy_digest(stale_purchase["permissions"])
        stale_purchase["intent_lock"]["permission_policy_digest"] = stale_purchase["permissions"]["policy_digest"]
        stale_purchase["task"]["requested_actions"] = [
            {
                "action_id": "action-spend", "action": "spend", "destination": "local",
                "project_id": "project-a", "data_classes": ["public"], "approval_id": "approval-spend",
                "amount_minor_units": 100, "billing_pool_id": "pool-metered",
                "price_evidence_ids": ["price-expired"],
            }
        ]
        stamp_document(stale_purchase)
        check("stale price evidence blocks purchase", "GC156" in error_codes(stale_purchase))
        trigger_only_purchase = copy.deepcopy(stale_purchase)
        trigger_only_purchase["budget_lock"]["price_evidence"][0]["expires_on"] = None
        trigger_only_purchase["budget_lock"]["price_evidence"][0]["revalidate_on"] = "provider price changes"
        stamp_document(trigger_only_purchase)
        check("non-deterministic trigger-only price evidence blocks purchase", "GC156" in error_codes(trigger_only_purchase))
        mismatch_errors: list[Diagnostic] = []
        wrong_root = root / "wrong"
        (wrong_root / ".selective-intelligence").mkdir(parents=True)
        wrong_lock = copy.deepcopy(start_lock)
        wrong_lock["control_digest"] = "c" * 64
        write_json_atomic(wrong_root / ".selective-intelligence" / "lock.json", wrong_lock)
        verify_start_pack_binding(case["start_pack_binding"], wrong_root, mismatch_errors)
        check("Start Pack digest mismatch is rejected", any(item.code == "GC035" for item in mismatch_errors))

        worker_run = make_run(
            "worker", "run-worker", "openai", "model-a", "work", "ctx-worker", "pool-free",
            ["public"], "run-orchestrator",
        )
        add_run(case, worker_run)
        finish_case_update(case)
        worker_parent_digest = case["canonical_digest"]
        worker_packet = make_worker_packet(case, worker_run)
        check("worker packet is typed and valid", not validate_document(worker_packet))
        record_export(case, worker_packet, worker_run["run_id"], worker_parent_digest)
        finish_case_update(case)
        completed_worker = copy.deepcopy(worker_run)
        completed_worker["completed_at"] = utc_now()
        worker_response = stamp_document(
            {
                "schema_version": SCHEMA_VERSION, "packet_type": "worker_response",
                "packet_id": "worker-response-a", "created_at": utc_now(),
                "parent": {"packet_id": worker_packet["packet_id"], "packet_type": "worker_packet", "digest": worker_packet["canonical_digest"]},
                "canonical_digest": "", "role_run": completed_worker, "attempted_actions": [],
                "summary": "Completed the bounded result and attached proof.", "artifact_refs": ["artifact-a"],
                "assumptions": [], "unknowns": [],
                "proofs": [
                    {
                        "proof_id": "proof-outcome", "status": "valid", "claim": "The bounded result exists.",
                        "evidence_refs": ["evidence-intent-seed"], "revision": "rev-a", "observed_at": utc_now(),
                        "supersedes": None,
                    }
                ],
            }
        )
        import_worker_response(case, worker_response)
        finish_case_update(case)
        check("worker response binds to its exact parent", case["worker_response"]["parent"]["digest"] == worker_packet["canonical_digest"])

        objector_run = make_run(
            "objector", "run-objector", "openai", "model-a", "chat", "ctx-objector", "pool-free",
            ["public"], "run-worker",
        )
        add_run(case, objector_run)
        finish_case_update(case)
        boundary_run = make_run(
            "objector", "run-boundary", "external", "model-b", "chat", "ctx-boundary", "pool-free",
            ["sanitized"], "run-worker",
        )
        boundary_rejected = False
        try:
            make_objector_packet(case, boundary_run)
        except ValueError:
            boundary_rejected = True
        check("objector export enforces its data boundary", boundary_rejected)
        objector_parent_digest = case["canonical_digest"]
        objector_packet = make_objector_packet(case, objector_run)
        check("same-model separate context receives honest grade", objector_packet["independence_grade"] == "separate_context_same_model")
        check(
            "objector packet is strictly read-only",
            objector_packet["permitted_actions"] == []
            and objector_packet["task"]["requested_actions"] == []
            and not validate_document(objector_packet),
        )
        record_export(case, objector_packet, objector_run["run_id"], objector_parent_digest)
        finish_case_update(case)
        completed_objector = copy.deepcopy(objector_run)
        completed_objector["completed_at"] = utc_now()
        objector_response = stamp_document(
            {
                "schema_version": SCHEMA_VERSION, "packet_type": "objector_response",
                "packet_id": "objector-response-a", "created_at": utc_now(),
                "parent": {"packet_id": objector_packet["packet_id"], "packet_type": "objector_packet", "digest": objector_packet["canonical_digest"]},
                "canonical_digest": "", "role_run": completed_objector,
                "independence_grade": "separate_context_same_model", "attempted_actions": [],
                "findings": [
                    {
                        "finding_id": "finding-a", "target_kind": "proof", "target_ref": "proof-outcome",
                        "category": "missing_evidence", "statement": "The proof needs revalidation after the material correction.",
                        "evidence_refs": ["proof-outcome"],
                        "counterexample_or_failed_test": "Change the material result and rerun the original proof without refreshing it.",
                        "recommended_correction": "Invalidate the old proof and run a revision-bound replacement check.",
                        "severity": "material", "material": True,
                    }
                ],
            }
        )
        write_attempt = copy.deepcopy(objector_response)
        write_attempt["attempted_actions"] = ["write_file"]
        stamp_document(write_attempt)
        check("objector mutation attempts are rejected", "GC258" in error_codes(write_attempt))
        vague_finding = copy.deepcopy(objector_response)
        vague_finding["findings"][0]["counterexample_or_failed_test"] = "too vague"
        vague_finding["findings"][0]["recommended_correction"] = "fix"
        stamp_document(vague_finding)
        vague_codes = error_codes(vague_finding)
        check("findings require a failed test and bounded correction", {"GC242A", "GC242B"}.issubset(vague_codes))
        overclaim = copy.deepcopy(objector_response)
        overclaim["independence_grade"] = "independent_model"
        stamp_document(overclaim)
        overclaim_rejected = False
        try:
            import_objector_response(copy.deepcopy(case), overclaim)
        except ValueError:
            overclaim_rejected = True
        check("independence overclaim is rejected", overclaim_rejected)
        import_objector_response(case, objector_response)
        finish_case_update(case)
        check("specific objector finding imports", case["objector_response"]["findings"][0]["target_ref"] == "proof-outcome")

        aligner_run = make_run(
            "aligner", "run-aligner", "openai", "model-a", "chat", "ctx-aligner", "pool-free",
            ["public"], "run-objector",
        )
        add_run(case, aligner_run)
        finish_case_update(case)
        alignment_parent_digest = case["canonical_digest"]
        alignment_packet = make_alignment_packet(case, aligner_run)
        record_export(case, alignment_packet, aligner_run["run_id"], alignment_parent_digest)
        finish_case_update(case)
        completed_aligner = copy.deepcopy(aligner_run)
        completed_aligner["completed_at"] = utc_now()
        alignment = stamp_document(
            {
                "schema_version": SCHEMA_VERSION, "packet_type": "alignment_record",
                "packet_id": "alignment-a", "created_at": utc_now(),
                "parent": {"packet_id": alignment_packet["packet_id"], "packet_type": "alignment_packet", "digest": alignment_packet["canonical_digest"]},
                "canonical_digest": "", "role_run": completed_aligner,
                "objector_response_digest": objector_response["canonical_digest"],
                "dispositions": [
                    {
                        "finding_id": "finding-a", "resolution": "sustained", "evidence_refs": ["proof-outcome"],
                        "rationale": "The objection correctly identifies proof invalidated by a material correction.",
                        "correction_id": "correction-a", "closed": True,
                    }
                ],
                "corrections": [
                    {
                        "correction_id": "correction-a", "finding_ids": ["finding-a"], "material": True,
                        "status": "revalidated", "invalidated_proof_ids": ["proof-outcome"],
                        "revalidated_proofs": [
                            {
                                "proof_id": "proof-outcome-v2", "status": "valid",
                                "claim": "The corrected bounded result is revalidated.",
                                "evidence_refs": ["evidence-intent-seed"], "revision": "rev-b",
                                "observed_at": utc_now(), "supersedes": "proof-outcome",
                            }
                        ],
                    }
                ],
                "alignment_verdict": "aligned", "workflow_gate": "pass", "open_finding_ids": [],
            }
        )
        missing_disposition = copy.deepcopy(alignment)
        missing_disposition["dispositions"] = []
        missing_disposition["corrections"] = []
        stamp_document(missing_disposition)
        check("every finding must be disposed exactly once", any(item.code == "GC303" for item in cross_validate_alignment(case, missing_disposition)))
        open_pass = copy.deepcopy(alignment)
        open_pass["dispositions"][0]["closed"] = False
        open_pass["open_finding_ids"] = ["finding-a"]
        stamp_document(open_pass)
        open_codes = {item.code for item in cross_validate_alignment(case, open_pass)}
        check("open findings cannot receive a pass verdict", bool(open_codes & {"GC292", "GC314"}))
        rejected_without_evidence = copy.deepcopy(alignment)
        rejected_without_evidence["dispositions"][0]["resolution"] = "rejected"
        rejected_without_evidence["dispositions"][0]["evidence_refs"] = []
        rejected_without_evidence["dispositions"][0]["correction_id"] = None
        rejected_without_evidence["corrections"] = []
        stamp_document(rejected_without_evidence)
        check("rejected findings still require evidence", "GC272" in error_codes(rejected_without_evidence))
        provisional_case = copy.deepcopy(case)
        provisional_case["intent_lock"]["confidence"] = "provisional"
        provisional_case["intent_lock"]["material_open_decisions"] = ["Human authority must choose the final channel."]
        check(
            "aligned verdict cannot claim provisional intent is resolved",
            "GC313A" in {item.code for item in cross_validate_alignment(provisional_case, alignment)},
        )
        objector_as_aligner = copy.deepcopy(alignment)
        objector_as_aligner["role_run"]["context_id"] = completed_objector["context_id"]
        stamp_document(objector_as_aligner)
        check(
            "Objector context cannot also serve as Aligner",
            "GC301A" in {item.code for item in cross_validate_alignment(case, objector_as_aligner)},
        )
        blocking_case = copy.deepcopy(case)
        blocking_case["objector_response"]["findings"][0]["severity"] = "blocking"
        check(
            "blocking sustained finding cannot pass the workflow gate",
            "GC317" in {item.code for item in cross_validate_alignment(blocking_case, alignment)},
        )
        no_revalidation = copy.deepcopy(alignment)
        no_revalidation["corrections"][0]["status"] = "pending"
        no_revalidation["corrections"][0]["invalidated_proof_ids"] = []
        no_revalidation["corrections"][0]["revalidated_proofs"] = []
        stamp_document(no_revalidation)
        check("material correction requires invalidation and revalidation", "GC282" in error_codes(no_revalidation))
        check("complete alignment cross-validates", not cross_validate_alignment(case, alignment))
        apply_alignment(case, alignment)
        finish_case_update(case)
        proof_status = {item["proof_id"]: item["status"] for item in case["proofs"]}
        check("material correction invalidates old proof", proof_status.get("proof-outcome") == "invalidated")
        check("material correction records replacement proof", proof_status.get("proof-outcome-v2") == "valid")
        check("closed findings can reach verified state", case["status"] == "verified")
        resume = make_resume_packet(case)
        check("resume packet is complete and valid", resume["next_required_role"] == "human_authority" and not validate_document(resume))
        ledger_errors: list[Diagnostic] = []
        validate_ledger(
            case["provenance_ledger"],
            {item["run_id"]: item for item in case["role_runs"]},
            "$.provenance_ledger",
            ledger_errors,
        )
        check("restrictive provenance ledger validates", not ledger_errors)
        broken_ledger = copy.deepcopy(case)
        broken_ledger["provenance_ledger"][1]["previous_entry_digest"] = "f" * 64
        stamp_document(broken_ledger)
        check("provenance chain tampering is rejected", "GC058" in error_codes(broken_ledger))
        false_actor_ledger = copy.deepcopy(case)
        false_actor_ledger["provenance_ledger"][0]["provider"] = "misattributed-provider"
        stamp_document(false_actor_ledger)
        check("provenance actor identity is bound to its role run", "GC054C" in error_codes(false_actor_ledger))
        check(
            "material provenance records validation and correction status",
            case["provenance_ledger"][0]["material"] is True
            and case["provenance_ledger"][0]["validation_status"] == "passed"
            and case["provenance_ledger"][-1]["correction_status"] == "revalidated",
        )
        unsafe_resume = copy.deepcopy(case)
        unsafe_resume["continuity"]["external_actions"] = [
            {
                "action_id": "external-a", "kind": "publish", "destination": "local", "status": "attempted",
                "idempotency_key": "idem-a", "receipt_ref": "receipt-a", "retry_safe": True,
            }
        ]
        resume_rejected = False
        try:
            make_resume_packet(unsafe_resume)
        except ValueError:
            resume_rejected = True
        check("ambiguous attempted actions block idempotent resume", resume_rejected)

    return passed, failed


def command_self_test(args: argparse.Namespace) -> int:
    passed, failed = self_test()
    result = {
        "result": "pass" if not failed else "fail",
        "count": len(passed),
        "passed": passed,
        "failed": failed,
        "scope": "deterministic local packet, permission, budget, binding, alignment, resume, and ledger controls only",
        "model_behavior_evaluation": "not_run",
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in passed:
            print(f"PASS: {item}")
        for item in failed:
            print(f"FAIL: {item}")
    return 1 if failed else 0


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--surface", required=True)
    parser.add_argument("--context-id", required=True)
    parser.add_argument("--billing-pool-id", required=True)
    parser.add_argument("--data-class", action="append", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic Selective Intelligence Guided Council controls")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a new default-deny Guided Council case")
    init.add_argument("--output", required=True)
    init.add_argument("--case-id")
    init.add_argument("--task-id")
    init.add_argument("--outcome", required=True)
    init.add_argument("--reason", required=True)
    init.add_argument("--primary-user", required=True)
    init.add_argument("--job", required=True)
    init.add_argument("--exact-task", required=True)
    init.add_argument("--output-contract", required=True)
    init.add_argument("--success-criterion", action="append", required=True)
    init.add_argument("--non-negotiable", action="append")
    init.add_argument("--prohibition", action="append")
    init.add_argument("--tradeoff-rule", action="append")
    init.add_argument("--included-scope", action="append", required=True)
    init.add_argument("--excluded-scope", action="append")
    init.add_argument("--open-decision", action="append")
    init.add_argument(
        "--confidence",
        choices=("locked", "supported", "provisional", "conflicted", "unknown"),
        default="provisional",
    )
    init.add_argument(
        "--authoritative-seed-summary",
        help="Faithful minimal summary of the authoritative human seed, kept separate from the candidate outcome",
    )
    init.add_argument("--intent-challenger-run-id")
    init.add_argument("--intent-challenger-provider")
    init.add_argument("--intent-challenger-model")
    init.add_argument("--intent-challenger-surface")
    init.add_argument(
        "--intent-challenger-context-id",
        help="Distinct context that challenged the candidate interpretation",
    )
    init.add_argument(
        "--intent-competing-interpretation",
        help="Substantive plausible alternative considered before Worker export",
    )
    init.add_argument(
        "--intent-consequence-difference",
        help="Observable product consequence that distinguishes the competing reading",
    )
    init.add_argument(
        "--intent-challenge-resolution",
        choices=("candidate_supported", "candidate_revised"),
        help="Resolved challenge verdict bound to the final candidate digest",
    )
    init.add_argument("--permission-policy-id", default="policy-default-deny")
    init.add_argument("--authority-owner", required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--adapter-id", default="generic")
    init.add_argument("--adapter-version", default="1")
    init.add_argument("--destination", action="append", required=True)
    init.add_argument("--mode", choices=("single_model", "multi_provider"), default="single_model")
    init.add_argument(
        "--required-independence",
        choices=("separate_context_same_model", "independent_model", "independent_human"),
        default="separate_context_same_model",
    )
    init.add_argument("--currency", default="USD")
    init.add_argument("--sensitivity", choices=("public", "internal", "confidential", "restricted"), default="internal")
    init.add_argument("--start-pack-root")
    add_run_arguments(init)
    init.set_defaults(func=command_init)

    validate = commands.add_parser("validate", help="validate any typed Council packet")
    validate.add_argument("--path", required=True)
    validate.add_argument("--start-pack-root")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=command_validate)

    status = commands.add_parser("status", help="show current Council case state and next role")
    status.add_argument("--case", required=True)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=command_status)

    export = commands.add_parser("export", help="export a worker, objector, or alignment packet")
    export.add_argument("--case", required=True)
    export.add_argument("--role", choices=("worker", "objector", "aligner"), required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--worker-response")
    add_run_arguments(export)
    export.set_defaults(func=command_export)

    import_objector = commands.add_parser("import-objector", help="validate and import a bound objector response")
    import_objector.add_argument("--case", required=True)
    import_objector.add_argument("--response", required=True)
    import_objector.set_defaults(func=command_import_objector)

    alignment = commands.add_parser("validate-alignment", help="cross-validate and optionally apply an alignment record")
    alignment.add_argument("--case", required=True)
    alignment.add_argument("--alignment", required=True)
    alignment.add_argument("--apply", action="store_true")
    alignment.add_argument("--json", action="store_true")
    alignment.set_defaults(func=command_validate_alignment)

    resume = commands.add_parser("export-resume", help="export a complete idempotent reserve handoff")
    resume.add_argument("--case", required=True)
    resume.add_argument("--output", required=True)
    resume.set_defaults(func=command_export_resume)

    ledger = commands.add_parser("ledger-doctor", help="validate the restrictive hash-chained provenance ledger")
    ledger.add_argument("--case", required=True)
    ledger.add_argument("--json", action="store_true")
    ledger.set_defaults(func=command_ledger_doctor)

    test = commands.add_parser("self-test", help="run deterministic local Council control fixtures")
    test.add_argument("--json", action="store_true")
    test.set_defaults(func=command_self_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
