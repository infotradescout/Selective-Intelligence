"""Plan import tests with real intent, checkpoint, engine and disk session code.

Capability probes, context selection, feedback and filesystem policy adapters are
isolated. These tests do not claim concurrency, live model or installed-client
coverage. All persisted sessions and workspaces live in temporary directories.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import checkpoint as CP
import lane_session as LS


class PlanImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = mock.patch.dict(os.environ, {"SI_SESSION_DIR": str(self.root / "sessions")})
        env.start()
        self.addCleanup(env.stop)
        modules = {name: types.ModuleType(name) for name in (
            "capabilities", "context_budget", "feedback", "policy_guard"
        )}
        modules["lane_session"] = LS
        policy = modules["policy_guard"]
        policy.PolicyDenied = type("PolicyDenied", (RuntimeError,), {})
        policy.PolicyGuard = mock.Mock()
        policy.guarded_run = mock.Mock()
        policy.guarded_write_text = mock.Mock()
        modules["capabilities"].inventory = mock.Mock(return_value=[])
        modules["context_budget"].select_context = mock.Mock(return_value={
            "outcomeCoverage": {"complete": True}, "selected": []
        })
        modules["context_budget"].validate_task_context = mock.Mock()
        spec = importlib.util.spec_from_file_location("si_plan_import_engine", SCRIPTS / "build_engine.py")
        self.engine = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.engine)
        self.engine._start_feedback = mock.Mock()
        self.engine._record_feedback = mock.Mock(return_value=False)

    def plan(self, title="Preserve approved active-business member access", session=None):
        result = {"planId": "synthetic-plan", "tasks": [{
            "key": "work", "title": title, "kind": "worker", "queue": "ready",
        }]}
        if session is not None:
            cp = CP.current_checkpoint(session)
            result["source"] = {
                "sessionId": session["sessionId"],
                "checkpointId": cp["checkpoint_id"], "intentHash": cp["intent_hash"],
            }
        return result

    def start(self, plan=None, request="Preserve approved business memberships."):
        return self.engine.start_project(
            request=request, workspace=str(self.root / "work"), canonical_roots=[], plan=plan,
        )

    def approve(self, session, plan=None):
        return self.engine.approve_project(session_id=session["sessionId"], plan=plan)

    def deny_approval(self, session, plan=None):
        path = LS.session_path(session["sessionId"])
        before = path.read_bytes()
        feedback_calls = self.engine._start_feedback.call_count
        with self.assertRaises(self.engine.EngineError):
            self.approve(session, plan)
        self.assertEqual(before, path.read_bytes())
        self.assertFalse((self.root / "work").exists())
        self.assertEqual(feedback_calls, self.engine._start_feedback.call_count)

    def corrected(self):
        initial = self.start(request="Build a SaaS platform.")
        session, result = self.engine.correct_project(
            session_id=initial["sessionId"], correction="I am not building SaaS.",
        )
        self.assertFalse(session["generationAuthority"])
        self.assertEqual(result["newCheckpoint"]["status"], "proposed")
        return session

    def test_initial_plan_still_approves_and_creates_current_bound_task(self):
        session = self.start(self.plan())
        result = self.approve(session)
        self.assertEqual(len(result["queue"]), 1)
        task = next(iter(result["queue"].values()))
        CP.assert_binding(result, task)
        self.assertEqual(task["status"], "ready")

    def test_initial_plan_is_detached_from_callers_mutable_data(self):
        plan = self.plan()
        session = self.start(plan)
        plan["tasks"][0]["title"] = "Build a SaaS platform"
        self.assertNotEqual(plan["tasks"][0]["title"], session["pendingPlan"]["tasks"][0]["title"])

    def test_staged_plan_mutation_is_denied_before_any_approval_side_effect(self):
        session = self.start(self.plan())
        session["pendingPlan"]["tasks"][0]["title"] = "Do different work"
        LS.save_session(session)
        self.deny_approval(session)

    def test_missing_staged_plan_cannot_silently_approve_its_checkpoint(self):
        session = self.start(self.plan())
        session.pop("pendingPlan")
        LS.save_session(session)
        self.deny_approval(session)

    def test_explicit_empty_pending_plan_is_not_treated_as_no_plan(self):
        session = self.start(self.plan())
        session["pendingPlan"] = {}
        LS.save_session(session)
        self.deny_approval(session)

    def test_unbound_import_is_not_automatically_stamped_with_current_authority(self):
        session = self.start()
        self.deny_approval(session, self.plan())

    def test_current_source_import_still_approves(self):
        session = self.start()
        result = self.approve(session, self.plan(session=session))
        self.assertEqual(len(result["queue"]), 1)
        CP.assert_binding(result, next(iter(result["queue"].values())))

    def test_wrong_session_plan_is_denied(self):
        session = self.start()
        plan = self.plan(session=session)
        plan["source"]["sessionId"] = "another-session"
        self.deny_approval(session, plan)

    def test_stale_checkpoint_plan_is_denied(self):
        session = self.start()
        plan = self.plan(session=session)
        plan["source"]["checkpointId"] = "older-checkpoint"
        self.deny_approval(session, plan)

    def test_stale_intent_plan_is_denied(self):
        session = self.start()
        plan = self.plan(session=session)
        plan["source"]["intentHash"] = "older-intent"
        self.deny_approval(session, plan)

    def test_malformed_source_is_a_controlled_denial(self):
        for source in (None, [], "old", {"sessionId": ""}):
            with self.subTest(source=source):
                session = self.start()
                plan = self.plan(session=session)
                plan["source"] = source
                self.deny_approval(session, plan)

    def test_old_plan_cannot_be_imported_after_correction(self):
        original = self.start()
        plan = self.plan(session=original)
        session, _ = self.engine.correct_project(
            session_id=original["sessionId"], correction="I am not building SaaS.",
        )
        self.deny_approval(session, plan)

    def test_bad_inline_replacement_does_not_undo_the_saved_correction(self):
        initial = self.start(self.plan())
        with self.assertRaises(self.engine.EngineError):
            self.engine.correct_project(
                session_id=initial["sessionId"], correction="I am not building SaaS.",
                replacement_plan=self.plan("Build a SaaS platform"),
            )
        saved = LS.load_session(initial["sessionId"])
        self.assertFalse(saved["generationAuthority"])
        self.assertIn("saas", saved["activeIntent"]["superseded_concepts"])
        self.assertNotIn("pendingPlan", saved)
        self.assertEqual(len(saved["invalidatedPlans"]), 1)

    def test_corrected_plan_with_rejected_product_claim_is_denied(self):
        session = self.corrected()
        self.deny_approval(session, self.plan("Build a SaaS platform", session))

    def test_rejected_claim_hidden_in_nested_task_metadata_is_denied(self):
        session = self.corrected()
        plan = self.plan(session=session)
        plan["tasks"][0]["metadata"] = {"requirements": {"business": ["The product is SaaS."]}}
        self.deny_approval(session, plan)

    def test_rejected_claim_in_acceptance_is_denied(self):
        session = self.corrected()
        plan = self.plan(session=session)
        plan["tasks"][0]["acceptanceRefs"] = ["The product must be a SaaS platform."]
        self.deny_approval(session, plan)

    def test_approved_external_provider_survives_correction(self):
        session = self.corrected()
        result = self.approve(session, self.plan("Keep the approved external SaaS email provider", session))
        self.assertIn("provider", next(iter(result["queue"].values()))["title"])

    def test_negated_product_identity_is_not_a_conflict(self):
        session = self.corrected()
        result = self.approve(session, self.plan("Do not build a SaaS platform", session))
        self.assertEqual(len(result["queue"]), 1)

    def test_memberships_and_fees_do_not_get_reclassified_as_saas(self):
        session = self.corrected()
        result = self.approve(session, self.plan("Preserve approved memberships and transaction fees", session))
        self.assertEqual(len(result["queue"]), 1)

    def test_replacement_plan_packet_roundtrip_survives_disk_reload(self):
        session = self.corrected()
        packet = self.engine.make_plan_packet(session_id=session["sessionId"])
        plan = self.plan()
        plan["source"] = json.loads(json.dumps(packet["source"]))
        result = self.approve(LS.load_session(session["sessionId"]), plan)
        self.assertEqual(len(result["queue"]), 1)
        self.assertNotIn("pendingPlan", result)

    def test_plan_packet_export_does_not_grant_execution_authority(self):
        session = self.corrected()
        before = LS.session_path(session["sessionId"]).read_bytes()
        packet = self.engine.make_plan_packet(session_id=session["sessionId"])
        packet["activeIntent"]["assumptions"].append("Mutated caller copy")
        self.assertEqual(before, LS.session_path(session["sessionId"]).read_bytes())
        self.assertFalse(LS.load_session(session["sessionId"])["generationAuthority"])

    def test_plan_packet_rejects_changed_active_intent(self):
        session = self.start()
        session["activeIntent"]["assumptions"].append("Changed without checkpoint")
        LS.save_session(session)
        with self.assertRaises(self.engine.EngineError):
            self.engine.make_plan_packet(session_id=session["sessionId"])

    def test_plan_packet_missing_session_is_controlled(self):
        with self.assertRaises(self.engine.EngineError):
            self.engine.make_plan_packet(session_id="missing-session")

    def test_malformed_plan_is_a_controlled_denial(self):
        for plan in (None, [], "plan", 1):
            with self.subTest(plan=plan), self.assertRaises(self.engine.EngineError):
                self.engine.validate_plan(plan)

    def test_dependency_order_is_rejected_before_partial_queue_creation(self):
        plan = {"tasks": [
            {"key": "first", "title": "First"},
            {"key": "second", "title": "Second", "dependencies": ["last"]},
            {"key": "last", "title": "Last"},
        ]}
        with self.assertRaises(self.engine.EngineError):
            self.engine.validate_plan(plan)

    def test_dependency_cycles_are_rejected(self):
        plan = {"tasks": [
            {"key": "first", "title": "First", "dependencies": ["second"]},
            {"key": "second", "title": "Second", "dependencies": ["first"]},
        ]}
        with self.assertRaises(self.engine.EngineError):
            self.engine.validate_plan(plan)

    def test_reserved_task_metadata_cannot_override_routing_or_authority(self):
        for key in ("kind", "planKey", "authorized_checkpoint_id", "authorized_intent_hash", "planSpecHash", "planSource"):
            plan = self.plan()
            plan["tasks"][0]["metadata"] = {key: "wrong"}
            with self.subTest(key=key), self.assertRaises(self.engine.EngineError):
                self.engine.validate_plan(plan)

    def test_bad_metadata_and_operations_are_controlled_denials(self):
        for field in ("metadata", "operation"):
            for value in ("oops", [], 3):
                plan = self.plan()
                plan["tasks"][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(self.engine.EngineError):
                    self.engine.validate_plan(plan)

    def test_unrecognized_worker_kind_does_not_create_stranded_work(self):
        plan = self.plan()
        plan["tasks"][0]["kind"] = "unknown-worker"
        with self.assertRaises(self.engine.EngineError):
            self.engine.validate_plan(plan)

    def test_ordered_dependencies_still_work(self):
        plan = {"tasks": [
            {"key": "first", "title": "First"},
            {"key": "second", "title": "Second", "dependencies": ["first"]},
        ]}
        result = self.approve(self.start(plan))
        tasks = list(result["queue"].values())
        self.assertEqual([t["status"] for t in tasks], ["ready", "pending"])
        self.assertEqual(tasks[1]["dependencies"], [tasks[0]["taskId"]])

    def test_applied_plan_is_idempotent(self):
        session = self.start(self.plan())
        pending = copy.deepcopy(session["pendingPlan"])
        result = self.approve(session)
        before = copy.deepcopy(result["queue"])
        self.engine.add_plan_tasks(result, pending)
        self.assertEqual(result["queue"], before)

    def test_changed_same_key_cannot_silently_reuse_a_task(self):
        session = self.start(self.plan())
        pending = copy.deepcopy(session["pendingPlan"])
        result = self.approve(session)
        pending["tasks"][0]["title"] = "Different work with the same key"
        before = copy.deepcopy(result)
        with self.assertRaises(self.engine.EngineError):
            self.engine.add_plan_tasks(result, pending)
        self.assertEqual(result, before)

    def test_stale_existing_task_cannot_satisfy_a_current_plan(self):
        session = self.start(self.plan())
        pending = copy.deepcopy(session["pendingPlan"])
        result = self.approve(session)
        task = next(iter(result["queue"].values()))
        task["authorized_intent_hash"] = "stale"
        before = copy.deepcopy(result)
        with self.assertRaises(self.engine.EngineError):
            self.engine.add_plan_tasks(result, pending)
        self.assertEqual(result, before)

    def test_cancel_requested_task_cannot_satisfy_a_current_plan(self):
        session = self.start(self.plan())
        pending = copy.deepcopy(session["pendingPlan"])
        result = self.approve(session)
        next(iter(result["queue"].values()))["cancelRequested"] = True
        with self.assertRaises(self.engine.EngineError):
            self.engine.add_plan_tasks(result, pending)

    def test_nested_plan_input_does_not_alias_created_task(self):
        plan = self.plan()
        plan["tasks"][0]["operation"] = {"input": {"description": "Original"}}
        session = self.start(plan)
        pending = copy.deepcopy(session["pendingPlan"])
        result = self.approve(session)
        pending["tasks"][0]["operation"]["input"]["description"] = "Changed"
        self.assertEqual(next(iter(result["queue"].values()))["operation"]["input"]["description"], "Original")

    def test_plan_task_insertion_failure_does_not_partially_mutate_session(self):
        plan = {"tasks": [{"key": "one", "title": "One"}, {"key": "two", "title": "Two"}]}
        session = self.start(plan)
        pending = copy.deepcopy(session["pendingPlan"])
        CP.approve_checkpoint(session, session["currentCheckpointId"])
        before = copy.deepcopy(session)
        real_add = LS.add_task
        calls = []
        def failing_add(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise RuntimeError("synthetic second-insertion failure")
            return real_add(*args, **kwargs)
        with mock.patch.object(LS, "add_task", side_effect=failing_add):
            with self.assertRaises(RuntimeError):
                self.engine.add_plan_tasks(session, pending)
        self.assertEqual(session, before)

    def test_legacy_pending_plan_without_snapshot_is_not_silently_upgraded(self):
        session = self.start(self.plan())
        CP.current_checkpoint(session).pop("pending_plan_hash", None)
        LS.save_session(session)
        self.deny_approval(session)

    def test_changed_displayed_plan_actions_are_denied(self):
        session = self.start(self.plan())
        CP.current_checkpoint(session)["planned_next_actions"] = ["Different work"]
        LS.save_session(session)
        self.deny_approval(session)

    def test_nonfinite_or_nonserializable_plan_values_are_denied(self):
        for value in (float("nan"), float("inf"), {"set-value"}):
            plan = self.plan()
            plan["tasks"][0]["metadata"] = {"value": value}
            with self.subTest(value=value), self.assertRaises(self.engine.EngineError):
                self.engine.validate_plan(plan)

    def test_unplanned_live_task_mutation_is_not_hidden_by_its_cached_hash(self):
        session = self.start(self.plan())
        pending = copy.deepcopy(session["pendingPlan"])
        result = self.approve(session)
        next(iter(result["queue"].values()))["title"] = "Different live task"
        with self.assertRaises(self.engine.EngineError):
            self.engine.add_plan_tasks(result, pending)

    def test_corrected_plan_reaches_current_worker_packet_after_disk_reload(self):
        session = self.corrected()
        plan_packet = self.engine.make_plan_packet(session_id=session["sessionId"])
        plan = self.plan()
        plan["source"] = plan_packet["source"]
        approved = self.approve(session, plan)
        task = next(iter(approved["queue"].values()))
        packet = self.engine.make_worker_packet(session_id=session["sessionId"], task_id=task["taskId"])
        self.assertEqual(packet["schemaVersion"], "si.worker_packet.v3")
        self.assertEqual(packet["activeIntent"], approved["activeIntent"])
        self.assertEqual(packet["requiredOutput"]["binding"]["authorized_intent_hash"], plan["source"]["intentHash"])
        self.assertEqual(LS.load_session(session["sessionId"])["authorizedCheckpointId"], plan["source"]["checkpointId"])

    def test_current_approval_without_any_plan_remains_supported(self):
        session = self.approve(self.start())
        self.assertTrue(session["generationAuthority"])
        self.assertEqual(session["queue"], {})


if __name__ == "__main__":
    unittest.main()
