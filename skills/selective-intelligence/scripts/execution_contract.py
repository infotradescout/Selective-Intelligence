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
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "si.execution-contract.v1"
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


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_contract(contract: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract must be an object"]

    if contract.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")

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
        if not isinstance(proof, list) or not proof or not all(_nonempty(item) for item in proof):
            errors.append("active deliverable proof must be a non-empty string array")
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
    sites_role = target.get("sitesRole")
    if sites_role not in SITES_ROLES:
        errors.append(f"executionTarget.sitesRole must be one of {sorted(SITES_ROLES)}")
    if not _nonempty(target.get("rationale")):
        errors.append("executionTarget.rationale must be a non-empty string")

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
    if kind == "sites" and sites_role == "primary" and operational:
        errors.append("Sites primary role conflicts with operational core dependencies")
    if production and established_available and repository_fit == "fit" and kind != "established_repository":
        errors.append("use the fitting established application or repository for production execution")
    if kind != "sites" and sites_role == "primary":
        errors.append("sitesRole primary requires executionTarget.kind sites")

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
                "proof": ["End-to-end capture, save, list, reopen, and edit test passes."],
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
