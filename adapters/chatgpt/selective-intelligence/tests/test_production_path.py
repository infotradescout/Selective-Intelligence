from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
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
from policy_guard import PolicyGuard


def _approve_current(session: dict) -> dict:
    checkpoint = CP.current_checkpoint(session)
    assert checkpoint is not None
    return CP.approve_checkpoint(session, checkpoint["checkpoint_id"])


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


class CheckpointLockTests(unittest.TestCase):
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


class InterruptTests(unittest.TestCase):
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


class SessionTests(unittest.TestCase):
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


class WorkerPacketTests(unittest.TestCase):
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
