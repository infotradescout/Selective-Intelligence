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


class ProjectResumeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="si-startup-resume-")
        self.addCleanup(temporary.cleanup)
        self.root = ProgressCheckpointTests.make_repository(self, Path(temporary.name))
        self.private = self.root / ".git/selective-intelligence/progress/latest.json"
        self.tracked = self.root / ".selective-intelligence/progress/latest.json"

    def save(self, outcome="current task", commit=False):
        return progress_checkpoint.save_checkpoint(root=self.root, outcome=outcome,
            next_safe_action="Verify only the next dependency", paths=["owned.txt"],
            completed=["Prior repair is complete"], do_not_repeat=["Do not rebuild the old fixture"],
            prohibitions=["No production changes"], commit=commit)

    def test_resume_selects_newer_private_instead_of_older_tracked(self):
        self.save("older tracked", commit=True)
        self.save("newer private")
        self.assertEqual(progress_checkpoint.checkpoint_status(self.root)["latestCheckpoint"]["outcome"], "older tracked")
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertEqual((result["state"], result["outcome"], result["checkpointSource"]), ("ready", "newer private", "private"))
        self.assertFalse(result["executionAuthorized"])
        self.assertFalse(result["releaseAuthorized"])

    def test_containing_commit_is_validated_as_current(self):
        operation = self.save(commit=True)
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["expectedHead"], operation["commitSha"])

    def test_subdirectory_finds_only_owning_project(self):
        self.save()
        child = self.root / "nested"; child.mkdir()
        result = progress_checkpoint.resume_checkpoint(child)
        self.assertEqual(result["projectRoot"], str(self.root.resolve()))
        self.assertEqual(result["state"], "ready")

    def test_absent_checkpoint_does_not_invent_work(self):
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertEqual(result["state"], "no_checkpoint")
        self.assertIsNone(result["nextSafeAction"])

    def test_malformed_private_cannot_fall_back_to_tracked(self):
        self.save(commit=True)
        self.private.parent.mkdir(parents=True, exist_ok=True)
        self.private.write_text('{"invalid":', encoding="utf-8")
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertEqual(result["state"], "reconciliation_required")
        self.assertIsNone(result["nextSafeAction"])

    def test_equal_time_conflicting_records_fail_closed(self):
        self.save()
        record = json.loads(self.private.read_text())
        record["outcome"] = "conflicting task"
        self.tracked.parent.mkdir(parents=True, exist_ok=True)
        self.tracked.write_text(json.dumps(record))
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertEqual(result["state"], "reconciliation_required")
        self.assertIsNone(result["nextSafeAction"])

    def test_selected_file_drift_requires_reconciliation(self):
        self.save()
        (self.root / "owned.txt").write_text("changed after checkpoint")
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertEqual(result["state"], "reconciliation_required")
        self.assertIn("saved_file_changed:owned.txt", result["issues"])
        self.assertIsNone(result["nextSafeAction"])

    def test_branch_drift_requires_reconciliation(self):
        self.save()
        subprocess.run(["git", "checkout", "-b", "task/different"], cwd=self.root, check=True, capture_output=True)
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertIn("source_branch_changed", result["issues"])
        self.assertIsNone(result["nextSafeAction"])

    def test_revision_drift_requires_reconciliation(self):
        self.save()
        subprocess.run(["git", "commit", "--allow-empty", "-m", "later change"], cwd=self.root, check=True, capture_output=True)
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertIn("source_revision_changed", result["issues"])

    def test_resume_does_not_rewrite_state(self):
        self.save()
        before = {str(p): p.read_bytes() for p in self.private.parent.rglob("*") if p.is_file()}
        result = progress_checkpoint.resume_checkpoint(self.root)
        after = {str(p): p.read_bytes() for p in self.private.parent.rglob("*") if p.is_file()}
        self.assertEqual(result["state"], "ready")
        self.assertEqual(before, after)

    def test_git_failure_is_not_reported_as_no_checkpoint(self):
        with patch.object(progress_checkpoint.subprocess, "run", side_effect=FileNotFoundError("git unavailable")):
            result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertEqual(result["state"], "reconciliation_required")
        self.assertIsNone(result["nextSafeAction"])

    def test_unsafe_saved_path_never_reads_sibling_files(self):
        self.save()
        record = json.loads(self.private.read_text())
        record["savedFiles"] = [{"path": "../foreign.txt", "sha256": "0" * 64}]
        self.private.write_text(json.dumps(record))
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertEqual(result["state"], "reconciliation_required")

    def test_oversize_checkpoint_is_rejected_before_json_parse(self):
        self.save()
        self.private.write_text(" " * (progress_checkpoint.MAX_BATCH_BYTES + 1))
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertEqual(result["state"], "reconciliation_required")

    def test_changed_tracked_checkpoint_cannot_claim_its_old_commit(self):
        self.save(commit=True)
        record = json.loads(self.tracked.read_text())
        record["outcome"] = "uncommitted replacement"
        self.tracked.write_text(json.dumps(record))
        result = progress_checkpoint.resume_checkpoint(self.root)
        self.assertEqual(result["state"], "reconciliation_required")
        self.assertIsNone(result["nextSafeAction"])


    def test_fresh_process_cli_returns_current_saved_action(self):
        self.save()
        command = [sys.executable, "-B", str(SCRIPTS / "progress_checkpoint.py"), "resume", "--root", str(self.root)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["nextSafeAction"], "Verify only the next dependency")
        (self.root / "owned.txt").write_text("later change")
        changed = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(changed.returncode, 2)
        self.assertIsNone(json.loads(changed.stdout)["nextSafeAction"])


if __name__ == "__main__":
    unittest.main()
