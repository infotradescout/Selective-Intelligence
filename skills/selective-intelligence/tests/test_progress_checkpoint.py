from __future__ import annotations

import subprocess
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_DIR = Path(__file__).resolve().parent
SKILL_ROOT = TEST_DIR.parent
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import progress_checkpoint  # noqa: E402


class ProgressCheckpointTests(unittest.TestCase):
    def make_repository(self, root):
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-b", "task/save"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "SI Test"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "si@example.invalid"], cwd=root, check=True)
        (root / "owned.txt").write_text("before\n", encoding="utf-8")
        (root / "unrelated.txt").write_text("baseline\n", encoding="utf-8")
        (root / ".gitignore").write_text(".selective-intelligence/\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore", "owned.txt", "unrelated.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, check=True, capture_output=True)
        return root

    def test_preserves_unrelated_staged_and_unstaged_work_with_ignored_state(self):
        with tempfile.TemporaryDirectory(prefix="si-progress-selective-") as temporary:
            root = self.make_repository(Path(temporary))
            (root / "owned.txt").write_text("after\n", encoding="utf-8")
            (root / "unrelated.txt").write_text("staged change\n", encoding="utf-8")
            subprocess.run(["git", "add", "unrelated.txt"], cwd=root, check=True)
            (root / "unrelated.txt").write_text("staged plus later work\n", encoding="utf-8")
            staged_before = subprocess.check_output(["git", "show", ":unrelated.txt"], cwd=root)
            result = progress_checkpoint.save_checkpoint(
                root=root, outcome="Save the owned change", next_safe_action="Continue",
                paths=["owned.txt"], commit=True,
            )
            self.assertTrue(result["committed"])
            self.assertEqual(subprocess.check_output(["git", "show", "HEAD:unrelated.txt"], cwd=root), b"baseline\n")
            self.assertEqual(subprocess.check_output(["git", "show", ":unrelated.txt"], cwd=root), staged_before)
            self.assertEqual((root / "unrelated.txt").read_text(), "staged plus later work\n")
            self.assertEqual(subprocess.check_output(["git", "show", "HEAD:owned.txt"], cwd=root), b"after\n")
            self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=root).decode().splitlines(), ["MM unrelated.txt"])

    def test_selected_filename_is_literal_and_directory_selection_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="si-progress-literal-") as temporary:
            root = self.make_repository(Path(temporary))
            (root / "owned[1].txt").write_text("selected\n")
            (root / "owned1.txt").write_text("unrelated\n")
            progress_checkpoint.save_checkpoint(
                root=root, outcome="Save one literal filename", next_safe_action="Continue",
                paths=["owned[1].txt"], commit=True,
            )
            self.assertEqual(subprocess.check_output(["git", "show", "HEAD:owned[1].txt"], cwd=root), b"selected\n")
            self.assertIn("?? owned1.txt", subprocess.check_output(["git", "status", "--porcelain"], cwd=root).decode())
            (root / "folder").mkdir()
            with self.assertRaises(progress_checkpoint.ProgressCheckpointError):
                progress_checkpoint.save_checkpoint(
                    root=root, outcome="Save selected work", next_safe_action="Select files",
                    paths=["folder"], commit=True,
                )

    def test_unverified_accepted_push_keeps_an_honest_receipt(self):
        with tempfile.TemporaryDirectory(prefix="si-progress-remote-") as temporary:
            root = self.make_repository(Path(temporary) / "work")
            remote = Path(temporary) / "remote.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
            original_run = progress_checkpoint._run
            for verification in (
                subprocess.CompletedProcess([], 1, "", "verification unavailable"),
                subprocess.CompletedProcess([], 0, "0" * 40 + "\trefs/heads/task/save\n", ""),
            ):
                def unavailable(project_root, *args, **kwargs):
                    if args[:2] == ("git", "ls-remote"):
                        return verification
                    return original_run(project_root, *args, **kwargs)
                with patch.object(progress_checkpoint, "_run", side_effect=unavailable):
                    with self.assertRaises(progress_checkpoint.ProgressCheckpointError):
                        progress_checkpoint.save_checkpoint(
                            root=root, outcome="Save remotely", next_safe_action="Inspect remote state",
                            paths=["owned.txt"], commit=True, push=True,
                        )
                operation = json.loads((root / ".git/selective-intelligence/progress/last-operation.json").read_text())
                self.assertTrue(operation["committed"])
                self.assertTrue(operation["pushAccepted"])
                self.assertFalse(operation["pushed"])
                self.assertFalse(operation["remoteVerified"])
                remote_head = subprocess.check_output(["git", "--git-dir", str(remote), "rev-parse", "refs/heads/task/save"]).decode().strip()
                self.assertEqual(remote_head, operation["commitSha"])

    def test_self_test_preserves_pushes_and_bounds_usage(self):
        result = progress_checkpoint.self_test()
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["checkpoint"]["committed"])
        self.assertTrue(result["checkpoint"]["pushed"])
        self.assertEqual(result["remoteHead"], result["checkpoint"]["commitSha"])
        self.assertTrue(result["checkpoint"]["remoteVerified"])
        self.assertEqual(result["checkpoint"]["remoteHead"], result["checkpoint"]["commitSha"])
        self.assertEqual(result["tracked"], [".selective-intelligence/progress/latest.json"])
        self.assertTrue(any(line.endswith(" unrelated.txt") for line in result["workingTree"]))
        self.assertEqual(result["usage"]["limits"]["filesPerBatch"], 12)
        self.assertEqual(result["usage"]["limits"]["bytesPerBatch"], 65_536)
        self.assertEqual(result["usage"]["limits"]["batchesBeforeDecision"], 3)

    def test_protected_branch_requires_exact_authority(self):
        with tempfile.TemporaryDirectory(prefix="si-progress-protected-") as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "SI Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "si@example.invalid"], cwd=root, check=True)
            (root / "owned.txt").write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "owned.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, check=True, capture_output=True)
            (root / "owned.txt").write_text("after\n", encoding="utf-8")
            with self.assertRaises(progress_checkpoint.ProgressCheckpointError):
                progress_checkpoint.save_checkpoint(
                    root=root,
                    outcome="Do not checkpoint directly to main",
                    completed=["Owned file changed"],
                    next_safe_action="Move work to a task branch",
                    paths=["owned.txt"],
                    commit=True,
                )

    def test_release_branch_prefix_is_also_protected(self):
        with tempfile.TemporaryDirectory(prefix="si-progress-release-") as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-b", "release/1.0.7"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "SI Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "si@example.invalid"], cwd=root, check=True)
            (root / "owned.txt").write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "owned.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, check=True, capture_output=True)
            (root / "owned.txt").write_text("after\n", encoding="utf-8")
            with self.assertRaises(progress_checkpoint.ProgressCheckpointError):
                progress_checkpoint.save_checkpoint(
                    root=root,
                    outcome="Do not checkpoint directly to a release branch",
                    completed=["Owned file changed"],
                    next_safe_action="Move work to a task branch",
                    paths=["owned.txt"],
                    commit=True,
                )

    def test_push_requires_commit(self):
        with tempfile.TemporaryDirectory(prefix="si-progress-no-git-") as temporary:
            with self.assertRaises(progress_checkpoint.ProgressCheckpointError):
                progress_checkpoint.save_checkpoint(
                    root=Path(temporary),
                    outcome="Invalid push request",
                    next_safe_action="Create a task branch",
                    push=True,
                )

    def test_usage_governor_blocks_fourth_batch_and_overlapping_owner(self):
        with tempfile.TemporaryDirectory(prefix="si-usage-") as temporary:
            root = self.make_repository(Path(temporary))
            progress_checkpoint.usage_start(root, "Inspect one bounded question")
            for index in range(3):
                status = progress_checkpoint.usage_record(
                    root,
                    kind="inspection",
                    question="Which module owns the public profile?",
                    owner="worker-1",
                    file_count=3,
                    byte_count=4096,
                    impact="proof",
                    result=f"batch {index + 1}",
                )
            self.assertTrue(status["decisionRequired"])
            with self.assertRaises(progress_checkpoint.ProgressCheckpointError):
                progress_checkpoint.usage_record(
                    root,
                    kind="search",
                    question="Which module owns the public profile?",
                    owner="worker-1",
                    file_count=1,
                    byte_count=100,
                    impact="proof",
                    result="fourth batch",
                )
            progress_checkpoint.usage_decide(root, action="narrow", summary="Use the selected route owner")
            with self.assertRaises(progress_checkpoint.ProgressCheckpointError):
                progress_checkpoint.usage_record(
                    root,
                    kind="inspection",
                    question="Which module owns the public profile?",
                    owner="worker-2",
                    file_count=1,
                    byte_count=100,
                    impact="proof",
                    result="duplicate owner",
                )


if __name__ == "__main__":
    unittest.main()
