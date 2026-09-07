"""Synthetic regressions for product-model corrections; not model-behavior proof."""
from __future__ import annotations

import copy
import importlib.util
import json
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


class ProductModelPropagationGaps(unittest.TestCase):
    """Regression coverage for the three originally reproduced propagation gaps."""

    def test_rejected_product_summary_must_not_remain_active(self):
        active = intent.merge_active_contract(None, intent.classify_intent("Build a SaaS platform."))
        merged = intent.merge_active_contract(active, intent.classify_intent("I'm not building SaaS."))
        self.assertNotEqual(merged["product_intent"], "Build a SaaS platform.")

    def test_adapter_must_not_restore_rejected_required_concept(self):
        event = intent.classify_intent(
            "I'm not building SaaS.",
            structured_override={"operation": "RETRACT", "required_concepts": ["SaaS subscription tiers"]},
        )
        self.assertNotIn("SaaS subscription tiers", event["required_concepts"])

    def test_model_rejection_must_preserve_approved_external_provider(self):
        approved = "Keep the approved external SaaS email provider."
        active = intent.merge_active_contract(None, intent.classify_intent(
            "Connect real businesses.", structured_override={"constraints": [approved]},
        ))
        merged = intent.merge_active_contract(active, intent.classify_intent("I'm not building SaaS."))
        self.assertIn(approved, merged["constraints"])


