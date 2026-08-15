import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import execution_contract as EC  # noqa: E402
import start_pack as SP  # noqa: E402


def valid_contract() -> dict:
    return {
        "schemaVersion": EC.SCHEMA_VERSION,
        "binding": {
            "projectId": "stone-inventory",
            "releaseId": "r001",
            "releaseVersion": "0.1.0",
            "buildId": "b001-capture",
            "lockVersion": "0.1.0",
        },
        "phase": "first_delivery",
        "wholeProduct": {
            "preserved": True,
            "summary": "Operational slab inventory from receiving through catalog publishing.",
            "complexity": "multi_deliverable",
        },
        "deliverables": [
            {
                "id": "D1",
                "active": True,
                "outcome": "Capture a slab and reopen its persisted inventory record.",
                "entry": "Open camera capture.",
                "ending": "Reopen and edit the saved inventory record.",
                "proof": [
                    {
                        "type": "automated_test",
                        "procedure": "Run the capture-to-reopen regression with a disposable inventory fixture.",
                        "expected": "The saved slab appears in inventory and reopens with editable fields.",
                        "observed": "The saved slab appeared in inventory and reopened with editable fields.",
                        "evidenceRef": "builds/b001-capture/evidence.md#capture-loop",
                    }
                ],
                "journeySteps": [
                    "Capture and crop one slab photo.",
                    "Save the inventory record.",
                    "Reopen and edit the persisted record.",
                ],
                "constraints": ["Use the established repository and preserve later deliverables."],
                "requirementIds": ["REQ-CAPTURE"],
                "completionScope": "active_deliverable",
                "completionClaims": [
                    {
                        "requirementId": "REQ-CAPTURE",
                        "scope": "active_deliverable",
                        "claim": "The saved slab record can be reopened and edited.",
                    }
                ],
                "excludedFromActive": ["Receiving, warehouse transfer, sales, and catalog publishing."],
                "informationComplete": True,
                "fitsExecutionWindow": True,
                "endToEnd": True,
            },
            {"id": "D2", "active": False, "outcome": "Add receiving and bundle inheritance."},
        ],
        "executionTarget": {
            "kind": "established_repository",
            "productionIntent": True,
            "establishedApplicationAvailable": True,
            "repositoryFit": "fit",
            "sitesRole": "none",
            "rationale": "The existing application supports durable operational workflows.",
            "constraintsConsidered": [
                "Durable state, permissions, image processing, and repository integration are required."
            ],
            "coreValueDependsOn": {name: True for name in EC.OPERATIONAL_DEPENDENCIES},
        },
    }


def apply_unbounded_self_certification(contract: dict) -> None:
    active = contract["deliverables"][0]
    active["outcome"] = "Build and release the entire product and every discovered capability"
    active["proof"] = [
        {
            "type": "manual_observation",
            "observation": "The implementation team confirms the complete product works",
            "evidenceRef": "builds/b001-capture/evidence.md#team-confirmation",
        }
    ]
    active["informationComplete"] = True
    active["fitsExecutionWindow"] = True
    active["endToEnd"] = True


