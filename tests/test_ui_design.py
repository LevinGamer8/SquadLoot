"""Regressions for the SquadLoot design system and the redesigned desktop UI.

The pure helpers (tokens, geometry, aggregation) are tested everywhere. The
full Tk smoke test needs tkinter plus a display and skips itself otherwise, so
headless CI still runs the rest of the file.
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'SquadLoot-Windows-Client'
sys.path.insert(0, str(CLIENT))

try:
    import tkinter  # noqa: F401
    HAS_TK = True
except ImportError:
    HAS_TK = False

app = importlib.import_module('app') if HAS_TK else None
HAS_DISPLAY = bool(os.environ.get('DISPLAY') or os.name == 'nt')


@unittest.skipUnless(HAS_TK, 'tkinter is not installed')
class DesignSystemTests(unittest.TestCase):
    def test_scaling_helper_rounds_up_and_never_collapses(self):
        self.assertGreaterEqual(app.px(1), 1)
        self.assertGreaterEqual(app.px(0.1), 1)
        self.assertEqual(app.px(16), round(16 * app.SCALE))

    def test_colour_mixer_stays_in_range(self):
        self.assertEqual(app.mix('#000000', '#ffffff', 0), '#000000')
        self.assertEqual(app.mix('#000000', '#ffffff', 1), '#ffffff')
        self.assertEqual(app.mix('#000000', '#ffffff', .5), '#808080')
        self.assertEqual(app.mix('#5b78f0', '#5b78f0', .37), '#5b78f0')

    def test_rounded_rect_outline_stays_inside_its_box(self):
        points = app.round_points(0, 0, 100, 60, 14)
        xs, ys = points[0::2], points[1::2]
        self.assertGreaterEqual(min(xs), -0.001)
        self.assertGreaterEqual(min(ys), -0.001)
        self.assertLessEqual(max(xs), 100.001)
        self.assertLessEqual(max(ys), 60.001)
        self.assertEqual(len(points) % 2, 0)
        # A radius larger than the box must clamp instead of inverting it.
        tiny = app.round_points(0, 0, 10, 4, 40)
        self.assertLessEqual(max(tiny[1::2]), 4.001)

    def test_every_icon_definition_is_well_formed(self):
        for name, shapes in app.ICONS.items():
            self.assertTrue(shapes, name)
            for shape in shapes:
                kind = shape[0]
                self.assertIn(kind, ('p', 'o', 'd', 'a'), name)
                if kind == 'p':
                    self.assertEqual(len(shape), 3, name)
                    self.assertEqual(len(shape[1]) % 2, 0, name)
                    self.assertGreaterEqual(len(shape[1]), 4, name)
                elif kind in ('o', 'd'):
                    self.assertEqual(len(shape[1]), 4, name)
                else:
                    self.assertEqual(len(shape[1]), 6, name)
                for value in shape[1]:
                    self.assertIsInstance(value, (int, float), name)

    def test_navigation_covers_every_page(self):
        keys = [key for key, _title, _icon in app.NAV]
        self.assertEqual(keys, ['dashboard', 'live', 'history', 'squad',
                                'settings', 'updates'])
        for key, _title, icon in app.NAV:
            self.assertIn(key, app.PAGE_META)
            self.assertIn(icon, app.ICONS)


@unittest.skipUnless(HAS_TK, 'tkinter is not installed')
class AggregationTests(unittest.TestCase):
    def members(self):
        return [
            {'name': 'A', 'live_chests': 17, 'ammo': 6, 'food': 3, 'destroyed': 2,
             'verified_chests': None, 'online': True},
            {'name': 'B', 'live_chests': 12, 'ammo': 4, 'food': 2, 'destroyed': 1,
             'verified_chests': 14, 'verified_ammo': 5, 'verified_food': 3,
             'verified_destroyed': 0, 'verified_treasures': 2, 'online': True},
            {'name': 'C', 'live_chests': 9, 'ammo': 2, 'food': 1, 'destroyed': 0,
             'verified_chests': None, 'online': False},
        ]

    def test_confirmed_values_win_over_live_estimates(self):
        totals = app.aggregate(self.members())
        self.assertEqual(totals['chests'], 17 + 14 + 9)
        self.assertEqual(totals['ammo'], 6 + 5 + 2)      # B uses its replay value
        self.assertEqual(totals['food'], 3 + 3 + 1)
        self.assertEqual(totals['destroyed'], 2 + 0 + 0)
        self.assertEqual(totals['treasures'], 2)
        self.assertEqual((totals['confirmed'], totals['estimated']), (1, 2))
        self.assertEqual(totals['online'], 2)

    def test_missing_verified_fields_fall_back_to_live(self):
        """An older server without verified_* keys must still aggregate."""
        legacy = [{'name': 'A', 'live_chests': 5, 'ammo': 2, 'food': 1,
                   'destroyed': 1, 'verified_chests': None, 'online': True}]
        totals = app.aggregate(legacy)
        self.assertEqual((totals['chests'], totals['ammo'], totals['food']), (5, 2, 1))

    def test_empty_round_is_all_zero(self):
        self.assertEqual(app.aggregate([])['chests'], 0)

    def test_relative_time_labels(self):
        self.assertEqual(app.ago(None), 'nie')
        self.assertEqual(app.ago(2), 'gerade eben')
        self.assertEqual(app.ago(42), 'vor 42 s')
        self.assertEqual(app.ago(300), 'vor 5 min')
        self.assertEqual(app.ago(7200), 'vor 2 h')
        self.assertEqual(app.clock(None), '–')
        self.assertEqual(app.clock('nonsense'), '–')


@unittest.skipUnless(HAS_TK and HAS_DISPLAY, 'needs tkinter and a display')
class DesktopSmokeTests(unittest.TestCase):
    """Builds the real window, walks every page and checks nothing clips away."""

    @classmethod
    def setUpClass(cls):
        import client_core
        cls.tmp = tempfile.TemporaryDirectory()
        profile = Path(cls.tmp.name)
        client_core.APPDIR = profile
        client_core.CONFIG = profile / 'config.json'
        client_core.STATE = profile / 'state.json'
        (profile / 'config.json').write_text(json.dumps({
            'client_id': 'test', 'server_url': '', 'token': '', 'name': 'Tester',
            'data_json': str(profile / 'data.json'), 'replay_dir': str(profile),
            'chestcounter_exe': '', 'vision_template': '', 'interact_key': 'E',
            'cf_access_client_id': '', 'cf_access_client_secret': '',
            'auto_update': False}), encoding='utf-8')
        app.CONFIG = client_core.CONFIG
        app.UNKNOWN_ICONS.clear()
        cls.gui = app.Gui()
        cls.gui.root.geometry('1060x680')
        cls.gui.root.update_idletasks()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.gui.close()
        except Exception:
            pass
        cls.tmp.cleanup()

    def pump(self):
        for _ in range(3):
            self.gui.root.update_idletasks()
            self.gui.root.update()

    def test_01_every_page_builds_and_switches(self):
        for key, _title, _icon in app.NAV:
            self.gui.show_page(key)
            self.pump()
            self.assertEqual(self.gui.active, key)
            self.assertTrue(self.gui.pages[key].winfo_ismapped())
            self.assertEqual(self.gui.page_title.get(), app.PAGE_META[key][0])

    def test_02_no_unknown_icon_was_requested(self):
        self.assertEqual(app.UNKNOWN_ICONS, set())

    def test_03_refresh_tolerates_an_empty_offline_state(self):
        self.gui.core.current_state = {}
        self.gui.core.connected = False
        self.gui.refresh()
        self.pump()
        self.assertEqual(self.gui.stats['squad'].value.get(), '0')
        self.assertIn('Nicht', self.gui.conn_pill._text)

    def test_04_refresh_renders_a_live_round(self):
        self.gui.core.current_state = {
            'round': {'id': 7, 'created': 1762700000.0, 'chests_total': 40,
                      'members': [
                          {'name': 'Tester', 'live_chests': 18, 'ammo': 4, 'food': 2,
                           'destroyed': 1, 'verified_chests': None, 'online': True},
                          {'name': 'Mate', 'live_chests': 10, 'ammo': 2, 'food': 1,
                           'destroyed': 0, 'verified_chests': 22,
                           'verified_treasures': 1, 'online': True}]},
            'history': [{'started': 1762600000.0, 'players': 2, 'chests': 31,
                         'destroyed': 2, 'reopened': 1, 'ammo': 7, 'food': 3,
                         'treasures': 1, 'breakdown': 'Tester: 18 / Mate: 13'}],
            'accounts': [{'name': 'Tester', 'matches': 3, 'chests': 55, 'ammo': 12,
                          'food': 5, 'treasures': 1}],
            'treasures': [], 'total_matches': 3}
        self.gui.core.connected = True
        self.gui.refresh()
        self.pump()
        self.assertEqual(self.gui.stats['squad'].value.get(), '40')
        self.assertEqual(self.gui.stats['round'].value.get(), '#7')
        self.assertTrue(self.gui.dash_members.winfo_children())
        self.assertTrue(self.gui.history_box.winfo_children())
        self.assertTrue(self.gui.account_box.winfo_children())
        self.assertEqual(app.UNKNOWN_ICONS, set())

    def test_05_settings_validation_reports_bad_input_inline(self):
        self.gui.show_page('settings')
        self.gui.fields['server_url'].set('not-a-url')
        self.gui.fields['token'].set('short')
        self.gui.fields['name'].set('')
        self.gui.fields['cf_access_client_id'].set('only-id')
        self.gui.fields['cf_access_client_secret'].set('')
        self.assertIsNone(self.gui.collect_settings())
        self.assertIn('Server-URL', self.gui.fields['server_url'].hint_var.get())
        self.assertIn('kurz', self.gui.fields['token'].hint_var.get())
        self.assertIn('Anzeigenamen', self.gui.fields['name'].hint_var.get())
        self.gui.fields['server_url'].set('https://loot.example.net')
        self.gui.fields['token'].set('x' * 30)
        self.gui.fields['name'].set('Tester')
        self.gui.fields['cf_access_client_secret'].set('only-secret')
        values = self.gui.collect_settings()
        self.assertIsNotNone(values)
        self.assertEqual(values['server_url'], 'https://loot.example.net')

    def test_06_secret_fields_are_masked_until_revealed(self):
        token = self.gui.fields['token']
        self.assertEqual(token.entry.cget('show'), '*')
        token.toggle_secret()
        self.assertEqual(token.entry.cget('show'), '')
        self.gui.show_page('dashboard')          # leaving settings re-masks
        self.assertEqual(token.entry.cget('show'), '*')

    def test_07_window_survives_a_small_and_a_large_size(self):
        for geometry in ('1060x680', '1600x1000', '1120x720'):
            self.gui.root.geometry(geometry)
            self.pump()
            self.gui.refresh()
            self.pump()
        self.assertEqual(app.UNKNOWN_ICONS, set())

    def test_09_live_language_quality_and_diagnostics_controls(self):
        self.gui.show_page('live')
        self.assertIn('Englisch (CHEST)', self.gui.live_language_values)
        self.assertEqual(self.gui.live_rate_values['Ausgewogen · 15 fps'], 15)
        self.assertIn('Munitionskiste', self.gui.missed_kind_values)
        self.gui.choose_live_rate('Sparsam · 10 fps')
        self.assertEqual(self.gui.core.config['live_process_fps'], 10)
        self.gui.choose_live_language('Deutsch (TRUHE · Beta)')
        self.assertEqual(self.gui.core.config['live_language'], 'de')
        # Nothing gets recorded just by opening the live tab.
        self.assertFalse(self.gui.live_engine.diagnostic_mode)
        self.gui.toggle_live_diagnostics(False)
        self.assertFalse(self.gui.core.config['live_diagnostics'])
        self.gui.choose_live_rate('Ausgewogen · 15 fps')
        self.gui.choose_live_language('Englisch (CHEST)')
        self.assertEqual(app.UNKNOWN_ICONS, set())

    def test_08_live_monitor_selector_shows_thumbnail(self):
        from unittest.mock import patch
        from vision import _ppm_from_bgra
        self.gui.show_page('live')
        with patch('app.list_capture_monitors', return_value=[
                    (0, 0, 1920, 1080), (1920, 0, 2560, 1440)]):
            self.gui.refresh_live_monitors()
        label = next(text for text, index in self.gui.live_monitor_values.items()
                     if index == 2)
        self.gui.live_monitor_var.set(label)
        self.assertIn('Monitor 2', self.gui.live_monitor_var.get())
        screenshot = _ppm_from_bgra(bytes([0, 0, 255, 0, 0, 255, 0, 0]), 2, 1)
        self.gui._show_live_monitor_preview(self.gui.monitor_preview_seq, 2, screenshot)
        self.assertEqual(self.gui.monitor_preview_image.width(), 2)
        self.assertEqual(self.gui.monitor_preview_image.height(), 1)
        self.assertIn('Monitor 2', self.gui.monitor_note.get())
        self.assertEqual(app.UNKNOWN_ICONS, set())


if __name__ == '__main__':
    unittest.main()
