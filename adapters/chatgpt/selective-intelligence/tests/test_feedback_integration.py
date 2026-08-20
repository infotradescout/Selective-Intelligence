from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS = TEST_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

import build_engine as BE
import feedback as FB


class AutomaticFeedbackTests(unittest.TestCase):
    def setUp(self):
        self._prior_session_dir = os.environ.get("SI_SESSION_DIR")

    def tearDown(self):
        if self._prior_session_dir is None:
            os.environ.pop("SI_SESSION_DIR", None)
        else:
            os.environ["SI_SESSION_DIR"] = self._prior_session_dir

    def test_approved_run_and_correction_record_privacy_safe_events_automatically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            os.environ["SI_SESSION_DIR"] = str(root / "sessions")
            session = BE.start_project(
                request="Build the wanted result",
                workspace=str(workspace),
                canonical_roots=[],
                plan={"tasks": [{"key": "work", "title": "work", "queue": "ready", "kind": "worker"}]},
                auto_approve=True,
            )
            store = workspace / FB.DEFAULT_STORE
            events, errors = FB.read_events(store)
            self.assertEqual(errors, [])
            self.assertEqual([event["event"] for event in events], ["task_started"])
            self.assertEqual(events[0]["task_id"], session["feedbackTaskId"])

            BE.interrupt_project(session_id=session["sessionId"], correction="That is not the result I meant.")
            events, errors = FB.read_events(store)

        self.assertEqual(errors, [])
        self.assertEqual([event["event"] for event in events], ["task_started", "user_correction"])
        self.assertTrue(all(set(event).issubset(FB.ALLOWED_KEYS) for event in events))


if __name__ == "__main__":
    unittest.main()
