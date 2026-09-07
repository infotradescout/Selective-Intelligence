"""Public-plugin delivery regressions using copied canonical runtime inputs.

These tests execute packaging code and packaged commands. They do not claim
platform acceptance, installation, or obedience by a running model.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

try:
    from tools import public_plugin
    from tools.build_chatgpt_adapter import EXECUTION_RUNTIME_FILES
except ImportError:
    import public_plugin
    from build_chatgpt_adapter import EXECUTION_RUNTIME_FILES


class PublicPluginDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="si-public-delivery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.skill = self.root / "skills/selective-intelligence"
        self.manifest_path = self.skill / "metadata/distribution.json"
        original = public_plugin.SKILL_ROOT
        self.distribution = json.loads((original / "metadata/distribution.json").read_text())
        for relative in self.distribution["runtime_files"] + ["metadata/distribution.json"]:
            destination = self.skill / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original / relative, destination)
        manifest = self.root / "plugin-submission/plugin.json"
        manifest.parent.mkdir(parents=True)
        shutil.copyfile(public_plugin.MANIFEST_PATH, manifest)
        icon = self.root / "assets/icon.svg"
        icon.parent.mkdir(parents=True)
        shutil.copyfile(public_plugin.ICON_PATH, icon)
        for name, value in (("REPO_ROOT", self.root), ("SKILL_ROOT", self.skill),
                            ("MANIFEST_PATH", manifest), ("ICON_PATH", icon)):
            patcher = mock.patch.object(public_plugin, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.destination = self.root / "out/plugin.zip"

    def write_members(self, files, name="modified.zip"):
        path = self.root / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative, content in sorted(files.items()):
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
        return path

    def test_complete_real_runtime_passes_archive_validation(self):
        result = public_plugin.write_archive(self.destination)
        self.assertEqual(result["files"], len(self.distribution["runtime_files"]) + 2)
        self.assertLessEqual(result["files"], public_plugin.MAX_RUNTIME_ENTRIES)
        self.assertEqual(public_plugin.zip_errors(self.destination), [])

    def test_removing_all_execution_files_is_rejected(self):
        files = public_plugin.projected_files()
        files = {name: content for name, content in files.items()
                 if not name.startswith("skills/selective-intelligence/scripts/")}
        errors = public_plugin.zip_errors(self.write_members(files))
        self.assertTrue(any("missing required" in error and "build_engine.py" in error for error in errors), errors)

    def test_each_missing_runtime_file_is_rejected(self):
        original = public_plugin.projected_files()
        for relative in self.distribution["runtime_files"]:
            projected = public_plugin.role_path_map([relative]).get(relative, relative)
            name = "skills/selective-intelligence/" + projected
            with self.subTest(file=relative):
                files = dict(original)
                files.pop(name)
                errors = public_plugin.zip_errors(self.write_members(files))
                self.assertTrue(any("missing required" in error and name in error for error in errors), errors)

    def test_changed_runtime_or_listing_content_is_rejected(self):
        original = public_plugin.projected_files()
        for name in ("skills/selective-intelligence/scripts/intent_contract.py",
                     "skills/selective-intelligence/SKILL.md", ".codex-plugin/plugin.json"):
            with self.subTest(file=name):
                files = dict(original)
                files[name] += b"\nchanged after packaging\n"
                errors = public_plugin.zip_errors(self.write_members(files))
                self.assertTrue(any("content differs" in error and name in error for error in errors), errors)

    def test_unlisted_archive_member_is_rejected(self):
        files = public_plugin.projected_files()
        files["unapproved.txt"] = b"not a canonical runtime member\n"
        errors = public_plugin.zip_errors(self.write_members(files))
        self.assertTrue(any("unexpected" in error and "unapproved.txt" in error for error in errors), errors)

    def test_manifest_cannot_omit_an_execution_dependency(self):
        for missing in sorted(EXECUTION_RUNTIME_FILES):
            with self.subTest(file=missing):
                changed = dict(self.distribution)
                changed["runtime_files"] = [name for name in self.distribution["runtime_files"] if name != missing]
                self.manifest_path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "execution dependenc"):
                    public_plugin.projected_files()
        self.manifest_path.write_text(json.dumps(self.distribution))

    def test_manifest_cannot_read_outside_the_skill(self):
        relative = "../outside.txt"
        (self.skill.parent / "outside.txt").write_text("temporary test sentinel")
        self.distribution["runtime_files"].append(relative)
        self.distribution["release_files"].append(relative)
        self.manifest_path.write_text(json.dumps(self.distribution))
        with self.assertRaisesRegex(ValueError, "unsafe runtime path"):
            public_plugin.projected_files()

    def test_symlinked_runtime_source_is_rejected(self):
        outside = self.root / "outside.py"
        outside.write_text("# temporary test sentinel\n")
        source = self.skill / "scripts/intent_contract.py"
        source.unlink()
        source.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            public_plugin.projected_files()

    def test_missing_source_preserves_previous_archive(self):
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(b"last usable archive")
        (self.skill / "scripts/intent_contract.py").unlink()
        with self.assertRaises(FileNotFoundError):
            public_plugin.write_archive(self.destination)
        self.assertEqual(self.destination.read_bytes(), b"last usable archive")

    def test_write_failure_preserves_previous_archive_and_cleans_staging(self):
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(b"last usable archive")
        original = zipfile.ZipFile.writestr
        writes = 0

        def fail_later(archive, *args, **kwargs):
            nonlocal writes
            writes += 1
            if writes == 3:
                raise OSError("simulated disk failure")
            return original(archive, *args, **kwargs)

        with mock.patch.object(zipfile.ZipFile, "writestr", fail_later):
            with self.assertRaises(OSError):
                public_plugin.write_archive(self.destination)
        self.assertEqual(self.destination.read_bytes(), b"last usable archive")
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_failed_validation_preserves_previous_archive(self):
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(b"last usable archive")
        with mock.patch.object(public_plugin, "zip_errors", return_value=["injected validation failure"]):
            with self.assertRaisesRegex(ValueError, "injected validation failure"):
                public_plugin.write_archive(self.destination)
        self.assertEqual(self.destination.read_bytes(), b"last usable archive")
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_symlinked_destination_does_not_change_its_target(self):
        target = self.root / "protected.zip"
        target.write_bytes(b"unrelated file")
        self.destination.parent.mkdir(parents=True)
        self.destination.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            public_plugin.write_archive(self.destination)
        self.assertEqual(target.read_bytes(), b"unrelated file")
        self.assertTrue(self.destination.is_symlink())

    def test_rebuild_is_byte_identical(self):
        first = public_plugin.write_archive(self.destination)
        second = public_plugin.write_archive(self.root / "other.zip")
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(hashlib.sha256(self.destination.read_bytes()).hexdigest(), first["sha256"])

    def test_extracted_engine_uses_packaged_execution_modules(self):
        public_plugin.write_archive(self.destination)
        extracted = self.root / "extracted"
        with zipfile.ZipFile(self.destination) as archive:
            archive.extractall(extracted)
        engine = extracted / "skills/selective-intelligence/scripts/build_engine.py"
        environment = dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-B", str(engine), "--help"],
                                cwd=extracted, env=environment, capture_output=True,
                                text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("usage:", result.stdout)


if __name__ == "__main__":
    unittest.main()
