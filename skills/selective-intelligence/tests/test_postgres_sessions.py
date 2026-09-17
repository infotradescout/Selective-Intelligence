"""Optional-store boundaries and opt-in real PostgreSQL recovery tests.

The integration class requires SI_TEST_POSTGRES_URL for a disposable database.
An absent database is reported as skipped, never simulated as a native pass.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import build_engine as E
import checkpoint as CP
import lane_session as LS
import postgres_sessions as PG

HAS_DRIVER = importlib.util.find_spec("psycopg") is not None
TEST_URL = os.environ.get("SI_TEST_POSTGRES_URL")


class StoreConfigurationTests(unittest.TestCase):
    def test_default_needs_no_driver_or_database(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(PG.configured_store())

    def test_unknown_backend_cannot_fall_back_to_files(self):
        with mock.patch.dict(os.environ, {"SI_SESSION_BACKEND": "postgrse"}):
            with self.assertRaisesRegex(PG.SessionStorageError, "must be file or postgres"):
                LS.load_session("si-test")

    def test_database_is_explicit(self):
        with self.assertRaisesRegex(PG.SessionStorageError, "DATABASE_URL is required"):
            PG.PostgresSessionStore("", "test")

    def test_postgres_requires_single_active_execution_contract(self):
        for mode in ("", "active-active", "automatic-failover"):
            with self.subTest(mode=mode):
                with mock.patch.dict(os.environ, {"SI_SESSION_BACKEND": "postgres", "SI_SESSION_EXECUTION_MODE": mode}):
                    with self.assertRaisesRegex(PG.SessionStorageError, "Automatic takeover is unsupported"):
                        LS.load_session("si-test")

    def test_namespace_is_explicit_and_restricted(self):
        for namespace in ("", "../other", "a b", "a" * 101):
            with self.subTest(namespace=namespace):
                with self.assertRaisesRegex(PG.SessionStorageError, "NAMESPACE"):
                    PG.PostgresSessionStore("postgresql://localhost/test", namespace)

    @unittest.skipUnless(HAS_DRIVER, "optional psycopg dependency is not installed")
    def test_remote_database_requires_verified_tls(self):
        for mode in ("disable", "prefer", "require", "verify-ca"):
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(PG.SessionStorageError, "verify-full"):
                    PG.PostgresSessionStore(f"postgresql://db.example/test?sslmode={mode}", "test")
        store = PG.PostgresSessionStore("postgresql://db.example/test", "test")
        self.assertEqual(store._options["sslmode"], "verify-full")
        self.assertEqual(store._options["sslrootcert"], "system")

    @unittest.skipUnless(HAS_DRIVER, "optional psycopg dependency is not installed")
    def test_transaction_pooler_or_implicit_host_is_rejected(self):
        for url in ("postgresql://ep-test-pooler.us-east-1.aws.neon.tech/test",
                    "postgresql://EP-TEST-POOLER.us-east-1.aws.neon.tech/test",
                    "dbname=test", "host=first,second dbname=test"):
            with self.subTest(url=url):
                with self.assertRaisesRegex(PG.SessionStorageError, "direct database host"):
                    PG.PostgresSessionStore(url, "test")


@unittest.skipUnless(TEST_URL and HAS_DRIVER, "requires SI_TEST_POSTGRES_URL and optional psycopg")
class PostgresRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="si-postgres-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "work"
        self.workspace.mkdir()
        self.namespace = "test-" + uuid.uuid4().hex
        environment = mock.patch.dict(os.environ, {
            "SI_SESSION_BACKEND": "postgres",
            "SI_SESSION_EXECUTION_MODE": "single-active",
            "SI_SESSION_DATABASE_URL": TEST_URL,
            "SI_SESSION_NAMESPACE": self.namespace,
            "SI_SESSION_DIR": str(self.root / "must-not-be-used"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.store = PG.configured_store()
        self.store.initialize()
        self.addCleanup(self.clean_rows)
        self.session = LS.new_session("Preserve approved membership access.", workspace=str(self.workspace))
        CP.approve_checkpoint(self.session, self.session["currentCheckpointId"])
        self.task = LS.add_task(self.session, title="Preserve membership access", queue="ready", metadata={"kind": "worker"})
        LS.save_session(self.session)
        self.sid = self.session["sessionId"]

    def clean_rows(self):
        connection = self.store._connect()
        try:
            connection.execute("DELETE FROM public.si_runtime_sessions WHERE namespace = %s", (self.namespace,))
            connection.execute("DELETE FROM public.si_runtime_sessions WHERE namespace = %s", (self.namespace + "-other",))
        finally:
            connection.close()

    def command(self, code, *args):
        return [sys.executable, "-B", "-c", "import sys;sys.path.insert(0,sys.argv[1]);" + code,
                str(SCRIPTS), *args]

    def child(self, code, *args):
        result = subprocess.run(self.command(code, *args), capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_stale_revision_and_insert_collision_are_rejected(self):
        stale = copy.deepcopy(self.session)
        LS.record_event(self.session, "newer", {})
        LS.save_session(self.session)
        with self.assertRaises(LS.SessionConflictError):
            LS.save_session(stale)
        stale["persistenceRevision"] = 0
        with self.assertRaises(LS.SessionConflictError):
            LS.save_session(stale)
        saved = LS.load_session(self.sid)
        self.assertEqual(saved["persistenceRevision"], 2)
        self.assertEqual(saved["events"][-1]["eventType"], "newer")

    def test_namespaces_separate_identical_session_ids(self):
        with mock.patch.dict(os.environ, {"SI_SESSION_NAMESPACE": self.namespace + "-other"}):
            self.assertIsNone(LS.load_session(self.sid))
            other = copy.deepcopy(self.session)
            other["persistenceRevision"] = 0
            other["objective"] = "Other project."
            LS.save_session(other)
            self.assertEqual(LS.load_session(self.sid)["objective"], "Other project.")
        self.assertEqual(LS.load_session(self.sid)["objective"], self.session["objective"])

    def test_concurrent_processes_preserve_all_checkpoints(self):
        code = """
