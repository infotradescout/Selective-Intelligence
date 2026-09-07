#!/usr/bin/env python3
"""Generate thin repository-native pointers to the one canonical skill."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "adapters" / "repository-pointer.md"


def outputs() -> dict[Path, str]:
    pointer = SOURCE.read_text(encoding="utf-8")
    skill_root = ROOT / "skills" / "selective-intelligence"
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    guide_path = skill_root / "AI-GUIDE.md"
    guide = guide_path.read_text(encoding="utf-8")
    sections = []
    for title in ("Authority and source routing", "Delivery states", "Product identity before templates", "SI defects and cold starts"):
        match = re.search(rf"^## {re.escape(title)}\n.*?(?=^## |\Z)", skill, re.M | re.S)
        if match is None:
            raise ValueError(f"canonical bootstrap section is missing: {title}")
        sections.append(match.group().strip())
    begin = "<!-- SELECTIVE_INTELLIGENCE_BOOTSTRAP_PROJECTION_BEGIN -->"
    end = "<!-- SELECTIVE_INTELLIGENCE_BOOTSTRAP_PROJECTION_END -->"
    if guide.count(begin) != 1 or guide.count(end) != 1:
        raise ValueError("strict guide requires one canonical bootstrap projection")
    guide = re.sub(re.escape(begin) + r".*?" + re.escape(end),
                   lambda _: begin + "\n\n" + "\n\n".join(sections) + "\n\n" + end,
                   guide, flags=re.S)
    return {
        guide_path: guide,
        ROOT / "AGENTS.md": pointer,
        ROOT / ".github" / "copilot-instructions.md": pointer,
        ROOT / "CLAUDE.md": "@AGENTS.md\n",
        ROOT / "GEMINI.md": "@./AGENTS.md\n",
        ROOT / ".cursor" / "rules" / "selective-intelligence.mdc": (
            "---\n"
            "description: Resolve the canonical Selective Intelligence skill and preserve its activation boundary.\n"
            "alwaysApply: true\n"
            "---\n\n"
            "@../../AGENTS.md\n"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated pointers are stale")
    args = parser.parse_args()
    stale: list[str] = []
    for path, content in outputs().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(ROOT).as_posix())
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    if stale:
        print("Native pointers are stale: " + ", ".join(stale))
        return 1
    print("Native pointers are current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
