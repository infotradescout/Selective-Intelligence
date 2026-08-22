#!/usr/bin/env python3
"""Verify that the generated ChatGPT adapter is complete and storeable."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_ROOT = REPO_ROOT / "adapters" / "chatgpt" / "selective-intelligence"
ADAPTER_METADATA = REPO_ROOT / "adapters" / "chatgpt" / "metadata" / "chatgpt-adapter.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    files = sorted(path.relative_to(ADAPTER_ROOT).as_posix() for path in ADAPTER_ROOT.rglob("*") if path.is_file())
    skill_entrypoints = [path for path in files if Path(path).name == "SKILL.md"]
    require(skill_entrypoints == ["SKILL.md"], f"expected one SKILL.md, found {skill_entrypoints}")
    require(len(files) <= 50, f"runtime adapter is bloated: {len(files)} files")
    require("scripts/project_index.py" in files, "project index tool is missing")
    require("references/project-index-and-reuse-gate.md" in files, "project index reference is missing")
    version = (ADAPTER_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    require(version == "1.0.5", f"unexpected runtime adapter version: {version}")
    require(ADAPTER_METADATA.is_file(), "repository adapter projection manifest is missing")
    projection = json.loads(ADAPTER_METADATA.read_text(encoding="utf-8"))
    require(projection.get("version") == version, "adapter projection manifest version drift")
    require(projection.get("runtime_file_count") == len(files), "adapter projection file count drift")
    require(
        projection.get("portable_source_path") == "skills/selective-intelligence"
        and projection.get("adapter_path") == "adapters/chatgpt/selective-intelligence",
        "adapter projection roots are invalid",
    )
    require("evals/evals.json" in files, "runtime behavior declarations are missing")
    require("subskills/si-worker/ROLE.md" in files, "Worker role reference is missing")
    require(not any("subskills/" in path and path.endswith("/SKILL.md") for path in files), "nested SKILL.md remains")
    role_refs = [path for path in files if path.startswith("subskills/") and path.endswith("/ROLE.md")]
    require(len(role_refs) == 7, f"expected seven Council role references, found {len(role_refs)}")
    require(not any(path.startswith("tests/") for path in files), "repository tests leaked into runtime adapter")
    require(not any(path.startswith("evals/results-") for path in files), "historical results leaked into runtime adapter")
    for excluded in ("AI-GUIDE.md", "CHANGELOG.md", "JUMPSTART.md", "LICENSE", "README.md", "scripts/release.py"):
        require(excluded not in files, f"repository-only file leaked into runtime adapter: {excluded}")

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

    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in ADAPTER_ROOT.rglob("*")
        if path.is_file()
    )
    require("MealScout" not in combined and "TradeScout" not in combined, "product-specific brand leaked into adapter")
    active_contracts = [
        "SKILL.md",
        "references/activation-and-adoption.md",
        "subskills/si-intake/ROLE.md",
    ]
    for relative in active_contracts:
        content = (ADAPTER_ROOT / relative).read_text(encoding="utf-8")
        require(
            "What outcome do you want to create or complete?" not in content,
            f"obsolete trigger handoff leaked into active adapter contract: {relative}",
        )

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

    for relative in files:
        if relative.endswith(".py"):
            ast.parse((ADAPTER_ROOT / relative).read_text(encoding="utf-8"), filename=relative)

    command = [sys.executable, str(ADAPTER_ROOT / "scripts" / "project_index.py"), "self-test"]
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    require(completed.returncode == 0, completed.stdout + completed.stderr)

    print(json.dumps({"status": "pass", "files": len(files), "skill_entrypoints": skill_entrypoints}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
