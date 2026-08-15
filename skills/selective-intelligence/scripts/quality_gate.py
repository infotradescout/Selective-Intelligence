#!/usr/bin/env python3
"""Run the complete local, no-paid SI change gate with one command."""
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
    return {
        "name": name,
        "passed": proc.returncode == 0,
        "exitCode": proc.returncode,
        "outputSha256": hashlib.sha256(output).hexdigest(),
        "outputBytes": len(output),
    }


def _source_identity() -> dict[str, Any]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
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
        records.append(
            {
                "path": normalized,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    snapshot = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "gitHead": head.stdout.strip() if head.returncode == 0 else None,
        "workingTreeDirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
        "sourceSnapshotSha256": hashlib.sha256(snapshot).hexdigest(),
        "sourceFileCount": len(records),
    }


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
    return {
        "schemaVersion": "si.quality_gate.v1",
        "observedAt": datetime.now(UTC).isoformat(),
        "sourceIdentity": _source_identity(),
        "paidServiceRequired": False,
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "boundary": "local deterministic protection; hosted branch enforcement is separate external state",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all portable SI change protections locally")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = run_gate()
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