class ExecutionContractTests(unittest.TestCase):
    def test_bounded_vertical_slice_in_established_repository_passes(self):
        self.assertEqual(EC.validate_contract(valid_contract()), [])

    def test_unbounded_or_layer_only_first_deliverable_fails(self):
        contract = valid_contract()
        contract["deliverables"][0]["fitsExecutionWindow"] = False
        contract["deliverables"][0]["endToEnd"] = False
        errors = EC.validate_contract(contract)
        self.assertIn("active deliverable must fit the execution window", errors)
        self.assertIn("active deliverable must be endToEnd", errors)

    def test_multi_deliverable_product_cannot_erase_later_work(self):
        contract = valid_contract()
        contract["deliverables"] = [contract["deliverables"][0]]
        errors = EC.validate_contract(contract)
        self.assertIn("a multi-deliverable product must preserve at least one later deliverable", errors)

    def test_sites_is_rejected_for_operational_production_application(self):
        contract = valid_contract()
        contract["executionTarget"]["kind"] = "sites"
        contract["executionTarget"]["sitesRole"] = "primary"
        errors = EC.validate_contract(contract)
        self.assertIn("Sites cannot be the primary target for an operational production application", errors)
        self.assertIn(
            "Sites execution must be classified as prototype or bounded_surface",
            errors,
        )

    def test_sites_remains_available_for_bounded_standalone_experience(self):
        contract = valid_contract()
        contract["wholeProduct"]["complexity"] = "single_deliverable"
        contract["deliverables"] = [contract["deliverables"][0]]
        contract["executionTarget"] = {
            "kind": "sites",
            "productionIntent": False,
            "establishedApplicationAvailable": False,
            "repositoryFit": "not_fit",
            "sitesRole": "prototype",
            "rationale": "This is a bounded standalone prototype without operational state.",
            "constraintsConsidered": [
                "No persistent operational state, permissions, backend workflow, or repository integration is needed."
            ],
            "coreValueDependsOn": {name: False for name in EC.OPERATIONAL_DEPENDENCIES},
        }
        self.assertEqual(EC.validate_contract(contract), [])

    def test_fitting_established_repository_wins_for_production(self):
        contract = copy.deepcopy(valid_contract())
        contract["executionTarget"]["kind"] = "standalone_application"
        errors = EC.validate_contract(contract)
        self.assertIn("use the fitting established application or repository for production execution", errors)

    def test_decision_booleans_cannot_be_omitted(self):
        for field in ("productionIntent", "establishedApplicationAvailable"):
            with self.subTest(field=field):
                contract = valid_contract()
                del contract["executionTarget"][field]
                self.assertIn(
                    f"executionTarget.{field} must be boolean",
                    EC.validate_contract(contract),
                )

    def test_binding_must_match_active_start_pack_identity(self):
        contract = valid_contract()
        expected = dict(contract["binding"])
        contract["binding"]["buildId"] = "unrelated-build"
        errors = EC.validate_contract(contract, expected_binding=expected)
        self.assertIn(
            "binding.buildId must match the active Start Pack value 'b001-capture'",
            errors,
        )

    def test_punctuation_layer_claim_and_self_attestation_do_not_pass(self):
        contract = valid_contract()
        contract["deliverables"][1]["outcome"] = "."
        contract["deliverables"][0]["journeySteps"] = ["UI layer"]
        contract["deliverables"][0]["proof"] = [
            {
                "type": "manual_observation",
                "procedure": "Open the saved record after completing the intake steps.",
                "expected": "The record reopens with editable fields.",
                "observed": "The author says this passes.",
                "evidenceRef": "build evidence",
            }
        ]
        errors = EC.validate_contract(contract)
        self.assertIn("deliverables[1].outcome must be a non-empty string", errors)
        self.assertIn(
            "active deliverable journeySteps must contain at least two meaningful steps",
            errors,
        )
        self.assertIn(
            "active deliverable proof[0] must report a reproducible observation, not confirmation or assertion",
            errors,
        )

    def test_typed_team_confirmation_is_not_reproducible_proof(self):
        contract = valid_contract()
        contract["deliverables"][0]["proof"] = [
            {
                "type": "manual_observation",
                "observation": "The implementation team confirms the complete product works",
                "evidenceRef": "builds/b001-capture/evidence.md#team-confirmation",
            }
        ]
        errors = EC.validate_contract(contract)
        self.assertIn("active deliverable proof[0].procedure must be meaningful", errors)
        self.assertIn("active deliverable proof[0].expected must be meaningful", errors)
        self.assertIn("active deliverable proof[0].observed must be meaningful", errors)
        self.assertIn(
            "active deliverable proof[0] must report a reproducible observation, not confirmation or assertion",
            errors,
        )

    def test_fully_shaped_maintainer_confirmation_is_still_self_attestation(self):
        contract = valid_contract()
        contract["deliverables"][0]["proof"] = [
            {
                "type": "manual_observation",
                "procedure": "Ask the maintainer whether the workflow works.",
                "expected": "The maintainer will approve the workflow.",
                "observed": "The maintainer confirms this works correctly.",
                "evidenceRef": "builds/b001-capture/evidence.md#maintainer-confirmation",
            }
        ]
        self.assertIn(
            "active deliverable proof[0] must report a reproducible observation, not confirmation or assertion",
            EC.validate_contract(contract),
        )

    def test_whole_product_self_certification_is_not_a_bounded_deliverable(self):
        contract = valid_contract()
        apply_unbounded_self_certification(contract)
        errors = EC.validate_contract(contract)
        self.assertIn("active deliverable proof[0].procedure must be meaningful", errors)
        self.assertIn(
            "active deliverable proof[0] must report a reproducible observation, not confirmation or assertion",
            errors,
        )
        self.assertIn(
            "active deliverable outcome may not claim whole-product or release completion",
            errors,
        )

    def test_placeholder_embedded_in_whole_product_summary_is_rejected(self):
        contract = valid_contract()
        contract["wholeProduct"]["summary"] = "TBD later after discovery"
        self.assertIn(
            "wholeProduct.summary must be a non-empty string",
            EC.validate_contract(contract),
        )

    def test_multi_deliverable_contract_requires_an_explicit_active_exclusion(self):
        contract = valid_contract()
        contract["deliverables"][0]["excludedFromActive"] = []
        self.assertIn(
            "multi-deliverable products require a meaningful excludedFromActive array",
            EC.validate_contract(contract),
        )

    def test_sites_primary_role_cannot_hide_behind_false_operational_flags(self):
        contract = valid_contract()
        contract["executionTarget"]["kind"] = "sites"
        contract["executionTarget"]["sitesRole"] = "primary"
        contract["executionTarget"]["productionIntent"] = False
        contract["executionTarget"]["establishedApplicationAvailable"] = False
        contract["executionTarget"]["repositoryFit"] = "not_fit"
        contract["executionTarget"]["coreValueDependsOn"] = {
            name: False for name in EC.OPERATIONAL_DEPENDENCIES
        }
        errors = EC.validate_contract(contract)
        self.assertIn(
            "Sites execution must be classified as prototype or bounded_surface",
            errors,
        )

    def test_sites_target_requires_an_explicit_bounded_role(self):
        contract = valid_contract()
        contract["wholeProduct"]["complexity"] = "single_deliverable"
        contract["deliverables"] = [contract["deliverables"][0]]
        contract["executionTarget"].update(
            {
                "kind": "sites",
                "productionIntent": False,
                "establishedApplicationAvailable": False,
                "repositoryFit": "not_fit",
                "sitesRole": "none",
                "coreValueDependsOn": {
                    name: False for name in EC.OPERATIONAL_DEPENDENCIES
                },
            }
        )
        self.assertIn(
            "Sites execution must be classified as prototype or bounded_surface",
            EC.validate_contract(contract),
        )


