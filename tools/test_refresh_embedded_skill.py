import importlib.util
import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('refresh', Path(__file__).with_name('refresh_embedded_skill.py'))
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.destination = self.root / '.agents/skills/selective-intelligence'
        self.destination.mkdir(parents=True)
        (self.destination / 'SKILL.md').write_text('old skill\n')
        (self.destination / 'custom-note.txt').write_text('preserve in backup\n')
        self.project = self.root / '.selective-intelligence'
        self.project.mkdir()
        (self.project / 'history.json').write_text('{"approved":"human intent"}\n')
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'SKILL.md').write_text('---\nname: selective-intelligence\n---\nSoftware does not imply SaaS.\n')
        (self.source / 'scripts').mkdir()
        (self.source / 'scripts/check.py').write_text('print("current")\n')
        (self.source / 'scripts/check.py').chmod(0o755)
        self.expected = refresh.directory_hash(self.source)
        self.pin = patch.object(refresh, 'SOURCE_TREE', self.expected)
        self.pin.start()
        self.original = refresh.directory_hash(self.destination)

    def tearDown(self):
        self.pin.stop()
        self.temp.cleanup()

    def archive(self, extras=(), omit=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.source.rglob('*')):
                if not path.is_file() or path.name == omit:
                    continue
                info = zipfile.ZipInfo(refresh.SOURCE_PREFIX + path.relative_to(self.source).as_posix())
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | (0o755 if path.stat().st_mode & 0o111 else 0o644)) << 16
                archive.writestr(info, path.read_bytes())
            for info, content in extras:
                archive.writestr(info, content)
        return output.getvalue()

    def test_check_does_not_write_or_download(self):
        with patch.object(refresh, 'download_source', side_effect=AssertionError('no network')):
            self.assertEqual(refresh.refresh(self.destination)['status'], 'outdated')
        self.assertEqual(refresh.directory_hash(self.destination), self.original)

    def test_full_replacement_preserves_project_and_old_customization(self):
        result = refresh.refresh(self.destination, apply=True, source=self.archive())
        self.assertEqual(result['status'], 'updated')
        self.assertEqual(refresh.directory_hash(self.destination), self.expected)
        self.assertEqual((self.project / 'history.json').read_text(), '{"approved":"human intent"}\n')
        copies = list((self.root / '.agents/.si-refresh-backups').glob('previous-*'))
        self.assertEqual(len(copies), 1)
        self.assertEqual(refresh.directory_hash(copies[0]), self.original)
        self.assertFalse(any(p.name.startswith('previous-') for p in self.destination.parent.iterdir()))

    def test_repeat_is_no_op_without_network(self):
        refresh.refresh(self.destination, apply=True, source=self.archive())
        with patch.object(refresh, 'download_source', side_effect=AssertionError('no network')):
            self.assertFalse(refresh.refresh(self.destination, apply=True)['changed'])

    def test_partial_archive_preserves_original(self):
        with self.assertRaises(ValueError):
            refresh.refresh(self.destination, apply=True, source=self.archive(omit='check.py'))
        self.assertEqual(refresh.directory_hash(self.destination), self.original)

    def test_wrong_content_preserves_original(self):
        (self.source / 'SKILL.md').write_text('unapproved replacement')
        with self.assertRaises(ValueError):
            refresh.refresh(self.destination, apply=True, source=self.archive())
        self.assertEqual(refresh.directory_hash(self.destination), self.original)

    def test_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            refresh.refresh(self.destination, apply=True, source=self.archive([(refresh.SOURCE_PREFIX + '../escape.txt', 'bad')]))
        self.assertFalse((self.root / 'escape.txt').exists())
        self.assertEqual(refresh.directory_hash(self.destination), self.original)

    def test_archive_symlink_is_rejected(self):
        info = zipfile.ZipInfo(refresh.SOURCE_PREFIX + 'link')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError):
            refresh.refresh(self.destination, apply=True, source=self.archive([(info, '/tmp')]))
        self.assertEqual(refresh.directory_hash(self.destination), self.original)

    def test_case_collision_is_rejected(self):
        with self.assertRaises(ValueError):
            refresh.refresh(self.destination, apply=True, source=self.archive([(refresh.SOURCE_PREFIX + 'skill.md', 'bad')]))
        self.assertEqual(refresh.directory_hash(self.destination), self.original)

    def test_existing_lock_is_not_removed(self):
        lock = self.destination.parent / '.selective-intelligence-refresh.lock'
        lock.write_text('another process')
        with self.assertRaises(FileExistsError):
            refresh.refresh(self.destination, apply=True, source=self.archive())
        self.assertEqual(lock.read_text(), 'another process')

    def test_unrelated_destination_is_rejected(self):
        with self.assertRaises(ValueError):
            refresh.refresh(self.project, apply=True, source=self.archive())
        self.assertTrue((self.project / 'history.json').exists())

    def test_symbolic_link_destination_is_rejected(self):
        link = self.root / '.claude/skills/selective-intelligence'
        link.parent.mkdir(parents=True)
        link.symlink_to(self.destination, target_is_directory=True)
        with self.assertRaises(ValueError):
            refresh.refresh(link, apply=True, source=self.archive())

    def test_concurrent_change_is_preserved_not_overwritten(self):
        def download():
            (self.destination / 'concurrent.txt').write_text('do not lose')
            return self.archive()
        with patch.object(refresh, 'download_source', side_effect=download):
            with self.assertRaises(ValueError):
                refresh.refresh(self.destination, apply=True)
        self.assertEqual((self.destination / 'concurrent.txt').read_text(), 'do not lose')
        self.assertEqual((self.destination / 'SKILL.md').read_text(), 'old skill\n')

    def test_failed_install_rolls_back(self):
        replace = os.replace
        def fail_stage(source, destination):
            if Path(source).name.startswith('stage-'):
                raise OSError('simulated installation failure')
            return replace(source, destination)
        with patch.object(refresh.os, 'replace', side_effect=fail_stage):
            with self.assertRaises(OSError):
                refresh.refresh(self.destination, apply=True, source=self.archive())
        self.assertEqual(refresh.directory_hash(self.destination), self.original)
        self.assertFalse((self.destination.parent / '.selective-intelligence-refresh.lock').exists())

    def test_git_tree_matches_git(self):
        import subprocess
        import shutil
        git_root = self.root / 'git-proof'
        shutil.copytree(self.source, git_root)
        subprocess.run(['git', 'init', '-q', str(git_root)], check=True)
        subprocess.run(['git', '-C', str(git_root), 'add', '.'], check=True)
        tree = subprocess.check_output(['git', '-C', str(git_root), 'write-tree'], text=True).strip()
        self.assertEqual(tree, self.expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
