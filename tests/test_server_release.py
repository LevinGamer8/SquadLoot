import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

BASE = Path(__file__).resolve().parents[1]

def load_module(filename, name):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

VERSION = (BASE / 'SquadLoot-Pi-Server' / 'VERSION').read_text(encoding='ascii').strip()
updater = load_module(BASE / 'SquadLoot-Pi-Server' / 'server_selfupdate.py', 'server_selfupdate_test')
builder = load_module(BASE / 'scripts' / 'build_release.py', 'server_release_builder_test')


class ReleaseTests(unittest.TestCase):
    def test_release_manifest_and_archive(self):
        with tempfile.TemporaryDirectory() as td:
            archive = builder.build(VERSION, 'LevinGamer8/SquadLoot', Path(td))
            meta = json.loads((Path(td) / 'latest.json').read_text())
            self.assertEqual(meta['version'], VERSION)
            self.assertEqual(meta['package_size'], archive.stat().st_size)
            self.assertEqual(meta['package_sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
            with tempfile.TemporaryDirectory() as extracted:
                files = updater.extract_release(archive.read_bytes(), Path(extracted), VERSION)
                self.assertEqual({str(f) for f in files}, set(updater.RELEASE_FILES))
                self.assertEqual((Path(extracted) / 'VERSION').read_text().strip(), VERSION)
                self.assertNotIn('.env', {str(f) for f in files})
                self.assertNotIn('server-update.conf', {str(f) for f in files})

    def test_release_rejects_traversal_and_extra_files(self):
        with tempfile.TemporaryDirectory() as td:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as zf:
                zf.writestr('../config.json', 'bad')
            with self.assertRaises(ValueError):
                updater.extract_release(buf.getvalue(), Path(td), VERSION)

    def test_update_keeps_local_secrets_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as td:
            location = Path(td) / 'install'
            location.mkdir()
            (location / 'VERSION').write_text('1.2.0')
            (location / 'app').mkdir()
            (location / 'app' / 'server.py').write_text('OLD')
            (location / '.env').write_text('CF_TUNNEL_TOKEN=SECRET')
            (location / 'server-update.conf').write_text('MANIFEST_URL=LOCAL')
            package = builder.build(VERSION, 'LevinGamer8/SquadLoot', Path(td) / 'dist').read_bytes()
            manifest = {'version': VERSION, 'notes': 'test'}
            with patch.object(updater, 'BASE', location), patch.object(updater, 'VERSION_FILE', location / 'VERSION'), patch.object(updater, 'BACKUPS', location / '.server_backups'), patch.object(updater, 'STATE', location / '.server_update_state.json'), patch.object(updater, 'compose_up'):
                updater.apply_release(package, manifest)
            self.assertEqual((location / 'VERSION').read_text().strip(), VERSION)
            self.assertEqual((location / '.env').read_text(), 'CF_TUNNEL_TOKEN=SECRET')
            self.assertEqual((location / 'server-update.conf').read_text(), 'MANIFEST_URL=LOCAL')
            self.assertNotEqual((location / 'app' / 'server.py').read_text(), 'OLD')
            self.assertEqual(len(list((location / '.server_backups').glob('1.2.0-*'))), 1)

    def test_rollback_if_compose_fails(self):
        with tempfile.TemporaryDirectory() as td:
            location = Path(td) / 'install'
            location.mkdir()
            (location / 'VERSION').write_text('1.2.0')
            (location / 'app').mkdir()
            (location / 'app' / 'server.py').write_text('OLD')
            package = builder.build(VERSION, 'LevinGamer8/SquadLoot', Path(td) / 'dist').read_bytes()
            calls = []
            def fail_once():
                calls.append(True)
                if len(calls) == 1:
                    raise RuntimeError('Docker build failed')
            with patch.object(updater, 'BASE', location), patch.object(updater, 'VERSION_FILE', location / 'VERSION'), patch.object(updater, 'BACKUPS', location / '.server_backups'), patch.object(updater, 'STATE', location / '.server_update_state.json'), patch.object(updater, 'compose_up', fail_once):
                with self.assertRaises(RuntimeError):
                    updater.apply_release(package, {'version': VERSION})
            self.assertEqual((location / 'VERSION').read_text().strip(), '1.2.0')
            self.assertEqual((location / 'app' / 'server.py').read_text(), 'OLD')
            self.assertEqual(len(calls), 2)


if __name__ == '__main__': unittest.main()
