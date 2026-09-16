"""Cross-platform index regressions; Git process failures are explicitly simulated."""
from __future__ import annotations
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import project_index as PI


class IndexPortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lf = b"def owned_value():\n    return 1\n"
        self.crlf = self.lf.replace(b"\n", b"\r\n")

    def test_newline_equivalent_copies_are_not_mislabeled_byte_identical(self):
        (self.root / "owner.py").write_bytes(self.crlf)
        (self.root / "copy.py").write_bytes(self.lf)
        result = PI.build_index(self.root)
        files = {item["path"]: item for item in result["inventory"]["files"]}
        self.assertNotEqual(files["owner.py"]["sha256"], files["copy.py"]["sha256"])
        self.assertEqual(files["owner.py"]["sha256"], hashlib.sha256(self.crlf).hexdigest())
        self.assertEqual(result["inventory"]["duplicates"]["exact_files"], [])
        copies = result["inventory"]["duplicates"]["line_ending_equivalent_files"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]["paths"], ["copy.py", "owner.py"])
        self.assertEqual(copies[0]["normalization"], "crlf-to-lf")
        self.assertTrue(any(item["code"] == "PI001" for item in result["findings"]))
        self.assertEqual((self.root / "owner.py").read_bytes(), self.crlf)

    def test_overlay_detects_newline_copy_without_writing_it(self):
        (self.root / "owner.py").write_bytes(self.crlf)
        result = PI.build_index(self.root, proposed_files={"new/copy.py": self.lf.decode()})
        self.assertTrue(any(item["code"] == "PI001" for item in result["findings"]))
        self.assertFalse((self.root / "new").exists())

    def test_exact_duplicates_keep_their_raw_byte_identity(self):
        for name in ("a.py", "b.py"):
            (self.root / name).write_bytes(self.crlf)
        result = PI.build_index(self.root)
        groups = result["inventory"]["duplicates"]
        self.assertEqual(groups["exact_files"][0]["sha256"], hashlib.sha256(self.crlf).hexdigest())
        self.assertEqual(groups.get("line_ending_equivalent_files", []), [])

    def test_missing_git_keeps_inventory_but_does_not_invent_revision(self):
        (self.root / "owner.py").write_bytes(self.lf)
        with mock.patch.object(PI.subprocess, "run", side_effect=FileNotFoundError()):
            result = PI.build_index(self.root)
        self.assertEqual(result["source"]["git_probe_status"], "unavailable")
        self.assertIsNone(result["source"]["revision"])
        self.assertIsNone(result["source"]["dirty"])
        self.assertEqual(result["summary"]["source_files"], 1)

    def test_git_access_denials_and_timeouts_still_fail_closed(self):
        for error in (PermissionError("denied"), subprocess.TimeoutExpired("git", 10)):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(PI.subprocess, "run", side_effect=error):
                    with self.assertRaises(type(error)):
                        PI.build_index(self.root)

    def test_content_changes_and_whitespace_are_not_equivalent_copies(self):
        (self.root / "a.py").write_bytes(self.crlf)
        (self.root / "b.py").write_bytes(self.lf.replace(b"return 1", b"return 2"))
        (self.root / "empty.py").write_bytes(b"\r\n")
        (self.root / "also_empty.py").write_bytes(b"\n")
        result = PI.build_index(self.root)
        self.assertFalse(any(item["code"] == "PI001" for item in result["findings"]))


if __name__ == "__main__":
    unittest.main()