def prepare_definition_pack(root: Path) -> tuple[dict, Path]:
    args = [
        "init",
        "--root",
        str(root),
        "--project-id",
        "stone-inventory",
        "--project-name",
        "Stone Inventory",
        "--release-id",
        "r001",
        "--release-version",
        "0.1.0",
        "--build-id",
        "b001-capture",
        "--profile",
        "micro",
    ]
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        if SP.main(args) != 0:
            raise AssertionError("Start Pack initialization failed")
    pack = root / SP.PACK_DIR
    lock_path = pack / "lock.json"
    manifest = json.loads(lock_path.read_text(encoding="utf-8"))
    manifest["release"]["smallest_complete_loop"] = (
        "Capture, persist, list, reopen, and edit one inventory record."
    )
    manifest["authority"]["decision_owners"]["product"] = "Inventory owner"
    manifest["verdicts"]["intent"] = "supported"
    manifest["verdicts"]["definition"] = "locked"
    manifest["requirements"] = [
        {
            "id": "REQ-CAPTURE",
            "scope": "mvp",
            "state": "specified",
            "depends_on": [],
            "owners": ["inventory"],
            "actor": "Warehouse operator",
            "trigger": "Starts a slab intake",
            "behavior": "Captures and saves one editable inventory record",
            "constraints": "Persist through the established repository workflow",
            "negative": "Do not claim success when persistence or reopen fails",
            "unchanged": "Later receiving and catalog deliverables remain deferred",
            "acceptance": "Capture, save, list, reopen, and edit all pass",
            "owner": "inventory",
            "proof": "An end-to-end repository test observes the complete loop",
        }
    ]
    manifest["builds"][0]["requirements"] = ["REQ-CAPTURE"]
    manifest["builds"][0]["claimed_owners"] = ["inventory"]
    manifest["builds"][0]["base_revision"] = "abc123"
    manifest["decisions"] = [
        {
            "id": "DEC-BOUNDED",
            "class": "release_commitment",
            "status": "accepted",
            "statement": "The first build closes only the capture-to-reopen loop.",
            "authority": "Inventory owner",
        }
    ]
    for artifact in manifest["artifacts"]:
        artifact_path = pack / artifact["path"]
        if artifact_path.suffix == ".md":
            artifact_path.write_text(
                artifact_path.read_text(encoding="utf-8").replace(
                    "UNRESOLVED", "Resolved for the bounded capture delivery"
                ),
                encoding="utf-8",
            )
    contract_path = pack / manifest["active_build"]["execution_contract"]
    contract_path.write_text(json.dumps(valid_contract(), indent=2) + "\n", encoding="utf-8")
    lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest, contract_path


