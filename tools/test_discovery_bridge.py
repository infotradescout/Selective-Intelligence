#!/usr/bin/env python3
"""Regression checks for the public discovery bridge and client pointers."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
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
        cls.indexnow = json.loads((ROOT / "adapters" / "indexnow.json").read_text(encoding="utf-8"))
        cls.queries = json.loads((ROOT / "adapters" / "discovery-queries.json").read_text(encoding="utf-8"))

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
        self.assertIn(
            '<meta name="google-site-verification" content="2HGXzalgV59ABuEMkGPZ9BiRYJGGR15458Wo8-10_zU">',
            self.html,
        )
        self.assertIn('type="application/ld+json"', self.html)
        structured_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', self.html, re.DOTALL)
        self.assertEqual(len(structured_blocks), 1)
        structured = json.loads(structured_blocks[0])
        self.assertEqual(structured["name"], TRIGGER)
        self.assertTrue(structured["isAccessibleForFree"])
        self.assertEqual(structured["about"]["name"], TRIGGER)
        self.assertEqual(structured["about"]["@type"], "DefinedTerm")
        self.assertIn("https://infotradescout.github.io/Selective-Intelligence/sitemap.xml", (DOCS / "robots.txt").read_text(encoding="utf-8"))
        self.assertIn("Selective Intelligence", (DOCS / "llms.txt").read_text(encoding="utf-8"))
        self.assertEqual(
            (DOCS / "SKILL.md").read_text(encoding="utf-8"),
            (ROOT / "skills" / "selective-intelligence" / "SKILL.md").read_text(encoding="utf-8"),
        )
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        self.assertRegex(citation, rf"(?m)^version: {re.escape(self.manifest['version'])}$")
        self.assertEqual(citation, (DOCS / "CITATION.cff").read_text(encoding="utf-8"))

    def test_problem_first_pages_are_distinct_and_crawlable(self) -> None:
        expected_guides = {
            "ai-built-the-wrong-thing",
            "ui-component-sprawl",
            "repository-drift",
            "free-ai-coding-workflow",
            "vague-idea-to-complete-outcome",
            "research-without-hallucinations",
            "one-prompt-website-first-deliverable",
            "reduce-ai-token-usage",
        }
        pages = [DOCS / "problems" / "index.html", DOCS / "questions" / "index.html", DOCS / "use-with-ai" / "index.html"]
        pages.extend(DOCS / "problems" / slug / "index.html" for slug in sorted(expected_guides))
        bodies = []
        for page in pages:
            self.assertTrue(page.exists(), page)
            body = page.read_text(encoding="utf-8")
            bodies.append(body)
            self.assertIn('<meta name="robots" content="index,follow', body)
            self.assertEqual(body.count('<link rel="canonical"'), 1)
            structured_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', body, re.DOTALL)
            self.assertEqual(len(structured_blocks), 1, page)
            json.loads(structured_blocks[0])
            self.assertNotIn("MealScout", body)
            self.assertNotIn("TradeScout profiles", body)
        self.assertEqual(len(bodies), len(set(bodies)))
        discovered = {path.parent.name for path in (DOCS / "problems").glob("*/index.html")}
        self.assertEqual(discovered, expected_guides)

    def test_query_map_is_broad_unique_and_truthfully_labeled(self) -> None:
        clusters = self.queries["clusters"]
        questions = [question for cluster in clusters for question in cluster["queries"]]
        self.assertGreaterEqual(len(clusters), 20)
        self.assertEqual(len(questions), 220)
        self.assertEqual(len({question.casefold() for question in questions}), len(questions))
        self.assertIn("no search-volume claim", self.queries["evidence_boundary"])
        self.assertTrue(self.queries["behavior"]["approval_required_before_adoption"])
        corpus = "\n".join(questions).casefold()
        for phrase in [
            "one prompt",
            "hallucinating",
            "scope drift",
            "five different versions of the same button",
            "without paying",
            "conflicting",
            "campaign",
            "private data",
            "resume",
        ]:
            self.assertIn(phrase, corpus)
        for cluster in clusters:
            self.assertEqual(len(cluster["queries"]), 10)
            self.assertTrue((DOCS / cluster["guide"] / "index.html").exists(), cluster["guide"])
        self.assertEqual(self.manifest["search_discovery"]["question_count"], len(questions))
        self.assertTrue(self.manifest["search_discovery"]["query_examples_are_not_search_volume"])
        public_queries = json.loads((DOCS / "discovery-queries.json").read_text(encoding="utf-8"))
        self.assertEqual(public_queries, self.queries)
        full_corpus = (DOCS / "llms-full.txt").read_text(encoding="utf-8")
        self.assertTrue(all(question in full_corpus for question in questions))

    def test_crawler_policy_sitemap_and_feed_cover_new_surfaces(self) -> None:
        robots = (DOCS / "robots.txt").read_text(encoding="utf-8")
        for agent in ["OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User", "PerplexityBot", "Perplexity-User"]:
            self.assertIn(f"User-agent: {agent}\nAllow: /", robots)
        self.assertIn("User-agent: *\nAllow: /", robots)
        sitemap = ET.parse(DOCS / "sitemap.xml")
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        sitemap_urls = {node.text for node in sitemap.findall("s:url/s:loc", namespace)}
        for url in [
            "https://infotradescout.github.io/Selective-Intelligence/problems/",
            "https://infotradescout.github.io/Selective-Intelligence/questions/",
            "https://infotradescout.github.io/Selective-Intelligence/use-with-ai/",
            "https://infotradescout.github.io/Selective-Intelligence/problems/one-prompt-website-first-deliverable/",
            "https://infotradescout.github.io/Selective-Intelligence/discovery-queries.json",
            "https://infotradescout.github.io/Selective-Intelligence/llms-full.txt",
            "https://infotradescout.github.io/Selective-Intelligence/SKILL.md",
        ]:
            self.assertIn(url, sitemap_urls)
        feed = ET.parse(DOCS / "feed.xml")
        self.assertGreaterEqual(len(feed.findall("{http://www.w3.org/2005/Atom}entry")), 10)

    def test_client_registry_is_bounded_and_source_backed(self) -> None:
        clients = self.manifest["clients"]
        self.assertEqual(self.manifest["client_support_verified_on"], "2026-08-14")
        ids = {client["id"] for client in clients}
        self.assertEqual(ids, {"chatgpt", "codex", "github-copilot", "claude-code", "cursor", "gemini-cli", "kiro", "web-ai"})
        for client in clients:
            self.assertTrue(client["official_documentation"].startswith("https://"))
            self.assertTrue(client["activation_boundary"])
        self.assertFalse(next(client for client in clients if client["id"] == "web-ai")["automatic_when_available"])
        self.assertTrue(self.manifest["repository_context"]["context_scoped"])
        self.assertTrue(self.manifest["repository_context"]["pointer_is_not_user_approval"])

    def test_indexnow_notification_is_valid_but_not_indexing_proof(self) -> None:
        key_file = DOCS / self.indexnow["key_file"]
        self.assertEqual(key_file.read_text(encoding="utf-8").strip(), self.indexnow["key"])
        self.assertEqual(self.indexnow["key_location"], f"https://infotradescout.github.io/Selective-Intelligence/{self.indexnow['key_file']}")
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "submit_indexnow.py"), "--dry-run"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["host"], "infotradescout.github.io")
        self.assertEqual(payload["keyLocation"], self.indexnow["key_location"])
        self.assertEqual(payload["urlList"], self.indexnow["url_list"])
        prefix = "https://infotradescout.github.io/Selective-Intelligence/"
        for url in self.indexnow["url_list"]:
            relative = url.removeprefix(prefix)
            local = DOCS / relative
            if not relative or relative.endswith("/"):
                local = local / "index.html"
            self.assertTrue(local.exists(), f"IndexNow URL has no generated public file: {url}")
        self.assertTrue(self.manifest["search_discovery"]["submitted_notification_is_not_indexing_proof"])

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
