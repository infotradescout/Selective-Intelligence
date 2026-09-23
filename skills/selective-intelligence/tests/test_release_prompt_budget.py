from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SKILL_ROOT = TEST_DIR.parent
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import release  # noqa: E402


class ReleasePromptBudgetTests(unittest.TestCase):
    def _openai_product_errors(self, products):
        with tempfile.TemporaryDirectory(prefix="si-openai-products-") as temporary:
            root = Path(temporary)
            agent_config = root / "agents" / "openai.yaml"
            agent_config.parent.mkdir()
            agent_config.write_text(
                'interface:\n'
                '  display_name: "Selective Intelligence"\n'
                '  short_description: "Recover failed work with verified execution"\n'
                '  default_prompt: "Use $selective-intelligence to complete this task."\n'
                'policy:\n'
                '  products:\n'
                + ''.join(f'    - "{product}"\n' for product in products)
                + '  allow_implicit_invocation: true\n',
                encoding="utf-8",
            )
            return release.skill_loader_metadata_errors(root, [agent_config])

    def test_openai_products_accept_current_chatgpt_and_codex_identifiers(self):
        self.assertEqual(self._openai_product_errors(["CHATGPT", "CODEX"]), [])

    def test_openai_products_reject_legacy_chat_and_unsupported_api(self):
        for product in ("CHAT", "api"):
            with self.subTest(product=product):
                errors = self._openai_product_errors([product, "CODEX"])
                self.assertTrue(
                    any(f"unsupported policy products: {product}" in error for error in errors),
                    errors,
                )

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

    def test_distribution_advertises_the_standing_role_default(self):
        metadata = json.loads((SKILL_ROOT / "metadata" / "distribution.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["execution_default"], "lean_orchestrator_worker_objector")
        self.assertEqual(release.jumpstart_errors(SKILL_ROOT, "0.3.0"), [])

    def test_jumpstart_checks_intent_before_index_refresh_or_worker_dispatch(self):
        text = (SKILL_ROOT / "JUMPSTART.md").read_text(encoding="utf-8")
        discovery = text.index("Use bounded read-only evidence to reconstruct the active outcome")
        challenge = text.index("Before Worker dispatch or work, Objector double-checks")
        execution = text.index("After resolving the check, begin the highest-value reversible work")
        index_refresh = text.index("create or refresh `.selective-intelligence/project-index.json`")
        self.assertLess(discovery, challenge)
        self.assertLess(challenge, execution)
        self.assertLess(challenge, index_refresh)

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

    def test_requires_prework_intent_challenge_and_postwork_review(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        required = (
            "Every work turn carries Orchestrator, Worker/Builder, and Objector.",
            "Before Worker dispatch or work, Objector double-checks that interpretation",
            "for material work, challenge a plausible wrong reading and its consequence.",
            "Objector checks result and proof before Orchestrator reports.",
            "label checks degraded, never independent.",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                _, errors = release.prompt_budget_errors(skill_text.replace(phrase, ""))
                self.assertTrue(any("missing lean execution contract" in error for error in errors))
        self.assertLess(skill_text.index("Before Worker dispatch or work"), skill_text.index("Worker executes"))
        self.assertLess(skill_text.index("Worker executes"), skill_text.index("Objector checks result"))

    def test_ordinary_material_case_does_not_spoon_feed_roles(self):
        cases = json.loads((SKILL_ROOT / "evals" / "behavior-cases.json").read_text(encoding="utf-8"))["cases"]
        case = next(item for item in cases if item["id"] == "intent-ordinary-material-work-role-sequence")
        for role in ("Orchestrator", "Worker", "Objector", "Council"):
            self.assertNotIn(role, case["worker_prompt"])
        self.assertIn("Before dispatching Worker", case["required_invariants"][1]["statement"])

    def test_standing_worker_objector_roles_do_not_trigger_heavy_default(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        _, errors = release.prompt_budget_errors(skill_text + "\nAlways run Worker and Objector checks.\n")
        self.assertFalse(any("automatic extra-role escalation" in error for error in errors))

    def test_rejects_automatic_aligner_escalation(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        _, errors = release.prompt_budget_errors(
            skill_text
            + "\nAutomatically spawn Worker, Objector, and Aligner agents for persistent work.\n"
        )
        self.assertTrue(any("automatic extra-role escalation" in error for error in errors))

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
            "five changed files",
            "Commit only owned files, verify pushes",
            "record local-only work",
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
