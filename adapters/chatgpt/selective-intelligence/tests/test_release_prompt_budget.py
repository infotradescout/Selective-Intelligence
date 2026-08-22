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

    def test_canonical_skill_fits_lean_budget(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        metrics, errors = release.prompt_budget_errors(skill_text)
        self.assertEqual(errors, [])
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


if __name__ == "__main__":
    unittest.main()
