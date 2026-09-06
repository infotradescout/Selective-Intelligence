"""Synthetic regressions for product-model corrections; not model-behavior proof."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "intent_contract.py"
spec = importlib.util.spec_from_file_location("si_product_model_intent", SCRIPT)
assert spec is not None and spec.loader is not None
intent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intent)


class ProductModelCorrectionTests(unittest.TestCase):
    def assert_rejected_model(self, text: str, **kwargs: object) -> dict:
        event = intent.classify_intent(text, **kwargs)
        self.assertEqual(event["operation"], "RETRACT")
        self.assertIn("saas", event["operation_targets"])
        self.assertIn("saas", event["superseded_concepts"])
        self.assertIn("saas", event["non_goals"])
        self.assertEqual(event["product_intent"], "")
        self.assertEqual(event["rawText"], text)
        self.assertEqual(event["intent_hash"], intent.intent_hash(event))
        return event

    def test_informal_assumption_complaint(self):
        self.assert_rejected_model(
            "Another problem is the assistant assuming im building saas and thats not correct."
        )

    def test_explicit_correction_event(self):
        self.assert_rejected_model("I'm not building SaaS.", event_type="correction")

    def test_request_path_also_recognizes_correction(self):
        self.assert_rejected_model("I'm not building SaaS.")

    def test_curly_apostrophe(self):
        self.assert_rejected_model("I’m not building a SaaS platform.")

    def test_we_arent(self):
        self.assert_rejected_model("We aren't building SaaS.")

    def test_product_identity_rejection(self):
        self.assert_rejected_model("This isn't a traditional SaaS business.")

    def test_spelled_out_model(self):
        event = self.assert_rejected_model("I am not building software-as-a-service.")
        self.assertEqual(event["operation_targets"], ["saas"])
        self.assertNotIn("service", intent.concept_tokens(event["operation_targets"]))

    def test_you_assumed_retains_target(self):
        self.assert_rejected_model("You assumed I was building SaaS.")

    def test_conflicting_add_override_cannot_reframe_correction(self):
        self.assert_rejected_model(
            "I'm not building SaaS.",
            structured_override={"operation": "ADD", "product_intent": "Build a SaaS platform."},
        )

    def test_same_operation_override_cannot_erase_text_target(self):
        self.assert_rejected_model(
            "I'm not building SaaS.",
            structured_override={"operation": "RETRACT", "operation_targets": []},
        )

    def test_same_operation_preserves_additional_targets(self):
        event = self.assert_rejected_model(
            "I'm not building SaaS.",
            structured_override={"operation": "RETRACT", "operation_targets": ["invented upsell"]},
        )
        self.assertIn("invented upsell", event["operation_targets"])

    def test_explicit_saas_request_remains_supported(self):
        event = intent.classify_intent("Build a SaaS product with my approved pricing.")
        self.assertEqual(event["operation"], "ADD")
        self.assertEqual(event["operation_targets"], [])
        self.assertEqual(event["non_goals"], [])

    def test_not_just_is_not_a_model_rejection(self):
        event = intent.classify_intent("I'm not just building SaaS.")
        self.assertNotEqual(event["operation"], "RETRACT")
        self.assertEqual(event["operation_targets"], [])

    def test_quoted_example_does_not_set_product_identity(self):
        event = intent.classify_intent('Explain the sentence "I am not building SaaS".')
        self.assertEqual(event["operation_targets"], [])
        self.assertEqual(event["non_goals"], [])

    def test_membership_request_does_not_imply_saas(self):
        event = intent.classify_intent("Show approved member prices to active business members.")
        self.assertEqual(event["operation_targets"], [])
        self.assertNotIn("saas", " ".join(event["assumptions"]).lower())

    def test_existing_halt_retraction_still_works(self):
        event = intent.classify_intent("I didnt say halt.")
        self.assertEqual(event["operation"], "RETRACT")
        self.assertIn("halt", event["operation_targets"])

    def test_retraction_removes_stale_assumption_not_approved_membership(self):
        active = intent.merge_active_contract(None, intent.classify_intent(
            "Connect real businesses with customers.",
            structured_override={
                "assumptions": ["This is a SaaS product."],
                "acceptance_criteria": ["Active business members see approved prices."],
            },
        ))
        merged = intent.merge_active_contract(active, intent.classify_intent("I'm not building SaaS."))
        self.assertEqual(merged["assumptions"], [])
        self.assertEqual(merged["product_intent"], "Connect real businesses with customers.")
        self.assertIn("Active business members see approved prices.", merged["acceptance_criteria"])
        self.assertNotIn("refinements", merged)
        self.assertIn("saas", merged["non_goals"])


if __name__ == "__main__":
    unittest.main()
