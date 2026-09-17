"""Counterexamples from a failed automatic-companion delivery; synthetic data only."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import delivery_acceptance as DA


class DeliveryAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.file("workflow.json", b'{"result":"fixture only"}')
        self.image = self.file("view.png", b'fixture-image-for-integrity-only')
        self.contract = {
            "schema": DA.SCHEMA, "project": "Synthetic automatic companion",
            "source_revision": "fixture-revision", "intent_source": "explicit-user-request",
            "canonical": {"code_root": "app", "entrypoint": "loopback:1234", "data_owner": "journal"},
            "user_facing": True, "requires_installation": True,
            "requirements": [{"id": "auto-harvest", "mode": "automatic", "primary": True,
                              "outcome": "Claim appears without entering a form",
                              "accepted_scopes": ["native"],
                              "required_evidence": ["workflow", "visual", "restart", "safety", "launch"]}],
        }
        self.packet = {
            "schema": "si.product_delivery.evidence.v1", "contract_hash": DA.digest(self.contract),
            "source_revision": self.contract["source_revision"], "canonical": self.contract["canonical"],
            "unresolved_user_rejections": [], "active_targets": [self.contract["canonical"]],
            "installation": {"running": True, "source_revision": self.contract["source_revision"],
                             "entrypoint": "loopback:1234", "artifact": self.artifact},
            "proofs": [self.proof(kind) for kind in ("workflow", "visual", "restart", "safety", "launch")],
        }

    def file(self, name, data):
        (self.root / name).write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    def proof(self, kind):
        return {"id": kind, "requirement_id": "auto-harvest", "kind": kind, "mode": "automatic",
                "status": "passed", "executed": True, "scope": "native", "runner": "synthetic-test-runner",
                "target": "app/automatic-harvest", "entrypoint": "loopback:1234",
                "source_revision": self.contract["source_revision"], "contract_hash": DA.digest(self.contract),
                "artifact": self.artifact, "manual_entry_steps": 0, "trigger_observed": True,
                "result_observed": True, "reviewed": True, "reviewer": "fixture-reviewer",
                "blocking_findings": [], "screenshot": self.image}

    def result(self):
        return DA.evaluate(self.contract, self.packet, self.root)

    def fails(self):
        result = self.result()
        self.assertFalse(result["passed"])
        self.assertTrue(result["blockers"])
        return result

    def test_complete_integrity_packet_only_reaches_review(self):
        self.assertEqual(self.result()["verdict"], "ready_for_review")
        self.assertEqual(self.result()["user_acceptance"], "not_claimed")

    def test_test_count_is_not_a_user_journey(self):
        self.packet["proofs"] = []
        self.packet["passed_tests"] = 10000
        self.fails()

    def test_manual_substitute_fails_automatic_requirement(self):
        for p in self.packet["proofs"]: p["mode"] = "manual"
        self.fails()

    def test_manual_form_in_automatic_path_fails(self):
        self.packet["proofs"][0]["manual_entry_steps"] = 1
        self.fails()

    def test_false_is_not_zero_manual_steps(self):
        self.packet["proofs"][0]["manual_entry_steps"] = False
        self.fails()

    def test_unobserved_game_event_fails(self):
        self.packet["proofs"][0]["trigger_observed"] = False
        self.fails()

    def test_unobserved_ui_result_fails(self):
        self.packet["proofs"][0]["result_observed"] = False
        self.fails()

    def test_synthetic_cannot_claim_native_acceptance(self):
        for p in self.packet["proofs"]: p["scope"] = "synthetic"
        self.fails()

    def test_wrong_revision_fails(self):
        self.packet["source_revision"] = "old"
        self.fails()

    def test_correction_invalidates_old_evidence(self):
        self.contract["requirements"][0]["outcome"] = "Changed authoritative outcome"
        self.fails()

    def test_second_app_blocks_delivery(self):
        self.packet["active_targets"].append({"entrypoint": "loopback:9999"})
        self.fails()

    def test_no_running_target_blocks_delivery(self):
        self.packet["active_targets"] = []
        self.fails()

    def test_working_url_is_not_installation_proof(self):
        self.packet["installation"].pop("artifact")
        self.fails()

    def test_stopped_installation_fails(self):
        self.packet["installation"]["running"] = False
        self.fails()

    def test_other_port_proof_is_rejected(self):
        self.packet["proofs"][0]["entrypoint"] = "loopback:9999"
        self.fails()

    def test_hash_mismatch_fails(self):
        (self.root / "workflow.json").write_bytes(b'changed')
        self.fails()

    def test_nonexistent_evidence_fails(self):
        (self.root / "workflow.json").unlink()
        self.fails()

    def test_path_traversal_fails(self):
        self.packet["proofs"][0]["artifact"] = {"path": "../workflow.json", "sha256": "0" * 64}
        self.fails()

    def test_symlink_escape_fails(self):
        outside = Path(self.temp.name).parent / (self.root.name + "-outside")
        outside.write_bytes(b'outside')
        self.addCleanup(outside.unlink)
        (self.root / "link").symlink_to(outside)
        self.assertFalse(DA._artifact({"path": "link", "sha256": hashlib.sha256(b'outside').hexdigest()}, self.root))

    def test_ui_review_blocker_fails(self):
        self.packet["proofs"][1]["blocking_findings"] = ["manual-first navigation"]
        self.fails()

    def test_screenshot_alone_is_not_visual_review(self):
        self.packet["proofs"][1].pop("reviewer")
        self.fails()

    def test_no_screenshot_fails(self):
        self.packet["proofs"][1].pop("screenshot")
        self.fails()

    def test_skip_is_not_pass(self):
        self.packet["proofs"][0]["status"] = "skipped"
        self.fails()

    def test_prepared_is_not_executed(self):
        self.packet["proofs"][0]["executed"] = False
        self.fails()

    def test_unresolved_user_rejection_blocks(self):
        self.packet["unresolved_user_rejections"] = ["not acceptable as first delivery"]
        self.fails()

    def test_missing_rejection_disposition_blocks(self):
        del self.packet["unresolved_user_rejections"]
        self.fails()

    def test_duplicate_proofs_block(self):
        self.packet["proofs"].append(copy.deepcopy(self.packet["proofs"][0]))
        self.fails()

    def test_missing_contract_fields_cannot_lower_bar(self):
        del self.contract["requirements"]
        self.fails()

    def test_invalid_enum_json_cannot_crash_gate(self):
        for field, value in (("mode", []), ("accepted_scopes", [{}]), ("required_evidence", [{}])):
            with self.subTest(field=field):
                c = copy.deepcopy(self.contract)
                c["requirements"][0][field] = value
                self.assertFalse(DA.evaluate(c, self.packet, self.root)["passed"])

    def test_cli_fails_closed_for_invalid_json(self):
        (self.root / "invalid.json").write_text("{bad")
        p = subprocess.run([sys.executable, str(SCRIPTS / "delivery_acceptance.py"),
                            "--contract", str(self.root / "invalid.json"), "--evidence", "missing",
                            "--artifact-root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertFalse(json.loads(p.stdout)["passed"])

    def test_no_progress_searches_do_not_loop(self):
        ledger = {}
        for _ in range(2):
            ledger = DA.admit_discovery(ledger, question="find owner", target="project", action="search")
        reloaded = json.loads(json.dumps(ledger))
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            DA.admit_discovery(reloaded, question="find owner", target="project", action="search")

    def test_known_path_is_read_not_searched(self):
        with self.assertRaisesRegex(ValueError, "Known target"):
            DA.admit_discovery({}, question="find owner", target="known.mjs", action="search", known_path=True)

    def test_pending_search_is_polled_not_restarted(self):
        ledger = {DA.digest(["q", "target"]): {"searches": 1, "pending": "search-id"}}
        with self.assertRaisesRegex(ValueError, "existing search handle"):
            DA.admit_discovery(ledger, question="q", target="target", action="search")
        self.assertEqual(DA.admit_discovery(ledger, question="q", target="target", action="poll"), ledger)

    def test_no_mutation_to_input_evidence(self):
        before = copy.deepcopy(self.packet)
        self.result()
        self.assertEqual(self.packet, before)



class QualityGateIntegrationTests(unittest.TestCase):
    setUp = DeliveryAcceptanceTests.setUp
    file = DeliveryAcceptanceTests.file
    proof = DeliveryAcceptanceTests.proof
    """Exercise the canonical CLI's explicit product mode with synthetic reports."""
    def cli(self, *extra):
        c=self.root/'contract.json';e=self.root/'evidence.json'
        c.write_text(json.dumps(self.contract));e.write_text(json.dumps(self.packet))
        return subprocess.run([sys.executable,str(SCRIPTS/'quality_gate.py'),*extra,
            '--contract',str(c),'--evidence',str(e),'--artifact-root',str(self.root)],capture_output=True,text=True)

    def test_canonical_quality_cli_checks_delivery(self):
        proc=self.cli('--delivery');self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['verdict'],'ready_for_review')

    def test_canonical_quality_cli_blocks_manual_substitute(self):
        self.packet['proofs'][0]['manual_entry_steps']=1
        proc=self.cli('--delivery');self.assertEqual(proc.returncode,1)
        self.assertEqual(json.loads(proc.stdout)['verdict'],'needs_repair')

    def test_product_inputs_cannot_silently_run_source_gate(self):
        proc=self.cli();self.assertEqual(proc.returncode,2)
        self.assertIn('--delivery',proc.stderr)

    def test_delivery_flag_without_contract_cannot_pass(self):
        proc=subprocess.run([sys.executable,str(SCRIPTS/'quality_gate.py'),'--delivery'],capture_output=True,text=True)
        self.assertEqual(proc.returncode,2)

    def test_unexpected_requirement_kind_type_fails_closed(self):
        self.contract['requirements'][0]['required_evidence']=5
        self.assertFalse(DA.evaluate(self.contract,self.packet,self.root)['passed'])

if __name__ == "__main__": unittest.main()
