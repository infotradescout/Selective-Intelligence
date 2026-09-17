#!/usr/bin/env python3
"""Fail-closed product delivery checks; not a substitute for observing the product.

Inputs are adapter-produced evidence. Hashes bind reports to files and revisions;
they do not establish that the report or a subjective design judgment is true.
The strongest verdict is ready_for_review, never user_accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "si.product_delivery.v1"
SHA = re.compile(r"^[a-f0-9]{64}$")
MODES = {"automatic", "manual", "optional_manual", "interactive"}
SCOPES = {"synthetic", "native", "live"}
KINDS = {"workflow", "visual", "restart", "safety", "launch"}
MAX_JSON = 2 * 1024 * 1024
MAX_ARTIFACT = 32 * 1024 * 1024


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def read_json(path: Path) -> Any:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_JSON:
        raise ValueError("Expected a bounded, regular JSON file")
    return json.loads(path.read_text(encoding="utf-8"),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 4096


def contract_errors(contract: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict) or contract.get("schema") != SCHEMA:
        return ["contract_schema_invalid"]
    for name in ("project", "source_revision", "intent_source"):
        if not _text(contract.get(name)):
            errors.append("contract_" + name + "_missing")
    owner = contract.get("canonical")
    if not isinstance(owner, dict) or any(not _text(owner.get(k)) for k in
                                        ("code_root", "entrypoint", "data_owner")):
        errors.append("canonical_owner_missing")
    requirements = contract.get("requirements")
    if not isinstance(requirements, list) or not requirements or len(requirements) > 100:
        return errors + ["requirements_missing_or_unbounded"]
    seen: set[str] = set()
    primary = 0
    for requirement in requirements:
        if not isinstance(requirement, dict):
            errors.append("requirement_invalid")
            continue
        rid = requirement.get("id")
        if not _text(rid) or rid in seen:
            errors.append("requirement_id_invalid_or_duplicate")
        else:
            seen.add(rid)
        if not isinstance(requirement.get("mode"), str) or requirement["mode"] not in MODES or not _text(requirement.get("outcome")):
            errors.append("requirement_semantics_missing")
        if type(requirement.get("primary")) is not bool:
            errors.append("requirement_primary_flag_missing")
        primary += requirement.get("primary") is True
        scopes = requirement.get("accepted_scopes")
        if not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) or s not in SCOPES for s in scopes):
            errors.append("requirement_evidence_scope_missing")
        kinds = requirement.get("required_evidence")
        if not isinstance(kinds, list) or not kinds or any(not isinstance(k, str) or k not in KINDS for k in kinds):
            errors.append("requirement_evidence_kind_missing")
        if requirement.get("primary") and (not isinstance(kinds, list) or "workflow" not in kinds):
            errors.append("primary_requires_workflow_evidence")
    if not primary:
        errors.append("primary_user_job_missing")
    if type(contract.get("user_facing")) is not bool:
        errors.append("surface_scope_missing")
    if type(contract.get("requires_installation")) is not bool:
        errors.append("installation_scope_missing")
    return errors


def _artifact(reference: Any, root: Path) -> bool:
    if not isinstance(reference, dict) or not _text(reference.get("path")):
        return False
    if not isinstance(reference.get("sha256"), str) or not SHA.fullmatch(reference["sha256"]):
        return False
    relative = Path(reference["path"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in reference["path"]:
        return False
    target = root / relative
    try:
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            return False
        if not target.is_file() or not 0 < target.stat().st_size <= MAX_ARTIFACT:
            return False
        return hashlib.sha256(target.read_bytes()).hexdigest() == reference["sha256"]
    except (OSError, RuntimeError):
        return False


def evaluate(contract: Any, evidence: Any, artifact_root: Path) -> dict[str, Any]:
    """Validate a delivery packet without reading or changing a product's save data."""
    blockers = contract_errors(contract)
    result = {"schema": "si.product_delivery.verdict.v1", "passed": False,
              "verdict": "needs_repair", "user_acceptance": "not_claimed",
              "blockers": blockers, "evaluated_requirements": [],
              "boundary": "Evidence integrity and coverage checks, not proof of subjective quality or client adoption."}
    if blockers:
        return result
    result["contract_hash"] = digest(contract)
    if not isinstance(evidence, dict) or evidence.get("schema") != "si.product_delivery.evidence.v1":
        blockers.append("evidence_schema_invalid")
        return result
    if evidence.get("contract_hash") != result["contract_hash"]:
        blockers.append("evidence_not_bound_to_current_intent")
    if evidence.get("source_revision") != contract["source_revision"]:
        blockers.append("evidence_not_bound_to_current_source")
    if evidence.get("canonical") != contract["canonical"]:
        blockers.append("evidence_wrong_product_owner")
    rejections = evidence.get("unresolved_user_rejections")
    if not isinstance(rejections, list) or rejections:
        blockers.append("user_rejection_unresolved_or_unreported")
    targets = evidence.get("active_targets")
    if not isinstance(targets, list) or targets != [contract["canonical"]]:
        blockers.append("competing_or_unverified_delivery_targets")
    if contract["requires_installation"]:
        install = evidence.get("installation") or {}
        if (not isinstance(install, dict) or install.get("running") is not True
                or install.get("source_revision") != contract["source_revision"]
                or install.get("entrypoint") != contract["canonical"]["entrypoint"]
                or not _artifact(install.get("artifact"), artifact_root)):
            blockers.append("intended_installation_not_verified")
    proofs = evidence.get("proofs")
    if not isinstance(proofs, list) or len(proofs) > 500:
        blockers.append("proofs_missing_or_unbounded")
        return result
    valid = []
    seen = set()
    for proof in proofs:
        if not isinstance(proof, dict):
            blockers.append("invalid_proof")
            continue
        pid = proof.get("id")
        if not _text(pid) or pid in seen:
            blockers.append("proof_id_invalid_or_duplicate")
            continue
        seen.add(pid)
        integrity = (proof.get("status") == "passed" and proof.get("executed") is True
                     and proof.get("source_revision") == contract["source_revision"]
                     and proof.get("contract_hash") == result["contract_hash"]
                     and isinstance(proof.get("scope"), str) and proof["scope"] in SCOPES
                     and isinstance(proof.get("kind"), str) and proof["kind"] in KINDS
                     and proof.get("entrypoint") == contract["canonical"]["entrypoint"]
                     and _text(proof.get("runner")) and _text(proof.get("target"))
                     and _artifact(proof.get("artifact"), artifact_root))
        if integrity:
            valid.append(proof)
    for requirement in contract["requirements"]:
        rid = requirement["id"]
        matching = [p for p in valid if p.get("requirement_id") == rid
                    and p.get("scope") in requirement["accepted_scopes"]
                    and p.get("mode") == requirement["mode"]]
        kinds = {p["kind"] for p in matching}
        missing = sorted(set(requirement["required_evidence"]) - kinds)
        failures = []
        if missing:
            failures.append("missing:" + ",".join(missing))
        if requirement["mode"] == "automatic":
            workflows = [p for p in matching if p["kind"] == "workflow"]
            if not workflows or not any(type(p.get("manual_entry_steps")) is int
                                         and p["manual_entry_steps"] == 0
                                         and p.get("trigger_observed") is True
                                         and p.get("result_observed") is True for p in workflows):
                failures.append("automatic_workflow_not_proved_without_manual_entry")
        if requirement["primary"] and contract["user_facing"]:
            reviews = [p for p in matching if p["kind"] == "visual"]
            if not reviews or not any(p.get("reviewed") is True
                                     and p.get("blocking_findings") == []
                                     and _text(p.get("reviewer"))
                                     and _artifact(p.get("screenshot"), artifact_root) for p in reviews):
                failures.append("primary_experience_not_rendered_and_reviewed")
        result["evaluated_requirements"].append({"id": rid, "passed": not failures,
                                                 "failures": failures})
        blockers.extend(rid + ":" + failure for failure in failures)
    result["passed"] = not blockers
    result["verdict"] = "ready_for_review" if result["passed"] else "needs_repair"
    return result


