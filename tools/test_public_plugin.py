#!/usr/bin/env python3
"""Verify the deterministic public Selective Intelligence plugin package."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from tools import public_plugin
except ImportError:  # direct execution from tools/
    import public_plugin  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]


class PublicPluginTests(unittest.TestCase):
    def write_fixture_archive(self, root: Path, names: list[str]) -> Path:
        archive_path = root / "fixture.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, b"fixture\n")
        return archive_path

    def test_doctor_and_deterministic_package(self) -> None:
        result = public_plugin.doctor()
        self.assertEqual(result["errors"], [], result)
        self.assertEqual(result["status"], "pass")

        first = Path(tempfile.mkdtemp(prefix="si-plugin-first-", dir=REPO_ROOT))
        second = Path(tempfile.mkdtemp(prefix="si-plugin-second-", dir=REPO_ROOT))
        try:
            first_path = first / public_plugin.archive_name()
            second_path = second / public_plugin.archive_name()
            public_plugin.write_archive(first_path)
            public_plugin.write_archive(second_path)
            self.assertEqual(
                hashlib.sha256(first_path.read_bytes()).hexdigest(),
                hashlib.sha256(second_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(public_plugin.zip_errors(first_path), [])
            with zipfile.ZipFile(first_path) as archive:
                names = archive.namelist()
                self.assertLessEqual(len(names), public_plugin.MAX_RUNTIME_ENTRIES)
                self.assertIn(".codex-plugin/plugin.json", names)
                self.assertIn("assets/icon.svg", names)
                self.assertIn("skills/selective-intelligence/subskills/si-worker/ROLE.md", names)
                self.assertNotIn("skills/selective-intelligence/subskills/si-worker/SKILL.md", names)
                self.assertFalse(any("/tests/" in name for name in names))
                self.assertFalse(any("/evals/results-" in name for name in names))
                self.assertFalse(any(name.endswith(("README.md", "CHANGELOG.md", "JUMPSTART.md")) for name in names))
                self.assertNotIn("skills/selective-intelligence/scripts/release.py", names)
                skill_files = [name for name in names if Path(name).name == "SKILL.md"]
                self.assertEqual(skill_files, ["skills/selective-intelligence/SKILL.md"])
                self.assertFalse(any(name.startswith(("mcp/", "apps/", "screenshots/")) for name in names))
                manifest = json.loads(archive.read(".codex-plugin/plugin.json"))
                self.assertEqual(manifest["name"], "selective-intelligence")
                self.assertEqual(manifest["skills"], "./skills/")
                self.assertEqual(manifest["version"], (public_plugin.SKILL_ROOT / "VERSION").read_text().strip())
                master = archive.read("skills/selective-intelligence/SKILL.md").decode("utf-8")
                self.assertIn("Public plugin rule:", master)
                self.assertIn(
                    "Do not choose or create ChatGPT Sites merely because the task involves a website.",
                    master,
                )
                self.assertEqual(
                    public_plugin.skill_frontmatter_errors(
                        master,
                        "skills/selective-intelligence/SKILL.md",
                    ),
                    [],
                )
                for icon_name in (
                    "assets/icon.svg",
                    "skills/selective-intelligence/assets/icon.svg",
                ):
                    self.assertEqual(
                        public_plugin.svg_dimension_errors(archive.read(icon_name), icon_name),
                        [],
                    )
        finally:
            shutil.rmtree(first, ignore_errors=True)
            shutil.rmtree(second, ignore_errors=True)

    def test_rejects_the_portal_reported_svg_and_skill_metadata_failures(self) -> None:
        undersized_viewbox = (
            b'<svg width="256" height="256" viewBox="0 0 24 24" '
            b'xmlns="http://www.w3.org/2000/svg"/>'
        )
        icon_errors = public_plugin.svg_dimension_errors(undersized_viewbox, "assets/icon.svg")
        self.assertTrue(any("viewBox" in error and "at least 48x48" in error for error in icon_errors))

        invalid_skill = """---
name: selective-intelligence
description: Recover failed work.
metadata:
  version: 1.0.3
---

# Selective Intelligence
"""
        metadata_errors = public_plugin.skill_frontmatter_errors(invalid_skill, "SKILL.md")
        self.assertTrue(any("only name and description" in error for error in metadata_errors))

        valid_skill = """---
name: selective-intelligence
description: Recover failed work.
---

# Selective Intelligence
"""
        self.assertEqual(public_plugin.skill_frontmatter_errors(valid_skill, "SKILL.md"), [])

    def test_archive_rejects_normalization_collision_type_conflict_and_long_path(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="si-plugin-adversarial-", dir=REPO_ROOT))
        try:
            collision = self.write_fixture_archive(root, ["Case.txt", "case.txt"])
            self.assertTrue(any("normal" in error and "collision" in error for error in public_plugin.zip_errors(collision)))

            conflict = self.write_fixture_archive(root, ["owner", "owner/child.txt"])
            self.assertTrue(any("path conflict" in error for error in public_plugin.zip_errors(conflict)))

            too_long = self.write_fixture_archive(root, ["a" * (public_plugin.MAX_PATH_BYTES + 1)])
            self.assertTrue(any("UTF-8 bytes" in error for error in public_plugin.zip_errors(too_long)))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_listing_uses_final_directory_limits(self) -> None:
        manifest = json.loads(public_plugin.MANIFEST_PATH.read_text(encoding="utf-8"))
        submission = json.loads(
            public_plugin.SUBMISSION_PATH.read_text(encoding="utf-8")
        )
        interface = manifest["interface"]
        self.assertLessEqual(len(interface["displayName"]), 30)
        self.assertLessEqual(len(interface["shortDescription"]), 30)
        self.assertLessEqual(len(interface["longDescription"]), 4_000)
        self.assertLessEqual(len(interface["developerName"]), 80)
        self.assertLessEqual(len(interface["defaultPrompt"]), 3)
        self.assertTrue(all(len(prompt) <= 128 for prompt in interface["defaultPrompt"]))
        self.assertEqual(public_plugin.manifest_errors(), [])
        website_case = next(
            case
            for case in submission["positive_test_cases"]
            if case["id"] == "one-prompt-website-useful-first-deliverable"
        )
        self.assertIn(
            "Does not invoke ChatGPT Sites",
            " ".join(website_case["expected_behavior"]),
        )


if __name__ == "__main__":
    unittest.main()
