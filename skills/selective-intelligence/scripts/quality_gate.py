#!/usr/bin/env python3
"""Run SI source protection, or explicit product-delivery acceptance.

A passing source gate is not evidence that a user's product is ready.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
SKILL_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = SKILL_ROOT.parents[1]


def _run(name: str, argv: list[str]) -> dict[str, Any]:
    proc = subprocess.run(argv, cwd=SKILL_ROOT, capture_output=True, text=True, check=False)
    output = (proc.stdout + proc.stderr).encode("utf-8", errors="replace")
    return {"name": name, "passed": proc.returncode == 0, "exitCode": proc.returncode,
            "outputSha256": hashlib.sha256(output).hexdigest(), "outputBytes": len(output)}


def _source_identity() -> dict[str, Any]:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT,
                          capture_output=True, text=True, check=False)
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=REPOSITORY_ROOT, capture_output=True, check=False)
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"],
                            cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False)
    if listed.returncode == 0:
        relative_paths = [Path(value.decode("utf-8")) for value in listed.stdout.split(b"\0") if value]
        root = REPOSITORY_ROOT
    else:
        relative_paths = [path.relative_to(SKILL_ROOT) for path in SKILL_ROOT.rglob("*") if path.is_file()]
        root = SKILL_ROOT
    records: list[dict[str, Any]] = []
    for relative in sorted(relative_paths, key=lambda value: value.as_posix()):
        normalized = relative.as_posix()
        if normalized.startswith((".selective-intelligence/", "artifacts/release/")):
            continue
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        records.append({"path": normalized, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    snapshot = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"gitHead": head.stdout.strip() if head.returncode == 0 else None,
            "workingTreeDirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
            "sourceSnapshotSha256": hashlib.sha256(snapshot).hexdigest(), "sourceFileCount": len(records)}


def run_gate() -> dict[str, Any]:
    py = sys.executable
    scripts = SKILL_ROOT / "scripts"
    tests = SKILL_ROOT / "tests"
    checks = [
        _run("deterministic_controls", [py, "-B", str(scripts / "eval.py"), "controls", "--json", "--skip-release"]),
        _run("council_safeguards", [py, "-B", str(scripts / "council.py"), "self-test"]),
        _run("behavior_evidence_safeguards", [py, "-B", str(scripts / "behavior_eval.py"), "self-test"]),
        _run("unit_tests", [py, "-B", "-m", "unittest", "discover", "-s", str(tests), "-p", "test_*.py"]),
        _run("release_integrity", [py, "-B", str(scripts / "release.py"), "doctor", "--json"]),
    ]
    return {"schemaVersion": "si.quality_gate.v1", "observedAt": datetime.now(UTC).isoformat(),
            "sourceIdentity": _source_identity(), "paidServiceRequired": False,
            "passed": all(check["passed"] for check in checks), "checks": checks,
            "productDelivery": "not_evaluated",
            "boundary": "local deterministic source protection; product acceptance and hosted enforcement are separate"}


def run_delivery(contract: Path, evidence: Path, artifact_root: Path) -> dict[str, Any]:
    # Use one canonical evaluator. Do not duplicate a weaker check in an adapter.
    from delivery_acceptance import evaluate, read_json
    return evaluate(read_json(contract), read_json(evidence), artifact_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    parser.add_argument("--delivery", action="store_true", help="Evaluate the product, not SI source tests")
    parser.add_argument("--contract")
    parser.add_argument("--evidence")
    parser.add_argument("--artifact-root")
    args = parser.parse_args()
    supplied = (args.contract, args.evidence, args.artifact_root)
    if (args.delivery and not all(supplied)) or (not args.delivery and any(supplied)):
        parser.error("Product acceptance requires --delivery, --contract, --evidence and --artifact-root together")
    try:
        result = run_delivery(*(Path(value) for value in supplied)) if args.delivery else run_gate()
    except (ValueError, OSError, TypeError) as exc:
        result = {"passed": False, "verdict": "needs_repair", "error": str(exc)}
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
