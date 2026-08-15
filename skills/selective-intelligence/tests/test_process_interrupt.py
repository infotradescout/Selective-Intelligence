from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS = TEST_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from policy_guard import PolicyGuard, guarded_run


class CancelableProcessTests(unittest.TestCase):
    def test_high_output_command_cannot_deadlock_on_a_full_pipe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "test_output.py").write_text(
                "import sys, unittest\n"
                "class Loud(unittest.TestCase):\n"
                "    def test_emit(self):\n"
                "        sys.stdout.write('x' * 2000000)\n"
                "        sys.stderr.write('y' * 200000)\n",
                encoding="utf-8",
            )
            guard = PolicyGuard(canonical_roots=[], writable_roots=[root])
            started = time.monotonic()
            _, evidence = guarded_run(
                [sys.executable, "-m", "unittest", "test_output.py"],
                cwd=root,
                guard=guard,
                session_id="si-output-test",
                task_id="task-output-test",
                timeout=10,
            )
            elapsed = time.monotonic() - started

        self.assertEqual(evidence["exitCode"], 0)
        self.assertLess(elapsed, 5)
        self.assertEqual(evidence["stdoutBytes"], 2000000)
        self.assertGreaterEqual(evidence["stderrBytes"], 200000)
        self.assertTrue(evidence["stdoutTruncated"])
        self.assertFalse(evidence["stderrTruncated"])
        self.assertIn("output truncated", evidence["stdout"])

    def test_si_owned_verification_process_stops_when_interrupt_is_observed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "test_slow.py").write_text(
                "import time, unittest\n"
                "class Slow(unittest.TestCase):\n"
                "    def test_wait(self): time.sleep(20)\n",
                encoding="utf-8",
            )
            guard = PolicyGuard(canonical_roots=[], writable_roots=[root])
            polls = 0

            def interrupted() -> bool:
                nonlocal polls
                polls += 1
                return polls >= 4

            started = time.monotonic()
            _, evidence = guarded_run(
                [sys.executable, "-m", "unittest", "test_slow.py"],
                cwd=root,
                guard=guard,
                session_id="si-interrupt-test",
                task_id="task-interrupt-test",
                timeout=10,
                cancel_check=interrupted,
            )
            elapsed = time.monotonic() - started

        self.assertTrue(evidence["cancelled"])
        self.assertLess(elapsed, 5, "interrupt should stop the SI-owned process promptly")
        self.assertNotEqual(evidence["exitCode"], 0)


if __name__ == "__main__":
    unittest.main()
