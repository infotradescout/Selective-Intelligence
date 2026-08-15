import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import site_review_gate as SRG  # noqa: E402


class SiteReviewGateTests(unittest.TestCase):
    def _receipt(self, root: Path) -> Path:
        renders = root / "renders"
        renders.mkdir()
        (renders / "mobile.png").write_bytes(b"mobile")
        (renders / "desktop.png").write_bytes(b"desktop")
        receipt = {
            "schemaVersion": "si.site_review.v1",
            "humanVeto": False,
            "renders": {"mobile": "renders/mobile.png", "desktop": "renders/desktop.png"},
            "primaryJourney": "pass",
            "objector": {"independent": True, "verdict": "strong_checkpoint", "blockingFindings": []},
            "dimensions": {name: "pass" for name in SRG.DIMENSIONS},
            "genericSignals": {name: False for name in SRG.GENERIC_SIGNALS},
        }
        path = root / "review.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        return path

    def test_complete_receipt_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            result = SRG.review_gate(self._receipt(Path(temp)))
            self.assertTrue(result["passed"])
            self.assertEqual(result["review"], "review.json")
            self.assertNotIn(str(Path(temp).parent), json.dumps(result))

    def test_human_veto_fails_even_when_everything_else_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._receipt(Path(temp))
            data = json.loads(path.read_text(encoding="utf-8"))
            data["humanVeto"] = True
            path.write_text(json.dumps(data), encoding="utf-8")
            result = SRG.review_gate(path)
            self.assertFalse(result["passed"])
            self.assertIn("human veto is present", result["errors"])

    def test_weak_dimension_and_missing_render_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self._receipt(Path(temp))
            data = json.loads(path.read_text(encoding="utf-8"))
            data["dimensions"]["hierarchy"] = "weak"
            data["renders"]["mobile"] = "renders/missing.png"
            path.write_text(json.dumps(data), encoding="utf-8")
            result = SRG.review_gate(path)
            self.assertFalse(result["passed"])
            self.assertTrue(any("hierarchy" in error for error in result["errors"]))
            self.assertTrue(any("mobile" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
