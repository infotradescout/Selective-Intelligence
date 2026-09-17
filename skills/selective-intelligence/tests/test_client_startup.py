"""Actual Git/checkpoint and fresh-process hook tests; no model or network."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import client_startup as CS
import progress_checkpoint as PC

class ClientStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="si-startup-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Synthetic Test")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / "module.py").write_text("value = 1\n")
        self.git("add", "module.py")
        self.git("commit", "-m", "Fixture baseline")
        self.save()
        self.event = {"hook_event_name": "SessionStart", "session_id": "fixture-1", "cwd": str(self.root)}

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.DEVNULL, text=True).strip()
    def save(self):
        PC.save_checkpoint(root=self.root, outcome="Continue this project", next_safe_action="Inspect the tested module before the next change.", paths=["module.py"], completed=["Baseline saved"], do_not_repeat=["Do not recreate this project"])
        self.path = PC._private_root(self.root, "progress") / "latest.json"
    def change(self, fn):
        data = json.loads(self.path.read_text()); fn(data)
        self.path.write_text(json.dumps(data))
    def test_current_checkpoint_from_subdirectory_without_mutation(self):
        child = self.root / "child"; child.mkdir()
        before = self.path.read_bytes()
        result = CS.project_context(str(child))
        self.assertEqual(result["status"], "resume_available")
        self.assertEqual(result["checkpoint"]["progress"]["nextSafeAction"], "Inspect the tested module before the next change.")
        self.assertEqual(self.path.read_bytes(), before)
    def test_new_revision_refuses_old_next_action(self):
        self.git("commit", "--allow-empty", "-m", "Different work")
        result = CS.project_context(str(self.root))
        self.assertEqual(result["status"], "checkpoint_stale")
        self.assertNotIn("checkpoint", result)
    def test_changed_file_is_not_current_evidence(self):
        (self.root / "module.py").write_text("value = 2\n")
        self.assertEqual(CS.project_context(str(self.root))["status"], "checkpoint_files_changed")
    def test_changed_branch_is_detected(self):
        self.git("checkout", "-b", "other")
        self.assertEqual(CS.project_context(str(self.root))["status"], "checkpoint_branch_mismatch")
    def test_unknown_project_gets_no_other_project_context(self):
        self.path.unlink()
        self.assertEqual(CS.project_context(str(self.root))["status"], "checkpoint_missing")
    def test_cross_project_binding_is_refused(self):
        self.change(lambda d: d.update(boundRoot=str(self.root.parent)))
        with self.assertRaises(CS.StartupError): CS.project_context(str(self.root))
    def test_sensitive_checkpoint_never_reaches_output(self):
        secret = "password=do-not-export-this-credential"
        self.change(lambda d: d.update(outcome=secret))
        output = CS.handle(self.event)
        self.assertNotIn(secret, json.dumps(output))
        self.assertIn("unavailable", json.dumps(output))
    def test_saved_file_cannot_escape_project(self):
        self.change(lambda d: d.update(savedFiles=[{"path": "../outside", "sha256": "x"}]))
        with self.assertRaises(CS.StartupError): CS.project_context(str(self.root))
    def test_oversized_checkpoint_is_refused(self):
        self.path.write_text(" " * (CS.MAX_CHECKPOINT + 1))
        self.assertIn("unavailable", json.dumps(CS.handle(self.event)))
    def test_stop_observation_never_completes_work(self):
        before = self.path.read_bytes()
        state = self.root.parent / "client-observations"
        self.assertEqual(CS.handle({**self.event, "hook_event_name": "Stop"}, state_root=state), {})
        receipt = json.loads(next(state.glob("*.json")).read_text())
        self.assertEqual(receipt["claim"], "hook_observation_not_task_completion")
        self.assertEqual(self.path.read_bytes(), before)
    def test_unsupported_events_are_not_command_execution(self):
        with self.assertRaises(CS.StartupError): CS.handle({**self.event, "hook_event_name": "PreToolUse"})
    def test_two_fresh_processes_recover_same_checkpoint(self):
        command = [sys.executable, "-B", str(Path(CS.__file__))]
        outputs = []
        for _ in range(2):
            proc = subprocess.run(command, input=json.dumps(self.event), text=True, capture_output=True, timeout=15)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            outputs.append(json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn("resume_available", outputs[0])
    def test_oversized_event_and_invalid_json_fail_without_echo(self):
        for value in ["{", "x" * (CS.MAX_INPUT + 1)]:
            proc = subprocess.run([sys.executable, "-B", CS.__file__], input=value, text=True, capture_output=True, timeout=10)
            self.assertEqual(proc.returncode, 1)
            self.assertLess(len(proc.stdout), 250)
    def test_external_checkpoint_registration_is_root_scoped(self):
        location = self.root.parent / "registry"; location.mkdir()
        checkpoint = json.loads(self.path.read_text())
        checkpoint["boundRoot"] = str(self.root)
        (location / "checkpoint.json").write_text(json.dumps(checkpoint))
        registry = location / "registry.json"
        registry.write_text(json.dumps({"schemaVersion": "si.client-registry.v1", "projects": [{"root": str(self.root), "checkpoint": "checkpoint.json"}]}))
        self.path.unlink()
        self.assertEqual(CS.project_context(str(self.root), registry)["status"], "resume_available")
    def test_caller_git_environment_cannot_change_repository(self):
        with patch.dict(os.environ, {"GIT_DIR": str(self.root / "missing")}):
            self.assertEqual(CS.project_context(str(self.root))["status"], "resume_available")

    def test_committed_canonical_checkpoint_remains_readable(self):
        self.git("checkout", "-b", "task/checkpoint")
        PC.save_checkpoint(root=self.root, outcome="Committed checkpoint", next_safe_action="Inspect the next task", commit=True)
        self.assertEqual(CS.project_context(str(self.root))["status"], "resume_available")
    def test_prompt_hook_does_not_repeat_unchanged_context(self):
        state = self.root.parent / "observations"
        CS.handle(self.event, state_root=state)
        self.assertEqual(CS.handle({**self.event, "hook_event_name": "UserPromptSubmit"}, state_root=state), {})
    def test_foreign_distribution_is_not_current_wsl(self):
        if sys.platform == "win32": return
        with patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}):
            with self.assertRaises(CS.StartupError): CS.normalized_path("//wsl.localhost/Other/home/user")

if __name__ == "__main__": unittest.main()
