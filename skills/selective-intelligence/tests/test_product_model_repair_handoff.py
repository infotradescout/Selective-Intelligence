"""Original requirements survive actual failed-verification repair handoffs.

Uses real sessions, checkpoints, file application and guarded unittest processes.
Synthetic implementation and checks; no running model or installed-client claim.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_engine as ENGINE
import checkpoint as CP
import lane_session as LS


class RepairHandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="si-repair-handoff-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = mock.patch.dict(os.environ, {
            "SI_SESSION_DIR": str(self.root / "sessions"), "PYTHONDONTWRITEBYTECODE": "1",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "zeta.txt").write_text("Zebra boundary.", encoding="utf-8")
        (self.workspace / "test_result.py").write_text(
            'from pathlib import Path\nimport unittest\n'
            'class Result(unittest.TestCase):\n'
            ' def test_result(self): self.assertEqual(Path("result.txt").read_text(), "correct")\n',
            encoding="utf-8",
        )
        self.session = LS.new_session("Preserve the approved community exchange.", workspace=str(self.workspace))
        CP.approve_checkpoint(self.session, self.session["currentCheckpointId"])
        self.task = LS.add_task(
            self.session, title="Implement the approved behavior", queue="ready",
            metadata={"requirements": {"access": "Active business memberships only",
                                       "preserve": ["Approved provider fees", "Human ownership"],
                                       "source": "zeta.txt"}},
            operation={"kind": "filesystem.write", "path": "result.txt"},
            invalidation_conditions=["Approved membership authority changes"],
        )
        LS.save_session(self.session)
        self.command = {"argv": [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_result.py"]}
        self.apply(self.task["taskId"], "wrong")
        failure = ENGINE.verify_task(session_id=self.session["sessionId"], task_id=self.task["taskId"], command=self.command)
        self.assertFalse(failure["passed"])
        self.assertEqual(failure["commandEvidence"]["exitCode"], 1)
        self.repair = failure["repairTask"]

    def packet(self, task_id):
        return ENGINE.make_worker_packet(session_id=self.session["sessionId"], task_id=task_id)

    def apply(self, task_id, content):
        packet = self.packet(task_id)
        artifact = copy.deepcopy(packet["requiredOutput"]["binding"])
        artifact.update(producer={"adapterId": "fixture", "surface": "synthetic", "generatedAt": "fixture"},
                        files={"result.txt": content})
        ENGINE.apply_worker_artifact(session_id=self.session["sessionId"], task_id=task_id, artifact=artifact)

    def test_repair_receives_exact_original_instructions_without_runtime_history(self):
        packet = self.packet(self.repair["taskId"])
        self.assertIn("originalTask", packet["task"]["metadata"])
        original = packet["task"]["metadata"]["originalTask"]
        self.assertEqual(original, CP._task_material(self.task))
        self.assertNotIn("attempts", original)
        self.assertNotIn("status", original)
        self.assertEqual(packet["task"]["metadata"]["kind"], "repair")
        self.assertNotIn("planKey", packet["task"]["metadata"])
        self.assertIn("zeta.txt", packet["contextBundle"]["outcomeCoverage"]["requiredPaths"])
        self.assertEqual(packet["failureEvidence"]["taskId"], self.task["taskId"])
        self.assertIn("AssertionError", packet["failureEvidence"]["stderr"])
        self.assertEqual(packet["failureEvidence"]["exitCode"], 1)

    def test_repair_cannot_receive_tampered_failure_output(self):
        session = LS.load_session(self.session["sessionId"])
        evidence = next(item for item in session["commandEvidence"] if item["evidenceId"] == self.repair["metadata"]["failureEvidenceId"])
        evidence["stderr"] = "A fabricated failure"
        LS.save_session(session)
        with self.assertRaisesRegex(ENGINE.EngineError, "repair failure evidence"):
            self.packet(self.repair["taskId"])

    def test_changed_inherited_instructions_cannot_keep_repair_approval(self):
        session = LS.load_session(self.session["sessionId"])
        saved = session["queue"][self.repair["taskId"]]
        self.assertIn("originalTask", saved["metadata"])
        saved["metadata"]["originalTask"]["metadata"]["requirements"]["access"] = "An unapproved upgrade"
        LS.save_session(session)
        with self.assertRaises(ENGINE.EngineError):
            self.packet(self.repair["taskId"])

    def test_second_failed_attempt_keeps_both_repair_context_and_original_rules(self):
        self.apply(self.repair["taskId"], "still wrong")
        failure = ENGINE.verify_task(session_id=self.session["sessionId"], task_id=self.repair["taskId"], command=self.command)
        self.assertFalse(failure["passed"])
        packet = self.packet(failure["repairTask"]["taskId"])
        self.assertIn("originalTask", packet["task"]["metadata"])
        prior = packet["task"]["metadata"]["originalTask"]
        self.assertEqual(prior["taskId"], self.repair["taskId"])
        self.assertEqual(prior["metadata"]["originalTask"], CP._task_material(self.task))

    def test_valid_repair_still_completes_after_reopening_saved_state(self):
        session = LS.load_session(self.session["sessionId"])
        self.assertIn("originalTask", session["queue"][self.repair["taskId"]]["metadata"])
        self.apply(self.repair["taskId"], "correct")
        result = ENGINE.verify_repair(session_id=self.session["sessionId"], repair_task_id=self.repair["taskId"], command=self.command)
        self.assertTrue(result["passed"])
        final = LS.load_session(self.session["sessionId"])
        self.assertEqual(final["queue"][self.task["taskId"]]["status"], "complete")
        self.assertEqual(final["queue"][self.repair["taskId"]]["status"], "complete")

    def test_second_repair_completes_every_original_task_with_bound_evidence(self):
        self.apply(self.repair["taskId"], "still wrong")
        failed = ENGINE.verify_repair(session_id=self.session["sessionId"], repair_task_id=self.repair["taskId"], command=self.command)
        second = failed["repairTask"]["taskId"]
        self.apply(second, "correct")
        final = ENGINE.verify_repair(session_id=self.session["sessionId"], repair_task_id=second, command=self.command)
        self.assertTrue(final["passed"])
        self.assertEqual(LS.global_state(final["session"]), "VERIFIED_COMPLETE")
        for original_id in [self.task["taskId"], self.repair["taskId"]]:
            completion = next(item for item in final["session"]["completionEvidence"] if item["originalTaskId"] == original_id)
            self.assertEqual(completion["repairTaskId"], second)
            self.assertEqual(completion["commandEvidenceId"], final["commandEvidence"]["evidenceId"])

    def test_repair_cannot_substitute_a_successful_version_check(self):
        self.apply(self.repair["taskId"], "still wrong")
        with self.assertRaisesRegex(ENGINE.EngineError, "original failed command"):
            ENGINE.verify_repair(session_id=self.session["sessionId"], repair_task_id=self.repair["taskId"], command={"argv": [sys.executable, "--version"]})
        self.assertNotEqual(LS.global_state(LS.load_session(self.session["sessionId"])), "VERIFIED_COMPLETE")

    def test_empty_unittest_collection_cannot_complete_a_task(self):
        self.apply(self.repair["taskId"], "correct")
        (self.workspace / "test_result.py").unlink()
        result = ENGINE.verify_repair(session_id=self.session["sessionId"], repair_task_id=self.repair["taskId"], command=self.command)
        self.assertRegex(result["commandEvidence"]["stderr"], r"Ran 0 tests")
        self.assertFalse(result["passed"])
        self.assertIsNotNone(result["repairTask"])


    def verify_repair_fixture(self, source):
        self.apply(self.repair["taskId"], "correct")
        (self.workspace / "test_result.py").write_text(source, encoding="utf-8", newline="")
        return ENGINE.verify_repair(session_id=self.session["sessionId"],
                                    repair_task_id=self.repair["taskId"], command=self.command)

    def test_skipped_only_unittest_cannot_complete_repair(self):
        result = self.verify_repair_fixture(
            'import unittest\nclass Result(unittest.TestCase):\n'
            ' @unittest.skip("fixture unavailable")\n'
            ' def test_result(self): self.fail("never executed")\n')
        self.assertEqual(result["commandEvidence"]["exitCode"], 0)
        self.assertIn("OK (skipped=1)", result["commandEvidence"]["stderr"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["session"]["queue"][self.task["taskId"]]["status"], "repairing")
        self.assertIsNotNone(result["repairTask"])

    def test_expected_failure_only_unittest_cannot_complete_repair(self):
        result = self.verify_repair_fixture(
            'import unittest\nclass Result(unittest.TestCase):\n'
            ' @unittest.expectedFailure\n'
            ' def test_result(self): self.assertEqual(1, 2)\n')
        self.assertEqual(result["commandEvidence"]["exitCode"], 0)
        self.assertIn("expected failures=1", result["commandEvidence"]["stderr"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["session"]["queue"][self.task["taskId"]]["status"], "repairing")

    def test_executed_success_with_optional_skip_still_completes(self):
        result = self.verify_repair_fixture(
            'import unittest\nfrom pathlib import Path\nclass Result(unittest.TestCase):\n'
            ' def test_result(self): self.assertEqual(Path("result.txt").read_text(), "correct")\n'
            ' @unittest.skip("optional fixture unavailable")\n'
            ' def test_optional(self): self.fail("never executed")\n')
        self.assertEqual(result["commandEvidence"]["exitCode"], 0)
        self.assertTrue(result["passed"])
        self.assertEqual(result["session"]["queue"][self.task["taskId"]]["status"], "complete")

    def test_stdout_summary_cannot_mask_zero_collected_tests(self):
        result = self.verify_repair_fixture('print("Ran 9 tests in 0.001s\\n\\nOK")\n')
        self.assertIn("Ran 0 tests", result["commandEvidence"]["stderr"])
        self.assertIn("Ran 9 tests", result["commandEvidence"]["stdout"])
        self.assertFalse(result["passed"])
        self.assertIsNotNone(result["repairTask"])

    def test_earlier_stderr_summary_cannot_mask_final_skipped_run(self):
        result = self.verify_repair_fixture(
            'import unittest, sys\nprint("Ran 9 tests in 0.001s\\n\\nOK", file=sys.stderr)\n'
            'class Result(unittest.TestCase):\n'
            ' @unittest.skip("unavailable")\n'
            ' def test_result(self): self.fail("never executed")\n')
        self.assertEqual(result["commandEvidence"]["exitCode"], 0)
        self.assertFalse(result["passed"])
        self.assertIsNotNone(result["repairTask"])



if __name__ == "__main__":
    unittest.main()
