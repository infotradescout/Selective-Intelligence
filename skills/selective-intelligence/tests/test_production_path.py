from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SKILL_ROOT = TEST_DIR.parent
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

import capabilities as CAP
import checkpoint as CP
import intent_contract as IC
import lane_session as LS
import build_engine as BE
import site_quality as SQ
from policy_guard import PolicyGuard


def _approve_current(session: dict) -> dict:
    checkpoint = CP.current_checkpoint(session)
    assert checkpoint is not None
    return CP.approve_checkpoint(session, checkpoint["checkpoint_id"])


class SessionEnvironmentIsolationMixin:
    """Keep per-test session directories from leaking into later tests."""

    def setUp(self) -> None:
        super().setUp()
        self._prior_session_dir = os.environ.get("SI_SESSION_DIR")

    def tearDown(self) -> None:
        if self._prior_session_dir is None:
            os.environ.pop("SI_SESSION_DIR", None)
        else:
            os.environ["SI_SESSION_DIR"] = self._prior_session_dir
        super().tearDown()


class IntentContractTests(unittest.TestCase):
    def test_explicit_prohibitions_survive_classification(self):
        event = IC.classify_intent(
            "Build a page. Do not commit, push, or install dependencies. The page must show verified adapters only."
        )
        self.assertTrue(any("Do not" in value for value in event["prohibitions"]))
        self.assertTrue(any("verified" in value.lower() for value in event["acceptance_criteria"]))
        self.assertEqual(event["operation"], "ADD")

    def test_screenshot_failure_didnt_say_halt_is_retract(self):
        """Acceptance: 'i didnt say halt did i? nope.' → RETRACT, not product intent."""
        event = IC.classify_intent(
            "i didnt say halt did i? nope.",
            event_type="correction",
        )
        self.assertEqual(event["operation"], "RETRACT")
        self.assertTrue(any("halt" in t.lower() for t in event["operation_targets"]))
        self.assertEqual(event["product_intent"], "")
        # Must not fall through as a product ask.
        self.assertFalse(event["process_directives"])

    def test_retract_survives_conflicting_model_override(self):
        """Defect 1: structured_override must not defeat text-derived RETRACT."""
        phrase = "i didnt say halt did i? nope."
        for bad_op in ("ADD", "MODIFY"):
            event = IC.classify_intent(
                phrase,
                event_type="correction",
                structured_override={"operation": bad_op},
            )
            self.assertEqual(
                event["operation"],
                "RETRACT",
                msg=f"override {bad_op} must not defeat RETRACT",
            )
            self.assertTrue(any("halt" in t.lower() for t in event["operation_targets"]))
            self.assertEqual(event["product_intent"], "")

    def test_retract_does_not_union_into_refinements(self):
        base = IC.classify_intent("Build the status panel and keep working.")
        active = IC.merge_active_contract(None, base)
        # Simulate a bad prior interpretation that invented halt.
        active["process_directives"] = ["halt all work until freeze/resume"]
        active["intent_hash"] = IC.intent_hash(active)
        correction = IC.classify_intent("i didnt say halt did i? nope.", event_type="correction")
        merged = IC.merge_active_contract(active, correction)
        self.assertEqual(correction["operation"], "RETRACT")
        self.assertEqual(merged.get("lastOperation"), "RETRACT")
        self.assertFalse(any("halt" in d.lower() for d in merged.get("process_directives", [])))
        refinements = merged.get("refinements") or []
        self.assertFalse(any("halt" in r.lower() or "nope" in r.lower() for r in refinements))
        self.assertTrue(merged.get("retractedInterpretations"))


class CapabilityTests(unittest.TestCase):
    def test_only_probe_verified_capabilities_are_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            reports = CAP.inventory(probe_root=temp)
        python = next(report for report in reports if report["adapterId"] == "python3_runtime")
        self.assertTrue(python["discovered"])
        self.assertTrue(python["adapterImplemented"])
        self.assertEqual(python["probeStatus"], "verified")
        self.assertTrue(python["executable"])
        credential = next(report for report in reports if report["adapterId"] == "anthropic_credential_reference")
        self.assertFalse(credential["executable"])
        self.assertEqual(credential["verifiedCapabilities"], [])


class SiteQualityTests(unittest.TestCase):
    def test_complete_minimal_site_passes_without_network_or_paid_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "index.html").write_text(
                """<!doctype html><html lang=\"en\"><head><title>River Repair</title>
                <meta name=\"description\" content=\"Book trusted neighborhood repair help without a long intake form.\">
                <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
                <style>main{max-width:70rem;margin:auto}@media(max-width:40rem){main{padding:1rem}}</style>
                </head><body><nav><a href=\"#services\">Services</a></nav><main><h1>Repairs without the runaround</h1>
                <section id=\"services\"><p>Tell us what broke and choose a time.</p><a href=\"mailto:help@river.test\">Request help</a></section>
                </main></body></html>""",
                encoding="utf-8",
            )
            result = SQ.audit_site(root)
        self.assertTrue(result["passed"], result["checks"])
        self.assertEqual(result["passedChecks"], result["totalChecks"])
        self.assertEqual(result["root"], root.name)
        self.assertNotIn(str(root.parent), json.dumps(result))

    def test_placeholders_and_missing_delivery_basics_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "index.html").write_text(
                "<html><body><h1>Your Company</h1><a href='#'>Coming soon</a></body></html>",
                encoding="utf-8",
            )
            result = SQ.audit_site(root)
        failed = {check["check"] for check in result["checks"] if not check["passed"]}
        self.assertFalse(result["passed"])
        self.assertTrue({"language", "title", "description", "viewport", "links", "no_placeholders"}.issubset(failed))


