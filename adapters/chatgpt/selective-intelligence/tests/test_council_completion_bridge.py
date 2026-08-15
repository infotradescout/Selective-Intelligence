import argparse
import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS))

import council as GC  # noqa: E402
import start_pack as SP  # noqa: E402
from test_execution_contract import prepare_definition_pack  # noqa: E402


def seal(root: Path, transition: str) -> tuple[int, str]:
    output = StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        result = SP.main(["seal", "--root", str(root), "--transition", transition])
    return result, output.getvalue()


def build_verified_case(root: Path, manifest: dict) -> dict:
    pack = root / SP.PACK_DIR
    case_path = root / "council-case.json"
    args = argparse.Namespace(
        output=str(case_path), case_id="case-completion", task_id="task-completion",
        outcome="Verify the bounded active build outcome.",
        reason="Positive completion requires independently inspectable evidence.",
        primary_user="The release owner", job="Approve a bounded verified build",
        exact_task="Verify the active build against its registered implementation evidence.",
        output_contract="Return an applied Council pass with current proof.",
        success_criterion=["The active requirement has byte-verified evidence and an alignment pass."],
        non_negotiable=[], prohibition=[], tradeoff_rule=[],
        included_scope=["The active build requirement"], excluded_scope=["Later deliverables"],
        open_decision=[], confidence="locked",
        authoritative_seed_summary="Verify the bounded active build outcome.",
        intent_challenger_run_id="run-intent-objector", intent_challenger_provider="openai",
        intent_challenger_model="model-a", intent_challenger_surface="chat",
        intent_challenger_context_id="ctx-intent-objector",
        intent_competing_interpretation="The request might mean accepting a plausible completion summary without inspecting evidence.",
        intent_consequence_difference="That reading would allow completion without byte-verifiable implementation proof.",
        intent_challenge_resolution="candidate_supported",
        permission_policy_id="policy-default-deny", authority_owner="release-owner",
        project_id=manifest["project"]["id"], adapter_id="generic", adapter_version="1",
        destination=["local"], mode="single_model",
        required_independence="separate_context_same_model", currency="USD",
        sensitivity="internal", start_pack_root=str(root), run_id="run-orchestrator",
        provider="openai", model="model-a", surface="chat", context_id="ctx-orchestrator",
        billing_pool_id="pool-free", data_class=["internal"],
    )
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        if GC.command_init(args) != 0:
            raise AssertionError("Council case init failed")
    case = GC.read_json(case_path)
    evidence_path = pack / manifest["active_build"]["observation_receipt"]
    case["evidence"][0]["locator"] = manifest["active_build"]["observation_receipt"] + "#/receipts/0"
    case["evidence"][0]["summary"] = "Structured runner receipt for the active requirement and exact source revision."
    case["evidence"][0]["classification"] = "confirmed"
    case["evidence"][0]["content_digest"] = SP.sha256(evidence_path)
    GC.stamp_document(case)

    worker = GC.make_run(
        "worker", "run-worker", "openai", "model-a", "work", "ctx-worker",
        "pool-free", ["internal"], "run-orchestrator",
    )
    GC.add_run(case, worker)
    GC.finish_case_update(case)
    parent_digest = case["canonical_digest"]
    worker_packet = GC.make_worker_packet(case, worker)
    GC.record_export(case, worker_packet, worker["run_id"], parent_digest)
    GC.finish_case_update(case)
    completed_worker = copy.deepcopy(worker)
    completed_worker["completed_at"] = GC.utc_now()
    response = GC.stamp_document(
        {
            "schema_version": GC.SCHEMA_VERSION, "packet_type": "worker_response",
            "packet_id": "worker-response-completion", "created_at": GC.utc_now(),
            "parent": {"packet_id": worker_packet["packet_id"], "packet_type": "worker_packet", "digest": worker_packet["canonical_digest"]},
            "canonical_digest": "", "role_run": completed_worker, "attempted_actions": [],
            "summary": "Verified the bounded active build against registered evidence.",
            "artifact_refs": [manifest["active_build"]["evidence"]], "assumptions": [], "unknowns": [],
            "proofs": [{
                "proof_id": "proof-outcome", "status": "valid",
                "claim": "The active bounded requirement is implemented and observed.",
                "evidence_refs": ["evidence-intent-seed"],
                "revision": manifest["builds"][0]["evidence_context"]["revision"],
                "observed_at": GC.utc_now(), "supersedes": None,
            }],
        }
    )
    GC.import_worker_response(case, response)
    GC.finish_case_update(case)

    objector = GC.make_run(
        "objector", "run-objector", "openai", "model-a", "chat", "ctx-objector",
        "pool-free", ["internal"], "run-worker",
    )
    GC.add_run(case, objector)
    GC.finish_case_update(case)
    parent_digest = case["canonical_digest"]
    objector_packet = GC.make_objector_packet(case, objector)
    GC.record_export(case, objector_packet, objector["run_id"], parent_digest)
    GC.finish_case_update(case)
    completed_objector = copy.deepcopy(objector)
    completed_objector["completed_at"] = GC.utc_now()
    objection = GC.stamp_document(
        {
            "schema_version": GC.SCHEMA_VERSION, "packet_type": "objector_response",
            "packet_id": "objector-response-completion", "created_at": GC.utc_now(),
            "parent": {"packet_id": objector_packet["packet_id"], "packet_type": "objector_packet", "digest": objector_packet["canonical_digest"]},
            "canonical_digest": "", "role_run": completed_objector,
            "independence_grade": "separate_context_same_model", "attempted_actions": [],
            "findings": [],
        }
    )
    GC.import_objector_response(case, objection)
    GC.finish_case_update(case)

    aligner = GC.make_run(
        "aligner", "run-aligner", "openai", "model-a", "chat", "ctx-aligner",
        "pool-free", ["internal"], "run-objector",
    )
    GC.add_run(case, aligner)
    GC.finish_case_update(case)
    parent_digest = case["canonical_digest"]
    alignment_packet = GC.make_alignment_packet(case, aligner)
    GC.record_export(case, alignment_packet, aligner["run_id"], parent_digest)
    GC.finish_case_update(case)
    completed_aligner = copy.deepcopy(aligner)
    completed_aligner["completed_at"] = GC.utc_now()
    alignment = GC.stamp_document(
        {
            "schema_version": GC.SCHEMA_VERSION, "packet_type": "alignment_record",
            "packet_id": "alignment-completion", "created_at": GC.utc_now(),
            "parent": {"packet_id": alignment_packet["packet_id"], "packet_type": "alignment_packet", "digest": alignment_packet["canonical_digest"]},
            "canonical_digest": "", "role_run": completed_aligner,
            "objector_response_digest": objection["canonical_digest"],
            "dispositions": [], "corrections": [], "alignment_verdict": "aligned",
            "workflow_gate": "pass", "open_finding_ids": [],
        }
    )
    if GC.cross_validate_alignment(case, alignment):
        raise AssertionError("Council alignment fixture failed cross-validation")
    GC.apply_alignment(case, alignment)
    GC.finish_case_update(case)
    if GC.validate_document(case):
        raise AssertionError("verified Council case fixture is invalid")
    return case


