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


if __name__ == "__main__":
    unittest.main()
