"""New resource-input checks; do not rerun the existing adapter suite."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import agent
import bootstrap
from test_agent import directory_alias

ARCHIVE = agent.ROOT.parents[2] / "evidence/resource-delivery/e194-canonical-source.zip"


class ResourceTests(unittest.TestCase):
    def test_prepare_uses_canonical_remote_with_redirects_disabled(self):
        class FetchStopped(Exception):
            pass

        self.assertFalse(bootstrap.SOURCE_READY_FOR_HOSTED_USE)
        actual_git = bootstrap.git
        observed = {}

        def stop_before_fetch(directory, *arguments):
            if arguments[0] == "fetch":
                observed["repository"] = actual_git(directory, "remote", "get-url", "origin")
                observed["follow_redirects"] = actual_git(directory, "config", "--get", "http.followRedirects")
                raise FetchStopped
            return actual_git(directory, *arguments)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "si-source"
            # Exercise real Git staging only. The test bypasses the readiness gate
            # and intercepts fetch before any network request can execute.
            with patch.object(bootstrap, "DESTINATION", destination), \
                    patch.object(bootstrap, "require_hosted_source"), \
                    patch.object(bootstrap, "git", side_effect=stop_before_fetch):
                with self.assertRaises(FetchStopped):
                    bootstrap.prepare(destination)
            self.assertEqual(list(root.iterdir()), [])
        self.assertEqual(observed["repository"], "https://github.com/flavorgood/Selective-Intelligence.git")
        self.assertEqual(observed["follow_redirects"], "false")

    def test_pinned_resource_build_keeps_exact_accepted_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rebuilt.zip"
            receipt = bootstrap.build_resources(agent.ROOT.parents[1], output)
            self.assertEqual(output.read_bytes(), ARCHIVE.read_bytes())
            self.assertEqual(receipt["resource_sha256"], bootstrap.RESOURCE_SHA256)
            self.assertEqual(receipt["files"], 119)

    def test_exported_inputs_execute_and_install_exact_complete_resources(self):
        raw, manifest, files = bootstrap.read_resources(ARCHIVE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exported = root / "export"
            with patch.object(agent, "api_request", side_effect=AssertionError("API call")):
                receipt = agent.export(exported, resources=ARCHIVE)
            environment = json.loads((exported / "session-environment.json").read_bytes())
            self.assertEqual(environment["network"], {"access": "disabled"})
            self.assertEqual(environment["capability_directories"], ["/workspace/si-source/skills"])
            self.assertEqual(json.loads((exported / "agent.json").read_bytes()), agent.definition())
            self.assertFalse(receipt["registration_allowed"])
            self.assertFalse(receipt["session_preparation_allowed"])
            self.assertEqual(len(environment["files"]), 2)
            workspace = root / "workspace"
            workspace.mkdir()
            for item in environment["files"]:
                (workspace / Path(item["path"]).name).write_bytes(base64.b64decode(item["data"], validate=True))
            self.assertEqual((workspace / "si-source-e194.zip").read_bytes(), raw)
            command = environment["setup_commands"][0]["command"].split()
            self.assertEqual(command[0], "python3")
            # Rebase only provider absolute paths onto the isolated Windows fixture.
            local = [sys.executable, "-B"] + [
                str(workspace / Path(part).name) if part.startswith("/workspace/") else part
                for part in command[1:]
            ]
            completed = subprocess.run(local, check=True, capture_output=True, text=True,
                                       cwd=workspace, env=bootstrap.git_environment())
            installed = json.loads(completed.stdout)
            self.assertEqual(installed["status"], "canonical_resource_inputs_installed_offline")
            self.assertEqual(installed["files"], 119)
            self.assertFalse(installed["hosted_acceptance"])
            self.assertFalse(installed["full_repository_checkout"])
            source = workspace / "si-source"
            actual = {str(path.relative_to(source)).replace("\\", "/") for path in
                      (source / "skills/selective-intelligence").rglob("*") if path.is_file()}
            self.assertEqual(actual, set(manifest["files"]))
            for name, data in files.items():
                self.assertEqual((source / name).read_bytes(), data)
                self.assertEqual(bootstrap.blob_id(data), manifest["files"][name]["blob"])
            for link in ("references/evidence-and-completion.md", "references/product-design-intelligence.md",
                         "references/public-profile-tier-parity.md", "subskills/si-objector/SKILL.md"):
                self.assertTrue((source / "skills/selective-intelligence" / link).is_file(), link)
            self.assertFalse(bootstrap.SOURCE_READY_FOR_HOSTED_USE)

    def test_corrupt_archive_creates_no_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corrupt = root / "corrupt.zip"
            corrupt.write_bytes(ARCHIVE.read_bytes() + b"tamper")
            target = root / "new"
            with self.assertRaisesRegex(ValueError, "pinned archive"):
                bootstrap.install_resources(corrupt, target)
            self.assertFalse(target.exists())

    def test_existing_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_bytes(b"owned before installation")
            with self.assertRaises(FileExistsError):
                bootstrap.install_resources(ARCHIVE, target)
            self.assertEqual(marker.read_bytes(), b"owned before installation")
            self.assertEqual(list(target.iterdir()), [marker])

    def test_redirected_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "owned"
            real.mkdir()
            directory_alias(root / "alias", real)
            with self.assertRaisesRegex(ValueError, "redirect"):
                bootstrap.install_resources(ARCHIVE, root / "alias" / "new")
            self.assertFalse((real / "new").exists())

    def test_unsafe_resource_paths_rejected(self):
        for name in ("../escape", "/skills/selective-intelligence/a", "skills/selective-intelligence/../a",
                     "skills/selective-intelligence/a//b", "skills/selective-intelligence/CON.txt",
                     "skills/selective-intelligence/a\\b", "skills/selective-intelligence/a:b",
                     "skills/selective-intelligence/a."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                bootstrap.resource_path(name)

    def test_manifest_provenance_cannot_be_changed(self):
        raw, manifest, _ = bootstrap.read_resources(ARCHIVE)
        for key, value in (("repository", "https://github.com/flavorgood/Selective-Intelligence.git"),
                           ("commit", "0" * 40), ("tree", "0" * 40)):
            changed = {**manifest, key: value}
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                corrupt = Path(directory) / "wrong-source.zip"
                with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(corrupt, "w") as dest:
                    for info in source.infolist():
                        dest.writestr(info, json.dumps(changed).encode() if info.filename == "source-manifest.json" else source.read(info))
                with patch.object(bootstrap, "RESOURCE_SHA256", hashlib.sha256(corrupt.read_bytes()).hexdigest()):
                    with self.assertRaisesRegex(ValueError, "provenance"):
                        bootstrap.read_resources(corrupt)

    def test_symlink_resource_rejected_even_under_synthetic_fingerprint(self):
        raw, _, _ = bootstrap.read_resources(ARCHIVE)
        with tempfile.TemporaryDirectory() as directory:
            corrupt = Path(directory) / "symlink.zip"
            with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(corrupt, "w") as dest:
                for info in source.infolist():
                    if info.filename.endswith("/SKILL.md"):
                        info.external_attr = 0o120777 << 16
                    dest.writestr(info, source.read(info))
            with patch.object(bootstrap, "RESOURCE_SHA256", hashlib.sha256(corrupt.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, "mode or symlink"):
                    bootstrap.read_resources(corrupt)


if __name__ == "__main__":
    unittest.main()