class CheckpointLockTests(SessionEnvironmentIsolationMixin, unittest.TestCase):
    def test_si_stays_on_after_activation_and_fails_closed_if_tampered_with(self):
        with tempfile.TemporaryDirectory() as temp:
            os.environ["SI_SESSION_DIR"] = temp
            session = BE.start_project(
                request="Build the wanted result and do not let me accidentally skip the checks",
                workspace=str(Path(temp) / "ws"),
                canonical_roots=[],
                plan={"tasks": [{"key": "work", "title": "work", "queue": "ready", "kind": "worker"}]},
                auto_approve=True,
            )
            task = next(iter(session["queue"].values()))
            self.assertTrue(session["siActive"])
            self.assertEqual(session["governanceMode"], "always_on_after_activation")
            session["siActive"] = False
            LS.save_session(session)
            with self.assertRaisesRegex(BE.EngineError, "governance is not active"):
                BE.make_worker_packet(session_id=session["sessionId"], task_id=task["taskId"])

    def test_no_side_effecting_work_before_approved_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            os.environ["SI_SESSION_DIR"] = temp
            session = BE.start_project(
                request="Build a status panel",
                workspace=str(Path(temp) / "ws"),
                canonical_roots=[],
                plan={
                    "tasks": [
                        {"key": "discovery", "title": "discover", "queue": "discovery", "kind": "discovery"},
                        {"key": "work", "title": "work", "queue": "ready", "kind": "worker", "dependencies": ["discovery"]},
                    ]
                },
                auto_approve=False,
            )
            self.assertTrue(session["executionLocked"])
            self.assertTrue(session["mutationFrozen"])
            self.assertEqual(session["queue"], {})
            self.assertIsNotNone(session.get("pendingPlan"))
            current = CP.current_checkpoint(session)
            self.assertEqual(current["status"], "proposed")
            with self.assertRaises(BE.EngineError):
                BE.add_plan_tasks(session, session["pendingPlan"])
            with self.assertRaises(CP.CheckpointError):
                LS.add_task(session, title="sneaky", queue="ready")

    def test_start_project_defers_workspace_mkdir_until_approve(self):
        """Defect 2: no filesystem write before checkpoint approval."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            os.environ["SI_SESSION_DIR"] = str(root / "sessions")
            workspace = root / "ws-deferred"
            self.assertFalse(workspace.exists())
            session = BE.start_project(
                request="Build a status panel",
                workspace=str(workspace),
                canonical_roots=[],
                plan={
                    "tasks": [
                        {"key": "discovery", "title": "discover", "queue": "discovery", "kind": "discovery"},
                    ]
                },
                auto_approve=False,
            )
            self.assertTrue(session["executionLocked"])
            self.assertFalse(workspace.exists(), "workspace must not exist before approve")
            session = BE.approve_project(session_id=session["sessionId"])
            self.assertTrue(workspace.exists())
            self.assertTrue(session["generationAuthority"])

    def test_approve_unlocks_plan_and_binds_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            os.environ["SI_SESSION_DIR"] = str(root / "sessions")
            workspace = root / "ws"
            session = BE.start_project(
                request="Build a status panel",
                workspace=str(workspace),
                canonical_roots=[],
                plan={
                    "tasks": [
                        {"key": "discovery", "title": "discover", "queue": "discovery", "kind": "discovery"},
                        {"key": "work", "title": "work", "queue": "ready", "kind": "worker", "dependencies": ["discovery"]},
                    ]
                },
            )
            session = BE.approve_project(session_id=session["sessionId"])
            self.assertFalse(session["executionLocked"])
            self.assertTrue(session["authorizedCheckpointId"])
            self.assertTrue(session["queue"])
            for task in session["queue"].values():
                self.assertEqual(task["authorized_checkpoint_id"], session["authorizedCheckpointId"])
                self.assertEqual(task["authorized_intent_hash"], session["authorizedIntentHash"])


class InterruptTests(SessionEnvironmentIsolationMixin, unittest.TestCase):
    def test_interrupt_cancels_queued_and_running_and_taints_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            os.environ["SI_SESSION_DIR"] = str(root / "sessions")
            session = BE.start_project(
                request="Build a generic status panel",
                workspace=str(root / "ws"),
                canonical_roots=[],
                plan={
                    "tasks": [
                        {"key": "discovery", "title": "discover", "queue": "discovery", "kind": "discovery"},
                        {
                            "key": "work",
                            "title": "generic health",
                            "queue": "ready",
                            "kind": "worker",
                            "dependencies": ["discovery"],
                            "tags": ["generic_health"],
                        },
                    ]
                },
                auto_approve=True,
            )
            discovery = next(t for t in session["queue"].values() if t["metadata"]["planKey"] == "discovery")
            work = next(t for t in session["queue"].values() if t["metadata"]["planKey"] == "work")
            self.assertEqual(discovery["status"], "complete")
            # Put worker into running to prove interrupt does not skip in-flight statuses.
            ok, reason = LS.transition_task(session, work["taskId"], "running")
            self.assertTrue(ok, reason)
            LS.save_session(session)

            session, result = BE.interrupt_project(
                session_id=session["sessionId"],
                correction="i didnt say halt did i? nope.",
            )
            self.assertEqual(result["operation"], "RETRACT")
            self.assertTrue(session["mutationFrozen"])
            self.assertTrue(session["executionLocked"])
            self.assertTrue(session["correctionMode"])
            self.assertIn(work["taskId"], result["cancelledTaskIds"])
            self.assertTrue(any(session["queue"][tid].get("tainted") for tid in result["taintedEffectIds"] if tid in session["queue"]))
            # No new side effects until re-approve.
            with self.assertRaises(BE.EngineError):
                BE.make_worker_packet(session_id=session["sessionId"], task_id=work["taskId"])

    def test_generation_authority_session_and_checkpoint_on_approve_interrupt(self):
        """Defect 3: session generationAuthority restored on approve; false on interrupt."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            os.environ["SI_SESSION_DIR"] = str(root / "sessions")
            session = BE.start_project(
                request="Build a panel",
                workspace=str(root / "ws"),
                canonical_roots=[],
                plan={
                    "tasks": [
                        {"key": "discovery", "title": "discover", "queue": "discovery", "kind": "discovery"},
                    ]
                },
                auto_approve=False,
            )
            self.assertFalse(session["generationAuthority"])
            proposed = CP.current_checkpoint(session)
            self.assertFalse(proposed["generation_authority"])

            session = BE.approve_project(session_id=session["sessionId"])
            approved = CP.authorized_checkpoint(session)
            self.assertTrue(session["generationAuthority"])
            self.assertTrue(approved["generation_authority"])

            session, result = BE.interrupt_project(
                session_id=session["sessionId"],
                correction="i didnt say halt did i? nope.",
            )
            interrupted = CP.get_checkpoint(session, result["interruptedCheckpointId"])
            self.assertFalse(session["generationAuthority"])
            self.assertFalse(interrupted["generation_authority"])
            self.assertFalse(result["generationAuthority"])

            session = BE.approve_project(session_id=session["sessionId"])
            reapproved = CP.authorized_checkpoint(session)
            self.assertTrue(session["generationAuthority"])
            self.assertTrue(reapproved["generation_authority"])

    def test_stale_checkpoint_approval_fails_closed(self):
        """Defect 4: approving an older proposed checkpoint must fail closed."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            os.environ["SI_SESSION_DIR"] = str(root / "sessions")
            session = BE.start_project(
                request="Build a panel",
                workspace=str(root / "ws"),
                canonical_roots=[],
                auto_approve=False,
            )
            stale = CP.current_checkpoint(session)
            # Emit a newer proposed checkpoint so stale is no longer current.
            CP.emit_checkpoint(
                session,
                active_intent=session["activeIntent"],
                evidence_basis=["newer interpretation"],
                status="proposed",
            )
            LS.save_session(session)
            self.assertNotEqual(session["currentCheckpointId"], stale["checkpoint_id"])
            with self.assertRaises(BE.EngineError):
                BE.approve_project(
                    session_id=session["sessionId"],
                    checkpoint_id=stale["checkpoint_id"],
                )
            with self.assertRaises(CP.CheckpointError):
                CP.reject_checkpoint(session, stale["checkpoint_id"])
            with self.assertRaises(BE.EngineError):
                BE.interrupt_project(
                    session_id=session["sessionId"],
                    correction="nope",
                    disliked_checkpoint_id=stale["checkpoint_id"],
                )

    def test_stale_checkpoint_hash_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            os.environ["SI_SESSION_DIR"] = str(root / "sessions")
            session = BE.start_project(
                request="Build a panel",
                workspace=str(root / "ws"),
                canonical_roots=[],
                plan={
                    "tasks": [
                        {"key": "discovery", "title": "discover", "queue": "discovery", "kind": "discovery"},
                        {"key": "work", "title": "work", "queue": "ready", "kind": "worker", "dependencies": ["discovery"]},
                    ]
                },
                auto_approve=True,
            )
            work = next(t for t in session["queue"].values() if t["metadata"]["planKey"] == "work")
            work["authorized_intent_hash"] = "deadbeef" * 8
            LS.save_session(session)
            with self.assertRaises(BE.EngineError):
                BE.make_worker_packet(session_id=session["sessionId"], task_id=work["taskId"])


class SessionTests(SessionEnvironmentIsolationMixin, unittest.TestCase):
    def test_correction_interrupts_and_taints_instead_of_preserving_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            os.environ["SI_SESSION_DIR"] = temp
            session = LS.new_session("Build a generic status panel")
            _approve_current(session)
            discovery = LS.add_task(session, title="discover", queue="discovery", tags=["discovery"])
            LS.transition_task(session, discovery["taskId"], "running")
            LS.transition_task(session, discovery["taskId"], "verifying")
            LS.transition_task(session, discovery["taskId"], "complete")
            generic = LS.add_task(
                session,
                title="generic health",
                queue="ready",
                dependencies=[discovery["taskId"]],
                tags=["generic_health"],
                invalidation_conditions=["generic service health"],
            )
            # Move generic into verifying to prove we no longer skip that status.
            LS.transition_task(session, generic["taskId"], "running")
            LS.transition_task(session, generic["taskId"], "verifying")
            result = LS.add_correction(
                session,
                "Display only verified adapter capabilities, not generic service health.",
            )
            self.assertIn(generic["taskId"], result["cancelledTaskIds"])
            self.assertEqual(result["preservedCompletedTaskIds"], [])
            self.assertIn(discovery["taskId"], result["taintedEffectIds"])
            self.assertTrue(session["queue"][discovery["taskId"]].get("tainted"))
            self.assertTrue(session["mutationFrozen"])

    def test_approve_requires_matching_intent_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            os.environ["SI_SESSION_DIR"] = temp
            session = LS.new_session("Build a pantry board")
            checkpoint = CP.current_checkpoint(session)
            assert checkpoint is not None
            with self.assertRaises(CP.CheckpointError) as ctx:
                CP.approve_checkpoint(
                    session,
                    checkpoint["checkpoint_id"],
                    expected_intent_hash="deadbeef" * 8,
                )
            self.assertIn("stale authorized_intent_hash", str(ctx.exception))
            self.assertTrue(session["executionLocked"])
            CP.approve_checkpoint(
                session,
                checkpoint["checkpoint_id"],
                expected_intent_hash=checkpoint["intent_hash"],
            )
            self.assertFalse(session["executionLocked"])
            self.assertEqual(session["authorizedIntentHash"], checkpoint["intent_hash"])

    def test_text_gate_approve_and_correct_use_same_transactions(self):
        import text_gate as TG

        with tempfile.TemporaryDirectory() as temp:
            os.environ["SI_SESSION_DIR"] = temp
            session = BE.start_project(
                request="Continue the ISSA own-shell fix only.",
                workspace=str(Path(temp) / "ws"),
                canonical_roots=[],
                auto_approve=False,
            )
            cp = CP.current_checkpoint(session)
            assert cp is not None
            self.assertTrue(session["executionLocked"])

            with self.assertRaises(TG.TextGateError):
                TG.parse_text_gate("looks good 👍")
            with self.assertRaises(TG.TextGateError):
                TG.parse_text_gate("Approve / Correct")

            approved = BE.apply_text_gate(
                session_id=session["sessionId"],
                raw_response="APPROVE",
                checkpoint_id=cp["checkpoint_id"],
                intent_hash=cp["intent_hash"],
            )
            self.assertEqual(approved["action"], "approve")
            self.assertFalse(approved["executionLocked"])

            corrected = BE.apply_text_gate(
                session_id=session["sessionId"],
                raw_response="CORRECT: i didnt say halt did i? nope. Continue own-shell only.",
                checkpoint_id=session.get("authorizedCheckpointId") or session.get("currentCheckpointId"),
            )
            self.assertEqual(corrected["action"], "correct")
            self.assertEqual(corrected["operation"], "RETRACT")
            self.assertTrue(corrected["executionLocked"])
            self.assertTrue(corrected["resumeRequiresApproval"])
            new_id = corrected["siCheckpointId"]
            self.assertNotEqual(new_id, cp["checkpoint_id"])

            # Side effects remain blocked until the new checkpoint is approved.
            session = LS.load_session(session["sessionId"])
            with self.assertRaises(CP.CheckpointError):
                CP.require_authorized_checkpoint(session)

            # Stale id+hash fail closed.
            with self.assertRaises(BE.EngineError) as stale_ctx:
                BE.approve_project(
                    session_id=session["sessionId"],
                    checkpoint_id=cp["checkpoint_id"],
                    intent_hash=cp["intent_hash"],
                )
            self.assertIn("stale checkpoint", str(stale_ctx.exception))

            new_cp = CP.current_checkpoint(session)
            assert new_cp is not None
            BE.approve_project(
                session_id=session["sessionId"],
                checkpoint_id=new_cp["checkpoint_id"],
                intent_hash=new_cp["intent_hash"],
            )
            session = LS.load_session(session["sessionId"])
            self.assertFalse(session["executionLocked"])


class TextGateUnitTests(unittest.TestCase):
    def test_parse_approve_and_correct(self):
        import text_gate as TG

        self.assertEqual(TG.parse_text_gate("APPROVE")["action"], "approve")
        self.assertEqual(TG.parse_text_gate("approve")["action"], "approve")
        parsed = TG.parse_text_gate("CORRECT: keep own-shell only")
        self.assertEqual(parsed["action"], "correct")
        self.assertEqual(parsed["correction"], "keep own-shell only")
        prompt = TG.text_gate_prompt(checkpoint_summary="Fix own-shell path")
        self.assertIn("APPROVE", prompt)
        self.assertIn("CORRECT:", prompt)
        self.assertNotIn("👍", prompt)
        self.assertNotIn("👎", prompt)


class WorkerPacketTests(SessionEnvironmentIsolationMixin, unittest.TestCase):
    def test_packet_preserves_constraints_and_excludes_sensitive_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            session_dir = root / "sessions"
            workspace.mkdir()
            (workspace / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (workspace / ".env").write_text("API_KEY=should-not-export\n", encoding="utf-8")
            os.environ["SI_SESSION_DIR"] = str(session_dir)
            plan = {
                "tasks": [
                    {"key": "discovery", "title": "discover", "queue": "discovery", "kind": "discovery"},
                    {"key": "work", "title": "work", "queue": "ready", "kind": "worker", "dependencies": ["discovery"]},
                ]
            }
            session = BE.start_project(
                request="Change app.py. Do not commit or expose secrets.",
                workspace=str(workspace),
                canonical_roots=[],
                plan=plan,
                auto_approve=True,
            )
            task = next(t for t in session["queue"].values() if t["metadata"].get("planKey") == "work")
            packet = BE.make_worker_packet(session_id=session["sessionId"], task_id=task["taskId"])
            selected = {item["path"] for item in packet["contextBundle"]["selected"]}
            excluded = {item["path"] for item in packet["contextBundle"]["excluded"]}
            self.assertIn("app.py", selected)
            self.assertIn(".env", excluded)
            self.assertTrue(packet["activeIntent"]["prohibitions"])
            self.assertEqual(packet["authorized_checkpoint_id"], session["authorizedCheckpointId"])
            self.assertNotIn("API_KEY=should-not-export", json.dumps(packet))


class WorkerArtifactReuseTests(SessionEnvironmentIsolationMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        os.environ["SI_SESSION_DIR"] = str(self.root / "sessions")
        self.session = BE.start_project(
            request="Repair the local source while reusing existing owners",
            workspace=str(self.workspace), canonical_roots=[],
            plan={"tasks": [
                {"key": "work", "title": "Repair the local source", "kind": "worker", "queue": "ready"},
            ]}, auto_approve=True,
        )
        self.sid = self.session["sessionId"]
        self.task_id = next(iter(self.session["queue"]))

    def apply_files(self, files):
        return BE.apply_worker_artifact(
            session_id=self.sid, task_id=self.task_id,
            artifact={
                "sessionId": self.sid, "taskId": self.task_id,
                "authorized_checkpoint_id": self.session["authorizedCheckpointId"],
                "authorized_intent_hash": self.session["authorizedIntentHash"],
                "producer": {"adapterId": "structured_worker_packet", "surface": "deterministic test",
                             "generatedAt": "2026-09-08T00:00:00Z"},
                "files": files,
            },
        )

    def test_new_duplicate_owner_rejects_entire_artifact_before_target_writes(self):
        source = "def shared_value():\n    return 1\n"
        original = "def current_value():\n    return 0\n"
        (self.workspace / "owner.py").write_text(source, encoding="utf-8")
        target = self.workspace / "app.py"
        target.write_text(original, encoding="utf-8")
        before = LS.load_session(self.sid)

        with mock.patch.object(BE, "guarded_write_text", wraps=BE.guarded_write_text) as writer:
            with mock.patch.object(BE.tempfile, "mkstemp", wraps=BE.tempfile.mkstemp) as temporary:
                with self.assertRaisesRegex(BE.EngineError, "duplicate|ownership"):
                    self.apply_files({
                        "app.py": "def current_value():\n    return 2\n",
                        "new/copy.py": source,
                    })

        writer.assert_not_called()
        self.assertFalse(any(call.kwargs.get("prefix") == ".si-stage-" for call in temporary.call_args_list))
        self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertEqual((self.workspace / "owner.py").read_text(encoding="utf-8"), source)
        self.assertFalse((self.workspace / "new").exists())
        persisted = LS.load_session(self.sid)
        self.assertEqual(persisted["artifacts"], before["artifacts"])
        self.assertEqual(persisted["actionReceipts"], before["actionReceipts"])

    def test_existing_owner_cannot_be_replaced_with_duplicate_source(self):
        source = "def shared_value():\n    return 1\n"
        original = "def distinct_value():\n    return 2\n"
        owner = self.workspace / "owner.py"
        owner.write_text(source, encoding="utf-8")
        target = self.workspace / "app.py"
        target.write_text(original, encoding="utf-8")
        original_stat = target.stat()
        before = LS.load_session(self.sid)

        with mock.patch.object(BE, "guarded_write_text", wraps=BE.guarded_write_text) as writer:
            with mock.patch.object(BE.tempfile, "mkstemp", wraps=BE.tempfile.mkstemp) as temporary:
                with self.assertRaisesRegex(BE.EngineError, "duplicate|ownership"):
                    self.apply_files({"app.py": source})

        writer.assert_not_called()
        self.assertFalse(any(call.kwargs.get("prefix") == ".si-stage-" for call in temporary.call_args_list))
        self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertEqual(target.stat().st_mtime_ns, original_stat.st_mtime_ns)
        self.assertEqual(owner.read_text(encoding="utf-8"), source)
        persisted = LS.load_session(self.sid)
        self.assertEqual(persisted["artifacts"], before["artifacts"])
        self.assertEqual(persisted["actionReceipts"], before["actionReceipts"])

    def test_preexisting_duplicate_debt_allows_unrelated_source_repair(self):
        duplicate = "def legacy_value():\n    return 1\n"
        for name in ("legacy.py", "legacy_copy.py"):
            (self.workspace / name).write_text(duplicate, encoding="utf-8")
        target = self.workspace / "app.py"
        target.write_text("def current_value():\n    return 0\n", encoding="utf-8")
        repaired = "def current_value():\n    return 2\n"

        result = self.apply_files({"app.py": repaired})

        self.assertEqual(target.read_text(encoding="utf-8"), repaired)
        self.assertEqual([record["relativePath"] for record in result["written"]], ["app.py"])
        self.assertEqual(LS.load_session(self.sid)["queue"][self.task_id]["status"], "verifying")
        for name in ("legacy.py", "legacy_copy.py"):
            self.assertEqual((self.workspace / name).read_text(encoding="utf-8"), duplicate)

    def test_distinct_default_export_pages_are_module_local_owners(self):
        source = "export default function Page() { return <main>Home</main>; }\n"
        proposed = "export default function Page() { return <main>About</main>; }\n"
        owner = self.workspace / "app/page.tsx"
        owner.parent.mkdir()
        owner.write_text(source, encoding="utf-8")

        result = self.apply_files({"app/about/page.tsx": proposed})

        self.assertEqual(owner.read_text(encoding="utf-8"), source)
        self.assertEqual((self.workspace / "app/about/page.tsx").read_text(encoding="utf-8"), proposed)
        self.assertEqual([item["relativePath"] for item in result["written"]], ["app/about/page.tsx"])
        self.assertEqual(LS.load_session(self.sid)["queue"][self.task_id]["status"], "verifying")

    def test_empty_and_whitespace_package_markers_are_not_duplicate_implementations(self):
        for package, content in (("empty_owner", ""), ("whitespace_owner", " \n\t\n")):
            marker = self.workspace / package / "__init__.py"
            marker.parent.mkdir()
            marker.write_text(content, encoding="utf-8")

        proposed = {"empty_package/__init__.py": "", "whitespace_package/__init__.py": " \n\t\n"}
        result = self.apply_files(proposed)

        self.assertEqual({item["relativePath"] for item in result["written"]}, set(proposed))
        for name, content in proposed.items():
            self.assertEqual((self.workspace / name).read_text(encoding="utf-8"), content)
        self.assertEqual(LS.load_session(self.sid)["queue"][self.task_id]["status"], "verifying")

    def test_named_exported_component_and_hook_collisions_remain_denied(self):
        cases = (
            ("Button.tsx", "export function Button() { return <button>Save</button>; }\n",
             "export function Button() { return <button>Submit</button>; }\n"),
            ("useSession.ts", "export function useSession() { return {ready: true}; }\n",
             "export function useSession() { return {ready: false}; }\n"),
        )
        for filename, source, proposed in cases:
            with self.subTest(filename=filename):
                owner = self.workspace / filename
                owner.write_text(source, encoding="utf-8")
                with self.assertRaisesRegex(BE.EngineError, "PI002"):
                    self.apply_files({f"copies/{filename}": proposed})
                self.assertEqual(owner.read_text(encoding="utf-8"), source)
                self.assertFalse((self.workspace / "copies" / filename).exists())
                self.assertEqual(LS.load_session(self.sid)["queue"][self.task_id]["status"], "ready")

    def test_nonempty_default_export_implementation_copies_remain_denied(self):
        source = "export default function Page() { return <main>Home</main>; }\n"
        owner = self.workspace / "page.tsx"
        owner.write_text(source, encoding="utf-8")

        with self.assertRaisesRegex(BE.EngineError, "PI001"):
            self.apply_files({"copies/page.tsx": source})

        self.assertEqual(owner.read_text(encoding="utf-8"), source)
        self.assertFalse((self.workspace / "copies").exists())
        self.assertEqual(LS.load_session(self.sid)["queue"][self.task_id]["status"], "ready")

    def test_unchanged_content_keeps_verification_lifecycle_without_staging(self):
        content = "def current_value():\n    return 1\n"
        target = self.workspace / "app.py"
        target.write_text(content, encoding="utf-8")
        target.chmod(0o640)
        os.utime(target, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        original_stat = target.stat()
        before = LS.load_session(self.sid)

        with mock.patch.object(BE, "guarded_write_text", wraps=BE.guarded_write_text) as writer:
            with mock.patch.object(BE.tempfile, "mkstemp", wraps=BE.tempfile.mkstemp) as temporary:
                result = self.apply_files({"app.py": content})

        writer.assert_not_called()
        self.assertFalse(any(call.kwargs.get("prefix") == ".si-stage-" for call in temporary.call_args_list))
        self.assertEqual(target.read_text(encoding="utf-8"), content)
        self.assertEqual(target.stat().st_mtime_ns, original_stat.st_mtime_ns)
        self.assertEqual(target.stat().st_ino, original_stat.st_ino)
        self.assertEqual(target.stat().st_mode, original_stat.st_mode)
        self.assertEqual(result["written"], [])
        self.assertEqual(len(result["unchanged"]), 1)
        record = result["unchanged"][0]
        self.assertIs(record["changed"], False)
        self.assertEqual(record["relativePath"], "app.py")
        self.assertEqual(record["taskId"], self.task_id)
        self.assertEqual(record["authorized_checkpoint_id"], self.session["authorizedCheckpointId"])
        self.assertEqual(record["authorized_intent_hash"], self.session["authorizedIntentHash"])
        persisted = LS.load_session(self.sid)
        self.assertIn(record, persisted["artifacts"])
        task = persisted["queue"][self.task_id]
        self.assertEqual(task["status"], "verifying")
        self.assertEqual(task["attempts"][-1]["fileArtifactIds"], [record["artifactId"]])
        self.assertEqual(
            [receipt for receipt in persisted["actionReceipts"] if receipt["action"] == "filesystem.write"],
            [receipt for receipt in before["actionReceipts"] if receipt["action"] == "filesystem.write"],
        )

    def test_unchanged_content_lifecycle_does_not_reset_exhausted_handoff_limit(self):
        content = "def current_value():\n    return 1\n"
        (self.workspace / "app.py").write_text(content, encoding="utf-8")
        for _ in range(3):
            BE.make_worker_packet(session_id=self.sid, task_id=self.task_id)

        result = self.apply_files({"app.py": content})
        self.assertEqual(result["written"], [])
        self.assertEqual(len(result["unchanged"]), 1)
        session = LS.load_session(self.sid)
        self.assertEqual(session["queue"][self.task_id]["status"], "verifying")
        ok, reason = LS.transition_task(session, self.task_id, "repairing")
        self.assertTrue(ok, reason)
        LS.save_session(session)

        with self.assertRaisesRegex(BE.EngineError, "three worker handoff"):
            BE.make_worker_packet(session_id=self.sid, task_id=self.task_id)
        self.assertEqual(LS.load_session(self.sid)["workerHandoffUsage"]["totalExports"], 3)

    def test_normal_source_update_writes_and_enters_verification(self):
        target = self.workspace / "app.py"
        target.write_text("def current_value():\n    return 0\n", encoding="utf-8")
        updated = "def current_value():\n    return 3\n"

        result = self.apply_files({"app.py": updated})

        self.assertEqual(target.read_text(encoding="utf-8"), updated)
        self.assertEqual(len(result["written"]), 1)
        record = result["written"][0]
        self.assertEqual(record["relativePath"], "app.py")
        self.assertEqual(record["taskId"], self.task_id)
        persisted = LS.load_session(self.sid)
        self.assertIn(record, persisted["artifacts"])
        self.assertEqual(persisted["queue"][self.task_id]["status"], "verifying")
        write_receipts = [receipt for receipt in persisted["actionReceipts"]
                          if receipt["action"] == "filesystem.write"]
        self.assertEqual(len(write_receipts), 1)
        self.assertEqual(write_receipts[0]["details"]["files"], ["app.py"])


class WorkerHandoffAdmissionTests(SessionEnvironmentIsolationMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        os.environ["SI_SESSION_DIR"] = str(self.root / "sessions")
        self.session = BE.start_project(
            request="Build a local result", workspace=str(self.workspace), canonical_roots=[],
            plan={"tasks": [
                {"key": "work", "title": "Build a local result", "kind": "worker", "queue": "ready"},
                {"key": "other", "title": "Build another local result", "kind": "worker", "queue": "ready"},
            ]}, auto_approve=True,
        )
        self.sid = self.session["sessionId"]
        self.tasks = list(self.session["queue"])

    def packet(self, task=None):
        return BE.make_worker_packet(session_id=self.sid, task_id=task or self.tasks[0])

    def exhaust(self):
        for _ in range(3):
            self.packet()

    def test_fourth_export_is_denied_before_retrieval_and_without_state_change(self):
        self.exhaust()
        before = LS.load_session(self.sid)
        with mock.patch.object(BE.CB, "select_context") as selection:
            with self.assertRaisesRegex(BE.EngineError, "three worker handoff"):
                self.packet()
        selection.assert_not_called()
        self.assertEqual(LS.load_session(self.sid), before)

    def test_usage_survives_a_fresh_cli_process(self):
        self.exhaust()
        proc = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "build_engine.py"), "packet",
             "--session", self.sid, "--task", self.tasks[0]],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("three worker handoff", proc.stdout)
        self.assertNotIn("contextBundle", proc.stdout)

    def test_other_task_can_progress_and_reapproval_cannot_reset_same_task(self):
        self.exhaust()
        self.packet(self.tasks[1])
        with self.assertRaises(BE.EngineError):
            BE.approve_project(session_id=self.sid)
        with self.assertRaisesRegex(BE.EngineError, "three worker handoff"):
            self.packet()
        self.assertEqual(LS.load_session(self.sid)["workerHandoffUsage"]["totalExports"], 4)

    def test_failed_context_retrievals_are_also_bounded(self):
        (self.workspace / "app.py").write_text("import helper\n", encoding="utf-8")
        (self.workspace / "helper.py").write_text("# local result\n" * 2000, encoding="utf-8")
        for _ in range(3):
            with self.assertRaisesRegex(BE.EngineError, "cannot preserve"):
                self.packet()
        with mock.patch.object(BE.CB, "select_context") as selection:
            with self.assertRaisesRegex(BE.EngineError, "three worker handoff"):
                self.packet()
        selection.assert_not_called()
        usage = LS.load_session(self.sid)["workerHandoffUsage"]
        self.assertEqual(usage["totalRetrievals"], 3)
        self.assertEqual(usage["totalExports"], 0)

    def test_full_payload_is_bounded_even_when_selected_files_are_small(self):
        session = LS.load_session(self.sid)
        LS.add_fact(session, "Observed local result", {"observation": "x" * 65536})
        LS.save_session(session)
        with self.assertRaisesRegex(BE.EngineError, "65536 UTF-8 payload bytes"):
            self.packet()
        usage = LS.load_session(self.sid)["workerHandoffUsage"]
        self.assertEqual(usage["totalRetrievals"], 1)
        self.assertEqual(usage["totalExports"], 0)

    def test_receipt_counts_actual_final_packet_bytes(self):
        packet = self.packet()
        expected = len((json.dumps(packet, indent=2) + "\n").encode("utf-8"))
        state = LS.load_session(self.sid)
        self.assertEqual(state["workerHandoffUsage"]["totalPayloadBytes"], expected)
        self.assertEqual(state["events"][-1]["payload"]["payloadBytes"], expected)

    def test_accepted_work_and_failed_verification_allow_a_repair_handoff(self):
        self.exhaust()
        session = LS.load_session(self.sid)
        session["capabilityInventory"] = CAP.inventory(probe_root=self.workspace)
        LS.save_session(session)
        artifact = {
            "sessionId": self.sid, "taskId": self.tasks[0],
            "authorized_checkpoint_id": session["authorizedCheckpointId"],
            "authorized_intent_hash": session["authorizedIntentHash"],
            "producer": {"adapterId": "structured_worker_packet", "surface": "deterministic test",
                         "generatedAt": "2026-09-08T00:00:00Z"},
            "files": {"test_result.py": "import unittest\nclass Result(unittest.TestCase):\n    def test_result(self):\n        self.fail('repair needed')\n"},
        }
        BE.apply_worker_artifact(session_id=self.sid, task_id=self.tasks[0], artifact=artifact)
        result = BE.verify_task(session_id=self.sid, task_id=self.tasks[0],
                                command={"argv": [sys.executable, "-m", "unittest", "test_result"]})
        self.assertFalse(result["passed"])
        packet = self.packet()
        self.assertEqual(packet["taskId"], self.tasks[0])
        usage = LS.load_session(self.sid)["workerHandoffUsage"]
        self.assertEqual(usage["totalExports"], 4)
        self.assertEqual(usage["tasks"][self.tasks[0]]["retrievals"], 1)

    def test_malformed_persisted_ledger_is_denied(self):
        session = LS.load_session(self.sid)
        session["workerHandoffUsage"] = {"schemaVersion": "unrecognized"}
        LS.save_session(session)
        with self.assertRaisesRegex(BE.EngineError, "invalid worker handoff"):
            self.packet()

    def test_build_transport_counts_its_entire_wrapper(self):
        session = BE.start_project(
            request="Build a local result", workspace=str(self.workspace), canonical_roots=[],
            plan={"tasks": [{"key": "work", "title": "Build a local result", "kind": "worker",
                             "queue": "ready", "metadata": {"requirements": "x" * 31000}}]},
            auto_approve=True,
        )
        task_id = next(iter(session["queue"]))
        packet = BE.make_worker_packet(session_id=session["sessionId"], task_id=task_id)
        self.assertLess(len(json.dumps(packet, indent=2).encode("utf-8")), 65536)
        proc = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "build_engine.py"), "build", "--session", session["sessionId"]],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("65536 UTF-8 payload bytes", proc.stdout)
        self.assertNotIn("workerPacket", proc.stdout)

    def test_concurrent_processes_share_the_final_admission(self):
        self.packet()
        self.packet()
        argv = [sys.executable, "-B", str(SCRIPTS / "build_engine.py"), "packet",
                "--session", self.sid, "--task", self.tasks[0]]
        processes = [subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(2)]
        outputs = [proc.communicate(timeout=15) for proc in processes]
        self.assertEqual(sorted(proc.returncode for proc in processes), [0, 2], outputs)
        usage = LS.load_session(self.sid)["workerHandoffUsage"]
        self.assertEqual(usage["totalRetrievals"], 3)
        self.assertEqual(usage["totalExports"], 3)


class PolicyTests(unittest.TestCase):
    def test_denies_before_adapter_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            canonical = base / "canonical"
            disposable = base / "disposable"
            canonical.mkdir()
            disposable.mkdir()
            guard = PolicyGuard(canonical_roots=[canonical], writable_roots=[disposable])
            decision = guard.authorize(
                session_id="si-test",
                task_id="task-test",
                action={"kind": "filesystem.write", "path": str(canonical / "bad.txt")},
            )
            self.assertFalse(decision["allowed"])
            self.assertEqual(decision["adapterInvocationStatus"], "NOT_INVOKED")
            self.assertFalse((canonical / "bad.txt").exists())

            bypasses = [
                ["git", "-C", str(disposable), "commit", "-m", "bad"],
                ["bash", "-c", "git commit -m bad"],
                ["npm", "--prefix", str(disposable), "install", "bad-package"],
            ]
            for argv in bypasses:
                nested = guard.authorize(
                    session_id="si-test",
                    task_id="task-test",
                    action={"kind": "process.run", "argv": argv, "cwd": str(disposable)},
                )
                self.assertFalse(nested["allowed"], argv)
                self.assertEqual(nested["adapterInvocationStatus"], "NOT_INVOKED")


class FullVerticalTests(unittest.TestCase):
    def test_vertical(self):
        runner = TEST_DIR / "run_instruction_fidelity_vertical.py"
        with tempfile.TemporaryDirectory() as temp:
            evidence_out = Path(temp) / "evidence.json"
            env = os.environ.copy()
            env["SI_VERTICAL_EVIDENCE_OUT"] = str(evidence_out)
            proc = subprocess.run(
                [sys.executable, str(runner)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
            result = json.loads(proc.stdout)
            self.assertEqual(result["classification"], "PRODUCTION_MODULE_PATH_PASS")
            self.assertEqual(result["failedExitCode"], 1)
            self.assertEqual(result["passedExitCode"], 0)
            self.assertEqual(result["deniedActionCount"], 4)
            self.assertTrue(result["canonicalUnchanged"])
            self.assertEqual(result["finalState"], "VERIFIED_COMPLETE")
            self.assertTrue(evidence_out.exists())


if __name__ == "__main__":
    unittest.main()
