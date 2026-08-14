#!/usr/bin/env python3
"""Regression checks for repository-native Selective Intelligence pointers."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPROVAL = "Use Selective Intelligence for this?"


class NativePointerTests(unittest.TestCase):
    def test_generated_pointers_are_current(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_native_pointers.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pointer_preserves_identity_and_approval_boundary(self) -> None:
        source = (ROOT / "adapters" / "repository-pointer.md").read_text(encoding="utf-8")
        self.assertEqual((ROOT / "AGENTS.md").read_text(encoding="utf-8"), source)
        self.assertEqual((ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8"), source)
        self.assertIn("`Selective Intelligence`", source)
        self.assertIn(APPROVAL, source)
        self.assertIn("not user approval", source)
        self.assertIn("cannot approve adoption", source)
        self.assertIn("skills/selective-intelligence/SKILL.md", source)
        self.assertIn("the user has already activated it", source)
        self.assertIn("Do not ask `Use Selective Intelligence for this?`", source)
        self.assertIn("the entire first response must be exactly two paragraphs", source)
        self.assertIn("Stop there", source)

    def test_canonical_skill_enforces_the_same_first_response_gate(self) -> None:
        skill = (ROOT / "skills" / "selective-intelligence" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("before using any Selective Intelligence doctrine", skill)
        self.assertIn("Never ask `Use Selective Intelligence for this?` after a direct trigger", skill)
        self.assertIn("The entire response must then be exactly two paragraphs", skill)
        self.assertIn("Do not apply the doctrine", skill)
        self.assertIn("they are never user approval", skill)
        self.assertIn("never call it “full operational authority.”", skill)
        self.assertIn("is a resolution source, not the person's active project", skill)
        self.assertIn("Selective Intelligence is active. No project or prior outcome is available", skill)

    def test_thin_client_files_reference_the_canonical_pointer(self) -> None:
        self.assertEqual((ROOT / "CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")
        self.assertEqual((ROOT / "GEMINI.md").read_text(encoding="utf-8"), "@./AGENTS.md\n")
        cursor = (ROOT / ".cursor" / "rules" / "selective-intelligence.mdc").read_text(encoding="utf-8")
        self.assertIn("alwaysApply: true", cursor)
        self.assertIn("@../../AGENTS.md", cursor)
        self.assertLess(len(cursor.splitlines()), 12)

    def test_supported_repository_clients_have_real_pointer_files(self) -> None:
        registry = json.loads((ROOT / "adapters" / "client-support.json").read_text(encoding="utf-8"))
        clients = {client["id"]: client for client in registry["clients"]}
        for client_id in {"codex", "github-copilot", "claude-code", "cursor", "gemini-cli", "kiro"}:
            pointer = clients[client_id]["repository_pointer"]
            self.assertTrue(pointer)
            self.assertTrue((ROOT / pointer).is_file(), f"missing {client_id} pointer: {pointer}")
        self.assertIsNone(clients["chatgpt"]["repository_pointer"])
        self.assertIsNone(clients["web-ai"]["repository_pointer"])


if __name__ == "__main__":
    unittest.main()
