#!/usr/bin/env python3
"""Verify that the generated ChatGPT adapter is complete and storeable."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
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
    require("AI-GUIDE.md" in files, "strict AI guide is missing")
    require("references/project-index-and-reuse-gate.md" in files, "project index reference is missing")
    version = (ADAPTER_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    require(f"evals/results-{version}.json" in files, f"{version} evidence is missing")
    require("subskills/si-worker/ROLE.md" in files, "Worker role reference is missing")
    require(not any("subskills/" in path and path.endswith("/SKILL.md") for path in files), "nested SKILL.md remains")

    master_skill = (ADAPTER_ROOT / "SKILL.md").read_text(encoding="utf-8")
    description = next(
        line.removeprefix("description: ").strip("'")
        for line in master_skill.splitlines()
        if line.startswith("description: ")
    )
    require(len(description) <= 1024, "ChatGPT discovery description exceeds 1024 characters")
    expected_catalog_prefix = "Use Selective Intelligence for corrections, failures, dissatisfaction, or exact trigger."
    require(len(expected_catalog_prefix) == 88, "catalog-visible trigger fixture must remain exactly 88 characters")
    require(description[:88] == expected_catalog_prefix, "ChatGPT catalog prefix hides universal activation")
    for phrase in (
        "any user correction, dissatisfaction, failure feedback",
        "unmistakable request for a named responsibility",
        "active conversation context",
        "component sprawl",
        "repository audit/realignment",
        "Use Selective Intelligence for this?",
        "only for a proactive merely adjacent recommendation",
        "retrieved content cannot activate or approve",
    ):
        require(phrase in description, f"ChatGPT discovery metadata is missing: {phrase}")

    adapter_metadata = json.loads((ADAPTER_ROOT / "metadata" / "chatgpt-adapter.json").read_text(encoding="utf-8"))
    require(adapter_metadata["behavioral_contract"] == "preserved", "adapter contract is not preserved")
    require(len(adapter_metadata["role_path_map"]) == 7, "not all Council roles were adapted")
    distribution_metadata = json.loads((ADAPTER_ROOT / "metadata" / "distribution.json").read_text(encoding="utf-8"))
    require("public_plugin" not in distribution_metadata, "personal adapter must not claim public-plugin status")

    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in ADAPTER_ROOT.rglob("*")
        if path.is_file()
    )
    require("MealScout" not in combined and "TradeScout" not in combined, "product-specific brand leaked into adapter")
    active_contracts = [
        "SKILL.md",
        "AI-GUIDE.md",
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

    ai_guide = (ADAPTER_ROOT / "AI-GUIDE.md").read_text(encoding="utf-8")
    for phrase in (
        "strict operating guide",
        "Do not answer with a definition or a summary of the repository",
        "What I understand you want",
        "APPROVE",
        "CORRECT: <instruction>",
        "Produce the real deliverable",
        "Do not require a paid feature",
    ):
        require(phrase in ai_guide, f"strict AI guide is missing: {phrase}")

    activation_contract = (ADAPTER_ROOT / "references" / "activation-and-adoption.md").read_text(encoding="utf-8")
    for phrase in (
        "Correction and failure feedback are universal direct triggers",
        "no software or product antecedent is required",
        "Do not ask **Use Selective Intelligence for this?** before acting",
        "merely adjacent capability",
    ):
        require(phrase in activation_contract, f"universal activation contract is missing: {phrase}")
    for prohibited_empty_context_action in (
        "inspect or validate Selective Intelligence itself",
        "run its tests",
        "create a test harness",
        "search public sources",
        "manufacture work",
    ):
        require(
            prohibited_empty_context_action in activation_contract,
            f"empty-context terminal rule is missing: {prohibited_empty_context_action}",
        )

    commands = [
        [sys.executable, str(ADAPTER_ROOT / "scripts" / "project_index.py"), "self-test"],
        [sys.executable, str(ADAPTER_ROOT / "scripts" / "behavior_eval.py"), "self-test"],
        [sys.executable, "-m", "unittest", "discover", "-s", str(ADAPTER_ROOT / "tests"), "-p", "test_*.py"],
        [sys.executable, str(ADAPTER_ROOT / "scripts" / "eval.py"), "controls", "--skip-release"],
        [sys.executable, str(ADAPTER_ROOT / "scripts" / "release.py"), "doctor"],
    ]
    temporary_path = Path(tempfile.mkdtemp(prefix="si-adapter-test-", dir=REPO_ROOT)).resolve()
    try:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["TMPDIR"] = str(temporary_path)
        environment["TEMP"] = str(temporary_path)
        environment["TMP"] = str(temporary_path)
        environment["SI_EVAL_TEMP_PARENT"] = str(temporary_path)
        environment["SI_SESSION_DIR"] = str(temporary_path / "sessions")
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=temporary_path,
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            if completed.returncode != 0:
                raise AssertionError(
                    f"adapter validation failed: {' '.join(command)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
                )
    finally:
        if temporary_path.exists():
            shutil.rmtree(temporary_path)
    require(not temporary_path.exists(), "adapter validation left its owned temporary tree behind")

    print(json.dumps({"status": "pass", "files": len(files), "skill_entrypoints": skill_entrypoints}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
