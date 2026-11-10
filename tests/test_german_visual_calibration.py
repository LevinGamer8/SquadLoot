"""German Visual Chest Counter calibration: safe opt-in v0.2.3 source patch.

No installed third-party program or screenshot of a real player is required.
The fake image tests only the color mask and NPY format, not real accuracy.
"""
import ast
import importlib
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1] / 'SquadLoot-Windows-Client'
sys.path.insert(0, str(CLIENT))
vision = importlib.import_module('vision')


class FakePhoto:
    def width(self):
        return 1280

    def height(self):
        return 720

    def get(self, x, y):
        if 805 <= x < 830 and 215 <= y < 225 and (x + y) % 3:
            return (242, 199, 244)
        return (10, 15, 16)


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.obs = self.root / 'obs_output'
        self.obs.mkdir()
        self.pkg = self.root / 'runtime' / 'lib' / 'fortnite_chest_counter'
        (self.pkg / 'detection').mkdir(parents=True)
        (self.pkg / 'templates' / 'chest' / 'en').mkdir(parents=True)
        (self.pkg / 'templates' / 'chest' / 'en' / 'chest.npy').write_bytes(b'original')
        self.visual = self.pkg / 'detection' / 'visual.py'
        self.settings = self.pkg / 'settings.py'
        self.original_visual = "CHEST_TEMPLATES = [\n]\n"
        self.original_settings = vision._FVCC_ORIGINAL_LANGUAGES + '\n'
        self.visual.write_text(self.original_visual, encoding='utf-8')
        self.settings.write_text(self.original_settings, encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_selection_mask_from_lavender_word(self):
        rows = vision.german_word_mask(FakePhoto(), (800, 210, 836, 231))
        self.assertGreaterEqual(len(rows[0]), 20)
        self.assertEqual(len(rows), 10)
        self.assertGreater(sum(map(sum, rows)), 30)
        with self.assertRaises(ValueError):
            vision.german_word_mask(FakePhoto(), (0, 0, 40, 20))
        with self.assertRaises(ValueError):
            vision.german_word_mask(FakePhoto(), (800, 340, 860, 360))

    def test_numpy_npy_v1_header_and_float_body(self):
        data = vision.german_numpy_template([[1.0, 0.0, 1.0], [0.0, 1.0, 0.0]])
        self.assertEqual(data[:8], b'\x93NUMPY\x01\x00')
        header_len = struct.unpack('<H', data[8:10])[0]
        self.assertEqual((10 + header_len) % 16, 0)
        header = ast.literal_eval(data[10:10+header_len].decode('latin1'))
        self.assertEqual(header['shape'], (2, 3))
        self.assertEqual(header['descr'], '<f4')
        self.assertEqual(struct.unpack('<6f', data[10+header_len:]),
                         (1.0, 0.0, 1.0, 0.0, 1.0, 0.0))

    def test_patch_is_explicit_backup_and_reversible(self):
        matrix = vision.german_word_mask(FakePhoto(), (800, 210, 836, 231))
        result = vision.install_german_visual_template(self.obs, matrix)
        self.assertTrue(result['fresh'])
        self.assertEqual(result['width'], 25)
        self.assertEqual(result['height'], 10)
        patched = self.visual.read_text(encoding='utf-8')
        choices = self.settings.read_text(encoding='utf-8')
        self.assertIn('"id": "de:TRUHE"', patched)
        self.assertIn('Deutsch (SquadLoot Beta)', choices)
        compile(patched, str(self.visual), 'exec')
        compile(choices, str(self.settings), 'exec')
        path = self.pkg / 'templates' / 'chest' / 'de' / 'truhe.npy'
        self.assertTrue(path.is_file())
        original = (self.root / '.squadloot-german-backup' / 'visual.py')
        self.assertEqual(original.read_text(encoding='utf-8'),
                         self.original_visual)
        result_again = vision.install_german_visual_template(self.obs, matrix)
        self.assertFalse(result_again['fresh'])
        self.assertEqual(self.visual.read_text(encoding='utf-8'), patched)
        vision.restore_german_visual_template(self.obs)
        self.assertEqual(self.visual.read_text(encoding='utf-8'),
                         self.original_visual)
        self.assertEqual(self.settings.read_text(encoding='utf-8'),
                         self.original_settings)
        self.assertFalse(path.exists())
        self.assertFalse((self.root / '.squadloot-german-backup').exists())

    def test_unknown_version_fails_without_creating_backups(self):
        self.settings.write_text('LANGUAGE_CHOICES = []\n', encoding='utf-8')
        matrix = [[1.0, 0.0], [0.0, 1.0]]
        with self.assertRaisesRegex(ValueError, 'nicht unterstützt'):
            vision.install_german_visual_template(self.obs, matrix)
        self.assertEqual(self.visual.read_text(encoding='utf-8'),
                         self.original_visual)
        self.assertFalse((self.root / '.squadloot-german-backup').exists())

    def test_version_upgraded_external_app_not_restored_over(self):
        matrix = vision.german_word_mask(FakePhoto(), (800, 210, 836, 231))
        vision.install_german_visual_template(self.obs, matrix)
        self.visual.write_text('CHEST_TEMPLATES = []\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'aktualisiert'):
            vision.restore_german_visual_template(self.obs)
        self.assertEqual(self.visual.read_text(encoding='utf-8'),
                         'CHEST_TEMPLATES = []\n')

    def test_client_features_preserved_and_no_new_update_files(self):
        app = (CLIENT / 'app.py').read_text(encoding='utf-8')
        update = (CLIENT / 'update_manager.py').read_text(encoding='utf-8')
        # 1.5.4 uses the already calibrated private template automatically;
        # the user sees no extra external-counter setup UI.
        self.assertNotIn('Deutsch kalibrieren', app)
        self.assertNotIn('OBS-Ordner wählen', app)
        self.assertIn('def toggle_integrated_live(self):', app)
        self.assertIn('self.live_engine = ManagedLiveEngine(self.core)', app)
        self.assertIn('def adopt_german_template(self, previous_obs):',
                      (CLIENT / 'vision.py').read_text(encoding='utf-8'))
        self.assertIn('ALLOWED_FILES', update)
        self.assertNotIn('de_template.npy', update)


if __name__ == '__main__':
    unittest.main()
