"""Opt-in adapter tests for GabrielGzS/fortnite-visual-chest-counter v0.2.3.

The external app writes cumulative CERTAIN/APPROX OBS text files.
SquadLoot must count positive deltas only and never mix historical rounds.
No external application, video decoder or Fortnite process is required.
"""
import importlib
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

CLIENT = Path(__file__).resolve().parents[1] / 'SquadLoot-Windows-Client'
sys.path.insert(0, str(CLIENT))
visual = importlib.import_module('vision')


class StubCore:
    def __init__(self):
        self.lock = threading.RLock()
        self.round_id = 11
        self.vision = 0
        self.last_live = 55.0


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.core = StubCore()
        self.write(5, 8)
        self.bridge = visual.VisualCounterBridge(self.core)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, certain, approx):
        (self.root / 'certain_chests.txt').write_text(
            f'CERTAIN OPENED CHESTS: {certain}\n', encoding='utf-8')
        (self.root / 'approximate_chests.txt').write_text(
            f'APPROX. OPENED CHESTS: {approx}\n', encoding='utf-8')

    def test_start_baselines_existing_cumulative_counts(self):
        self.bridge.start(self.root)
        self.assertEqual(self.bridge.last_raw, (5, 8))
        self.assertEqual(self.bridge.estimated, 0)
        self.assertEqual(self.core.vision, 0)
        self.assertFalse(self.bridge.poll())

    def test_new_events_are_deltas_approx_includes_certain(self):
        self.bridge.start(self.root)
        self.write(6, 10)
        self.assertTrue(self.bridge.poll())
        self.assertEqual(self.bridge.certain, 1)
        self.assertEqual(self.bridge.estimated, 2)
        self.assertEqual(self.core.vision, 2)  # not 2+1
        self.assertFalse(self.bridge.poll())
        self.assertEqual(self.core.vision, 2)
        self.write(7, 11)
        self.bridge.poll()
        self.assertEqual(self.core.vision, 3)

    def test_new_round_is_not_carryover(self):
        self.bridge.start(self.root)
        self.write(6, 10)
        self.bridge.poll()
        self.core.round_id = 12
        self.core.vision = 0  # core itself resets on new replay
        self.assertFalse(self.bridge.poll())
        self.assertEqual(self.core.vision, 0)
        self.write(7, 11)
        self.assertTrue(self.bridge.poll())
        self.assertEqual(self.core.vision, 1)
        self.assertEqual(self.bridge.certain, 1)

    def test_external_reset_or_profile_switch_does_not_overcount(self):
        self.bridge.start(self.root)
        self.write(6, 10)
        self.bridge.poll()
        self.write(0, 0)
        self.assertFalse(self.bridge.poll())
        self.assertEqual(self.core.vision, 2)
        self.write(1, 1)
        self.assertTrue(self.bridge.poll())
        self.assertEqual(self.core.vision, 3)

    def test_manual_reset_is_respected(self):
        self.bridge.start(self.root)
        self.write(6, 10)
        self.bridge.poll()
        self.core.vision = 0
        self.bridge.reset_baseline()
        self.assertEqual(self.bridge.estimated, 0)
        self.write(7, 11)
        self.bridge.poll()
        self.assertEqual(self.core.vision, 1)

    def test_missing_or_invalid_source_never_changes_existing_count(self):
        self.bridge.start(self.root)
        self.write(6, 10)
        self.bridge.poll()
        (self.root / 'approximate_chests.txt').unlink()
        self.assertFalse(self.bridge.poll())
        self.assertEqual(self.core.vision, 2)
        self.assertTrue(self.bridge.error)

    def test_trust_bounds_and_thousands_parsing(self):
        self.write('1,234', '1,235')
        self.assertEqual(visual.read_visual_counts(self.root), (1234, 1235))
        self.write(20, 4)
        with self.assertRaisesRegex(ValueError, 'CERTAIN'):
            visual.read_visual_counts(self.root)
        (self.root / 'approximate_chests.txt').write_text('APPROX: 3/500\n')
        with self.assertRaises(ValueError):
            visual.read_visual_counts(self.root)

    def test_no_implicit_start(self):
        self.assertFalse(self.bridge.running)
        self.assertFalse(self.bridge.poll())
        self.assertEqual(self.core.vision, 0)


if __name__ == '__main__':
    unittest.main()
