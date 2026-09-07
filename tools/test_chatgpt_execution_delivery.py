"""Delivery regressions with actual builder and execution source in temp fixtures.

Non-executed documentation/metadata files are explicit synthetic fixtures. The
execution scripts are copied from the real canonical source. This does not prove
that the full distribution was built, uploaded, installed, or invoked by a model.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "skills" / "selective-intelligence"
CORE = ("build_engine", "capabilities", "checkpoint", "context_budget", "feedback",
        "intent_contract", "lane_session", "policy_guard", "text_gate")
REQUIRED = {"scripts/" + name + ".py" for name in CORE} | {
    "scripts/lane_registry.py", "lanes/si.execution.json", "lanes/si.planning.json",
    "schemas/lane.schema.json",
}
ROLES = ("aligner", "intake", "objector", "planner", "queue-manager", "verifier", "worker")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="si-delivery-proof-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.portable = self.root / "skills" / "selective-intelligence"
        self.destination = self.root / "adapters" / "chatgpt" / "selective-intelligence"
        self.metadata = self.destination.parent / "metadata" / "chatgpt-adapter.json"
        self.dist = self.root / "dist"
        spec = importlib.util.spec_from_file_location("si_delivery_builder", REPO / "tools" / "build_chatgpt_adapter.py")
        self.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.builder)
        self.builder.REPO_ROOT = self.root
        self.builder.PORTABLE_ROOT = self.portable
        self.builder.ADAPTER_METADATA = self.metadata
        self.files = sorted(REQUIRED | {"SKILL.md", "VERSION"} |
                            {f"subskills/si-{role}/SKILL.md" for role in ROLES})
        for relative in self.files:
            path = self.portable / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Synthetic non-executed delivery fixture\n", encoding="utf-8")
        # All engine code used in the archive smoke proof is canonical code.
        for name in CORE:
            shutil.copyfile(SOURCE / "scripts" / (name + ".py"), self.portable / "scripts" / (name + ".py"))
        # No registry API is used by this bounded engine journey. Avoid a fake
        # importable registry: the canonical engine's optional fallback is tested.
        (self.portable / "scripts/lane_registry.py").write_text(
            'raise ImportError("registry not exercised by synthetic delivery fixture")\n', encoding="utf-8")
        (self.portable / "SKILL.md").write_text(
            "---\nname: selective-intelligence\ndescription: synthetic delivery fixture\n---\n"
            "<!-- SELECTIVE_INTELLIGENCE_RUNTIME_PROJECTION -->\n"
            "Preserve the actual product; do not infer SaaS.\n"
            "subskills/si-worker/SKILL.md\n", encoding="utf-8")
        (self.portable / "VERSION").write_text("1.0.7\n")
        self.manifest = {"version": "1.0.7", "runtime_files": self.files,
                         "release_files": self.files + ["metadata/distribution.json"]}
        self.save_manifest()

    def save_manifest(self):
        path = self.portable / "metadata/distribution.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def build(self):
        return self.builder.build_adapter(self.destination)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()
                and ("adapters" in p.parts or "dist" in p.parts)}

    def old_copy(self):
        self.destination.mkdir(parents=True, exist_ok=True)
        (self.destination / "previous.txt").write_text("last usable copy")
        self.metadata.parent.mkdir(parents=True, exist_ok=True)
        self.metadata.write_text('{"previous":true}\n')
        return self.snapshot()

    def test_actual_entry_projection_respects_existing_budget(self):
        import re
        source = (SOURCE / "SKILL.md").read_text(encoding="utf-8")
        projected = self.builder.rewrite_text("SKILL.md", source, {})
        self.assertLessEqual(len(re.findall(r"\b[\w’'-]+\b", projected)), 1200)
        self.assertLessEqual(len(projected), 10000)
        before_description = next(line for line in source.splitlines() if line.startswith("description:"))
        self.assertIn(before_description, projected)
        self.assertIn("Software does not imply SaaS", projected)
        self.assertIn("memberships, fees, providers, and services", projected)
        self.assertIn("references/model-neutral-execution.md#product-identity-and-corrected-execution", projected)

    def test_entry_reference_retains_product_scope_and_real_client_protocol(self):
        guide = (SOURCE / "references/model-neutral-execution.md").read_text(encoding="utf-8")
        for phrase in (
            "## Product identity and corrected execution",
            "Do not infer subscription tiers, seat billing, tenant boundaries, dashboards, upgrade funnels",
            "rejecting SaaS does not revoke explicitly approved memberships, fees, existing providers, or shared services",
            "Identify the existing control owner",
            "plan-packet", "stage-plan", "sessionId", "taskId",
            "authorized_checkpoint_id", "authorized_intent_hash",
            "Do not relabel an old plan or result",
            "Do not invent another approval before each harmless edit",
            "A built archive is not installed-client or live-model proof",
        ):
            self.assertIn(phrase, guide)

    def test_runtime_recipe_contains_execution_owners_and_dependencies(self):
        metadata = json.loads((SOURCE / "metadata/distribution.json").read_text())
        self.assertTrue(REQUIRED.issubset(metadata["runtime_files"]), sorted(REQUIRED - set(metadata["runtime_files"])))
        self.assertTrue(set(metadata["runtime_files"]).issubset(metadata["release_files"]))

    def test_missing_execution_dependency_is_rejected_before_replacing_old_copy(self):
        before = self.old_copy()
        self.manifest["runtime_files"] = [p for p in self.files if p != "scripts/lane_session.py"]
        self.save_manifest()
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(self.snapshot(), before)

    def test_missing_source_preserves_previous_adapter_and_metadata(self):
        before = self.old_copy()
        (self.portable / "scripts/policy_guard.py").unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()
        self.assertEqual(self.snapshot(), before)

    def test_bad_rewrite_anchor_preserves_previous_adapter(self):
        before = self.old_copy()
        (self.portable / "SKILL.md").write_text("no adapter anchor")
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(self.snapshot(), before)

    def test_parent_escape_in_manifest_cannot_delete_previous_adapter(self):
        before = self.old_copy()
        self.manifest["runtime_files"].append("../outside.txt")
        self.manifest["release_files"].append("../outside.txt")
        (self.portable.parent / "outside.txt").write_text("outside")
        self.save_manifest()
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(self.snapshot(), before)

    def test_symlink_source_is_rejected_without_copying_external_bytes(self):
        before = self.old_copy()
        target = self.portable / "scripts/policy_guard.py"
        target.unlink()
        outside = self.root / "outside.txt"
        outside.write_text("must not be copied")
        target.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(self.snapshot(), before)

    def test_projection_collisions_fail_before_replacing_old_copy(self):
        before = self.old_copy()
        relative = "subskills/si-worker/ROLE.md"
        self.manifest["runtime_files"].append(relative)
        self.manifest["release_files"].append(relative)
        (self.portable / relative).write_text("conflict")
        self.save_manifest()
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(self.snapshot(), before)

    def test_version_disagreement_preserves_old_copy(self):
        before = self.old_copy()
        (self.portable / "VERSION").write_text("2.0.0\n")
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(self.snapshot(), before)

    def test_staging_failure_preserves_old_copy(self):
        before = self.old_copy()
        original = self.builder.write_text
        def fail(path, text, mode):
            if path.name == "lane_session.py":
                raise OSError("injected staging failure")
            return original(path, text, mode)
        with mock.patch.object(self.builder, "write_text", side_effect=fail):
            with self.assertRaises(OSError):
                self.build()
        self.assertEqual(self.snapshot(), before)

    def test_metadata_replace_failure_restores_previous_adapter(self):
        before = self.old_copy()
        original = self.builder.os.replace
        failed = False
        def fail(source, target):
            nonlocal failed
            if Path(target) == self.metadata and not failed:
                failed = True
                raise OSError("injected metadata replace failure")
            return original(source, target)
        with mock.patch.object(self.builder.os, "replace", side_effect=fail):
            with self.assertRaises(OSError):
                self.build()
        self.assertEqual(self.snapshot(), before)

    def test_interruption_during_publication_restores_previous_copy(self):
        before = self.old_copy()
        original = self.builder.os.replace
        interrupted = False
        def stop(source, target):
            nonlocal interrupted
            if Path(target) == self.metadata and not interrupted:
                interrupted = True
                raise KeyboardInterrupt("injected interruption")
            return original(source, target)
        with mock.patch.object(self.builder.os, "replace", side_effect=stop):
            with self.assertRaises(KeyboardInterrupt):
                self.build()
        self.assertEqual(self.snapshot(), before)

    def test_failed_rollback_preserves_last_usable_copy_for_recovery(self):
        self.old_copy()
        original = self.builder.os.replace
        def fail(source, target):
            if Path(target) == self.metadata or Path(source).name == "previous":
                raise OSError("injected publication and restoration failure")
            return original(source, target)
        with mock.patch.object(self.builder.os, "replace", side_effect=fail):
            with self.assertRaises((OSError, RuntimeError)):
                self.build()
        saved = list(self.destination.parent.glob(".si-adapter-stage-*/previous/previous.txt"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_text(), "last usable copy")

    def test_parent_file_collision_is_preflighted_before_old_copy_replacement(self):
        before = self.old_copy()
        relative = "scripts"
        self.manifest["runtime_files"].append(relative)
        self.manifest["release_files"].append(relative)
        self.save_manifest()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.build()
        self.assertEqual(self.snapshot(), before)

    def test_directory_symlink_source_cannot_read_outside_source_root(self):
        before = self.old_copy()
        original = self.portable / "subskills/si-worker"
        outside = self.root / "outside-role"
        original.rename(outside)
        original.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(self.snapshot(), before)

    def test_archive_failure_does_not_truncate_last_archive(self):
        self.build()
        previous = self.builder.build_archive(self.destination, self.dist)
        before = Path(previous["archive"]).read_bytes()
        with mock.patch.object(self.builder.zipfile.ZipFile, "writestr", side_effect=OSError("injected zip write failure")):
            with self.assertRaises(OSError):
                self.builder.build_archive(self.destination, self.dist)
        self.assertEqual(Path(previous["archive"]).read_bytes(), before)
        self.assertEqual(len(list(self.dist.iterdir())), 1)

    def test_archive_checks_exact_bytes_not_only_before_and_after_tree(self):
        self.build()
        original_read = Path.read_bytes
        target = self.destination / "scripts/checkpoint.py"
        reads = 0
        def altered_read(path):
            nonlocal reads
            raw = original_read(path)
            if path == target:
                reads += 1
                if reads == 2:  # the archive read, between two validation reads
                    return raw + b"\n# unrecognized transient write\n"
            return raw
        with mock.patch.object(Path, "read_bytes", altered_read):
            with self.assertRaises(ValueError):
                self.builder.build_archive(self.destination, self.dist)
        self.assertFalse(list(self.dist.glob("*.zip")))

    def test_projection_identifies_exact_canonical_execution_sources(self):
        result = self.build()
        projection = json.loads(self.metadata.read_text())
        self.assertEqual(result["execution_entrypoint"], "scripts/build_engine.py")
        for name in CORE:
            relative = "scripts/" + name + ".py"
            original = (SOURCE / relative).read_bytes()
            self.assertEqual((self.destination / relative).read_bytes(), original)
            self.assertEqual(projection["source_file_sha256"][relative], hashlib.sha256(original).hexdigest())
        self.assertEqual([p.relative_to(self.destination).as_posix() for p in self.destination.rglob("SKILL.md")], ["SKILL.md"])
        self.assertEqual(len(list(self.destination.rglob("ROLE.md"))), 7)
        self.assertNotEqual(projection["behavioral_contract"], "preserved")

    def test_stale_canonical_source_blocks_archiving_previous_projection(self):
        self.build()
        result = self.builder.build_archive(self.destination, self.dist)
        before = Path(result["archive"]).read_bytes()
        target = self.portable / "scripts/checkpoint.py"
        target.write_bytes(target.read_bytes() + b"\n# changed source\n")
        with self.assertRaises(ValueError):
            self.builder.build_archive(self.destination, self.dist)
        self.assertEqual(Path(result["archive"]).read_bytes(), before)

    def test_altered_adapter_blocks_archiving(self):
        self.build()
        (self.destination / "scripts/checkpoint.py").write_text("changed")
        with self.assertRaises(ValueError):
            self.builder.build_archive(self.destination, self.dist)
        self.assertFalse(self.dist.exists())

    def test_missing_execution_file_blocks_archiving(self):
        self.build()
        (self.destination / "scripts/lane_session.py").unlink()
        with self.assertRaises(ValueError):
            self.builder.build_archive(self.destination, self.dist)
        self.assertFalse(self.dist.exists())

    def test_stale_projection_metadata_blocks_archiving(self):
        self.build()
        self.metadata.write_text('{"version":"1.0.7"}')
        with self.assertRaises(ValueError):
            self.builder.build_archive(self.destination, self.dist)

    def test_archive_is_deterministic_and_contains_execution_code(self):
        self.build()
        first = self.builder.build_archive(self.destination, self.dist)
        second = self.builder.build_archive(self.destination, self.dist)
        self.assertEqual(first["sha256"], second["sha256"])
        with zipfile.ZipFile(first["archive"]) as archive:
            for name in CORE:
                relative = "scripts/" + name + ".py"
                self.assertEqual(archive.read("selective-intelligence/" + relative), (SOURCE / relative).read_bytes())
            self.assertEqual(len([n for n in archive.namelist() if n.endswith("/SKILL.md")]), 1)

    def test_extracted_archive_runs_actual_corrected_execution_owner(self):
        self.build()
        result = self.builder.build_archive(self.destination, self.dist)
        extracted = self.root / "unpacked"
        with zipfile.ZipFile(result["archive"]) as archive:
            archive.extractall(extracted)
        engine = extracted / "selective-intelligence/scripts/build_engine.py"
        env = {"PATH": os.defpath, "HOME": str(self.root), "SI_SESSION_DIR": str(self.root / "sessions"),
               "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            if key in os.environ:
                env[key] = os.environ[key]
        def call(*args):
            with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                proc = subprocess.run([sys.executable, str(engine), *args], env=env,
                                      stdout=out, stderr=err, timeout=20)
                out.seek(0); err.seek(0)
                stdout, stderr = out.read().decode(), err.read().decode()
            self.assertEqual(proc.returncode, 0, stdout + stderr)
            return json.loads(stdout)
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"tasks": [{"key": "members", "title": "Preserve approved business memberships", "kind": "worker"}]}))
        session = call("start", "--request", "Build a SaaS platform. Preserve approved business memberships.",
                       "--workspace", str(self.root / "work"), "--plan", str(plan))
        call("approve", "--session", session["sessionId"])
        correction = call("correct", "--session", session["sessionId"], "--correction", "I am not building SaaS.")
        current = call("show", "--session", session["sessionId"])
        self.assertTrue(correction["correctionSaved"])
        self.assertTrue(current["executionLocked"])
        self.assertNotIn("saas", current["objective"].lower())
        self.assertIn("memberships", json.dumps(current["activeIntent"]).lower())
        self.assertTrue(all(task["status"] == "cancelled" for task in current["queue"]))


if __name__ == "__main__":
    unittest.main()
