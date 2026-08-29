from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SKILL_ROOT = TEST_DIR.parent
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import progress_checkpoint  # noqa: E402


class ProgressCheckpointTests(unittest.TestCase):
    def test_self_test_preserves_pushes_and_bounds_usage(self):
        result = progress_checkpoint.self_test()
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["checkpoint"]["committed"])
        self.assertTrue(result["checkpoint"]["pushed"])
        self.assertEqual(result["remoteHead"], result["checkpoint"]["commitSha"])
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
            root = Path(temporary)
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
