"""Isolated handoff regressions using real engine/checkpoint/intent code.

Storage, context selection, and provider/file-policy adapters are test doubles.
Valid outputs write only inside TemporaryDirectory. This is not live-worker,
concurrency, full-repository, filesystem-policy, or model-behavior proof.
"""
from __future__ import annotations

import copy
from contextlib import nullcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import checkpoint as CP
import intent_contract as IC


class WorkerBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        modules = {name: types.ModuleType(name) for name in (
            "capabilities", "context_budget", "feedback", "lane_session", "policy_guard"
        )}
        policy = modules["policy_guard"]
        policy.PolicyDenied = type("PolicyDenied", (RuntimeError,), {})
        policy.PolicyGuard = mock.Mock()
        policy.PolicyGuard.return_value.authorize.return_value = {"allowed": True}
        policy.guarded_run = mock.Mock()
        policy.guarded_write_text = mock.Mock(side_effect=self.write_file)
        self.writer = policy.guarded_write_text
        self.storage = modules["lane_session"]
        self.storage.session_lock = lambda session_id: nullcontext()
        self.storage.SessionConflictError = type("SessionConflictError", (RuntimeError,), {})
        self.storage.load_session = mock.Mock(side_effect=self.load)
        self.storage.save_session = mock.Mock(side_effect=self.save)
        self.storage.transition_task = mock.Mock(side_effect=self.transition)
        self.storage.record_policy_decision = mock.Mock()
        self.storage.record_artifact = mock.Mock(side_effect=lambda s, r: s["artifacts"].append(r))
        self.storage.record_event = mock.Mock(return_value={"eventId": "test-event"})
        modules["context_budget"].select_context = mock.Mock(return_value={
            "outcomeCoverage": {"complete": True}, "selected": []
        })
        spec = importlib.util.spec_from_file_location("si_worker_binding_engine", SCRIPT_DIR / "build_engine.py")
        assert spec and spec.loader
        self.engine = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.engine)
        self.reset_session()

    def reset_session(self):
        event = IC.classify_intent("Build a community exchange.")
        self.session = {
            "sessionId": "synthetic-session", "objective": event["product_intent"],
            "activeIntent": IC.merge_active_contract(None, event),
            "intentEvents": [event], "siActive": True,
            "governanceMode": "always_on_after_activation", "queue": {},
            "artifacts": [], "workspace": str(self.workspace),
        }
        cp = CP.emit_checkpoint(self.session)
        CP.approve_checkpoint(self.session, cp["checkpoint_id"])
        self.session["queue"]["task-one"] = CP.bind_authorization(self.session, {
            "taskId": "task-one", "title": "Preserve approved member access",
            "status": "ready", "attempts": [],
        })
        self.writer.reset_mock()
        self.storage.transition_task.reset_mock()
        self.storage.save_session.reset_mock()
        for path in self.workspace.glob("*.txt"):
            path.unlink()

    def load(self, session_id):
        return copy.deepcopy(self.session) if session_id == self.session["sessionId"] else None

    def save(self, session):
        self.session = copy.deepcopy(session)

    def transition(self, session, task_id, status, **kwargs):
        session["queue"][task_id]["status"] = status
        return True, ""

    def write_file(self, target, content, **kwargs):
        target.write_text(content, encoding="utf-8")
        data = content.encode("utf-8")
        return {"allowed": True}, {
            "evidenceId": "test-write", "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "timestamp": "2026-09-06T00:00:00Z",
        }

    def artifact(self):
        return {
            "sessionId": self.session["sessionId"], "taskId": "task-one",
            "authorized_checkpoint_id": self.session["authorizedCheckpointId"],
            "authorized_intent_hash": self.session["authorizedIntentHash"],
            "producer": {"adapterId": "synthetic", "surface": "test", "generatedAt": "2026-09-06T00:00:00Z"},
            "files": {"result.txt": "Approved member access is preserved.\n"},
        }

    def apply(self, artifact):
        return self.engine.apply_worker_artifact(
            session_id=self.session["sessionId"], task_id="task-one", artifact=artifact
        )

    def assert_denied_without_side_effect(self, artifact):
        before = copy.deepcopy(self.session)
        with self.assertRaises(self.engine.EngineError):
            self.apply(artifact)
        self.writer.assert_not_called()
        self.storage.transition_task.assert_not_called()
        self.storage.save_session.assert_not_called()
        self.assertFalse((self.workspace / "result.txt").exists())
        self.assertEqual(self.session, before)

    def test_current_bound_artifact_is_applied(self):
        artifact = self.artifact()
        result = self.apply(artifact)
        self.assertEqual((self.workspace / "result.txt").read_text(), artifact["files"]["result.txt"])
        self.assertEqual(result["session"]["queue"]["task-one"]["status"], "verifying")
        self.assertEqual(result["written"][0]["authorized_checkpoint_id"], artifact["authorized_checkpoint_id"])
        self.assertEqual(result["written"][0]["authorized_intent_hash"], artifact["authorized_intent_hash"])

    def test_missing_identity_or_binding_is_denied(self):
        for field in ("sessionId", "taskId", "authorized_checkpoint_id", "authorized_intent_hash"):
            with self.subTest(field=field):
                self.reset_session()
                artifact = self.artifact()
                artifact.pop(field)
                self.assert_denied_without_side_effect(artifact)

    def test_wrong_session_is_denied(self):
        artifact = self.artifact()
        artifact["sessionId"] = "different-session"
        self.assert_denied_without_side_effect(artifact)

    def test_wrong_task_is_denied(self):
        artifact = self.artifact()
        artifact["taskId"] = "different-task"
        self.assert_denied_without_side_effect(artifact)

    def test_stale_checkpoint_is_denied(self):
        artifact = self.artifact()
        artifact["authorized_checkpoint_id"] = "old-checkpoint"
        self.assert_denied_without_side_effect(artifact)

    def test_stale_intent_hash_is_denied(self):
        artifact = self.artifact()
        artifact["authorized_intent_hash"] = "old-intent-hash"
        self.assert_denied_without_side_effect(artifact)

    def test_empty_or_nonstring_binding_is_denied(self):
        for field in ("sessionId", "taskId", "authorized_checkpoint_id", "authorized_intent_hash"):
            for value in ("", "  ", None, [], 1, False):
                with self.subTest(field=field, value=value):
                    self.reset_session()
                    artifact = self.artifact()
                    artifact[field] = value
                    self.assert_denied_without_side_effect(artifact)

    def test_nonobject_artifact_is_a_controlled_denial(self):
        for value in (None, [], "result", 3):
            with self.subTest(value=value):
                self.assert_denied_without_side_effect(value)

    def test_interrupted_session_denies_pre_correction_result(self):
        artifact = self.artifact()
        CP.interrupt(self.session, correction="I am not building SaaS.")
        self.assert_denied_without_side_effect(artifact)

    def test_new_approval_does_not_relabel_old_result(self):
        artifact = self.artifact()
        result = CP.interrupt(self.session, correction="I am not building SaaS.")
        CP.approve_checkpoint(self.session, result["newCheckpoint"]["checkpoint_id"])
        # Deliberately make a fresh task with the same external task identifier.
        self.session["queue"]["task-one"] = CP.bind_authorization(self.session, {
            "taskId": "task-one", "title": "Preserve approved member access",
            "status": "ready", "attempts": [],
        })
        self.assert_denied_without_side_effect(artifact)

    def test_current_artifact_cannot_authorize_stale_task(self):
        artifact = self.artifact()
        self.session["queue"]["task-one"]["authorized_intent_hash"] = "old-hash"
        self.assert_denied_without_side_effect(artifact)

    def test_live_intent_drift_still_blocks_writing(self):
        artifact = self.artifact()
        self.session["activeIntent"]["assumptions"].append("The product is SaaS.")
        self.assert_denied_without_side_effect(artifact)

    def test_packet_requires_returned_identity_and_binding(self):
        packet = self.engine.make_worker_packet(session_id=self.session["sessionId"], task_id="task-one")
        for field in ("sessionId", "taskId", "authorized_checkpoint_id", "authorized_intent_hash"):
            self.assertIn(field, packet["requiredOutput"]["required"])
            self.assertEqual(packet["requiredOutput"]["binding"][field], packet[field])

    def test_packet_to_artifact_roundtrip_survives_serialization(self):
        packet = self.engine.make_worker_packet(session_id=self.session["sessionId"], task_id="task-one")
        artifact = self.artifact()
        for field in ("sessionId", "taskId", "authorized_checkpoint_id", "authorized_intent_hash"):
            artifact[field] = packet[field]
        result = self.apply(json.loads(json.dumps(artifact)))
        self.assertEqual(len(result["written"]), 1)

    def test_existing_invalid_producer_is_still_denied(self):
        artifact = self.artifact()
        artifact["producer"] = {}
        self.assert_denied_without_side_effect(artifact)

    def test_existing_empty_files_are_still_denied(self):
        artifact = self.artifact()
        artifact["files"] = {}
        self.assert_denied_without_side_effect(artifact)


if __name__ == "__main__":
    unittest.main()
