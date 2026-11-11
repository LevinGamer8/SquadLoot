"""Tests for the unreleased English HUD loot prototype (no gameplay included)."""
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

CLIENT = pathlib.Path(__file__).resolve().parents[1] / 'SquadLoot-Windows-Client'
sys.path.insert(0, str(CLIENT))

from vision import ManagedComponentStore, ManagedLiveEngine, _LOOT_WORKER_SOURCE


class LootPopupPatchTests(unittest.TestCase):
    def test_worker_source_compiles_without_installing_packages(self):
        compile(_LOOT_WORKER_SOURCE, 'squadloot_loot_popup.py', 'exec')
        self.assertIn('fftconvolve', _LOOT_WORKER_SOURCE)
        self.assertIn('ammo', _LOOT_WORKER_SOURCE)
        self.assertIn('food', _LOOT_WORKER_SOURCE)
        self.assertNotIn('cv2', _LOOT_WORKER_SOURCE)

    def test_pinned_source_patch_idempotent_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            store = ManagedComponentStore(root=root)
            pkg = store.visual_root() / 'runtime/lib/fortnite_chest_counter'
            pkg.mkdir(parents=True)
            counter = pkg / 'counter.py'
            original = (
                'def run(source, session, est, cfg):\n'
                '    if guard is not None:\n'
                '        guard.on_request = source.request_stop\n'
                '    try:\n'
                '        for t, frame in source.frames():\n'
                '            applied = session.apply(est.process_frame(t, frame), t)\n'
                '    finally:\n'
                '        pass\n'
            )
            counter.write_text(original, encoding='utf-8')
            self.assertTrue(store.install_loot_popup())
            patched = counter.read_text(encoding='utf-8')
            self.assertIn('# SquadLootLootPopupsV1', patched)
            self.assertIn('squadloot_loot.update(t, frame)', patched)
            self.assertEqual(counter.with_name('counter.py.squadloot-original').read_text(), original)
            self.assertFalse(store.install_loot_popup())
            self.assertEqual(patched, counter.read_text(encoding='utf-8'))
            self.assertTrue((pkg / 'squadloot_loot_popup.py').is_file())

    def test_unknown_counter_source_remains_unmodified(self):
        with tempfile.TemporaryDirectory() as td:
            store = ManagedComponentStore(root=td)
            pkg = store.visual_root() / 'runtime/lib/fortnite_chest_counter'
            pkg.mkdir(parents=True)
            (pkg / 'counter.py').write_text('print("unknown")', encoding='utf-8')
            with self.assertRaises(RuntimeError):
                store.install_loot_popup()
            self.assertFalse((pkg / 'squadloot_loot_popup.py').exists())

    def test_feed_only_english_ammo_and_food(self):
        class Core:
            def __init__(self):
                self.config = {'live_language': 'en'}
                self.ammo = self.food = 0
            def adjust(self, kind, n):
                setattr(self, kind, getattr(self, kind) + n)
        core = Core()
        engine = ManagedLiveEngine(core)
        self.assertTrue(engine.feed_loot_message({
            'type': 'squadloot_loot', 'kind': 'ammo', 'confidence': 0.98}))
        self.assertTrue(engine.feed_loot_message({
            'type': 'squadloot_loot', 'kind': 'food', 'confidence': 0.98}))
        self.assertEqual((core.ammo, core.food), (1, 1))
        for kind in ('chest', 'destroyed', 'other'):
            self.assertFalse(engine.feed_loot_message({
                'type': 'squadloot_loot', 'kind': kind, 'confidence': 0.99}))
        self.assertFalse(engine.feed_loot_message({
            'type': 'squadloot_loot', 'kind': 'ammo', 'confidence': 0.11}))
        self.assertEqual((core.ammo, core.food), (1, 1))
        core.config['live_language'] = 'de'
        self.assertFalse(engine.feed_loot_message({
            'type': 'squadloot_loot', 'kind': 'ammo', 'confidence': 0.99}))

if __name__ == '__main__':
    unittest.main()