class ProductModelContinuityTests(unittest.TestCase):
    def active(self, summary="Connect real businesses.", **fields):
        return intent.merge_active_contract(None, intent.classify_intent(
            summary, structured_override=fields or None,
        ))

    def corrected(self, active):
        return intent.merge_active_contract(active, intent.classify_intent("I'm not building SaaS."))

    def test_same_provider_word_does_not_authorize_product_identity(self):
        for value in (
            "Build a SaaS platform and keep the approved external SaaS email provider.",
            "Keep the approved external SaaS email provider while building a SaaS platform.",
            "Use the approved external SaaS email provider for our SaaS product.",
        ):
            with self.subTest(value=value):
                merged = self.corrected(self.active(assumptions=[value]))
                self.assertNotIn(value, merged["assumptions"])

    def test_negated_product_identity_and_safety_rules_survive(self):
        for value in (
            "Never describe the product as SaaS.",
            "Do not build SaaS subscription tiers.",
            "This product is not SaaS.",
            "Do not publish member prices.",
            "Only active business members see approved prices.",
        ):
            with self.subTest(value=value):
                merged = self.corrected(self.active(constraints=[value]))
                self.assertIn(value, merged["constraints"])

    def test_double_negative_does_not_launder_positive_model(self):
        for value in (
            "Do not forget to build a SaaS product.",
            "Never stop building SaaS subscription tiers.",
            "Do not remove SaaS subscription tiers.",
            "We are not just building a SaaS product.",
        ):
            with self.subTest(value=value):
                merged = self.corrected(self.active(assumptions=[value]))
                self.assertNotIn(value, merged["assumptions"])

    def test_spelled_out_alias_is_reconciled(self):
        merged = self.corrected(self.active("Build a software-as-a-service platform."))
        self.assertEqual(merged["product_intent"], "")

    def test_unaffected_summary_sentence_survives(self):
        active = self.active("Build a SaaS platform. Connect real businesses.")
        # The parser's product extraction deliberately excludes the second
        # sentence, so provide the exact mixed stored summary being tested.
        active["product_intent"] = "Build a SaaS platform. Connect real businesses."
        merged = self.corrected(active)
        self.assertEqual(merged["product_intent"], "Connect real businesses.")

    def test_old_summary_alias_cannot_supply_rejected_identity(self):
        active = self.active("Build a SaaS platform.")
        active["intent_summary"] = "Build a SaaS platform."
        merged = self.corrected(active)
        self.assertEqual(merged["product_intent"], "")
        self.assertEqual(merged["intent_summary"], "")

    def test_refinements_are_reconciled_without_discarding_other_work(self):
        active = self.active()
        active["refinements"] = ["Build SaaS subscription tiers.", "Keep approved membership pricing."]
        merged = self.corrected(active)
        self.assertEqual(merged["refinements"], ["Keep approved membership pricing."])

    def test_other_current_fields_are_reconciled(self):
        for key in ("process_directives", "constraints", "acceptance_criteria", "assumptions", "required_concepts", "scope"):
            with self.subTest(key=key):
                merged = self.corrected(self.active(**{key: ["Build SaaS subscription tiers."]}))
                self.assertEqual(merged[key], [])

    def test_adapter_other_fields_cannot_restore_model_on_correction(self):
        for key in ("process_directives", "constraints", "acceptance_criteria", "assumptions", "required_concepts", "scope"):
            with self.subTest(key=key):
                event = intent.classify_intent("I'm not building SaaS.", structured_override={
                    "operation": "RETRACT", key: ["Build SaaS subscription tiers."]
                })
                self.assertNotIn("Build SaaS subscription tiers.", event[key])
                self.assertTrue(event["contradictions"])

    def test_adapter_reentry_blocked_after_resume(self):
        active = json.loads(json.dumps(self.corrected(self.active())))
        for key in ("product_intent", "process_directives", "constraints", "acceptance_criteria", "assumptions", "required_concepts", "scope"):
            value = "Build a SaaS platform." if key == "product_intent" else ["Build SaaS subscription tiers."]
            with self.subTest(key=key):
                event = intent.classify_intent("Continue the approved work.", structured_override={key: value})
                merged = intent.merge_active_contract(active, event)
                if key == "product_intent":
                    self.assertNotIn(value, merged.get("refinements", []))
                else:
                    self.assertNotIn("Build SaaS subscription tiers.", merged[key])
                self.assertIn("saas", merged["non_goals"])

    def test_adapter_replace_cannot_erase_prior_model_rejection(self):
        active = self.corrected(self.active())
        event = intent.classify_intent("Continue the approved work.", structured_override={
            "operation": "SUPERSEDE", "product_intent": "Build a SaaS platform.",
            "non_goals": [], "superseded_concepts": [],
        })
        merged = intent.merge_active_contract(active, event)
        self.assertIn("saas", merged["non_goals"])
        self.assertNotEqual(merged["product_intent"], "Build a SaaS platform.")

    def test_user_can_explicitly_replace_prior_model_decision(self):
        active = self.corrected(self.active())
        event = intent.classify_intent("Replace prior scope. Build a SaaS product.")
        merged = intent.merge_active_contract(active, event)
        self.assertIn("Build a SaaS product.", merged["product_intent"])
        self.assertNotIn("saas", merged["non_goals"])
        self.assertNotIn("saas", merged["superseded_concepts"])

    def test_provider_and_member_rules_survive_resume(self):
        provider = "Keep the approved external SaaS email provider."
        active = self.corrected(self.active(constraints=[provider, "Preserve approved member pricing."]))
        resumed = json.loads(json.dumps(active))
        merged = intent.merge_active_contract(resumed, intent.classify_intent("Continue the approved work."))
        self.assertIn(provider, merged["constraints"])
        self.assertIn("Preserve approved member pricing.", merged["constraints"])

    def test_explicit_provider_retraction_is_not_exempt(self):
        provider = "Keep the approved external SaaS email provider."
        event = intent.classify_intent("Remove the SaaS email provider.", event_type="correction",
            structured_override={"operation": "RETRACT", "operation_targets": ["SaaS email provider"]})
        merged = intent.merge_active_contract(self.active(constraints=[provider]), event)
        self.assertNotIn(provider, merged["constraints"])

    def test_correction_does_not_mutate_original_snapshot(self):
        active = self.active(assumptions=["This is a SaaS product."])
        original = copy.deepcopy(active)
        self.corrected(active)
        self.assertEqual(active, original)

    def test_add_does_not_mutate_original_refinements(self):
        active = self.active()
        active["refinements"] = ["Keep the approved layout."]
        original = copy.deepcopy(active)
        intent.merge_active_contract(active, intent.classify_intent("Add the approved contact path."))
        self.assertEqual(active, original)

    def test_initial_contract_hash_matches_its_own_authority(self):
        active = self.active()
        self.assertEqual(active["intent_hash"], intent.intent_hash(active))

    def test_corrected_contract_hash_changes_and_remains_reproducible(self):
        active = self.active("Build a SaaS platform.")
        merged = self.corrected(active)
        self.assertNotEqual(active["intent_hash"], merged["intent_hash"])
        self.assertEqual(merged["intent_hash"], intent.intent_hash(merged))

    def test_first_message_correction_filters_adapter_fields(self):
        event = intent.classify_intent("I'm not building SaaS.", structured_override={
            "required_concepts": ["SaaS subscription tiers"]
        })
        active = intent.merge_active_contract(None, event)
        self.assertEqual(active["required_concepts"], [])
        self.assertEqual(active["intent_hash"], intent.intent_hash(active))

    def test_retracted_history_remains_audit_evidence_not_active_direction(self):
        active = self.active("Build a SaaS platform.")
        merged = self.corrected(active)
        self.assertEqual(merged["product_intent"], "")
        self.assertIn("Build a SaaS platform.", merged["lastOperationDiff"]["removed"]["product_intent"])
        self.assertEqual(merged["retractedInterpretations"][-1]["rawText"], "I'm not building SaaS.")

    def test_model_rejection_is_not_a_blanket_billing_ban(self):
        rules = ["Keep the approved membership fee.", "Preserve the approved billing provider.", "Keep the shared service."]
        merged = self.corrected(self.active(constraints=rules))
        self.assertEqual(merged["constraints"], rules)

    def test_invalid_adapter_shapes_fail_before_classification(self):
        for override in ({"operation_targets": "saas"}, {"required_concepts": "SaaS"}, {"unknown_field": []}):
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    intent.classify_intent("I'm not building SaaS.", structured_override=override)


if __name__ == "__main__":
    unittest.main()
