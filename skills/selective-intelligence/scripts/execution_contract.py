#!/usr/bin/env python3
"""Validate bounded-delivery and execution-target decisions.

The model still reconstructs the product and chooses the delivery boundary. This
validator fails closed when the resulting decision erases the whole product,
does not define a complete active loop, or selects Sites for an operational
production application that needs a stronger execution environment.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "si.execution-contract.v1"
BINDING_FIELDS = ("projectId", "releaseId", "releaseVersion", "buildId", "lockVersion")
OPERATIONAL_DEPENDENCIES = (
    "persistentOperationalData",
    "complexPermissions",
    "substantialBackendWorkflows",
    "repositoryIntegration",
    "businessStateImageProcessing",
    "multiStageBusinessLogic",
    "migrationsAuditOrSystemOfRecord",
)
TARGET_KINDS = {"sites", "established_repository", "standalone_application", "other"}
SITES_ROLES = {"none", "prototype", "bounded_surface", "primary"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SELF_ATTESTATION_MARKERS = (
    "author says",
    "self-attest",
    "self attest",
    "because i say",
    "because we say",
)
SELF_ATTESTATION_RE = re.compile(
    r"\b(?:author|implementation team|team|maintainer|developer|implementer|owner|we|i)\s+"
    r"(?:confirm|confirms|confirmed|assert|asserts|asserted|declare|declares|declared|say|says|said)\b",
    re.IGNORECASE,
)
EVIDENCE_TYPES = {"automated_test", "manual_observation", "artifact_inspection", "runtime_trace"}
WHOLE_PRODUCT_COMPLETION_RE = re.compile(
    r"\b(?:build|complete|finish|release|ship)\b.*\b(?:entire|whole|every|all)\b.*\b(?:product|capabilit(?:y|ies))\b",
    re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(r"\b(?:UNRESOLVED|TBD|TO[- ]?DO)\b", re.IGNORECASE)


def _nonempty(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return (
        bool(stripped)
        and any(character.isalnum() for character in stripped)
        and PLACEHOLDER_RE.search(stripped) is None
    )


def _meaningful_string_array(value: Any, *, minimum: int = 1) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= minimum
        and all(_nonempty(item) for item in value)
    )


def validate_contract(
    contract: Any,
    *,
    expected_binding: dict[str, str] | None = None,
    expected_requirement_ids: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract must be an object"]

    if contract.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")

    binding = contract.get("binding")
    if not isinstance(binding, dict):
        errors.append("binding must be an object")
    else:
        for field in BINDING_FIELDS:
            if not _nonempty(binding.get(field)):
                errors.append(f"binding.{field} must be a non-empty string")
            elif expected_binding is not None and binding.get(field) != expected_binding.get(field):
                errors.append(
                    f"binding.{field} must match the active Start Pack value "
                    f"{expected_binding.get(field)!r}"
                )

    whole = contract.get("wholeProduct")
    if not isinstance(whole, dict):
        errors.append("wholeProduct must be an object")
    else:
        if whole.get("preserved") is not True:
            errors.append("wholeProduct.preserved must be true")
        if not _nonempty(whole.get("summary")):
            errors.append("wholeProduct.summary must be a non-empty string")
        if whole.get("complexity") not in {"single_deliverable", "multi_deliverable"}:
            errors.append("wholeProduct.complexity must be single_deliverable or multi_deliverable")

    phase = contract.get("phase")
    if phase not in {"first_delivery", "continuation"}:
        errors.append("phase must be first_delivery or continuation")

    deliverables = contract.get("deliverables")
    active: list[dict[str, Any]] = []
    if not isinstance(deliverables, list) or not deliverables:
        errors.append("deliverables must be a non-empty array")
        deliverables = []
    else:
        seen: set[str] = set()
        for index, item in enumerate(deliverables):
            label = f"deliverables[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{label} must be an object")
                continue
            deliverable_id = item.get("id")
            if not _nonempty(deliverable_id):
                errors.append(f"{label}.id must be a non-empty string")
            elif deliverable_id in seen:
                errors.append(f"duplicate deliverable id: {deliverable_id}")
            else:
                seen.add(deliverable_id)
            if not _nonempty(item.get("outcome")):
                errors.append(f"{label}.outcome must be a non-empty string")
            if item.get("active") is True:
                active.append(item)

    if len(active) != 1:
        errors.append("exactly one deliverable must be active")
    else:
        current = active[0]
        if phase == "first_delivery" and current.get("id") != "D1":
            errors.append("the active first deliverable must have id D1")
        for field in ("entry", "ending"):
            if not _nonempty(current.get(field)):
                errors.append(f"active deliverable {field} must be a non-empty string")
        proof = current.get("proof")
        if not isinstance(proof, list) or not proof:
            errors.append("active deliverable proof must contain typed observable evidence")
        else:
            for index, item in enumerate(proof):
                label = f"active deliverable proof[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{label} must be an evidence object")
                    continue
                if item.get("type") not in EVIDENCE_TYPES:
                    errors.append(f"{label}.type must be one of {sorted(EVIDENCE_TYPES)}")
                for field in ("procedure", "expected", "observed"):
                    if not _nonempty(item.get(field)):
                        errors.append(f"{label}.{field} must be meaningful")
                evidence_text = " ".join(
                    item.get(field, "")
                    for field in ("procedure", "expected", "observed", "observation")
                    if isinstance(item.get(field), str)
                )
                if SELF_ATTESTATION_RE.search(evidence_text) or any(
                    marker in evidence_text.casefold() for marker in SELF_ATTESTATION_MARKERS
                ):
                    errors.append(f"{label} must report a reproducible observation, not confirmation or assertion")
                if not _nonempty(item.get("evidenceRef")):
                    errors.append(f"{label}.evidenceRef must identify the evidence location")
        journey = current.get("journeySteps")
        if not _meaningful_string_array(journey, minimum=2):
            errors.append("active deliverable journeySteps must contain at least two meaningful steps")
        constraints = current.get("constraints")
        if not _meaningful_string_array(constraints):
            errors.append("active deliverable constraints must be a non-empty string array")
        requirement_ids = current.get("requirementIds")
        if (
            not isinstance(requirement_ids, list)
            or not requirement_ids
            or any(not isinstance(item, str) or not ID_RE.fullmatch(item) for item in requirement_ids)
            or len(requirement_ids) != len(set(requirement_ids))
        ):
            errors.append("active deliverable requirementIds must contain unique valid IDs")
        elif (
            expected_requirement_ids is not None
            and set(requirement_ids) != expected_requirement_ids
        ):
            errors.append("active deliverable requirementIds must exactly match the active build requirements")
        if current.get("completionScope") != "active_deliverable":
            errors.append("active deliverable completionScope must be active_deliverable")
        completion_claims = current.get("completionClaims")
        claim_requirement_ids: set[str] = set()
        if not isinstance(completion_claims, list) or not completion_claims:
            errors.append("active deliverable completionClaims must be a non-empty array")
        else:
            for index, claim in enumerate(completion_claims):
                label = f"active deliverable completionClaims[{index}]"
                if not isinstance(claim, dict):
                    errors.append(f"{label} must be an object")
                    continue
                requirement_id = claim.get("requirementId")
                if not isinstance(requirement_id, str) or not ID_RE.fullmatch(requirement_id):
                    errors.append(f"{label}.requirementId must be a valid ID")
                else:
                    claim_requirement_ids.add(requirement_id)
                if claim.get("scope") != "active_deliverable":
                    errors.append(f"{label}.scope must be active_deliverable")
                if not _nonempty(claim.get("claim")):
                    errors.append(f"{label}.claim must be meaningful")
                elif WHOLE_PRODUCT_COMPLETION_RE.search(claim["claim"]):
                    errors.append(f"{label}.claim may not claim whole-product or release completion")
        if (
            isinstance(requirement_ids, list)
            and requirement_ids
            and claim_requirement_ids != set(requirement_ids)
        ):
            errors.append("active deliverable completionClaims must cover exactly its requirementIds")
        if _nonempty(current.get("outcome")) and WHOLE_PRODUCT_COMPLETION_RE.search(current["outcome"]):
            errors.append("active deliverable outcome may not claim whole-product or release completion")
        excluded = current.get("excludedFromActive")
        if isinstance(whole, dict) and whole.get("complexity") == "multi_deliverable":
            if not _meaningful_string_array(excluded):
                errors.append("multi-deliverable products require a meaningful excludedFromActive array")
        elif not isinstance(excluded, list) or any(not _nonempty(item) for item in excluded):
            errors.append("active deliverable excludedFromActive must be an array of meaningful strings")
        if current.get("informationComplete") is not True:
            errors.append("active deliverable must be informationComplete")
        if current.get("fitsExecutionWindow") is not True:
            errors.append("active deliverable must fit the execution window")
        if current.get("endToEnd") is not True:
            errors.append("active deliverable must be endToEnd")

    if (
        isinstance(whole, dict)
        and whole.get("complexity") == "multi_deliverable"
        and len(deliverables) < 2
    ):
        errors.append("a multi-deliverable product must preserve at least one later deliverable")

    target = contract.get("executionTarget")
    if not isinstance(target, dict):
        errors.append("executionTarget must be an object")
        return errors

    kind = target.get("kind")
    if kind not in TARGET_KINDS:
        errors.append(f"executionTarget.kind must be one of {sorted(TARGET_KINDS)}")
    for field in ("productionIntent", "establishedApplicationAvailable"):
        if not isinstance(target.get(field), bool):
            errors.append(f"executionTarget.{field} must be boolean")
    sites_role = target.get("sitesRole")
    if sites_role not in SITES_ROLES:
        errors.append(f"executionTarget.sitesRole must be one of {sorted(SITES_ROLES)}")
    if not _nonempty(target.get("rationale")):
        errors.append("executionTarget.rationale must be a non-empty string")
    if not _meaningful_string_array(target.get("constraintsConsidered")):
        errors.append("executionTarget.constraintsConsidered must be a non-empty string array")

    dependencies = target.get("coreValueDependsOn")
    if not isinstance(dependencies, dict):
        errors.append("executionTarget.coreValueDependsOn must be an object")
        dependencies = {}
    else:
        for name in OPERATIONAL_DEPENDENCIES:
            if not isinstance(dependencies.get(name), bool):
                errors.append(f"executionTarget.coreValueDependsOn.{name} must be boolean")

    production = target.get("productionIntent") is True
    operational = any(dependencies.get(name) is True for name in OPERATIONAL_DEPENDENCIES)
    established_available = target.get("establishedApplicationAvailable") is True
    repository_fit = target.get("repositoryFit")
    if repository_fit not in {"fit", "not_fit", "unknown"}:
        errors.append("executionTarget.repositoryFit must be fit, not_fit, or unknown")

    if kind == "sites" and production and operational:
        errors.append("Sites cannot be the primary target for an operational production application")
    if kind == "sites" and sites_role not in {"prototype", "bounded_surface"}:
        errors.append("Sites execution must be classified as prototype or bounded_surface")
    if production and established_available and repository_fit == "fit" and kind != "established_repository":
        errors.append("use the fitting established application or repository for production execution")
    if kind != "sites" and sites_role != "none":
        errors.append("non-Sites execution targets require sitesRole none")

    return errors


def validate_path(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "errors": [f"cannot read contract: {exc}"]}
    errors = validate_contract(payload)
    return {"passed": not errors, "errors": errors}


def _self_test() -> int:
    valid = {
        "schemaVersion": SCHEMA_VERSION,
        "binding": {
            "projectId": "stone-inventory",
            "releaseId": "r001",
            "releaseVersion": "0.1.0",
            "buildId": "b001-capture",
            "lockVersion": "0.1.0",
        },
        "phase": "first_delivery",
        "wholeProduct": {
            "preserved": True,
            "summary": "Operational inventory system with receiving through catalog publishing.",
            "complexity": "multi_deliverable",
        },
        "deliverables": [
            {
                "id": "D1",
                "active": True,
                "outcome": "Capture a slab and reopen its persisted inventory record.",
                "entry": "Open camera capture.",
                "ending": "Reopen and edit the saved inventory record.",
                "proof": [
                    {
                        "type": "automated_test",
                        "procedure": "Run the capture-to-reopen regression with a disposable inventory fixture.",
                        "expected": "The saved slab appears in inventory and reopens with editable fields.",
                        "observed": "The saved slab appeared in inventory and reopened with editable fields.",
                        "evidenceRef": "builds/b001-capture/evidence.md#capture-loop",
                    }
                ],
                "journeySteps": [
                    "Capture and crop one slab photo.",
                    "Save the inventory record.",
                    "Reopen and edit the persisted record.",
                ],
                "constraints": ["Use the established repository and preserve later deliverables."],
                "requirementIds": ["REQ-CAPTURE"],
                "completionScope": "active_deliverable",
                "completionClaims": [
                    {
                        "requirementId": "REQ-CAPTURE",
                        "scope": "active_deliverable",
                        "claim": "The saved slab record can be reopened and edited.",
                    }
                ],
                "excludedFromActive": ["Receiving, warehouse transfer, sales, and catalog publishing."],
                "informationComplete": True,
                "fitsExecutionWindow": True,
                "endToEnd": True,
            },
            {"id": "D2", "active": False, "outcome": "Add receiving and bundle inheritance."},
        ],
        "executionTarget": {
            "kind": "established_repository",
            "productionIntent": True,
            "establishedApplicationAvailable": True,
            "repositoryFit": "fit",
            "sitesRole": "none",
            "rationale": "The established application supports durable operational workflows.",
            "constraintsConsidered": [
                "Durable state, permissions, image processing, and repository integration are required."
            ],
            "coreValueDependsOn": {name: True for name in OPERATIONAL_DEPENDENCIES},
        },
    }
    if validate_contract(valid):
        return 1
    invalid = json.loads(json.dumps(valid))
    invalid["executionTarget"]["kind"] = "sites"
    invalid["executionTarget"]["sitesRole"] = "primary"
    if not validate_contract(invalid):
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an SI execution contract")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("contract", type=Path)
    subparsers.add_parser("self-test")
    args = parser.parse_args()

    if args.command == "self-test":
        return _self_test()
    result = validate_path(args.contract)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
