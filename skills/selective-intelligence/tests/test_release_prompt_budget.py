from __future__ import annotations

import sys
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SKILL_ROOT = TEST_DIR.parent
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import release  # noqa: E402


class ReleasePromptBudgetTests(unittest.TestCase):
    def test_all_skill_frontmatter_uses_supported_loader_fields_only(self):
        metadata, metadata_errors = release.read_distribution_metadata(SKILL_ROOT)
        self.assertEqual(metadata_errors, [])
        self.assertIsNotNone(metadata)
        files, file_errors = release.release_files(SKILL_ROOT, metadata)
        self.assertEqual(file_errors, [])
        self.assertEqual(release.skill_loader_metadata_errors(SKILL_ROOT, files), [])

    def test_canonical_skill_fits_tight_lean_budget(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        metrics, errors = release.prompt_budget_errors(skill_text)
        self.assertEqual(errors, [])
        self.assertLessEqual(metrics["core_words"], 1_100)
        self.assertLessEqual(metrics["core_characters"], 10_000)
        self.assertLessEqual(metrics["core_words"], release.CORE_SKILL_MAX_WORDS)
        self.assertLessEqual(metrics["core_characters"], release.CORE_SKILL_MAX_CHARACTERS)

    def test_rejects_heavy_default_regression(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        _, errors = release.prompt_budget_errors(
            skill_text + "\nUse these seven small passes in sequence.\n"
        )
        self.assertTrue(any("forbidden heavy default" in error for error in errors))

    def test_rejects_missing_lean_contract(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        skill_text = skill_text.replace("Lean execution is the default", "Execution")
        _, errors = release.prompt_budget_errors(skill_text)
        self.assertTrue(any("missing lean execution contract" in error for error in errors))

    def test_rejects_paraphrased_automatic_role_default(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        _, errors = release.prompt_budget_errors(
            skill_text
            + "\nAutomatically spawn Worker, Objector, and Aligner agents for persistent work.\n"
        )
        self.assertTrue(any("automatic multi-role execution" in error for error in errors))

    def test_rejects_approval_before_every_local_edit(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        _, errors = release.prompt_budget_errors(
            skill_text + "\nBefore every local edit, require an approval checkpoint.\n"
        )
        self.assertTrue(
            any("approval checkpoint before every harmless mutation" in error for error in errors)
        )

    def test_whole_run_usage_governor_is_core_behavior(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "Whole-run usage governor",
            "Token efficiency governs the entire run, not only startup.",
            "at most 12 text files or 64 KB",
            "After three search batches",
            "No duplicate crawls",
            "bundled checkpoint helper must open a usage ledger",
            "a fourth batch",
        ):
            self.assertIn(phrase, skill_text)

    def test_progress_checkpoint_is_distinct_and_non_blocking(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "Two checkpoint types — never confuse them",
            "A progress checkpoint is automatic, non-blocking",
            "five materially changed files",
            "push to the existing task branch",
            "verify its remote revision",
            "A progress message without saved state is not a checkpoint.",
        ):
            self.assertIn(phrase, skill_text)

    def test_silent_decision_integrity_cannot_disappear(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "Silent human decision integrity",
            "Use color deliberately",
            "bait-and-switch offers",
            "hidden fees",
            "lead resale",
            "payment diversion",
        ):
            self.assertIn(phrase, skill_text)


if __name__ == "__main__":
    unittest.main()
