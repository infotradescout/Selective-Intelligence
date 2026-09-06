"""Product-neutral intent-to-checkpoint regressions; no network or live workers."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import checkpoint as CP
import intent_contract as IC


def session_for(product: str = "Build a SaaS platform.") -> dict:
    event = IC.classify_intent(product)
    return {
        "sessionId": "synthetic-session",
        "objective": product,
        "activeIntent": IC.merge_active_contract(None, event),
        "intentEvents": [event],
        "siActive": True,
        "governanceMode": "always_on_after_activation",
        "queue": {},
        "artifacts": [],
    }


def approved(product: str = "Build a community exchange.") -> tuple[dict, dict]:
    session = session_for(product)
    cp = CP.emit_checkpoint(session)
    CP.approve_checkpoint(session, cp["checkpoint_id"])
    return session, cp


class ProductModelCheckpointTests(unittest.TestCase):
    def test_corrected_checkpoint_does_not_fallback_to_rejected_objective(self):
        session, _ = approved("Build a SaaS platform.")
        result = CP.interrupt(session, correction="I am not building SaaS.")
        self.assertEqual(result["newCheckpoint"]["intent_summary"], "")

    def test_corrected_session_objective_uses_surviving_intent(self):
        session, _ = approved("Build a SaaS platform. Preserve the human exchange.")
        CP.interrupt(session, correction="I am not building SaaS.")
        self.assertEqual(session["objective"], session["activeIntent"]["product_intent"])
        self.assertNotIn("SaaS", session["objective"])

    def test_explicit_empty_active_intent_does_not_load_old_session_intent(self):
        session = session_for()
        cp = CP.emit_checkpoint(session, active_intent={})
        self.assertEqual(cp["intent_summary"], "")
        self.assertEqual(cp["active_intent_snapshot"], {})

    def test_explicit_empty_next_actions_remain_empty(self):
        session = session_for("Build a community exchange. First inspect the old template.")
        self.assertTrue(session["activeIntent"]["process_directives"])
        cp = CP.emit_checkpoint(session, planned_next_actions=[])
        self.assertEqual(cp["planned_next_actions"], [])

    def test_checkpoint_snapshot_does_not_share_nested_intent_lists(self):
        session = session_for()
        session["activeIntent"]["scope"] = ["approved scope"]
        cp = CP.emit_checkpoint(session)
        session["activeIntent"]["scope"].append("unapproved additional scope")
        self.assertEqual(cp["active_intent_snapshot"]["scope"], ["approved scope"])

    def test_checkpoint_public_view_is_detached(self):
        session = session_for()
        session["activeIntent"]["constraints"] = ["Keep membership access."]
        cp = CP.emit_checkpoint(session)
        public = CP.checkpoint_public_view(cp)
        public["constraints"].clear()
        self.assertEqual(cp["constraints"], ["Keep membership access."])

    def test_interrupt_invalidates_pending_plan_and_preserves_history(self):
        session, cp = approved("Build a SaaS platform.")
        plan = {"planId": "old-plan", "tasks": [{"key": "pricing", "title": "Build SaaS subscriptions"}]}
        session["pendingPlan"] = plan
        CP.interrupt(session, correction="I am not building SaaS.")
        self.assertNotIn("pendingPlan", session)
        record = session["invalidatedPlans"][-1]
        self.assertEqual(record["plan"], plan)
        self.assertEqual(record["checkpoint_id"], cp["checkpoint_id"])
        self.assertIsNot(record["plan"], plan)

    def test_interrupt_without_pending_plan_is_supported(self):
        session, _ = approved()
        result = CP.interrupt(session, correction="Do not add a pricing tier.")
        self.assertTrue(result["mutationFrozen"])
        self.assertNotIn("pendingPlan", session)

    def test_interrupt_cancels_waiting_tasks_and_rejects_old_binding(self):
        session, _ = approved()
        task = CP.bind_authorization(session, {"taskId": "t1", "status": "ready"})
        session["queue"]["t1"] = task
        result = CP.interrupt(session, correction="I am not building SaaS.")
        self.assertEqual(task["status"], "cancelled")
        self.assertIn("t1", result["cancelledTaskIds"])
        with self.assertRaises(CP.CheckpointError):
            CP.assert_binding(session, task)

    def test_corrected_approval_never_authorizes_old_task(self):
        session, _ = approved()
        old = CP.bind_authorization(session, {"status": "ready"})
        result = CP.interrupt(session, correction="I am not building SaaS.")
        new = result["newCheckpoint"]
        CP.approve_checkpoint(session, new["checkpoint_id"])
        with self.assertRaises(CP.CheckpointError):
            CP.assert_binding(session, old)

    def test_cancelled_and_invalidated_objects_cannot_execute(self):
        session, _ = approved()
        for status in ("cancelled", "invalidated", "superseded", "disliked", "correction_mode"):
            with self.subTest(status=status):
                obj = CP.bind_authorization(session, {"status": status})
                with self.assertRaises(CP.CheckpointError):
                    CP.assert_binding(session, obj)

    def test_tainted_or_cancel_requested_objects_cannot_execute(self):
        session, _ = approved()
        for marker in ("tainted", "cancelRequested"):
            with self.subTest(marker=marker):
                obj = CP.bind_authorization(session, {"status": "ready", marker: True})
                with self.assertRaises(CP.CheckpointError):
                    CP.assert_binding(session, obj)

    def test_current_intent_drift_blocks_all_side_effect_gates(self):
        session, _ = approved()
        session["activeIntent"]["product_intent"] = "Build a SaaS platform."
        for kind in CP.SIDE_EFFECT_KINDS:
            with self.subTest(kind=kind):
                self.assertFalse(CP.side_effect_allowed(session, kind))

    def test_refinement_changes_invalidate_authority(self):
        session, _ = approved()
        session["activeIntent"].setdefault("refinements", []).append("Build SaaS subscription tiers.")
        with self.assertRaises(CP.CheckpointError):
            CP.require_authorized_checkpoint(session)

    def test_assumption_changes_invalidate_authority(self):
        session, _ = approved()
        session["activeIntent"].setdefault("assumptions", []).append("The product is SaaS.")
        with self.assertRaises(CP.CheckpointError):
            CP.require_authorized_checkpoint(session)

    def test_snapshot_drift_blocks_authority(self):
        session, cp = approved()
        cp["active_intent_snapshot"]["product_intent"] = "Build another product."
        with self.assertRaises(CP.CheckpointError):
            CP.require_authorized_checkpoint(session)

    def test_missing_snapshot_does_not_authorize_execution(self):
        session, cp = approved()
        cp.pop("active_intent_snapshot")
        with self.assertRaises(CP.CheckpointError):
            CP.require_authorized_checkpoint(session)

    def test_stale_current_checkpoint_cannot_execute(self):
        session, _ = approved()
        session["currentCheckpointId"] = "different-checkpoint"
        with self.assertRaises(CP.CheckpointError):
            CP.require_authorized_checkpoint(session)

    def test_generation_authority_is_required(self):
        for where in ("session", "checkpoint"):
            with self.subTest(where=where):
                session, cp = approved()
                if where == "session":
                    session["generationAuthority"] = False
                else:
                    cp["generation_authority"] = False
                with self.assertRaises(CP.CheckpointError):
                    CP.require_authorized_checkpoint(session)

    def test_proposal_cannot_be_approved_after_current_intent_drift(self):
        session = session_for()
        cp = CP.emit_checkpoint(session)
        session["activeIntent"]["product_intent"] = "Build another product."
        with self.assertRaises(CP.CheckpointError):
            CP.approve_checkpoint(session, cp["checkpoint_id"])
        self.assertEqual(cp["status"], "proposed")
        self.assertTrue(session["executionLocked"])

    def test_snapshot_cannot_be_edited_then_approved(self):
        session = session_for()
        cp = CP.emit_checkpoint(session)
        cp["active_intent_snapshot"]["prohibitions"].append("No membership prices.")
        with self.assertRaises(CP.CheckpointError):
            CP.approve_checkpoint(session, cp["checkpoint_id"])

    def test_foreign_session_checkpoint_cannot_be_approved(self):
        session = session_for()
        cp = CP.emit_checkpoint(session)
        cp["session_id"] = "another-session"
        with self.assertRaises(CP.CheckpointError):
            CP.approve_checkpoint(session, cp["checkpoint_id"])

    def test_fresh_approval_and_binding_still_work(self):
        session, cp = approved()
        obj = CP.bind_authorization(session, {"status": "ready"})
        CP.assert_binding(session, obj)
        self.assertEqual(CP.require_authorized_checkpoint(session), cp)

    def test_reload_preserves_correction_and_fresh_authorization(self):
        session, _ = approved("Build a community exchange.")
        session["activeIntent"]["constraints"] = ["Keep active business membership access."]
        # Emit a checkpoint for this explicitly updated test state.
        cp = CP.emit_checkpoint(session)
        CP.approve_checkpoint(session, cp["checkpoint_id"])
        result = CP.interrupt(session, correction="I am not building SaaS.")
        session = json.loads(json.dumps(session))
        CP.approve_checkpoint(session, result["newCheckpoint"]["checkpoint_id"])
        CP.require_authorized_checkpoint(session)
        self.assertIn("saas", session["activeIntent"]["non_goals"])
        self.assertIn("Keep active business membership access.", session["activeIntent"]["constraints"])

    def test_provider_and_membership_survive_correction_checkpoint(self):
        session, _ = approved("Build a SaaS platform.")
        session["activeIntent"]["constraints"] = [
            "Keep the approved external SaaS email provider.",
            "Keep active business memberships.",
        ]
        result = CP.interrupt(session, correction="I am not building SaaS.")
        self.assertEqual(result["newCheckpoint"]["constraints"], session["activeIntent"]["constraints"])
        self.assertEqual(len(result["newCheckpoint"]["constraints"]), 2)

    def test_action_receipt_rejects_changed_intent(self):
        session, _ = approved()
        session["activeIntent"]["constraints"].append("A new constraint.")
        with self.assertRaises(CP.CheckpointError):
            CP.receipt(session, action="worker.dispatch")
        self.assertEqual(session.get("actionReceipts", []), [])

    def test_empty_product_field_is_not_replaced_by_old_summary_in_hash(self):
        contract = {"product_intent": "", "intent_summary": "Build SaaS"}
        self.assertEqual(IC.intent_hash(contract), IC.intent_hash({"product_intent": ""}))

    def test_unchanged_legacy_hash_without_new_semantic_fields_is_stable(self):
        import hashlib
        payload = {"product_intent": "Build a community exchange."}
        fields = {
            "product_intent": payload["product_intent"], "process_directives": [],
            "constraints": [], "prohibitions": [], "acceptance_criteria": [],
            "required_concepts": [], "superseded_concepts": [], "scope": [],
            "non_goals": [], "operation": None, "operation_targets": [],
        }
        expected = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(IC.intent_hash(payload), expected)


if __name__ == "__main__":
    unittest.main()