def admit_discovery(ledger: dict[str, Any], *, question: str, target: str,
                    action: str, known_path: bool = False) -> dict[str, Any]:
    """Durable callers must save returned ledger; calls outside SI are not intercepted.

    At most two equivalent searches per unresolved question and target. Rewording
    the query or a fresh context cannot reset that count. A pending search is
    continued with its existing handle, not another search. No safety denial is
    made retryable by this helper.
    """
    if not all(_text(v) for v in (question, target, action)):
        raise ValueError("Discovery identity is required")
    if action not in {"search", "read", "poll", "act"}:
        raise ValueError("Unknown discovery action")
    state = json.loads(json.dumps(ledger, allow_nan=False))
    entry = state.setdefault(digest([question, target]), {"searches": 0})
    if type(entry.get("searches")) is not int or entry["searches"] < 0:
        raise ValueError("Corrupt discovery ledger")
    if action == "search":
        if known_path:
            raise ValueError("Known target: read it instead of searching again")
        if entry.get("pending"):
            raise ValueError("Continue the existing search handle instead of launching another")
        if entry["searches"] >= 2:
            raise ValueError("No-progress search budget exhausted; act, narrow using evidence, or checkpoint")
        entry["searches"] += 1
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--artifact-root", required=True)
    args = parser.parse_args()
    try:
        result = evaluate(read_json(Path(args.contract)), read_json(Path(args.evidence)),
                          Path(args.artifact_root))
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps({"passed": False, "verdict": "needs_repair", "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
