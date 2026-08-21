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
                self.assertIn(".codex-plugin/plugin.json", names)
                self.assertIn("assets/icon.svg", names)
                self.assertIn("skills/selective-intelligence/subskills/si-worker/ROLE.md", names)
                self.assertNotIn("skills/selective-intelligence/subskills/si-worker/SKILL.md", names)
                skill_files = [name for name in names if Path(name).name == "SKILL.md"]
                self.assertEqual(skill_files, ["skills/selective-intelligence/SKILL.md"])
                self.assertFalse(any(name.startswith(("mcp/", "apps/", "screenshots/")) for name in names))
                manifest = json.loads(archive.read(".codex-plugin/plugin.json"))
                self.assertEqual(manifest["name"], "selective-intelligence")
                self.assertEqual(manifest["skills"], "./skills/")
                master = archive.read("skills/selective-intelligence/SKILL.md").decode("utf-8")
                self.assertIn("Public plugin rule:", master)
        finally:
            shutil.rmtree(first, ignore_errors=True)
            shutil.rmtree(second, ignore_errors=True)

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
        interface = manifest["interface"]
        self.assertLessEqual(len(interface["displayName"]), 30)
        self.assertLessEqual(len(interface["shortDescription"]), 30)
        self.assertLessEqual(len(interface["longDescription"]), 4_000)
        self.assertLessEqual(len(interface["developerName"]), 80)
        self.assertLessEqual(len(interface["defaultPrompt"]), 3)
        self.assertTrue(all(len(prompt) <= 128 for prompt in interface["defaultPrompt"]))
        self.assertEqual(public_plugin.manifest_errors(), [])


if __name__ == "__main__":
    unittest.main()
