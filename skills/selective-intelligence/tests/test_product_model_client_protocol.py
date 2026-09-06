"""Real-process CLI integration; no mocked policy, storage, context or feedback.

Uses synthetic workspaces and the actual command/verification adapters. This is
not installed-client, live-model, arbitrary worker shutdown or concurrency proof.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ENGINE = Path(__file__).resolve().parents[1] / "scripts" / "build_engine.py"
BINDING = ("sessionId", "taskId", "authorized_checkpoint_id", "authorized_intent_hash")
CORRECTION = "I am not building SaaS."


class ClientProtocolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="si-client-proof-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "work"
        self.env = {"PATH": os.defpath, "HOME": str(self.root),
                    "SI_SESSION_DIR": str(self.root / "sessions"),
                    "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            if key in os.environ:
                self.env[key] = os.environ[key]
        self.counter = 0

    def document(self, value):
        self.counter += 1
        path = self.root / f"input-{self.counter}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def call(self, command, *args, expected=0):
        result = subprocess.run(
            [sys.executable, str(ENGINE), command, *map(str, args)],
            cwd=self.root, env=self.env, text=True, capture_output=True, timeout=20,
        )
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail("client response was not a JSON object: " + result.stdout + result.stderr)
        self.assertIsInstance(payload, dict)
        return payload

    def raw(self, session):
        path = self.root / "sessions" / (session["sessionId"] + ".session.json")
        return json.loads(path.read_text(encoding="utf-8"))

    def plan(self, titles=None, source=None):
        tasks = [{"key": f"work-{i}", "title": title, "kind": "worker", "queue": "ready"}
                 for i, title in enumerate(titles or ["Preserve approved business memberships"])]
        result = {"tasks": tasks}
        if source is not None:
            result["source"] = copy.deepcopy(source)
        return result

    def start(self, approved=False, titles=None, request="Build a SaaS platform. Preserve approved business memberships."):
        session = self.call("start", "--request", request, "--workspace", self.workspace,
                            "--plan", self.document(self.plan(titles)))
        return self.approve(session) if approved else session

    def approve(self, session):
        cp = session["currentCheckpoint"]
        return self.call("approve", "--session", session["sessionId"],
                         "--checkpoint", cp["checkpoint_id"], "--intent-hash", cp["intent_hash"])

    def packet(self, session, index=0):
        return self.call("packet", "--session", session["sessionId"],
                         "--task", session["queue"][index]["taskId"])

    def artifact(self, packet, files=None):
        return {**{field: packet[field] for field in BINDING},
                "producer": {"adapterId": "synthetic-client", "surface": "process-test",
                             "generatedAt": "2026-09-06T00:00:00Z"},
                "files": files or {"result.txt": "Approved memberships are preserved.\n"}}

    def assert_correction_saved(self, session, result):
        saved = self.raw(session)
        self.assertTrue(saved["executionLocked"])
        self.assertTrue(result["correctionSaved"])
        self.assertFalse(saved["generationAuthority"])
        self.assertIsNone(saved["authorizedCheckpointId"])
        self.assertNotEqual(saved["currentCheckpointId"], session["currentCheckpoint"]["checkpoint_id"])
        self.assertIn("saas", json.dumps(saved["activeIntent"]["superseded_concepts"]).lower())
        self.assertNotIn("pendingPlan", saved)
        self.assertTrue(all(task["status"] == "cancelled" for task in saved["queue"].values()))
        return saved

    def fresh_plan(self, session):
        packet = self.call("plan-packet", "--session", session["sessionId"])
        return self.plan(source=packet["source"])

    def corrected(self, session=None):
        session = session or self.start(approved=True)
        result = self.call("correct", "--session", session["sessionId"], "--correction", CORRECTION)
        return self.call("show", "--session", session["sessionId"]), result

    def test_start_remains_locked_without_workspace_mutation(self):
        session = self.start()
        self.assertTrue(session["executionLocked"])
        self.assertFalse(self.workspace.exists())
        self.assertEqual(session["queue"], [])

    def test_plan_alias_does_not_silently_approve(self):
        session = self.call("plan", "--idea", "Preserve approved memberships",
                            "--workspace", self.workspace, "--plan", self.document(self.plan()))
        self.assertTrue(session["executionLocked"])
        self.assertFalse(self.workspace.exists())
        self.assertIsNone(session["authorizedCheckpointId"])

    def test_malformed_replacement_cannot_erase_correction(self):
        session = self.start(approved=True)
        path = self.root / "bad.json"
        path.write_text("{broken", encoding="utf-8")
        result = self.call("correct", "--session", session["sessionId"], "--correction", CORRECTION,
                           "--plan", path, expected=2)
        self.assert_correction_saved(session, result)
        self.assertEqual(result["code"], "correction_saved_attachment_rejected")

    def test_missing_replacement_cannot_erase_correction(self):
        session = self.start(approved=True)
        result = self.call("correct", "--session", session["sessionId"], "--correction", CORRECTION,
                           "--plan", self.root / "missing.json", expected=2)
        self.assert_correction_saved(session, result)

    def test_nonobject_replacement_cannot_erase_correction(self):
        session = self.start(approved=True)
        result = self.call("correct", "--session", session["sessionId"], "--correction", CORRECTION,
                           "--plan", self.document([]), expected=2)
        self.assert_correction_saved(session, result)

    def test_stale_replacement_reports_that_correction_survived(self):
        session = self.start(approved=True)
        old_plan = self.fresh_plan(session)
        result = self.call("correct", "--session", session["sessionId"], "--correction", CORRECTION,
                           "--plan", self.document(old_plan), expected=2)
        self.assert_correction_saved(session, result)
        self.assertNotEqual(result["planPacket"]["source"], old_plan["source"])

    def test_bad_model_override_cannot_prevent_plain_correction(self):
        session = self.start(approved=True)
        result = self.call("correct", "--session", session["sessionId"], "--correction", CORRECTION,
                           "--intent-override", self.document([]), expected=2)
        self.assert_correction_saved(session, result)

    def test_interrupt_also_saves_correction_when_override_is_missing(self):
        session = self.start(approved=True)
        result = self.call("interrupt", "--session", session["sessionId"], "--correction", CORRECTION,
                           "--intent-override", self.root / "missing.json", expected=2)
        self.assert_correction_saved(session, result)

    def test_normal_correction_returns_fresh_nonexecuting_plan_packet(self):
        session = self.start(approved=True)
        result = self.call("correct", "--session", session["sessionId"], "--correction", CORRECTION)
        saved = self.assert_correction_saved(session, result)
        self.assertEqual(result["planPacket"]["source"]["checkpointId"], saved["currentCheckpointId"])
        self.assertEqual(result["planPacket"]["activeIntent"], saved["activeIntent"])

    def test_staging_fresh_plan_does_not_approve_or_create_tasks(self):
        session, _ = self.corrected(self.start())
        plan = self.fresh_plan(session)
        staged = self.call("stage-plan", "--session", session["sessionId"], "--plan", self.document(plan))
        saved = self.raw(session)
        self.assertTrue(staged["executionLocked"])
        self.assertFalse(saved["generationAuthority"])
        self.assertEqual(saved["pendingPlan"], plan)
        self.assertEqual(saved["queue"], {})
        self.assertFalse(self.workspace.exists())
        self.assertEqual(staged["pendingPlan"], plan)

    def test_staging_stale_plan_leaves_saved_state_unchanged(self):
        original = self.start()
        plan = self.fresh_plan(original)
        session, _ = self.corrected(original)
        before = self.raw(session)
        self.call("stage-plan", "--session", session["sessionId"], "--plan", self.document(plan), expected=2)
        self.assertEqual(before, self.raw(session))

    def test_staging_unbound_plan_is_not_silently_relabelled(self):
        session, _ = self.corrected(self.start())
        before = self.raw(session)
        self.call("stage-plan", "--session", session["sessionId"], "--plan", self.document(self.plan()), expected=2)
        self.assertEqual(before, self.raw(session))

    def test_staging_rejected_product_model_is_denied(self):
        session, _ = self.corrected(self.start())
        plan = self.fresh_plan(session)
        plan["tasks"][0]["title"] = "Build a SaaS platform"
        before = self.raw(session)
        self.call("stage-plan", "--session", session["sessionId"], "--plan", self.document(plan), expected=2)
        self.assertEqual(before, self.raw(session))

    def test_staging_cannot_replace_existing_approval(self):
        session = self.start(approved=True)
        before = self.raw(session)
        self.call("stage-plan", "--session", session["sessionId"],
                  "--plan", self.document(self.fresh_plan(session)), expected=2)
        self.assertEqual(before, self.raw(session))

    def test_approval_of_altered_staged_plan_is_denied(self):
        session, _ = self.corrected(self.start())
        plan = self.fresh_plan(session)
        self.call("stage-plan", "--session", session["sessionId"], "--plan", self.document(plan))
        saved = self.raw(session)
        saved["pendingPlan"]["tasks"][0]["title"] = "Do different work"
        path = self.root / "sessions" / (session["sessionId"] + ".session.json")
        path.write_text(json.dumps(saved), encoding="utf-8")
        self.call("approve", "--session", session["sessionId"], expected=2)
        self.assertTrue(self.raw(session)["executionLocked"])
        self.assertFalse(self.workspace.exists())

    def test_build_alias_accepts_current_bound_result(self):
        session = self.start(approved=True)
        artifact = self.artifact(self.packet(session))
        result = self.call("build", "--session", session["sessionId"], "--artifact", self.document(artifact))
        self.assertEqual((self.workspace / "result.txt").read_text(), artifact["files"]["result.txt"])
        self.assertEqual(len(result["written"]), 1)

    def test_build_routes_to_results_actual_task_not_first_ready_task(self):
        session = self.start(approved=True, titles=["Preserve approved memberships", "Preserve approved fees"])
        artifact = self.artifact(self.packet(session, index=1))
        self.call("build", "--session", session["sessionId"], "--artifact", self.document(artifact))
        saved = self.raw(session)
        self.assertEqual(saved["queue"][session["queue"][0]["taskId"]]["status"], "ready")
        self.assertEqual(saved["queue"][artifact["taskId"]]["status"], "verifying")

    def test_build_does_not_fabricate_missing_result_binding(self):
        session = self.start(approved=True)
        artifact = self.artifact(self.packet(session))
        del artifact["authorized_intent_hash"]
        before = self.raw(session)
        self.call("build", "--session", session["sessionId"], "--artifact", self.document(artifact), expected=2)
        self.assertEqual(before, self.raw(session))
        self.assertFalse((self.workspace / "result.txt").exists())

    def test_build_rejects_result_after_correction(self):
        session = self.start(approved=True)
        artifact = self.artifact(self.packet(session))
        self.corrected(session)
        before = self.raw(session)
        self.call("build", "--session", session["sessionId"], "--artifact", self.document(artifact), expected=2)
        self.assertEqual(before, self.raw(session))
        self.assertFalse((self.workspace / "result.txt").exists())

    def test_build_without_result_exports_current_packet(self):
        session = self.start(approved=True)
        result = self.call("build", "--session", session["sessionId"], expected=3)
        self.assertEqual(result["code"], "worker_input_required")
        self.assertEqual(result["workerPacket"]["schemaVersion"], "si.worker_packet.v3")
        self.assertEqual(result["humanActions"], [])

    def test_build_locked_handoff_is_controlled_not_traceback(self):
        session = self.start(approved=True)
        saved = self.raw(session)
        saved["executionLocked"] = True
        path = self.root / "sessions" / (session["sessionId"] + ".session.json")
        path.write_text(json.dumps(saved), encoding="utf-8")
        self.call("build", "--session", session["sessionId"], expected=2)
        self.assertEqual(saved, self.raw(session))

    def test_invalid_later_file_is_rejected_before_any_file_is_written(self):
        session = self.start(approved=True)
        artifact = self.artifact(self.packet(session), {"safe.txt": "must not be written", "../escape.txt": "denied"})
        before = self.raw(session)
        self.call("apply", "--session", session["sessionId"], "--task", artifact["taskId"],
                  "--artifact", self.document(artifact), expected=2)
        self.assertFalse((self.workspace / "safe.txt").exists())
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertEqual(before, self.raw(session))

    def test_later_policy_denial_prevents_earlier_allowed_write(self):
        session = self.start(approved=True)
        protected = self.root / "protected"
        protected.mkdir()
        try:
            (self.workspace / "outside").symlink_to(protected, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"this environment cannot create the symlink test fixture: {exc}")
        artifact = self.artifact(self.packet(session), {"safe.txt": "must not be written", "outside/no.txt": "denied"})
        before = self.raw(session)
        self.call("apply", "--session", session["sessionId"], "--task", artifact["taskId"],
                  "--artifact", self.document(artifact), expected=3)
        self.assertFalse((self.workspace / "safe.txt").exists())
        self.assertFalse((protected / "no.txt").exists())
        self.assertEqual(before, self.raw(session))

    def test_duplicate_resolved_targets_are_rejected_before_write(self):
        session = self.start(approved=True)
        artifact = self.artifact(self.packet(session), {"result.txt": "first", "./result.txt": "second"})
        self.call("apply", "--session", session["sessionId"], "--task", artifact["taskId"],
                  "--artifact", self.document(artifact), expected=2)
        self.assertFalse((self.workspace / "result.txt").exists())

    def test_existing_directory_target_prevents_entire_file_batch(self):
        session = self.start(approved=True)
        (self.workspace / "occupied").mkdir()
        artifact = self.artifact(self.packet(session), {"safe.txt": "first", "occupied": "denied"})
        self.call("apply", "--session", session["sessionId"], "--task", artifact["taskId"],
                  "--artifact", self.document(artifact), expected=2)
        self.assertFalse((self.workspace / "safe.txt").exists())

    def test_real_context_selects_relevant_file_and_excludes_feedback(self):
        session = self.start(approved=True)
        (self.workspace / "memberships.txt").write_text("Approved business memberships remain available.")
        packet = self.packet(session)
        selected = {item["path"] for item in packet["contextBundle"]["selected"]}
        self.assertIn("memberships.txt", selected)
        self.assertFalse(any("feedback/" in path for path in selected))

    def test_default_discovery_uses_actual_safe_capability_probes(self):
        session = self.call("start", "--request", "Preserve approved memberships", "--workspace", self.workspace)
        session = self.approve(session)
        adapters = {item["adapterId"]: item for item in session["capabilityInventory"]}
        self.assertTrue(adapters["python3_runtime"]["executable"])
        self.assertTrue(adapters["local_filesystem_tmp"]["executable"])
        self.assertTrue(adapters["local_process_runner"]["executable"])
        self.assertTrue(any(task["status"] == "complete" for task in session["queue"]))

    def test_correct_stage_text_approve_apply_verify_reload_full_journey(self):
        session = self.start(approved=True)
        self.call("text-gate", "--session", session["sessionId"], "--response", "CORRECT: " + CORRECTION)
        plan = self.fresh_plan(session)
        staged = self.call("stage-plan", "--session", session["sessionId"], "--plan", self.document(plan))
        cp = staged["currentCheckpoint"]
        self.call("text-gate", "--session", session["sessionId"], "--response", "APPROVE",
                  "--checkpoint", cp["checkpoint_id"], "--intent-hash", cp["intent_hash"])
        current = self.call("show", "--session", session["sessionId"])
        task = next(item for item in current["queue"] if item["status"] == "ready")
        packet = self.call("packet", "--session", session["sessionId"], "--task", task["taskId"])
        files = {"memberships.py": "def allowed(active):\n    return active is True\n",
                 "test_memberships.py": "import unittest\nfrom memberships import allowed\nclass Access(unittest.TestCase):\n    def test_active(self):\n        self.assertTrue(allowed(True))\n        self.assertFalse(allowed(False))\n"}
        artifact = self.artifact(packet, files)
        self.call("build", "--session", session["sessionId"], "--artifact", self.document(artifact))
        verified = self.call("verify", "--session", session["sessionId"], "--task", task["taskId"],
                             "--command", self.document({"argv": [sys.executable, "-m", "unittest", "test_memberships"]}))
        self.assertTrue(verified["passed"])
        self.assertEqual(verified["commandEvidence"]["adapterInvocationStatus"], "INVOKED")
        self.assertEqual(verified["commandEvidence"]["exitCode"], 0)
        reloaded = self.raw(session)
        self.assertEqual(reloaded["queue"][task["taskId"]]["status"], "complete")
        self.assertIn("memberships", json.dumps(reloaded["activeIntent"]).lower())
        events = [json.loads(line) for line in (self.workspace / ".selective-intelligence/feedback/events.jsonl").read_text().splitlines()]
        self.assertTrue({"task_started", "user_correction", "validation_passed"}.issubset({e["event"] for e in events}))
        self.assertTrue(all("prompt" not in event and "correction" not in event for event in events))

    def test_correction_stops_si_owned_verification_process(self):
        session = self.start(approved=True)
        packet = self.packet(session)
        files = {"test_wait.py": "import time, unittest\nfrom pathlib import Path\nclass Wait(unittest.TestCase):\n    def test_wait(self):\n        Path('started.txt').write_text('started')\n        time.sleep(15)\n        Path('should_not_finish.txt').write_text('wrong')\n"}
        artifact = self.artifact(packet, files)
        self.call("apply", "--session", session["sessionId"], "--task", packet["taskId"], "--artifact", self.document(artifact))
        process = subprocess.Popen([sys.executable, str(ENGINE), "verify", "--session", session["sessionId"],
                                    "--task", packet["taskId"], "--command", self.document({"argv": [sys.executable, "-m", "unittest", "test_wait"]})],
                                   cwd=self.root, env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 8
            while not (self.workspace / "started.txt").exists() and time.monotonic() < deadline:
                time.sleep(.03)
            self.assertTrue((self.workspace / "started.txt").exists())
            self.call("correct", "--session", session["sessionId"], "--correction", CORRECTION)
            stdout, stderr = process.communicate(timeout=8)
            self.assertNotIn("Traceback", stderr)
            self.assertEqual(process.returncode, 5, stdout + stderr)
            result = json.loads(stdout)
            self.assertFalse(result["passed"])
            self.assertTrue(result["commandEvidence"]["cancelled"])
            self.assertFalse((self.workspace / "should_not_finish.txt").exists())
            self.assertTrue(self.raw(session)["executionLocked"])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=20)


    def test_schema_invalid_model_override_cannot_prevent_correction(self):
        session = self.start(approved=True)
        result = self.call("correct", "--session", session["sessionId"], "--correction", CORRECTION,
                           "--intent-override", self.document({"operation": ["ADD"]}), expected=2)
        self.assert_correction_saved(session, result)

    def test_valid_conflicting_override_cannot_restore_rejected_identity(self):
        session = self.start(approved=True)
        result = self.call("correct", "--session", session["sessionId"], "--correction", CORRECTION,
                           "--intent-override", self.document({"operation": "ADD", "product_intent": "Build a SaaS platform"}))
        saved = self.assert_correction_saved(session, result)
        self.assertNotIn("saas", saved["objective"].lower())
        self.assertEqual(result["operation"], "RETRACT")

    def test_empty_correction_does_not_invalidate_current_approval(self):
        session = self.start(approved=True)
        before = self.raw(session)
        result = self.call("correct", "--session", session["sessionId"], "--correction", " ", expected=2)
        self.assertFalse(result["correctionSaved"])
        self.assertEqual(before, self.raw(session))

    def test_invalid_session_does_not_claim_correction_saved(self):
        result = self.call("correct", "--session", "missing-session", "--correction", CORRECTION, expected=2)
        self.assertFalse(result["correctionSaved"])

    def test_parent_child_output_conflict_prevents_entire_batch(self):
        session = self.start(approved=True)
        artifact = self.artifact(self.packet(session), {"safe.txt": "first", "parent": "file", "parent/child.txt": "conflict"})
        self.call("apply", "--session", session["sessionId"], "--task", artifact["taskId"],
                  "--artifact", self.document(artifact), expected=2)
        self.assertFalse((self.workspace / "safe.txt").exists())
        self.assertFalse((self.workspace / "parent").exists())

    def test_existing_parent_file_prevents_entire_batch(self):
        session = self.start(approved=True)
        (self.workspace / "parent").write_text("untouched")
        artifact = self.artifact(self.packet(session), {"safe.txt": "first", "parent/child.txt": "conflict"})
        self.call("apply", "--session", session["sessionId"], "--task", artifact["taskId"],
                  "--artifact", self.document(artifact), expected=2)
        self.assertFalse((self.workspace / "safe.txt").exists())
        self.assertEqual((self.workspace / "parent").read_text(), "untouched")

    def test_wrong_result_session_is_not_rebound_by_build_alias(self):
        session = self.start(approved=True)
        artifact = self.artifact(self.packet(session))
        artifact["sessionId"] = "another-session"
        before = self.raw(session)
        self.call("build", "--session", session["sessionId"], "--artifact", self.document(artifact), expected=2)
        self.assertEqual(before, self.raw(session))
        self.assertFalse((self.workspace / "result.txt").exists())


if __name__ == "__main__":
    unittest.main()
