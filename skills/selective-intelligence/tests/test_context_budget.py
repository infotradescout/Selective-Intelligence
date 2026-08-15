from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS = TEST_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

import context_budget as CB


class ContextBudgetTests(unittest.TestCase):
    def test_relevant_file_beats_alphabetical_filler(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "aaa_notes.txt").write_text("unrelated notes", encoding="utf-8")
            (root / "zzz_mobile_menu.py").write_text("def open_mobile_menu(): return True", encoding="utf-8")
            result = CB.select_context(root, objective="Fix the broken mobile menu", max_files=1)
        self.assertEqual([item["path"] for item in result["selected"]], ["zzz_mobile_menu.py"])
        self.assertGreater(result["estimatedTokens"]["avoided"], 0)

    def test_explicit_acceptance_reference_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "menu.py").write_text("mobile menu mobile menu mobile menu", encoding="utf-8")
            (root / "contract.md").write_text("Acceptance contract", encoding="utf-8")
            result = CB.select_context(
                root,
                objective="Fix the mobile menu",
                acceptance_refs=["contract.md"],
                max_files=1,
            )
        self.assertEqual(result["selected"][0]["path"], "contract.md")
        self.assertEqual(result["selected"][0]["selectionReason"], "explicit acceptance reference")

    def test_secrets_private_feedback_and_hard_budgets_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".env").write_text("API_KEY=not-for-context", encoding="utf-8")
            feedback = root / ".selective-intelligence" / "feedback"
            feedback.mkdir(parents=True)
            (feedback / "events.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "one.txt").write_text("target " * 4, encoding="utf-8")
            (root / "two.txt").write_text("target " * 4, encoding="utf-8")
            result = CB.select_context(root, objective="target", max_files=1, max_bytes=30, max_file_bytes=30)
        selected = result["selected"]
        excluded = {item["path"]: item["reason"] for item in result["excluded"]}
        self.assertEqual(len(selected), 1)
        self.assertLessEqual(result["budget"]["usedBytes"], 30)
        self.assertIn(".env", excluded)
        self.assertEqual(excluded[".selective-intelligence/feedback/events.jsonl"], "private feedback store excluded")
        self.assertRegex(result["contextDigest"], r"^[a-f0-9]{64}$")
        self.assertEqual(result["estimatedTokens"]["selected"], selected[0]["estimatedTokens"])

    def test_common_credential_shapes_never_enter_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            credentials = {
                "aws.txt": "AWS_ACCESS_KEY_ID=" + "AKIA" + ("A" * 16),
                "bearer.txt": "Authorization" + ": " + "Bearer " + ("a" * 26),
                "github.txt": "token=" + "ghp_" + ("A" * 30),
                "fine-grained.txt": "github_" + "pat_" + ("A" * 30),
                "jwt.txt": "eyJ" + ("A" * 11) + "." + "eyJ" + ("B" * 11) + "." + ("C" * 11),
            }
            for name, value in credentials.items():
                (root / name).write_text(value, encoding="utf-8")
            (root / "safe.txt").write_text("target implementation", encoding="utf-8")
            result = CB.select_context(root, objective="target")
        self.assertEqual([item["path"] for item in result["selected"]], ["safe.txt"])
        excluded = {item["path"]: item["reason"] for item in result["excluded"]}
        for name in credentials:
            self.assertEqual(excluded[name], "potential secret content")

    def test_local_dependency_closure_preserves_the_outcome_or_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helpers = root / "helpers"
            helpers.mkdir()
            (root / "app.py").write_text(
                "from helpers.price import format_price\n\ndef checkout_total(value):\n    return format_price(value)\n",
                encoding="utf-8",
            )
            (helpers / "price.py").write_text(
                "def format_price(value):\n    return f'${value:.2f}'\n",
                encoding="utf-8",
            )
            complete = CB.select_context(root, objective="Fix checkout total in app.py", max_files=2)
            incomplete = CB.select_context(root, objective="Fix checkout total in app.py", max_files=1)
        self.assertEqual([item["path"] for item in complete["selected"]], ["app.py", "helpers/price.py"])
        self.assertTrue(complete["outcomeCoverage"]["complete"])
        self.assertIn("local dependency", complete["selected"][1]["selectionReason"])
        self.assertFalse(incomplete["outcomeCoverage"]["complete"])
        self.assertEqual(incomplete["outcomeCoverage"]["unresolvedPaths"], ["helpers/price.py"])


if __name__ == "__main__":
    unittest.main()
