import hashlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('loader', Path(__file__).resolve().parents[1] / 'adapters/refresh_embedded_skill.py')
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)

class LoaderTests(unittest.TestCase):
    def test_approved_utility_hash_matches_real_file(self):
        utility = Path(__file__).with_name('refresh_embedded_skill.py').read_bytes()
        self.assertEqual(hashlib.sha256(utility).hexdigest(), loader.UTILITY_SHA256)

    def test_approved_utility_runs_in_existing_installation_location(self):
        body = b'def main():\n    from pathlib import Path\n    return 17 if Path(__file__).name == "refresh_embedded_skill.py" else 1\n'
        with patch.object(loader, 'UTILITY_SHA256', hashlib.sha256(body).hexdigest()), patch.object(loader.urllib.request, 'urlopen', return_value=io.BytesIO(body)):
            self.assertEqual(loader.main(), 17)

    def test_unapproved_code_is_never_executed(self):
        body = b'raise AssertionError("MUST NOT EXECUTE")'
        with patch.object(loader.urllib.request, 'urlopen', return_value=io.BytesIO(body)), patch('sys.stderr', io.StringIO()):
            self.assertEqual(loader.main(), 1)

    def test_oversized_download_is_never_executed(self):
        body = b'#' * (loader.MAX_UTILITY + 1)
        with patch.object(loader, 'UTILITY_SHA256', hashlib.sha256(body).hexdigest()), patch.object(loader.urllib.request, 'urlopen', return_value=io.BytesIO(body)), patch('sys.stderr', io.StringIO()):
            self.assertEqual(loader.main(), 1)

    def test_network_failure_does_not_claim_update(self):
        with patch.object(loader.urllib.request, 'urlopen', side_effect=OSError('offline')), patch('sys.stderr', io.StringIO()) as error:
            self.assertEqual(loader.main(), 1)
            self.assertIn('not updated', error.getvalue())

if __name__ == '__main__':
    unittest.main(verbosity=2)
