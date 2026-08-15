import copy
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import execution_contract as EC  # noqa: E402


def valid_contract() -> dict:
    return {
        "schemaVersion": EC.SCHEMA_VERSION,
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
                "proof": ["Capture, save, list, reopen, and edit pass end to end."],
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
            "coreValueDependsOn": {name: True for name in EC.OPERATIONAL_DEPENDENCIES},
        },
    }


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
        self.assertIn("Sites primary role conflicts with operational core dependencies", errors)

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
            "coreValueDependsOn": {name: False for name in EC.OPERATIONAL_DEPENDENCIES},
        }
        self.assertEqual(EC.validate_contract(contract), [])

    def test_fitting_established_repository_wins_for_production(self):
        contract = copy.deepcopy(valid_contract())
        contract["executionTarget"]["kind"] = "standalone_application"
        errors = EC.validate_contract(contract)
        self.assertIn("use the fitting established application or repository for production execution", errors)


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
