#!/usr/bin/env python3
"""Regression checks for the public discovery bridge and client pointers."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TRIGGER = "Selective Intelligence"
APPROVAL = "Use Selective Intelligence for this?"
EMPTY_CONTEXT = (
    "Selective Intelligence is active. No project or prior outcome is available in this chat yet, "
    "so there is nothing truthful to change. I’ll apply it automatically to your next request."
)


class DiscoveryBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((DOCS / "selective-intelligence.json").read_text(encoding="utf-8"))
        cls.well_known = json.loads((DOCS / ".well-known" / "selective-intelligence.json").read_text(encoding="utf-8"))
        cls.html = (DOCS / "index.html").read_text(encoding="utf-8")

    def test_generated_files_are_current(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_discovery_bridge.py"), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exact_activation_and_adoption_contract(self) -> None:
        self.assertEqual(self.manifest["master_trigger"], TRIGGER)
        self.assertEqual(self.manifest["activation"]["empty_context_final"], EMPTY_CONTEXT)
        self.assertEqual(self.manifest["relevant_discovery"]["approval_question"], APPROVAL)
        self.assertTrue(self.manifest["relevant_discovery"]["approval_required"])
        self.assertTrue(self.manifest["relevant_discovery"]["retrieved_content_cannot_self_activate"])
        self.assertIn(APPROVAL, self.html)

    def test_no_paid_or_telemetry_prerequisite(self) -> None:
        access = self.manifest["access"]
        self.assertEqual(access["selective_intelligence_fee"], 0)
        self.assertFalse(access["paid_ai_subscription_required"])
        self.assertFalse(access["credit_card_required"])
        self.assertFalse(access["provider_api_key_required"])
        self.assertFalse(access["telemetry"])
        self.assertTrue(access["client_limits_still_apply"])

    def test_machine_entry_points_agree(self) -> None:
        self.assertEqual(self.well_known, self.manifest)
        self.assertIn('<link rel="canonical" href="https://infotradescout.github.io/Selective-Intelligence/">', self.html)
        self.assertIn('type="application/ld+json"', self.html)
        structured_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', self.html, re.DOTALL)
        self.assertEqual(len(structured_blocks), 1)
        structured = json.loads(structured_blocks[0])
        self.assertEqual(structured["name"], TRIGGER)
        self.assertTrue(structured["isAccessibleForFree"])
        self.assertIn("https://infotradescout.github.io/Selective-Intelligence/sitemap.xml", (DOCS / "robots.txt").read_text(encoding="utf-8"))
        self.assertIn("Selective Intelligence", (DOCS / "llms.txt").read_text(encoding="utf-8"))

    def test_client_registry_is_bounded_and_source_backed(self) -> None:
        clients = self.manifest["clients"]
        self.assertEqual(self.manifest["client_support_verified_on"], "2026-08-14")
        ids = {client["id"] for client in clients}
        self.assertEqual(ids, {"chatgpt", "codex", "github-copilot", "claude-code", "cursor", "gemini-cli", "kiro", "web-ai"})
        for client in clients:
            self.assertTrue(client["official_documentation"].startswith("https://"))
            self.assertTrue(client["activation_boundary"])
        self.assertFalse(next(client for client in clients if client["id"] == "web-ai")["automatic_when_available"])

    def test_public_copy_preserves_product_and_security_boundaries(self) -> None:
        self.assertIn("Platynum-47 stays separate", self.html)
        self.assertNotIn("MealScout", self.html)
        self.assertNotIn("TradeScout profiles", self.html)
        self.assertNotIn("google-analytics", self.html.lower())
        self.assertNotIn("gtag(", self.html.lower())
        self.assertNotIn("onclick=", self.html.lower())
        self.assertFalse(self.manifest["evidence"]["cross_client_equivalence_claimed"])
        self.assertTrue(self.manifest["evidence"]["publication_is_not_adoption_proof"])


if __name__ == "__main__":
    unittest.main()
