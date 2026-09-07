"""Exercise the real queue commands; no provider calls or storage substitutes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL_ROOT = Path(os.environ.get("SI_TEST_SKILL_ROOT", str(Path(__file__).resolve().parents[1])))
SCRIPT = SKILL_ROOT / "scripts" / "prompt_queue.py"


class PromptQueueContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="si-queue-continuity-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.queue = self.root / "queue.jsonl"
        self.snapshot = self.root / "snapshot.json"

    def command(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], cwd=self.root,
                              capture_output=True, text=True, timeout=10, check=False)

    def prepare(self, *, count: int = 1, selected: int = 0, position: int | None = None) -> None:
        ids = []
        for index in range(count):
            result = self.command("enqueue", "--queue", str(self.queue), "--prompt",
                                  f"Preserve approved requirement {index}", "--source", "synthetic-test",
                                  "--branch", "repair")
            self.assertEqual(result.returncode, 0, result.stderr)
            ids.append(result.stdout.splitlines()[0])
        records = [json.loads(line) for line in self.queue.read_text().splitlines()]
        for index, record in enumerate(records):
            record["created_at"] = f"2026-01-01T00:00:{index:02d}Z"
        self.queue.write_text("".join(json.dumps(record) + "\n" for record in records))
        result = self.command("claim", "--queue", str(self.queue), "--queue-id", ids[selected],
                              "--owner", "worker-one")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = ["snapshot", "--queue", str(self.queue), "--snapshot", str(self.snapshot),
                "--queue-id", ids[selected], "--owner", "worker-one"]
        if position is not None:
            args.extend(["--expected-position", str(position)])
        result = self.command(*args)
        self.assertEqual(result.returncode, 0, result.stderr)

    def check(self) -> tuple[subprocess.CompletedProcess[str], dict]:
        queue_before = self.queue.read_bytes()
        snapshot_before = self.snapshot.read_bytes()
        result = self.command("check", "--queue", str(self.queue), "--snapshot", str(self.snapshot),
                              "--check-owner", "--check-branch", "--enforce-sequential")
        self.assertEqual(self.queue.read_bytes(), queue_before)
        self.assertEqual(self.snapshot.read_bytes(), snapshot_before)
        return result, json.loads(result.stdout)

    def test_default_snapshot_allows_first_valid_task(self) -> None:
        self.prepare()
        self.assertIsNone(json.loads(self.snapshot.read_text())["expected_position"])
        result, outcome = self.check()
        self.assertEqual(result.returncode, 0, outcome)
        self.assertEqual(outcome["decision"], "continue")

    def test_default_snapshot_still_blocks_later_task(self) -> None:
        self.prepare(count=2, selected=1)
        result, outcome = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(outcome["decision"], "interrupt")
        self.assertIn("expects 1", outcome["reason"][0])

    def test_legacy_missing_position_uses_same_default(self) -> None:
        self.prepare()
        snapshot = json.loads(self.snapshot.read_text())
        del snapshot["expected_position"]
        self.snapshot.write_text(json.dumps(snapshot))
        result, outcome = self.check()
        self.assertEqual(result.returncode, 0, outcome)
        self.assertEqual(outcome["decision"], "continue")

    def test_explicit_first_position_remains_valid(self) -> None:
        self.prepare(position=1)
        result, outcome = self.check()
        self.assertEqual(result.returncode, 0, outcome)

    def test_explicit_second_position_is_preserved(self) -> None:
        self.prepare(count=2, selected=1, position=2)
        result, outcome = self.check()
        self.assertEqual(result.returncode, 0, outcome)
        self.assertEqual(outcome["position"], 2)

    def test_explicit_wrong_position_is_rejected(self) -> None:
        self.prepare(position=2)
        result, outcome = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(outcome["decision"], "interrupt")

    def test_owner_mismatch_still_interrupts(self) -> None:
        self.prepare()
        snapshot = json.loads(self.snapshot.read_text())
        snapshot["owner_id"] = "different-worker"
        self.snapshot.write_text(json.dumps(snapshot))
        result, outcome = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertTrue(any("owner mismatch" in reason for reason in outcome["reason"]))

    def test_branch_mismatch_still_interrupts(self) -> None:
        self.prepare()
        snapshot = json.loads(self.snapshot.read_text())
        snapshot["branch"] = "different-branch"
        self.snapshot.write_text(json.dumps(snapshot))
        result, outcome = self.check()
        self.assertEqual(result.returncode, 2)
        self.assertTrue(any("branch mismatch" in reason for reason in outcome["reason"]))


if __name__ == "__main__":
    unittest.main()