def strip_execution_contract_awareness(root: Path, manifest: dict, contract_path: Path) -> None:
    relative = manifest["active_build"].pop("execution_contract")
    manifest["builds"][0].pop("execution_contract")
    manifest.pop("execution_contract_policy")
    manifest["artifacts"] = [
        item for item in manifest["artifacts"] if item["path"] != relative
    ]
    contract_path.unlink()
    (root / SP.PACK_DIR / "lock.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def write_legacy_definition_seal(root: Path, manifest: dict) -> Path:
    pack = root / SP.PACK_DIR
    lock_path = pack / "lock.json"
    snapshot, error = SP.artifact_snapshot(pack, manifest)
    if error:
        raise AssertionError(error)
    for artifact in manifest["artifacts"]:
        artifact["sha256"] = snapshot[artifact["path"]]
    semantic = SP.semantic_contract_digest(manifest)
    timestamp = SP.utc_now()
    manifest["sealed_at"] = timestamp
    manifest["semantic_digest"] = semantic
    manifest["seal_history"] = [
        {
            "sealed_at": timestamp,
            "amendment": None,
            "transition": "definition",
            "checkpoint": False,
            "active_build": manifest["active_build"]["id"],
            "lock_version": manifest["builds"][0]["lock_version"],
            "build_status": manifest["builds"][0]["status"],
            "as_built_verdict": manifest["verdicts"]["as_built"],
            "invalidated_requirements": [],
            "semantic_digest": semantic,
            "artifact_digests": snapshot,
            "decision_authorities": dict(manifest["authority"]["decision_owners"]),
        }
    ]
    manifest["control_digest"] = SP.control_digest(manifest)
    lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return lock_path


class StartPackExecutionContractTests(unittest.TestCase):
    def seal(self, root: Path, transition: str) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            result = SP.main(["seal", "--root", str(root), "--transition", transition])
        return result, output.getvalue()

    def advance_to_build(self, root: Path) -> tuple[Path, Path]:
        _, contract_path = prepare_definition_pack(root)
        result, output = self.seal(root, "definition")
        self.assertEqual(result, 0, output)
        lock_path = root / SP.PACK_DIR / "lock.json"
        manifest = json.loads(lock_path.read_text(encoding="utf-8"))
        manifest["verdicts"]["build"] = "aligned"
        manifest["builds"][0]["status"] = "locked"
        lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        result, output = self.seal(root, "build")
        self.assertEqual(result, 0, output)
        return lock_path, contract_path

    def erase_active_pointer(self, lock_path: Path) -> dict:
        manifest = json.loads(lock_path.read_text(encoding="utf-8"))
        manifest["active_build"].pop("execution_contract")
        manifest["control_digest"] = SP.control_digest(manifest)
        lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest

    def test_init_registers_a_build_bound_blocked_execution_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    SP.main(
                        [
                            "init", "--root", str(root),
                            "--project-id", "project-one",
                            "--project-name", "Project One",
                            "--release-id", "r001",
                            "--build-id", "b001",
                            "--profile", "micro",
                        ]
                    ),
                    0,
                )
            pack = root / SP.PACK_DIR
            manifest = json.loads((pack / "lock.json").read_text(encoding="utf-8"))
            relative = manifest["active_build"]["execution_contract"]
            self.assertEqual(relative, manifest["builds"][0]["execution_contract"])
            self.assertIn(relative, {item["path"] for item in manifest["artifacts"]})
            contract = json.loads((pack / relative).read_text(encoding="utf-8"))
            self.assertEqual(contract["binding"]["projectId"], "project-one")
            self.assertIn("active deliverable must fit the execution window", EC.validate_contract(contract))

    def test_definition_seal_rejects_missing_unbounded_sites_and_substituted_contracts(self):
        mutations = {
            "missing": lambda manifest, contract: (
                manifest["active_build"].pop("execution_contract"),
                manifest["builds"][0].pop("execution_contract"),
            ),
            "unbounded": lambda manifest, contract: contract["deliverables"][0].__setitem__(
                "fitsExecutionWindow", False
            ),
            "operational_sites": lambda manifest, contract: (
                contract["executionTarget"].__setitem__("kind", "sites"),
                contract["executionTarget"].__setitem__("sitesRole", "primary"),
            ),
            "substituted": lambda manifest, contract: contract["binding"].__setitem__(
                "buildId", "unrelated-build"
            ),
            "omitted_decision": lambda manifest, contract: contract["executionTarget"].pop(
                "productionIntent"
            ),
            "whole_product_self_certified": lambda manifest, contract: apply_unbounded_self_certification(
                contract
            ),
            "placeholder_summary": lambda manifest, contract: contract["wholeProduct"].__setitem__(
                "summary", "TBD later after discovery"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest, contract_path = prepare_definition_pack(root)
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                mutate(manifest, contract)
                contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
                (root / SP.PACK_DIR / "lock.json").write_text(
                    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
                )
                result, output = self.seal(root, "definition")
                self.assertEqual(result, 2)
                self.assertIn("Execution contract blocks sealing", output)

    def test_build_seal_rejects_self_certification_and_placeholder_summary(self):
        mutations = {
            "whole_product_self_certified": apply_unbounded_self_certification,
            "placeholder_summary": lambda contract: contract["wholeProduct"].__setitem__(
                "summary", "TBD later after discovery"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, contract_path = prepare_definition_pack(root)
                result, output = self.seal(root, "definition")
                self.assertEqual(result, 0, output)

                lock_path = root / SP.PACK_DIR / "lock.json"
                manifest = json.loads(lock_path.read_text(encoding="utf-8"))
                manifest["verdicts"]["build"] = "aligned"
                manifest["builds"][0]["status"] = "locked"
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                mutate(contract)
                contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
                lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

                result, output = self.seal(root, "build")
                self.assertEqual(result, 2)
                self.assertIn("Execution contract blocks sealing", output)

    def test_stripped_new_pack_cannot_downgrade_before_first_seal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, contract_path = prepare_definition_pack(root)
            strip_execution_contract_awareness(root, manifest, contract_path)
            result, output = self.seal(root, "definition")
            self.assertEqual(result, 2)
            self.assertIn(
                "Execution contract migration required before any transition or checkpoint seal",
                output,
            )

    def test_genuine_legacy_shape_is_readable_but_requires_migration_to_seal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, contract_path = prepare_definition_pack(root)
            strip_execution_contract_awareness(root, manifest, contract_path)
            lock_path = write_legacy_definition_seal(root, manifest)

            for command in ("validate", "status", "resume"):
                output = StringIO()
                with redirect_stdout(output), redirect_stderr(output):
                    result = SP.main([command, "--root", str(root), "--json"])
                self.assertEqual(result, 0, f"{command}: {output.getvalue()}")

            legacy = json.loads(lock_path.read_text(encoding="utf-8"))
            legacy["verdicts"]["build"] = "aligned"
            legacy["builds"][0]["status"] = "locked"
            legacy["control_digest"] = SP.control_digest(legacy)
            lock_path.write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")
            result, output = self.seal(root, "build")
            self.assertEqual(result, 2)
            self.assertIn(
                "Execution contract migration required before any transition or checkpoint seal",
                output,
            )

    def test_legacy_discriminator_requires_no_policy_pointer_or_registered_contract(self):
        genuine_legacy_shape = {
            "active_build": {"id": "b001"},
            "builds": [{"id": "b001"}],
            "artifacts": [],
        }
        self.assertFalse(SP.execution_contract_aware(genuine_legacy_shape))
        contract_aware = copy.deepcopy(genuine_legacy_shape)
        contract_aware["execution_contract_policy"] = SP.EXECUTION_CONTRACT_POLICY
        self.assertTrue(SP.execution_contract_aware(contract_aware))

    def test_pointer_erasure_blocks_as_built_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path, _ = self.advance_to_build(root)
            manifest = self.erase_active_pointer(lock_path)
            manifest["verdicts"]["as_built"] = "partial"
            manifest["control_digest"] = SP.control_digest(manifest)
            lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            result, output = self.seal(root, "as-built")
            self.assertEqual(result, 2)
            self.assertIn("Execution contract blocks sealing", output)

            resume_output = StringIO()
            with redirect_stdout(resume_output), redirect_stderr(resume_output):
                resume_result = SP.main(["resume", "--root", str(root), "--json"])
            self.assertEqual(resume_result, 1)
            self.assertGreater(json.loads(resume_output.getvalue())["validation_errors"], 0)

    def test_pointer_erasure_blocks_release_after_valid_as_built(self):
        from test_council_completion_bridge import prepare_positive_completion

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path, _, _ = prepare_positive_completion(root)
            result, output = self.seal(root, "as-built")
            self.assertEqual(result, 0, output)

            manifest = self.erase_active_pointer(lock_path)
            manifest["verdicts"]["release"] = "closed"
            manifest["requirements"][0]["state"] = "verified"
            manifest["control_digest"] = SP.control_digest(manifest)
            lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result, output = self.seal(root, "release")
            self.assertEqual(result, 2)
            self.assertIn("Execution contract blocks sealing", output)

    def test_valid_operational_repository_contract_advances_definition_and_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_definition_pack(root)
            result, output = self.seal(root, "definition")
            self.assertEqual(result, 0, output)

            lock_path = root / SP.PACK_DIR / "lock.json"
            manifest = json.loads(lock_path.read_text(encoding="utf-8"))
            manifest["verdicts"]["build"] = "aligned"
            manifest["builds"][0]["status"] = "locked"
            lock_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            result, output = self.seal(root, "build")
            self.assertEqual(result, 0, output)
            resealed = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(resealed["seal_history"][-1]["transition"], "build")


class ExecutionContractWiringTests(unittest.TestCase):
    def test_skill_reference_evals_and_release_manifest_keep_the_gate_wired(self):
        skill_root = Path(__file__).resolve().parents[1]
        skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        checkpoint = (skill_root / "references" / "first-checkpoint.md").read_text(encoding="utf-8")
        evals = json.loads((skill_root / "evals" / "evals.json").read_text(encoding="utf-8"))
        distribution = json.loads(
            (skill_root / "metadata" / "distribution.json").read_text(encoding="utf-8")
        )

        self.assertIn("references/execution-bounding-and-target-selection.md", skill)
        self.assertIn("scripts/execution_contract.py", skill)
        self.assertIn("Discovery can be broad;", checkpoint)
        self.assertIn("execution must be bounded", checkpoint)
        self.assertIn("convenient-target adoption", checkpoint)

        case_ids = {case["id"] for case in evals["cases"]}
        self.assertIn("bounded-first-deliverable-operational-inventory", case_ids)
        self.assertIn("execution-target-reject-sites-operational-app", case_ids)

        release_files = set(distribution["release_files"])
        self.assertIn("references/execution-bounding-and-target-selection.md", release_files)
        self.assertIn("scripts/execution_contract.py", release_files)
        self.assertIn("tests/test_execution_contract.py", release_files)


if __name__ == "__main__":
    unittest.main()
