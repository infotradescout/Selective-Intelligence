"""Fault and concurrency tests for actual SI persistence/execution owners.

Synthetic temporary workspaces only. Write/replace faults are deliberately
injected. Thread and subprocess tests use real session locks and saved files.
No live model, external IDE or production product is exercised.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS)) if str(SCRIPTS) not in sys.path else None
import build_engine as E
import checkpoint as CP
import lane_session as LS


class TransactionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="si-transaction-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.workspace = self.root / "work"
        self.workspace.mkdir()
        env = mock.patch.dict(os.environ, {"SI_SESSION_DIR": str(self.root / "sessions")})
        env.start()
        self.addCleanup(env.stop)
        self.session = LS.new_session("Preserve a community exchange and approved memberships.", workspace=str(self.workspace))
        CP.approve_checkpoint(self.session, self.session["currentCheckpointId"])
        self.task = LS.add_task(self.session, title="Preserve membership access", queue="ready", metadata={"kind": "worker"})
        LS.save_session(self.session)
        self.sid = self.session["sessionId"]
        self.tid = self.task["taskId"]

    def artifact(self, files=None):
        return {"sessionId": self.sid, "taskId": self.tid,
                "authorized_checkpoint_id": self.session["authorizedCheckpointId"],
                "authorized_intent_hash": self.session["authorizedIntentHash"],
                "producer": {"adapterId": "synthetic", "surface": "test", "generatedAt": "2026-09-06"},
                "files": files or {"first.txt": "new first", "second.txt": "new second"}}

    def apply(self, files=None):
        return E.apply_worker_artifact(session_id=self.sid, task_id=self.tid, artifact=self.artifact(files))

    def test_failed_second_write_preserves_existing_files(self):
        (self.workspace / "first.txt").write_bytes(b"original\x00bytes\xff")
        original = E.guarded_write_text
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 2:
                raise OSError("injected second staging failure")
            return original(*args, **kwargs)
        with mock.patch.object(E, "guarded_write_text", side_effect=fail_second):
            with self.assertRaises((E.EngineError, OSError)):
                self.apply()
        self.assertEqual((self.workspace / "first.txt").read_bytes(), b"original\x00bytes\xff")
        self.assertFalse((self.workspace / "second.txt").exists())
        self.assertEqual(LS.load_session(self.sid)["artifacts"], [])

    def test_failed_second_write_leaves_no_new_first_file(self):
        original = E.guarded_write_text
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 2:
                raise OSError("injected failure")
            return original(*args, **kwargs)
        with mock.patch.object(E, "guarded_write_text", side_effect=fail_second):
            with self.assertRaises((E.EngineError, OSError)):
                self.apply()
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_failed_session_save_restores_original_files(self):
        (self.workspace / "first.txt").write_text("original", encoding="utf-8")
        original = LS.save_session
        failed = False
        def fail_once(session):
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("injected session save failure")
            return original(session)
        with mock.patch.object(LS, "save_session", side_effect=fail_once):
            with self.assertRaises((E.EngineError, OSError)):
                self.apply()
        self.assertEqual((self.workspace / "first.txt").read_text(), "original")
        self.assertFalse((self.workspace / "second.txt").exists())
        self.assertNotEqual(LS.global_state(LS.load_session(self.sid)), "VERIFIED_COMPLETE")

    def test_successful_batch_preserves_existing_file_permissions(self):
        target = self.workspace / "first.txt"
        target.write_text("old")
        target.chmod(0o640)
        self.apply()
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertEqual(target.read_text(), "new first")
        self.assertEqual(sorted(p.name for p in self.workspace.iterdir()), ["first.txt", "second.txt"])

    def test_correction_during_apply_is_saved_after_the_cooperative_batch(self):
        entered = threading.Event()
        attempted = threading.Event()
        corrected = threading.Event()
        errors = []
        original = E.guarded_write_text
        def correct():
            try:
                self.assertTrue(entered.wait(5))
                attempted.set()
                E.interrupt_project(session_id=self.sid, correction="I am not building SaaS.")
                corrected.set()
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=correct, daemon=True)
        worker.start()
        first = True
        def paused_write(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                entered.set()
                self.assertTrue(attempted.wait(5))
                time.sleep(0.05)
                self.assertFalse(corrected.is_set(), "correction bypassed the active write transaction")
            return original(*args, **kwargs)
        try:
            with mock.patch.object(E, "guarded_write_text", side_effect=paused_write):
                self.apply()
        finally:
            entered.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(corrected.is_set())
        current = LS.load_session(self.sid)
        self.assertTrue(current["executionLocked"])
        self.assertTrue(all(a.get("tainted") for a in current["artifacts"]))
        self.assertNotEqual(LS.global_state(current), "VERIFIED_COMPLETE")

    def verify(self, script="assert True\n"):
        self.apply({"test_fixture.py": "import unittest\nclass Fixture(unittest.TestCase):\n    def test_behavior(self):\n        " + script.strip() + "\n"})
        return E.verify_task(session_id=self.sid, task_id=self.tid, command={"argv": [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_fixture.py"]})

    def test_corrected_completed_session_cannot_reuse_old_success(self):
        self.assertTrue(self.verify()["passed"])
        E.interrupt_project(session_id=self.sid, correction="I am not building SaaS.")
        self.assertNotEqual(LS.global_state(LS.load_session(self.sid)), "VERIFIED_COMPLETE")

    def test_unrelated_success_cannot_prove_an_unverified_task(self):
        result = self.verify()
        session = result["session"]
        other = LS.add_task(session, title="Different unverified behavior", queue="ready", metadata={"kind": "worker"})
        other["status"] = "complete"
        self.assertNotEqual(LS.global_state(session), "VERIFIED_COMPLETE")

    def test_changed_completed_task_cannot_keep_verified_status(self):
        session = self.verify()["session"]
        session["queue"][self.tid]["title"] = "Different behavior"
        self.assertNotEqual(LS.global_state(session), "VERIFIED_COMPLETE")

    def test_missing_command_evidence_is_not_verification(self):
        session = self.verify()["session"]
        session["commandEvidence"].clear()
        self.assertNotEqual(LS.global_state(session), "VERIFIED_COMPLETE")

    def test_changed_command_evidence_cannot_keep_verified_status(self):
        session = self.verify()["session"]
        session["commandEvidence"][-1]["exitCode"] = 1
        self.assertNotEqual(LS.global_state(session), "VERIFIED_COMPLETE")

    def test_current_real_success_still_completes(self):
        session = self.verify()["session"]
        self.assertEqual(LS.global_state(session), "VERIFIED_COMPLETE")
        self.assertEqual(LS.global_state(LS.load_session(self.sid)), "VERIFIED_COMPLETE")

    def test_repair_proof_completes_original_and_repair(self):
        failure = self.verify("assert False\n")
        repair = failure["repairTask"]
        packet = E.make_worker_packet(session_id=self.sid, task_id=repair["taskId"])
        artifact = {k: packet[k] for k in ("sessionId", "taskId", "authorized_checkpoint_id", "authorized_intent_hash")}
        artifact.update(producer=self.artifact()["producer"], files={"test_fixture.py": "import unittest\nclass Fixture(unittest.TestCase):\n    def test_behavior(self):\n        assert True\n"})
        E.apply_worker_artifact(session_id=self.sid, task_id=repair["taskId"], artifact=artifact)
        result = E.verify_repair(session_id=self.sid, repair_task_id=repair["taskId"], command={"argv": [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_fixture.py"]})
        self.assertTrue(result["passed"])
        self.assertEqual(LS.global_state(result["session"]), "VERIFIED_COMPLETE")

    def test_parallel_verification_is_rejected_without_running_twice(self):
        self.apply({"test_fixture.py": "import unittest\nclass Fixture(unittest.TestCase):\n    def test_behavior(self):\n        assert True\n"})
        original = E.guarded_run
        entered = threading.Event()
        release = threading.Event()
        results = []
        calls = []
        def paused_run(*args, **kwargs):
            calls.append(1)
            entered.set()
            if len(calls) == 1:
                self.assertTrue(release.wait(5))
            return original(*args, **kwargs)
        def run_first():
            try:
                results.append(E.verify_task(session_id=self.sid, task_id=self.tid, command={"argv": [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_fixture.py"]}))
            except BaseException as exc:
                results.append(exc)
        with mock.patch.object(E, "guarded_run", side_effect=paused_run):
            thread = threading.Thread(target=run_first, daemon=True)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(E.EngineError):
                    E.verify_task(session_id=self.sid, task_id=self.tid, command={"argv": [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_fixture.py"]})
            finally:
                release.set()
                thread.join(5)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], dict)
        self.assertTrue(results[0]["passed"])

    def test_stale_verification_keeps_original_evidence_binding(self):
        self.apply({"test_fixture.py": "import unittest\nclass Fixture(unittest.TestCase):\n    def test_behavior(self):\n        assert True\n"})
        original = E.guarded_run
        old_checkpoint = self.session["authorizedCheckpointId"]
        def correct_after_process(*args, **kwargs):
            decision, evidence = original(*args, **kwargs)
            E.interrupt_project(session_id=self.sid, correction="I am not building SaaS.")
            return decision, evidence
        with mock.patch.object(E, "guarded_run", side_effect=correct_after_process):
            try:
                result = E.verify_task(session_id=self.sid, task_id=self.tid, command={"argv": [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_fixture.py"]})
                self.assertFalse(result["passed"])
            except E.EngineError:
                pass
        current = LS.load_session(self.sid)
        self.assertTrue(current["executionLocked"])
        self.assertEqual(current["commandEvidence"][-1]["authorized_checkpoint_id"], old_checkpoint)
        self.assertFalse(any(v.get("passed") for v in current["verificationAttempts"]))

    def test_process_failure_clears_verification_claim_without_completion(self):
        self.apply({"test_fixture.py": "import unittest\nclass Fixture(unittest.TestCase):\n    def test_behavior(self):\n        assert True\n"})
        with mock.patch.object(E, "guarded_run", side_effect=OSError("injected launch error")):
            with self.assertRaises((E.EngineError, OSError)):
                E.verify_task(session_id=self.sid, task_id=self.tid, command={"argv": [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_fixture.py"]})
        current = LS.load_session(self.sid)
        self.assertIsNone(current["queue"][self.tid].get("activeVerification"))
        self.assertNotEqual(LS.global_state(current), "VERIFIED_COMPLETE")
        self.assertEqual(current["queue"][self.tid]["status"], "failed")

    def test_two_processes_cannot_silently_overwrite_the_same_revision(self):
        script = self.root / "race.py"
        script.write_text('''import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import lane_session as LS
sid, root, name = sys.argv[2:]
root = Path(root)
session = LS.load_session(sid)
(root / (name + '.ready')).write_text('ready')
deadline = time.monotonic() + 10
while not (root / 'go').exists():
    if time.monotonic() > deadline: raise RuntimeError('barrier timeout')
    time.sleep(.01)
LS.record_event(session, 'race.' + name, {})
try:
    LS.save_session(session)
    outcome = 'saved'
except LS.SessionConflictError:
    outcome = 'conflict'
(root / (name + '.result')).write_text(outcome)
''', encoding="utf-8")
        children = []
        with tempfile.TemporaryFile() as output:
            try:
                for name in ("one", "two"):
                    children.append(subprocess.Popen([sys.executable, str(script), str(SCRIPTS), self.sid, str(self.root), name], stdout=output, stderr=output))
                deadline = time.monotonic() + 10
                while not all((self.root / (name + ".ready")).exists() for name in ("one", "two")):
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.01)
                (self.root / "go").write_text("go")
                for child in children:
                    self.assertEqual(child.wait(timeout=10), 0)
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
        self.assertEqual(sorted((self.root / (name + ".result")).read_text() for name in ("one", "two")), ["conflict", "saved"])
        current = LS.load_session(self.sid)
        self.assertEqual(len([event for event in current["events"] if event["eventType"].startswith("race.")]), 1)


if __name__ == "__main__":
    unittest.main()
