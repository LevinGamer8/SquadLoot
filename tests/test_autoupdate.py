import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
CLIENT=ROOT/'SquadLoot-Windows-Client'
SERVER=ROOT/'SquadLoot-Pi-Server'
sys.path.insert(0,str(CLIENT))
from client_core import Api
import update_manager as updater

spec=importlib.util.spec_from_file_location('squad_updates_server',SERVER/'app'/'server.py')
server=importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
TOKEN='test-very-long-and-secret-squad-token-1234'


def client_archive():
    with io.BytesIO() as out:
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name in sorted(updater.ALLOWED_FILES):
                path=CLIENT/name
                if path.is_file():z.write(path,arcname=name)
        return out.getvalue()


class AutoUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.basedir=Path(cls.tmp.name)
        cls.updates=cls.basedir/'updates'
        cls.updates.mkdir()
        cls.raw=client_archive()
        cls.manifest={'version':'1.3.1','archive_sha256':hashlib.sha256(cls.raw).hexdigest(),
                      'archive_size':len(cls.raw),'notes':'Dark layout and auto updates'}
        (cls.updates/'client.zip').write_bytes(cls.raw)
        (cls.updates/'latest.json').write_text(json.dumps(cls.manifest),encoding='utf-8')
        server.TOKEN=TOKEN
        server.DB_PATH=cls.basedir/'db.sqlite3'
        server.UPDATE_ZIP=cls.updates/'client.zip'
        server.UPDATE_MANIFEST=cls.updates/'latest.json'
        server.init_database()
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.http.server_port)
        cls.api=Api(cls.url,TOKEN)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(3)
        cls.tmp.cleanup()

    def test_01_manifest_and_download_require_token(self):
        m=self.api.call('/api/client-update/manifest')
        self.assertEqual(m['version'],'1.3.1')
        self.assertEqual(self.api.download_update(),self.raw)
        with self.assertRaisesRegex(RuntimeError,'401'):
            Api(self.url,'x'*26).call('/api/client-update/manifest')
        with self.assertRaisesRegex(RuntimeError,'401'):
            Api(self.url,'x'*26).download_update()

    def test_02_reject_dangerous_zip_path(self):
        with io.BytesIO() as buffer:
            with zipfile.ZipFile(buffer,'w') as z:
                for name in updater.REQUIRED_FILES:
                    z.writestr(name,'1.3.1' if name=='VERSION' else '# test')
                z.writestr('../evil.py','something')
            with self.assertRaisesRegex(ValueError,'nicht erlaubte'):
                updater.inspect_archive(buffer.getvalue(),'1.3.1')

    def test_03_verify_manifest(self):
        self.assertEqual(updater.validate_manifest(self.manifest)['version'],'1.3.1')
        with self.assertRaises(ValueError):
            updater.validate_manifest({**self.manifest,'archive_sha256':'broken'})
        with self.assertRaises(ValueError):
            updater.validate_manifest({**self.manifest,'version':'1.3.1\nevil'})
        self.assertIsNone(updater.validate_manifest({'version':None,'available':False}))

    def test_04_download_apply_preserves_user_data_and_blocks_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            root=folder/'app'; root.mkdir()
            settings=folder/'profile';settings.mkdir()
            update_dir=settings/'updates';update_dir.mkdir()
            (root/'VERSION').write_text('1.0.0')
            (root/'app.py').write_text('OLD APP')
            (root/'my-private-config.json').write_text('{"token":"keep"}')
            cfg={'server_url':self.url,'token':TOKEN}
            with patch.object(updater,'PENDING_DIR',update_dir),\
                 patch.object(updater,'PENDING_FILE',update_dir/'pending.json'),\
                 patch.object(updater,'ARCHIVE_FILE',update_dir/'pending.zip'):
                self.assertEqual(updater.check_and_stage(cfg,root=root),'1.3.1')
                self.assertEqual(updater.apply_pending(root=root),'1.3.1')
                self.assertEqual((root/'VERSION').read_text().strip(),'1.3.1')
                self.assertIn('class Gui', (root/'app.py').read_text())
                self.assertEqual((root/'my-private-config.json').read_text(),'{"token":"keep"}')
                self.assertFalse((update_dir/'pending.json').exists())
                self.assertIsNone(updater.check_and_stage(cfg,root=root))

    def test_05_corrupt_download_refused(self):
        wrong={**self.manifest,'archive_sha256':'0'*64}
        with patch.object(updater,'validate_manifest',return_value=wrong):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                (root/'VERSION').write_text('1.0.0')
                with self.assertRaisesRegex(ValueError,'Integritaetspruefung'):
                    updater.check_and_stage({'server_url':self.url,'token':TOKEN},root=root)

    def test_06_server_manifest_missing_returns_none(self):
        prior=server.UPDATE_MANIFEST
        try:
            server.UPDATE_MANIFEST=self.basedir/'missing.json'
            self.assertEqual(self.api.call('/api/client-update/manifest')['available'],False)
        finally:
            server.UPDATE_MANIFEST=prior

if __name__=='__main__':unittest.main()
