"""The unpublished Windows Live-Beta must not share the stable profile."""
import pathlib
import sys
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_live_test_bundle import build, FOLDER

class BetaIsolationTests(unittest.TestCase):
    def test_bundle_contents_and_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = build(pathlib.Path(tmp) / 'beta.zip')
            with zipfile.ZipFile(archive) as z:
                contents = set(z.namelist())
                self.assertTrue(all(s.startswith(FOLDER + '/') for s in contents))
                self.assertNotIn(FOLDER + '/STARTEN.cmd', contents)
                self.assertFalse(any(p.lower().endswith('/config.json') for p in contents))
                self.assertFalse(any(p.lower().endswith('/state.json') for p in contents))
                cmd = z.read(FOLDER + '/TEST-STARTEN.cmd').decode('utf-8')
                self.assertIn('set "SQUADLOOT_BETA_TEST=1"', cmd)
                self.assertIn('set "APPDATA=%~dp0_testdaten', cmd)
                self.assertIn('set "LOCALAPPDATA=%~dp0_testdaten', cmd)
                boot = z.read(FOLDER + '/bootstrap.py').decode('utf-8')
                self.assertIn("os.getenv('SQUADLOOT_BETA_TEST') != '1'", boot)
                gui = z.read(FOLDER + '/app.py').decode('utf-8')
                self.assertIn('def export_live_beta_report', gui)
                self.assertIn("self.live_test_mode = self.beta_mode or current_version() == '1.5.6'", gui)
                self.assertIn('TEST 1.5.6', gui)

if __name__ == '__main__':
    unittest.main()