import lane_session as LS
with LS.session_lock(sys.argv[2]):
    session = LS.load_session(sys.argv[2])
    LS.record_event(session, 'child-checkpoint', {'child': sys.argv[3]})
    LS.save_session(session)
"""
        children = [subprocess.Popen(self.command(code, self.sid, str(n)), stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True) for n in range(8)]
        try:
            for child in children:
                _, error = child.communicate(timeout=40)
                self.assertEqual(child.returncode, 0, error)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait()
        saved = LS.load_session(self.sid)
        events = [e for e in saved["events"] if e["eventType"] == "child-checkpoint"]
        self.assertEqual({e["payload"]["child"] for e in events}, {str(n) for n in range(8)})
        self.assertEqual(len(events), 8)
        self.assertEqual(saved["persistenceRevision"], 9)

    def test_killed_process_releases_lock_and_keeps_committed_checkpoint(self):
        marker = self.root / "checkpoint-saved"
        code = """
import lane_session as LS
from pathlib import Path
import time
with LS.session_lock(sys.argv[2]):
    session = LS.load_session(sys.argv[2])
    LS.record_event(session, 'before-process-death', {})
    LS.save_session(session)
    Path(sys.argv[3]).write_text('saved')
    time.sleep(60)
"""
        child = subprocess.Popen(self.command(code, self.sid, str(marker)), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 15
            while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "child did not commit its checkpoint")
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        recovered = self.child("import lane_session as LS,json;print(json.dumps(LS.load_session(sys.argv[2])))", self.sid)
        self.assertEqual(recovered["persistenceRevision"], 2)
        self.assertEqual(recovered["events"][-1]["eventType"], "before-process-death")
        self.assertEqual(recovered["authorizedCheckpointId"], self.session["authorizedCheckpointId"])

    def test_lost_lock_does_not_advance_state_or_fall_back(self):
        with self.store.lock(self.sid) as connection:
            connection.close()
            with self.assertRaisesRegex(PG.SessionStorageError, "lock was lost"):
                LS.save_session(self.session)
        self.assertEqual(self.session["persistenceRevision"], 1)
        self.assertEqual(LS.load_session(self.sid)["persistenceRevision"], 1)
        self.assertFalse((self.root / "must-not-be-used").exists())

    def test_fresh_process_recovers_verified_engine_evidence(self):
        artifact = {
            "sessionId": self.sid, "taskId": self.task["taskId"],
            "authorized_checkpoint_id": self.session["authorizedCheckpointId"],
            "authorized_intent_hash": self.session["authorizedIntentHash"],
            "producer": {"adapterId": "synthetic", "surface": "test", "generatedAt": "2026-09-17"},
            "files": {"test_fixture.py": "import unittest\nclass Fixture(unittest.TestCase):\n    def test_access(self):\n        self.assertEqual(2 + 2, 4)\n"},
        }
        E.apply_worker_artifact(session_id=self.sid, task_id=self.task["taskId"], artifact=artifact)
        result = E.verify_task(session_id=self.sid, task_id=self.task["taskId"], command={
            "argv": [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_fixture.py"]})
        self.assertTrue(result["passed"])
        before = LS.load_session(self.sid)
        recovered = self.child("""
import lane_session as LS,json
session = LS.load_session(sys.argv[2])
print(json.dumps({'state': LS.global_state(session), 'session': session}))
""", self.sid)
        self.assertEqual(recovered["state"], "VERIFIED_COMPLETE")
        self.assertEqual(recovered["session"], before)
        E.interrupt_project(session_id=self.sid, correction="Membership access must require a new explicit approval.")
        self.assertNotEqual(LS.global_state(LS.load_session(self.sid)), "VERIFIED_COMPLETE")


if __name__ == "__main__":
    unittest.main()
