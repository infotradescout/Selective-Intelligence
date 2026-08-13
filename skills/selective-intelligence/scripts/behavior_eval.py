#!/usr/bin/env python3
"""Evidence-bearing behavior evaluation for Selective Intelligence.

This utility never calls or grades a model. It prevents a behavior claim from
passing on case IDs and booleans alone by requiring captured outputs, independent
per-invariant grading evidence, digests, repetitions, and an improvement frontier.
Synthetic fixture prompts are safe to retain; never use raw private conversations.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "behavior-cases.json"
HEX64 = re.compile(r"^[a-f0-9]{64}$")
DOMAINS = {"intent", "product_design", "bridge", "completion"}
ACTIONS = {"proceed", "reconstruct_then_proceed", "ask_one_question", "block"}
INDEPENDENCE = {"separate_context", "independent_model", "independent_human"}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    if path.is_symlink():
        raise ValueError(f"refusing symlinked path: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def meaningful(value: Any, minimum: int = 8) -> bool:
    return isinstance(value, str) and len(value.strip()) >= minimum


def case_errors(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["behavior suite must be an object"]
    if payload.get("schema_version") != 1 or payload.get("skill") != "selective-intelligence":
        errors.append("behavior suite identity is invalid")
    if not meaningful(payload.get("suite"), 3):
        errors.append("behavior suite name is required")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        return errors + ["behavior suite needs cases"]
    seen: set[str] = set()
    domains: set[str] = set()
    for index, case in enumerate(cases):
        path = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{path} must be an object")
            continue
        required = {
            "id", "domain", "risk", "minimum_repetitions", "worker_prompt",
            "expected_action", "required_invariants", "forbidden_invariants", "observable_outcome",
        }
        if set(case) != required:
            errors.append(f"{path} must use exact keys {sorted(required)}")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            errors.append(f"{path}.id must be unique")
        else:
            seen.add(case_id)
        if case.get("domain") not in DOMAINS:
            errors.append(f"{path}.domain is invalid")
        else:
            domains.add(case["domain"])
        if case.get("risk") not in {"low", "material", "high"}:
            errors.append(f"{path}.risk is invalid")
        if not isinstance(case.get("minimum_repetitions"), int) or case["minimum_repetitions"] < 2:
            errors.append(f"{path}.minimum_repetitions must be at least 2")
        if not meaningful(case.get("worker_prompt"), 40):
            errors.append(f"{path}.worker_prompt is too sparse")
        if case.get("expected_action") not in ACTIONS:
            errors.append(f"{path}.expected_action is invalid")
        if not meaningful(case.get("observable_outcome"), 20):
            errors.append(f"{path}.observable_outcome is too sparse")
        invariant_ids: set[str] = set()
        for group in ("required_invariants", "forbidden_invariants"):
            items = case.get(group)
            if not isinstance(items, list) or not items:
                errors.append(f"{path}.{group} must be non-empty")
                continue
            for item_index, item in enumerate(items):
                item_path = f"{path}.{group}[{item_index}]"
                if not isinstance(item, dict) or set(item) != {"id", "statement"}:
                    errors.append(f"{item_path} must contain id and statement")
                    continue
                if not isinstance(item.get("id"), str) or not item["id"] or item["id"] in invariant_ids:
                    errors.append(f"{item_path}.id must be unique within the case")
                else:
                    invariant_ids.add(item["id"])
                if not meaningful(item.get("statement"), 15):
                    errors.append(f"{item_path}.statement is too sparse")
    missing_domains = DOMAINS - domains
    if missing_domains:
        errors.append(f"behavior suite is missing domains: {sorted(missing_domains)}")
    return errors


def load_cases() -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[str]]:
    try:
        payload = load_json(CASES_PATH)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {}, {}, [f"cannot read behavior cases: {exc}"]
    errors = case_errors(payload)
    cases = {
        case["id"]: case
        for case in payload.get("cases", [])
        if isinstance(case, dict) and isinstance(case.get("id"), str)
    }
    return payload, cases, errors


def worker_view(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "suite": "selective-intelligence-behavior",
        "case_id": case["id"],
        "domain": case["domain"],
        "risk": case["risk"],
        "task": case["worker_prompt"],
        "output_contract": (
            "Return the outcome you would take, the understanding that governs it, the action or question you would use next, "
            "and the proof you would require. Do not assume that a polished or passing artifact is perfect."
        ),
        "case_digest": digest(case),
    }


def timestamp_valid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_run(payload: Any, cases: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["model run must be an object"]
    required = {"schema_version", "skill", "version", "model_client", "observed_at", "suite_digest", "result", "cases"}
    if set(payload) != required:
        errors.append(f"model run must use exact keys {sorted(required)}")
        return errors
    if payload.get("schema_version") != 2 or payload.get("skill") != "selective-intelligence":
        errors.append("model run identity is invalid")
    if not meaningful(payload.get("version"), 3) or not meaningful(payload.get("model_client"), 3):
        errors.append("model run version and model_client are required")
    if not timestamp_valid(payload.get("observed_at")):
        errors.append("model run observed_at must be timezone-aware")
    suite_payload = load_json(CASES_PATH)
    if payload.get("suite_digest") != digest(suite_payload):
        errors.append("model run suite_digest does not match current behavior cases")
    if payload.get("result") not in {"pass", "fail", "partial"}:
        errors.append("model run result is invalid")
    results = payload.get("cases")
    if not isinstance(results, list):
        return errors + ["model run cases must be an array"]
    seen: set[str] = set()
    any_failed = False
    for index, result in enumerate(results):
        path = f"cases[{index}]"
        if not isinstance(result, dict) or set(result) != {"id", "case_digest", "runs"}:
            errors.append(f"{path} must contain id, case_digest, and runs")
            continue
        case_id = result.get("id")
        if not isinstance(case_id, str) or case_id in seen or case_id not in cases:
            errors.append(f"{path}.id is duplicate or undeclared")
            continue
        seen.add(case_id)
        case = cases[case_id]
        if result.get("case_digest") != digest(case):
            errors.append(f"{path}.case_digest is stale")
        runs = result.get("runs")
        if not isinstance(runs, list) or len(runs) < case["minimum_repetitions"]:
            errors.append(f"{path}.runs needs at least {case['minimum_repetitions']} repetitions")
            continue
        repetition_ids: set[int] = set()
        expected_criteria = {
            item["id"] for item in case["required_invariants"] + case["forbidden_invariants"]
        }
        for run_index, run in enumerate(runs):
            run_path = f"{path}.runs[{run_index}]"
            run_keys = {"repetition", "worker_context_id", "worker_output", "output_sha256", "grader"}
            if not isinstance(run, dict) or set(run) != run_keys:
                errors.append(f"{run_path} must use exact run keys")
                continue
            repetition = run.get("repetition")
            if not isinstance(repetition, int) or repetition < 1 or repetition in repetition_ids:
                errors.append(f"{run_path}.repetition must be unique and positive")
            else:
                repetition_ids.add(repetition)
            output = run.get("worker_output")
            if not meaningful(output, 40):
                errors.append(f"{run_path}.worker_output is missing or too sparse")
            elif run.get("output_sha256") != text_digest(output):
                errors.append(f"{run_path}.output_sha256 does not match captured output")
            if not meaningful(run.get("worker_context_id"), 3):
                errors.append(f"{run_path}.worker_context_id is required")
            grader = run.get("grader")
            grader_keys = {"identity", "version", "context_id", "independence", "verdict", "criteria", "improvement_frontier"}
            if not isinstance(grader, dict) or set(grader) != grader_keys:
                errors.append(f"{run_path}.grader must use exact grader keys")
                continue
            if not all(meaningful(grader.get(key), 2) for key in ("identity", "version", "context_id")):
                errors.append(f"{run_path}.grader identity, version, and context are required")
            if grader.get("context_id") == run.get("worker_context_id"):
                errors.append(f"{run_path}.grader must use a distinct context")
            if grader.get("independence") not in INDEPENDENCE:
                errors.append(f"{run_path}.grader independence is invalid")
            if grader.get("verdict") not in {"pass", "fail"}:
                errors.append(f"{run_path}.grader verdict is invalid")
            if grader.get("verdict") == "fail":
                any_failed = True
            criteria = grader.get("criteria")
            if not isinstance(criteria, list):
                errors.append(f"{run_path}.grader.criteria must be an array")
                continue
            seen_criteria: set[str] = set()
            criterion_failed = False
            for criterion_index, criterion in enumerate(criteria):
                criterion_path = f"{run_path}.grader.criteria[{criterion_index}]"
                if not isinstance(criterion, dict) or set(criterion) != {"id", "verdict", "evidence"}:
                    errors.append(f"{criterion_path} must contain id, verdict, and evidence")
                    continue
                criterion_id = criterion.get("id")
                if criterion_id not in expected_criteria or criterion_id in seen_criteria:
                    errors.append(f"{criterion_path}.id is duplicate or unexpected")
                else:
                    seen_criteria.add(criterion_id)
                if criterion.get("verdict") not in {"pass", "fail"}:
                    errors.append(f"{criterion_path}.verdict is invalid")
                elif criterion["verdict"] == "fail":
                    criterion_failed = True
                    any_failed = True
                if not meaningful(criterion.get("evidence"), 12):
                    errors.append(f"{criterion_path}.evidence must explain the observed output or absence")
            missing = sorted(expected_criteria - seen_criteria)
            if missing:
                errors.append(f"{run_path}.grader.criteria is missing {missing}")
            if criterion_failed and grader.get("verdict") != "fail":
                errors.append(f"{run_path}.grader verdict must fail when a criterion fails")
            frontier = grader.get("improvement_frontier")
            if not isinstance(frontier, list) or not frontier or any(not meaningful(item, 8) for item in frontier):
                errors.append(f"{run_path}.grader.improvement_frontier must retain at least one material next challenge")
    missing_cases = sorted(set(cases) - seen)
    if missing_cases:
        errors.append(f"model run is missing declared behavior cases: {missing_cases}")
    if payload.get("result") == "pass" and (any_failed or errors):
        errors.append("model run cannot report pass with failed criteria or structural errors")
    if payload.get("result") == "fail" and not any_failed:
        errors.append("model run reports fail without a failed graded criterion")
    return errors


def command_doctor(args: argparse.Namespace) -> int:
    payload, cases, errors = load_cases()
    result = {
        "valid": not errors,
        "case_count": len(cases),
        "domains": sorted({case["domain"] for case in cases.values()}),
        "suite_digest": digest(payload) if payload else None,
        "execution_status": "behavior_cases_declared_not_executed",
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 1 if errors else 0


def command_worker_packet(args: argparse.Namespace) -> int:
    _, cases, errors = load_cases()
    if errors:
        print(json.dumps({"errors": errors}, indent=2), file=sys.stderr)
        return 1
    case = cases.get(args.case)
    if case is None:
        print(f"unknown case: {args.case}", file=sys.stderr)
        return 2
    print(json.dumps(worker_view(case), indent=2))
    return 0


def command_validate_run(args: argparse.Namespace) -> int:
    _, cases, case_load_errors = load_cases()
    if case_load_errors:
        print(json.dumps({"valid": False, "errors": case_load_errors}, indent=2))
        return 1
    try:
        payload = load_json(Path(args.path))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
        return 1
    errors = validate_run(payload, cases)
    print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
    return 1 if errors else 0


def command_self_test(args: argparse.Namespace) -> int:
    suite, cases, errors = load_cases()
    if errors:
        print(json.dumps({"passed": False, "errors": errors}, indent=2))
        return 1
    case = next(iter(cases.values()))
    criteria = [
        {"id": item["id"], "verdict": "pass", "evidence": f"Synthetic structural evidence for {item['id']}."}
        for item in case["required_invariants"] + case["forbidden_invariants"]
    ]
    output = "Synthetic captured worker output used only to validate behavior evidence structure and digest enforcement."
    runs = []
    for repetition in range(1, case["minimum_repetitions"] + 1):
        runs.append({
            "repetition": repetition,
            "worker_context_id": f"worker-{repetition}",
            "worker_output": output,
            "output_sha256": text_digest(output),
            "grader": {
                "identity": "structural-self-test-grader",
                "version": "v1",
                "context_id": f"grader-{repetition}",
                "independence": "separate_context",
                "verdict": "pass",
                "criteria": copy.deepcopy(criteria),
                "improvement_frontier": ["Semantic correctness still requires an independent behavior grader."],
            },
        })
    run = {
        "schema_version": 2,
        "skill": "selective-intelligence",
        "version": "self-test",
        "model_client": "structural-fixture",
        "observed_at": "2026-01-01T00:00:00Z",
        "suite_digest": digest(suite),
        "result": "partial",
        "cases": [{"id": case["id"], "case_digest": digest(case), "runs": runs}],
    }
    partial_errors = validate_run(run, {case["id"]: case})
    broken = copy.deepcopy(run)
    broken["cases"][0]["runs"][0]["worker_output"] = (
        "Changed captured worker output that is intentionally long enough while retaining the stale digest."
    )
    broken_errors = validate_run(broken, {case["id"]: case})
    passed = not partial_errors and any("output_sha256" in error for error in broken_errors)
    print(json.dumps({
        "passed": passed,
        "checks": [
            "valid evidence-bearing partial run accepted",
            "captured output digest mismatch rejected",
            "worker view excludes hidden oracle",
        ],
        "worker_view_keys": sorted(worker_view(case)),
        "hidden_oracle_exposed": any(key in worker_view(case) for key in ("required_invariants", "forbidden_invariants", "observable_outcome")),
        "errors": partial_errors if partial_errors else [],
    }, indent=2))
    return 0 if passed and not any(key in worker_view(case) for key in ("required_invariants", "forbidden_invariants", "observable_outcome")) else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Selective Intelligence behavior evidence controls")
    commands = root.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor")
    doctor.set_defaults(func=command_doctor)
    packet = commands.add_parser("worker-packet")
    packet.add_argument("--case", required=True)
    packet.set_defaults(func=command_worker_packet)
    validate = commands.add_parser("validate-run")
    validate.add_argument("--path", required=True)
    validate.set_defaults(func=command_validate_run)
    self_test = commands.add_parser("self-test")
    self_test.set_defaults(func=command_self_test)
    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
