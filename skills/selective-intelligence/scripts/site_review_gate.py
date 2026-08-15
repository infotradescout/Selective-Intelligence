#!/usr/bin/env python3
"""Validate the evidence receipt for a rendered website review.

This gate makes a human veto and Product Design Objector findings fail closed.
It validates the review evidence; it does not pretend JSON can judge an image.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DIMENSIONS = {
    "comprehension",
    "hierarchy",
    "restraint",
    "coherence",
    "distinctiveness",
    "density",
    "mobile_composition",
    "trust",
}

GENERIC_SIGNALS = {
    "interchangeable_brand",
    "unjustified_template_structure",
    "decoration_over_meaning",
    "desktop_stack_on_mobile",
    "copy_compensates_for_weak_design",
}


def _safe_render(review_path: Path, value: Any) -> tuple[bool, str]:
    if not isinstance(value, str) or not value.strip():
        return False, "render path is missing"
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False, "render path must be relative and cannot traverse upward"
    resolved = (review_path.parent / candidate).resolve()
    base = review_path.parent.resolve()
    if resolved != base and base not in resolved.parents:
        return False, "render path escapes the evidence directory"
    if not resolved.is_file() or resolved.stat().st_size == 0:
        return False, f"render is missing or empty: {value}"
    return True, value


def review_gate(review_path: Path) -> dict[str, Any]:
    review_path = review_path.resolve()
    try:
        data = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schemaVersion": "si.site_review_gate.v1",
            "passed": False,
            "review": review_path.name,
            "errors": [f"review receipt is unreadable ({type(exc).__name__})"],
        }

    errors: list[str] = []
    if data.get("schemaVersion") != "si.site_review.v1":
        errors.append("schemaVersion must be si.site_review.v1")
    if data.get("humanVeto") is True:
        errors.append("human veto is present")

    renders = data.get("renders") if isinstance(data.get("renders"), dict) else {}
    render_evidence: dict[str, str] = {}
    for viewport in ("mobile", "desktop"):
        passed, detail = _safe_render(review_path, renders.get(viewport))
        if not passed:
            errors.append(f"{viewport}: {detail}")
        else:
            render_evidence[viewport] = detail

    if data.get("primaryJourney") != "pass":
        errors.append("primaryJourney must pass")

    objector = data.get("objector") if isinstance(data.get("objector"), dict) else {}
    if objector.get("independent") is not True:
        errors.append("Product Design Objector must be independent")
    if objector.get("verdict") != "strong_checkpoint":
        errors.append("Product Design Objector verdict must be strong_checkpoint")
    findings = objector.get("blockingFindings")
    if not isinstance(findings, list) or findings:
        errors.append("blockingFindings must be an empty list")

    dimensions = data.get("dimensions") if isinstance(data.get("dimensions"), dict) else {}
    for name in sorted(DIMENSIONS):
        if dimensions.get(name) != "pass":
            errors.append(f"dimension did not pass: {name}")

    signals = data.get("genericSignals") if isinstance(data.get("genericSignals"), dict) else {}
    for name in sorted(GENERIC_SIGNALS):
        if signals.get(name) is not False:
            errors.append(f"generic-template signal not cleared: {name}")

    return {
        "schemaVersion": "si.site_review_gate.v1",
        "passed": not errors,
        "review": review_path.name,
        "renders": render_evidence,
        "errors": errors,
        "boundary": "Validates a rendered-review receipt; it does not independently judge image quality.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail closed on weak or rejected website-review evidence")
    parser.add_argument("review")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = review_gate(Path(args.review))
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
