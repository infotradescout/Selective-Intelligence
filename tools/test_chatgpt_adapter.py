#!/usr/bin/env python3
"""Verify that the generated ChatGPT adapter is complete and storeable."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_ROOT = REPO_ROOT / "adapters" / "chatgpt" / "selective-intelligence"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    files = sorted(path.relative_to(ADAPTER_ROOT).as_posix() for path in ADAPTER_ROOT.rglob("*") if path.is_file())
    skill_entrypoints = [path for path in files if Path(path).name == "SKILL.md"]
    require(skill_entrypoints == ["SKILL.md"], f"expected one SKILL.md, found {skill_entrypoints}")
    require("scripts/project_index.py" in files, "project index tool is missing")
    require("references/project-index-and-reuse-gate.md" in files, "project index reference is missing")
    require("evals/results-0.4.0.json" in files, "0.4.0 evidence is missing")
    require("subskills/si-worker/ROLE.md" in files, "Worker role reference is missing")
    require(not any("subskills/" in path and path.endswith("/SKILL.md") for path in files), "nested SKILL.md remains")

    adapter_metadata = json.loads((ADAPTER_ROOT / "metadata" / "chatgpt-adapter.json").read_text(encoding="utf-8"))
    require(adapter_metadata["behavioral_contract"] == "preserved", "adapter contract is not preserved")
    require(len(adapter_metadata["role_path_map"]) == 7, "not all Council roles were adapted")

    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in ADAPTER_ROOT.rglob("*")
        if path.is_file()
    )
    require("MealScout" not in combined and "TradeScout" not in combined, "product-specific brand leaked into adapter")
    active_contracts = [
        "SKILL.md",
        "JUMPSTART.md",
        "README.md",
        "references/activation-and-adoption.md",
        "subskills/si-intake/ROLE.md",
    ]
    for relative in active_contracts:
        content = (ADAPTER_ROOT / relative).read_text(encoding="utf-8")
        require(
            "What outcome do you want to create or complete?" not in content,
            f"obsolete trigger handoff leaked into active adapter contract: {relative}",
        )

    commands = [
        [sys.executable, str(ADAPTER_ROOT / "scripts" / "project_index.py"), "self-test"],
        [sys.executable, str(ADAPTER_ROOT / "scripts" / "behavior_eval.py"), "self-test"],
        [sys.executable, "-m", "unittest", "discover", "-s", str(ADAPTER_ROOT / "tests"), "-p", "test_*.py"],
        [sys.executable, str(ADAPTER_ROOT / "scripts" / "eval.py"), "controls", "--skip-release"],
        [sys.executable, str(ADAPTER_ROOT / "scripts" / "release.py"), "doctor"],
    ]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=ADAPTER_ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"adapter validation failed: {' '.join(command)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )

    print(json.dumps({"status": "pass", "files": len(files), "skill_entrypoints": skill_entrypoints}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
