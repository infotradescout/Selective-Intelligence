from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SKILL_ROOT = TEST_DIR.parent
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from policy_guard import PolicyGuard, _command_basename, _resolve_command_argv


class CommandResolutionUnitTests(unittest.TestCase):
    def test_normalizes_paths_quotes_case_and_repeated_suffixes(self):
        self.assertEqual(_command_basename(r"C:\Program Files\Git\cmd\git.exe"), "git")
        self.assertEqual(_command_basename(r'"C:\Program Files\Git\cmd\git.exe"'), "git")
        self.assertEqual(_command_basename("/usr/bin/git"), "git")
        self.assertEqual(_command_basename("git.exe"), "git")
        self.assertEqual(_command_basename(r"C:\Program Files\nodejs\npm.cmd"), "npm")
        self.assertEqual(_command_basename("git.exe.cmd"), "git")

    def test_returns_structured_resolution(self):
        argv = ["env", "TOKEN=secret", "nice", "git.exe", "status"]
        resolution = _resolve_command_argv(argv)
        self.assertEqual(resolution["originalArgv"], argv)
        self.assertEqual(
            resolution["redactedOriginalArgv"],
            ["env", "TOKEN=<redacted>", "nice", "git.exe", "status"],
        )
        self.assertEqual(resolution["effectiveArgv"], ["git.exe", "status"])
        self.assertEqual(resolution["normalizedExecutable"], "git")
        self.assertEqual(resolution["wrapperChain"], ["env", "nice"])
        self.assertEqual(resolution["status"], "resolved")
        self.assertTrue(resolution["reason"])

    def test_fails_closed_on_ambiguous_or_missing_commands(self):
        cases = (
            (["env"] * 33 + ["git", "status"], "ambiguous", "depth"),
            (["env", "-u"], "ambiguous", "missing"),
            (["env", "-S", "git status"], "ambiguous", "ambiguous"),
            (["nice", "-n"], "ambiguous", "missing"),
            (["nice", "-n", "fast", "git", "status"], "ambiguous", "invalid"),
            (["timeout", "--signal"], "ambiguous", "missing"),
            (["timeout", "soon", "git", "status"], "ambiguous", "invalid"),
            (["sudo", "-u"], "ambiguous", "missing"),
            (["env", "-C", "/tmp", "git", "status"], "ambiguous", "context"),
            (["sudo", "--chdir", "/tmp", "git", "status"], "ambiguous", "context"),
            ([], "no_command", "no effective command"),
            ([""], "no_command", "empty executable"),
        )
        for argv, status, reason_fragment in cases:
            with self.subTest(argv=argv):
                resolution = _resolve_command_argv(argv)
                self.assertEqual(resolution["status"], status)
                self.assertIn(reason_fragment, resolution["reason"])

    def test_rejects_shell_form_action_argv(self):
        resolution = _resolve_command_argv("git status")
        self.assertEqual(resolution["status"], "ambiguous")
        self.assertIn("shell-form string", resolution["reason"])
        malformed = _resolve_command_argv(["git", 1])  # type: ignore[list-item]
        self.assertEqual(malformed["status"], "ambiguous")
        self.assertIn("non-string", malformed["reason"])


class PolicyCommandCanonicalizationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        base = Path(self._temp.name)
        self.canonical = base / "canonical"
        self.disposable = base / "disposable"
        self.canonical.mkdir()
        self.disposable.mkdir()
        self.guard = PolicyGuard(
            canonical_roots=[self.canonical],
            writable_roots=[self.disposable],
        )

    def tearDown(self):
        self._temp.cleanup()

    def _run(self, argv: list[str]):
        return self.guard.authorize(
            session_id="si-test",
            task_id="task-test",
            action={"kind": "process.run", "argv": argv, "cwd": str(self.disposable)},
        )

    def test_denies_windows_suffix_git_and_install(self):
        for argv in (
            ["git.exe", "commit", "-m", "x"],
            ["npm.cmd", "install"],
            ["npm.ps1", "install"],
        ):
            decision = self._run(argv)
            self.assertFalse(decision["allowed"], argv)
            self.assertEqual(decision["adapterInvocationStatus"], "NOT_INVOKED")

    def test_denies_wrapper_and_git_global_option_mutations(self):
        for argv in (
            ["env", "git", "commit", "-m", "x"],
            ["command", "git", "push"],
            ["nice", "npm", "install"],
            ["git", "-C", str(self.disposable), "commit", "-m", "x"],
            ["git.exe", "--git-dir", str(self.disposable / ".git"), "push"],
        ):
            decision = self._run(argv)
            self.assertFalse(decision["allowed"], argv)
            self.assertEqual(decision["adapterInvocationStatus"], "NOT_INVOKED")

    def test_denies_shell_and_interpreter_indirection(self):
        for argv in (
            ["sh", "-c", "echo safe-looking"],
            ["zsh", "-c", "echo safe-looking"],
            ["fish", "-c", "echo safe-looking"],
            ["cmd", "/c", "git commit -m x"],
            ["cmd", "/c", "echo safe-looking"],
            ["cmd.exe", "/c", "npm install"],
            ["PowerShell", "-Command", "git commit -m x"],
            ["pwsh", "-c", "Write-Output ok"],
            ["powershell.exe", "-Command", "npm install bad"],
            ["bash", "-c", "git commit -m x"],
            ["bash", "-c", "echo ok"],
            ["python", "-c", "import os; os.system('git commit -m x')"],
            ["py", "-c", "print('ok')"],
            ["python3", "-c", "import os; os.system('npm install')"],
            ["node", "-e", "require('child_process').exec('git push')"],
            ["nodejs", "--eval", "console.log('ok')"],
            ["node", "--eval=console.log('ok')"],
            ["python", "-m", "pip", "install", "requests"],
            ["python.exe", "-m", "pip", "install", "requests"],
        ):
            decision = self._run(argv)
            self.assertFalse(decision["allowed"], argv)
            self.assertEqual(decision["adapterInvocationStatus"], "NOT_INVOKED")

    def test_denies_inline_writes_to_canonical_path(self):
        target = str(self.canonical / "should-not-exist.txt")
        for argv in (
            ["bash", "-c", f"printf bad > '{target}'"],
            ["python", "-c", f"open({target!r}, 'w').write('bad')"],
            ["node", "-e", f"require('fs').writeFileSync({target!r}, 'bad')"],
        ):
            decision = self._run(argv)
            self.assertFalse(decision["allowed"], argv)
            self.assertEqual(decision["adapterInvocationStatus"], "NOT_INVOKED")
        self.assertFalse(Path(target).exists())

    def test_fails_closed_resolution_before_adapter(self):
        for argv in (
            [],
            ["env", "-S", "git status"],
            ["env", "-u"],
            ["nice", "-n"],
            ["timeout", "5"],
            ["sudo", "-u"],
            ["env", "-C", str(self.canonical), "git", "status"],
            ["sudo", "--chdir", str(self.canonical), "git", "status"],
            ["env"] * 33 + ["git", "status"],
        ):
            decision = self._run(argv)
            self.assertFalse(decision["allowed"], argv)
            self.assertIn(decision["resolutionStatus"], {"ambiguous", "no_command"})
            self.assertEqual(decision["adapterInvocationStatus"], "NOT_INVOKED")

        string_decision = self.guard.authorize(
            session_id="si-test",
            task_id="task-test",
            action={"kind": "process.run", "argv": "git status", "cwd": str(self.disposable)},
        )
        self.assertFalse(string_decision["allowed"])
        self.assertEqual(string_decision["resolutionStatus"], "ambiguous")

    def test_redacts_secrets_and_emits_resolution_evidence(self):
        secret = "super-secret-value"
        decision = self._run(["env", f"API_TOKEN={secret}", "git", "status"])
        serialized = json.dumps(decision)
        self.assertTrue(decision["allowed"])
        self.assertNotIn(secret, serialized)
        self.assertEqual(
            decision["requestedOperation"]["argv"],
            ["env", "API_TOKEN=<redacted>", "git", "status"],
        )
        self.assertEqual(decision["normalizedExecutable"], "git")
        self.assertEqual(decision["effectiveArgv"], ["git", "status"])
        self.assertEqual(decision["wrapperChain"], ["env"])
        self.assertEqual(decision["resolutionStatus"], "resolved")
        self.assertEqual(decision["matchedConstraint"], decision["relevantConstraint"])
        self.assertEqual(decision["adapterInvocationStatus"], "PENDING")

    def test_preserves_safe_positive_controls(self):
        for argv in (
            ["git", "status"],
            ["git.exe", "status"],
            ["env", "git", "status"],
            ["python", "-m", "unittest", "discover", "-s", "tests"],
            ["python", "--version"],
            ["node", "--version"],
        ):
            decision = self._run(argv)
            self.assertTrue(decision["allowed"], argv)
            self.assertEqual(decision["adapterInvocationStatus"], "PENDING")

    def test_denies_commands_outside_explicit_allowlist(self):
        for argv in (
            ["npm", "test"],
            ["python", "script.py"],
            ["node", "script.js"],
            ["echo", "ok"],
            ["git", "diff", "--output", str(self.canonical / "bad.diff")],
            ["git", "show", "--ext-diff"],
            ["git", "-C", str(self.canonical), "status"],
        ):
            decision = self._run(argv)
            self.assertFalse(decision["allowed"], argv)
            self.assertIn("allowlist", decision["matchedConstraint"])


if __name__ == "__main__":
    unittest.main()