def prepare_positive_completion(root: Path) -> tuple[Path, dict, Path]:
    prepare_definition_pack(root)
    result, output = seal(root, "definition")
    if result:
        raise AssertionError(output)
    lock_path = root / SP.PACK_DIR / "lock.json"
    manifest = json.loads(lock_path.read_text(encoding="utf-8"))
    manifest["verdicts"]["build"] = "aligned"
    manifest["builds"][0]["status"] = "locked"
    lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    result, output = seal(root, "build")
    if result:
        raise AssertionError(output)
    manifest = json.loads(lock_path.read_text(encoding="utf-8"))
    manifest["verdicts"]["as_built"] = "reconciled"
    manifest["builds"][0]["status"] = "reconciled"
    manifest["builds"][0]["evidence_context"] = {
        "revision": "abc123-complete", "environment": "test", "configuration": "default",
        "role": "release verifier", "fixture": "disposable capture fixture",
        "observed_at": SP.utc_now(), "expected": "The complete bounded loop passes.",
        "actual": "The complete bounded loop passed.", "flaky": False,
    }
    manifest["requirements"][0]["state"] = "verified"
    lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    pack = root / SP.PACK_DIR
    output_path = pack / manifest["active_build"]["observation_output"]
    output_path.write_text(
        "capture-to-reopen: passed\nrecord persisted, listed, reopened, and edited\n",
        encoding="utf-8",
    )
    receipt_path = pack / manifest["active_build"]["observation_receipt"]
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": SP.OBSERVATION_RECEIPT_SCHEMA_VERSION,
                "receipts": [
                    {
                        "receipt_id": "receipt-capture",
                        "run_id": "run-worker",
                        "proof_id": "proof-outcome",
                        "requirement_id": "REQ-CAPTURE",
                        "source_revision": "abc123-complete",
                        "evidence_type": "automated_test",
                        "procedure": "Run the capture-to-reopen regression with a disposable inventory fixture.",
                        "expected": "The saved slab appears in inventory and reopens with editable fields.",
                        "observed": "The saved slab appeared in inventory and reopened with editable fields.",
                        "verdict": "passed",
                        "exit_code": 0,
                        "observed_at": SP.utc_now(),
                        "output_path": manifest["active_build"]["observation_output"],
                        "output_digest": SP.sha256(output_path),
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    case = build_verified_case(root, manifest)
    review_path = root / SP.PACK_DIR / manifest["active_build"]["council_review"]
    alignment = case["alignment_record"]
    review = {
        "schema_version": SP.COUNCIL_REVIEW_SCHEMA_VERSION,
        "status": "verified",
        "binding": SP._review_binding(manifest, manifest["builds"][0]),
        "case_packet_id": case["packet_id"],
        "case_digest": GC.document_digest(case),
        "alignment_packet_id": alignment["packet_id"],
        "alignment_digest": GC.document_digest(alignment),
        "requirement_proofs": [{
            "requirement_id": "REQ-CAPTURE",
            "proof_ids": ["proof-outcome"],
            "receipt_ids": ["receipt-capture"],
        }],
        "case": case,
    }
    review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    return lock_path, manifest, review_path


class CouncilCompletionBridgeTests(unittest.TestCase):
    def test_definition_build_and_partial_do_not_require_council_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_definition_pack(root)
            self.assertEqual(seal(root, "definition")[0], 0)
            lock_path = root / SP.PACK_DIR / "lock.json"
            manifest = json.loads(lock_path.read_text(encoding="utf-8"))
            manifest["verdicts"]["build"] = "aligned"
            manifest["builds"][0]["status"] = "locked"
            lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(seal(root, "build")[0], 0)
            manifest = json.loads(lock_path.read_text(encoding="utf-8"))
            manifest["verdicts"]["as_built"] = "partial"
            manifest["builds"][0]["status"] = "reconciled"
            manifest["builds"][0]["evidence_context"] = {
                "revision": "abc123-partial", "environment": "test", "configuration": "default",
                "role": "release verifier", "fixture": "disposable partial fixture",
                "observed_at": SP.utc_now(), "expected": "Observed evidence is classified.",
                "actual": "Evidence remains partial.", "flaky": False,
            }
            lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(seal(root, "as-built")[0], 0)

    def test_verified_digest_bound_council_case_allows_positive_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, _ = prepare_positive_completion(root)
            result, output = seal(root, "as-built")
            self.assertEqual(result, 0, output)

    def test_verified_review_remains_bound_for_release_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path, _, _ = prepare_positive_completion(root)
            result, output = seal(root, "as-built")
            self.assertEqual(result, 0, output)
            manifest = json.loads(lock_path.read_text(encoding="utf-8"))
            manifest["verdicts"]["release"] = "closed"
            lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result, output = seal(root, "release")
            self.assertEqual(result, 0, output)

    def test_pending_review_blocks_transactionally(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path, manifest, review_path = prepare_positive_completion(root)
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["status"] = "pending"
            review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
            before_lock = lock_path.read_bytes()
            before_review = review_path.read_bytes()
            result, output = seal(root, "as-built")
            self.assertEqual(result, 2)
            self.assertIn("verified Council review", output)
            self.assertEqual(lock_path.read_bytes(), before_lock)
            self.assertEqual(review_path.read_bytes(), before_review)

    def test_binding_or_case_digest_substitution_blocks(self):
        for mutation in ("binding", "case_digest"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, _, review_path = prepare_positive_completion(root)
                review = json.loads(review_path.read_text(encoding="utf-8"))
                if mutation == "binding":
                    review["binding"]["build_id"] = "other-build"
                else:
                    review["case_digest"] = "0" * 64
                review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
                self.assertEqual(seal(root, "as-built")[0], 2)

    def test_council_case_must_bind_the_exact_start_pack_subject(self):
        mutations = ("null", "project_id", "release_id", "semantic_digest")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, _, review_path = prepare_positive_completion(root)
                review = json.loads(review_path.read_text(encoding="utf-8"))
                binding = review["case"]["start_pack_binding"]
                if mutation == "null":
                    review["case"]["start_pack_binding"] = None
                elif mutation == "semantic_digest":
                    binding[mutation] = "0" * 64
                else:
                    binding[mutation] = "foreign-subject"
                GC.stamp_document(review["case"])
                review["case_digest"] = GC.document_digest(review["case"])
                review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
                self.assertEqual(seal(root, "as-built")[0], 2)

    def test_fake_or_digest_mismatched_evidence_blocks(self):
        for mutation in ("locator", "digest"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, _, review_path = prepare_positive_completion(root)
                review = json.loads(review_path.read_text(encoding="utf-8"))
                evidence = review["case"]["evidence"][0]
                if mutation == "locator":
                    evidence["locator"] = "plausible-but-missing.log#success"
                else:
                    evidence["content_digest"] = "f" * 64
                GC.stamp_document(review["case"])
                review["case_digest"] = GC.document_digest(review["case"])
                review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
                self.assertEqual(seal(root, "as-built")[0], 2)

    def test_governance_summary_cannot_be_sole_implementation_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, review_path = prepare_positive_completion(root)
            review = json.loads(review_path.read_text(encoding="utf-8"))
            governance = root / SP.PACK_DIR / "builds/b001-capture/evidence.md"
            self.assertIn("Verdict: Unverifiable", governance.read_text(encoding="utf-8"))
            evidence = review["case"]["evidence"][0]
            evidence["locator"] = "builds/b001-capture/evidence.md#/capture-loop"
            evidence["content_digest"] = SP.sha256(governance)
            GC.stamp_document(review["case"])
            review["case_digest"] = GC.document_digest(review["case"])
            review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
            result, output = seal(root, "as-built")
            self.assertEqual(result, 2)
            self.assertIn("qualifying structured runner receipt", output)

    def test_receipt_fragment_result_revision_and_output_digest_are_enforced(self):
        for mutation in ("fragment", "verdict", "revision", "proof", "run", "output_digest"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, manifest, review_path = prepare_positive_completion(root)
                review = json.loads(review_path.read_text(encoding="utf-8"))
                receipt_path = root / SP.PACK_DIR / manifest["active_build"]["observation_receipt"]
                receipt_document = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt = receipt_document["receipts"][0]
                if mutation == "fragment":
                    review["case"]["evidence"][0]["locator"] = manifest["active_build"]["observation_receipt"] + "#/receipts/99"
                elif mutation == "verdict":
                    receipt["verdict"] = "unverifiable"
                elif mutation == "revision":
                    receipt["source_revision"] = "stale-revision"
                elif mutation == "proof":
                    receipt["proof_id"] = "proof-foreign"
                elif mutation == "run":
                    receipt["run_id"] = "run-foreign"
                else:
                    receipt["output_digest"] = "f" * 64
                if mutation != "fragment":
                    receipt_path.write_text(json.dumps(receipt_document, indent=2) + "\n", encoding="utf-8")
                    review["case"]["evidence"][0]["content_digest"] = SP.sha256(receipt_path)
                GC.stamp_document(review["case"])
                review["case_digest"] = GC.document_digest(review["case"])
                review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
                lock_path = root / SP.PACK_DIR / "lock.json"
                output_path = root / SP.PACK_DIR / manifest["active_build"]["observation_output"]
                before = {
                    "lock": lock_path.read_bytes(),
                    "review": review_path.read_bytes(),
                    "receipt": receipt_path.read_bytes(),
                    "output": output_path.read_bytes(),
                }
                self.assertEqual(seal(root, "as-built")[0], 2)
                self.assertEqual(lock_path.read_bytes(), before["lock"])
                self.assertEqual(review_path.read_bytes(), before["review"])
                self.assertEqual(receipt_path.read_bytes(), before["receipt"])
                self.assertEqual(output_path.read_bytes(), before["output"])

    def test_requirement_coverage_and_distinct_contexts_are_enforced(self):
        for mutation in ("coverage", "context"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, _, review_path = prepare_positive_completion(root)
                review = json.loads(review_path.read_text(encoding="utf-8"))
                if mutation == "coverage":
                    review["requirement_proofs"] = []
                else:
                    review["case"]["alignment_record"]["role_run"]["context_id"] = "ctx-objector"
                    GC.stamp_document(review["case"]["alignment_record"])
                    GC.stamp_document(review["case"])
                    review["alignment_digest"] = GC.document_digest(review["case"]["alignment_record"])
                    review["case_digest"] = GC.document_digest(review["case"])
                review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
                self.assertEqual(seal(root, "as-built")[0], 2)

    def test_missing_pointer_and_legacy_positive_completion_require_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path, manifest, _ = prepare_positive_completion(root)
            manifest["active_build"].pop("council_review")
            lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result, output = seal(root, "as-built")
            self.assertEqual(result, 2)
            self.assertIn("council_review", output)


if __name__ == "__main__":
    unittest.main()
