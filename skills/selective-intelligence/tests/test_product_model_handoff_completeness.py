"""Verify that current task requirements reach the actual worker handoff.

Real session, checkpoint, registry, context broker and engine; no live model.
The role checks verify shipped instructions structurally, not model obedience.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import build_engine as ENGINE
import checkpoint as CP
import context_budget as CB
import lane_session as LS


class HandoffCompletenessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="si-complete-handoff-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patch = mock.patch.dict(os.environ, {"SI_SESSION_DIR": str(self.root / "sessions")})
        patch.start()
        self.addCleanup(patch.stop)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.session = LS.new_session("Preserve the approved community exchange.", workspace=str(self.workspace))
        CP.approve_checkpoint(self.session, self.session["currentCheckpointId"])
        self.task = LS.add_task(
            self.session, title="Complete the approved change", queue="ready",
            metadata={"requirements": {"access": "Only active business memberships unlock prices.",
                                       "preserve": ["Approved provider fees", "Human ownership of work"]}},
            operation={"kind": "filesystem.write", "path": "result.txt"},
            invalidation_conditions=["Membership authority changes"],
        )
        LS.save_session(self.session)

    def packet(self):
        return ENGINE.make_worker_packet(session_id=self.session["sessionId"], task_id=self.task["taskId"])

    def test_nested_requirements_reach_worker(self):
        packet = self.packet()
        self.assertEqual(packet["task"].get("metadata"), self.task["metadata"])

    def test_operation_reaches_worker_without_authorizing_its_execution(self):
        packet = self.packet()
        self.assertEqual(packet["task"].get("operation"), self.task["operation"])
        self.assertFalse((self.workspace / "result.txt").exists())

    def test_invalidation_conditions_reach_worker(self):
        self.assertEqual(self.packet()["task"].get("invalidationConditions"), self.task["invalidationConditions"])

    def test_packet_preserves_every_bound_instruction_not_only_a_short_allowlist(self):
        expected = CP._task_material(self.task)
        actual = self.packet()["task"]
        for field, value in expected.items():
            with self.subTest(field=field):
                self.assertIn(field, actual)
                self.assertEqual(actual[field], value)

    def test_packet_mutation_does_not_change_saved_requirements(self):
        packet = self.packet()
        self.assertIn("metadata", packet["task"])
        packet["task"]["metadata"]["requirements"]["access"] = "Replaced by an unapproved monthly upgrade"
        saved = LS.load_session(self.session["sessionId"])
        self.assertEqual(saved["queue"][self.task["taskId"]]["metadata"], self.task["metadata"])
        CP.assert_binding(saved, saved["queue"][self.task["taskId"]])

    def test_missing_or_changed_approval_still_denies_complete_packet(self):
        self.session["queue"][self.task["taskId"]]["metadata"]["requirements"]["access"] = "Changed"
        LS.save_session(self.session)
        with self.assertRaises(ENGINE.EngineError):
            self.packet()

    def test_context_selection_uses_nested_requirement_file_references(self):
        (self.workspace / "membership-source.txt").write_text("Active membership source.", encoding="utf-8")
        (self.workspace / "00-unrelated.txt").write_text("Unrelated material.", encoding="utf-8")
        task = {"title": "Complete the approved change", "metadata": {
            "requirements": {"source": "membership-source.txt"}}}
        bundle = CB.select_context(self.workspace, objective="Preserve the approved exchange", task=task, max_files=1)
        self.assertEqual([item["path"] for item in bundle["selected"]], ["membership-source.txt"])
        self.assertIn("membership-source.txt", bundle["outcomeCoverage"]["requiredPaths"])

    def test_context_selection_uses_operation_references(self):
        (self.workspace / "zeta.txt").write_text("Zebra boundary.", encoding="utf-8")
        (self.workspace / "00-unrelated.txt").write_text("Unrelated material.", encoding="utf-8")
        task = {"title": "Complete the approved change", "operation": {"source": "zeta.txt"}}
        bundle = CB.select_context(self.workspace, objective="Preserve the approved exchange", task=task, max_files=1)
        self.assertEqual([item["path"] for item in bundle["selected"]], ["zeta.txt"])

    def test_budget_exclusion_of_required_nested_source_is_not_complete(self):
        for name in ("members.txt", "prices.txt"):
            (self.workspace / name).write_text("Approved source.", encoding="utf-8")
        task = {"title": "Complete the approved change", "metadata": {
            "requirements": {"sources": ["members.txt", "prices.txt"]}}}
        bundle = CB.select_context(self.workspace, objective="Preserve the exchange", task=task, max_files=1)
        self.assertFalse(bundle["outcomeCoverage"]["complete"])
        self.assertEqual(len(bundle["outcomeCoverage"]["unresolvedPaths"]), 1)

    def test_runtime_attempts_do_not_expand_selected_context(self):
        (self.workspace / "approved.txt").write_text("Approved source.", encoding="utf-8")
        (self.workspace / "old-work.txt").write_text("Historical output.", encoding="utf-8")
        task = {"title": "Read approved.txt", "attempts": [{"output": "old-work.txt"}]}
        bundle = CB.select_context(self.workspace, objective="Read the source", task=task, max_files=1)
        self.assertEqual([item["path"] for item in bundle["selected"]], ["approved.txt"])
        self.assertNotIn("old-work.txt", bundle["outcomeCoverage"]["requiredPaths"])

    def test_context_identity_changes_when_current_requirements_change(self):
        (self.workspace / "source.txt").write_text("Same source file.", encoding="utf-8")
        task = {"title": "Read source.txt", "metadata": {"requirements": "Preserve memberships"}}
        original = CB.select_context(self.workspace, objective="Read source.txt", task=task)
        task["metadata"]["requirements"] = "Replace memberships"
        changed = CB.select_context(self.workspace, objective="Read source.txt", task=task)
        self.assertNotEqual(original["contextDigest"], changed["contextDigest"])

    def test_oversized_task_is_rejected_without_truncating_or_exporting(self):
        task = LS.add_task(self.session, title="Preserve the complete requirements", queue="ready",
                           metadata={"requirements": "x" * 70_000})
        LS.save_session(self.session)
        before = LS.load_session(self.session["sessionId"])
        with self.assertRaisesRegex(ENGINE.EngineError, "bounded handoff"):
            ENGINE.make_worker_packet(session_id=self.session["sessionId"], task_id=task["taskId"])
        self.assertEqual(LS.load_session(self.session["sessionId"]), before)

    def test_credential_in_task_is_blocked_without_export_or_error_disclosure(self):
        secret = "fixture" + "credential" + "value"
        task = LS.add_task(self.session, title="Keep provider access private", queue="ready",
                           metadata={"provider": {"api_key": secret}})
        LS.save_session(self.session)
        before = LS.load_session(self.session["sessionId"])
        with self.assertRaises(ENGINE.EngineError) as raised:
            ENGINE.make_worker_packet(session_id=self.session["sessionId"], task_id=task["taskId"])
        self.assertNotIn(secret, str(raised.exception))
        self.assertEqual(LS.load_session(self.session["sessionId"]), before)

    def test_provider_credential_reference_remains_allowed(self):
        task = {"metadata": {"provider": {"credential_reference": "approved-provider-access"}}}
        bundle = CB.select_context(self.workspace, objective="Preserve the approved provider", task=task)
        self.assertTrue(bundle["outcomeCoverage"]["complete"])

    def test_required_secret_file_is_excluded_and_incomplete(self):
        secret = "fixture" + "credential" + "value"
        (self.workspace / "provider.txt").write_text("API_KEY=" + secret, encoding="utf-8")
        task = {"metadata": {"requirements": {"source": "provider.txt"}}}
        bundle = CB.select_context(self.workspace, objective="Read the source", task=task)
        self.assertFalse(bundle["outcomeCoverage"]["complete"])
        self.assertIn("provider.txt", bundle["outcomeCoverage"]["unresolvedPaths"])
        self.assertEqual(bundle["selected"], [])
        self.assertNotIn(secret, json.dumps(bundle))

    def test_required_oversized_source_is_not_silently_complete(self):
        (self.workspace / "source.txt").write_text("x" * 100, encoding="utf-8")
        bundle = CB.select_context(self.workspace, objective="Read the source",
                                   task={"metadata": {"source": "source.txt"}}, max_file_bytes=10)
        self.assertFalse(bundle["outcomeCoverage"]["complete"])
        self.assertIn("source.txt", bundle["outcomeCoverage"]["unresolvedPaths"])

    def test_context_identity_ignores_runtime_progress(self):
        task = {"title": "Preserve memberships", "metadata": {"exclusive": False, "minimum": 4}}
        original = CB.select_context(self.workspace, objective="Preserve the exchange", task=task)
        task.update(status="running", attempts=[{"output": "stale output"}], updatedAt="later")
        progressed = CB.select_context(self.workspace, objective="Preserve the exchange", task=task)
        self.assertEqual(original["contextDigest"], progressed["contextDigest"])

    def test_context_identity_binds_numeric_boolean_and_unknown_requirements(self):
        task = {"title": "Preserve memberships", "metadata": {"exclusive": False, "minimum": 4}}
        original = CB.select_context(self.workspace, objective="Preserve the exchange", task=task)
        for key, value in (("exclusive", True), ("minimum", 5), ("new_requirement", {"limit": 0})):
            with self.subTest(key=key):
                changed_task = copy.deepcopy(task)
                changed_task["metadata"][key] = value
                changed = CB.select_context(self.workspace, objective="Preserve the exchange", task=changed_task)
                self.assertNotEqual(original["contextDigest"], changed["contextDigest"])

    def test_real_command_exports_complete_task(self):
        output = self.root / "packet.json"
        with (self.root / "command.log").open("w", encoding="utf-8") as log:
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "build_engine.py"), "packet",
                                     "--session", self.session["sessionId"], "--task", self.task["taskId"],
                                     "--output", str(output)], stdout=log, stderr=subprocess.STDOUT,
                                    timeout=15, check=False)
        self.assertEqual(result.returncode, 0, (self.root / "command.log").read_text(encoding="utf-8"))
        packet = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(packet["task"]["metadata"], self.task["metadata"])
        self.assertEqual(packet["task"]["operation"], self.task["operation"])
        self.assertEqual(packet["requiredOutput"]["binding"]["taskId"], self.task["taskId"])
        self.assertFalse((self.workspace / "result.txt").exists())

    def test_full_packet_still_supports_existing_bound_result(self):
        packet = self.packet()
        artifact = copy.deepcopy(packet["requiredOutput"]["binding"])
        artifact.update(producer={"adapterId": "test", "surface": "synthetic fixture", "generatedAt": "test"},
                        files={"result.txt": "Active memberships preserved."})
        ENGINE.apply_worker_artifact(session_id=packet["sessionId"], task_id=packet["taskId"], artifact=artifact)
        self.assertEqual((self.workspace / "result.txt").read_text(encoding="utf-8"), "Active memberships preserved.")


class NativeRoleContractTests(unittest.TestCase):
    def test_worker_uses_actual_engine_packet_and_complete_task(self):
        text = (ROOT / "subskills/si-worker/SKILL.md").read_text(encoding="utf-8")
        for marker in ("requiredOutput", "metadata", "sessionId", "taskId", "authorized_checkpoint_id",
                       "authorized_intent_hash", "producer", "files", "Do not relabel"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertIn("model-neutral-execution.md#product-identity-and-corrected-execution", text)

    def test_planner_uses_post_correction_source_without_granting_approval(self):
        text = (ROOT / "subskills/si-planner/SKILL.md").read_text(encoding="utf-8")
        for marker in ("plan-packet", "stage-plan", "source", "tasks", "no execution authority", "Start Pack"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertIn("model-neutral-execution.md#product-identity-and-corrected-execution", text)

    def test_existing_lean_boundaries_remain_in_both_roles(self):
        planner = (ROOT / "subskills/si-planner/SKILL.md").read_text(encoding="utf-8")
        worker = (ROOT / "subskills/si-worker/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Clear bounded work does not invoke this role", planner)
        self.assertIn("Do not invoke it merely because the task involves repository edits", worker)
        self.assertNotIn("Trade" + "Scout", planner + worker)


if __name__ == "__main__":
    unittest.main()
