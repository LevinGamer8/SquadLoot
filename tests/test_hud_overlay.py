"""Regressions for the in-game HUD overlay.

Everything that can be checked without Windows runs here: hotkey parsing,
configuration defaults and persistence, geometry at several display scales,
clamping onto a visible monitor, repaint suppression and clean shutdown.

The Win32-only behaviour (click-through via WS_EX_TRANSPARENT, tool-window
style, transparent colour key, RegisterHotKey) cannot be exercised on Linux.
These tests assert that those paths degrade to documented no-ops instead, so
the HUD stays usable on a developer machine.
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
    import tkinter as tk
    HAS_TK = True
except ImportError:
    HAS_TK = False

app = importlib.import_module('app') if HAS_TK else None
client_core = importlib.import_module('client_core') if HAS_TK else None
HAS_DISPLAY = bool(os.environ.get('DISPLAY') or os.name == 'nt')


def demo_members(count=4):
    rows = [{'name': 'LevinGamer8', 'value': 17, 'confirmed': False, 'online': True},
            {'name': 'NoBuildNiko', 'value': 14, 'confirmed': True, 'online': True},
            {'name': 'ChugJugChris', 'value': 21, 'confirmed': False, 'online': True},
            {'name': 'ZonewarsZoe', 'value': 9, 'confirmed': False, 'online': False}]
    return rows[:count]


def demo_data(**overrides):
    data = {'squad': 64, 'personal': 17, 'round': 128, 'connected': True,
            'confirmed': 1, 'estimated': 3, 'members': demo_members(),
            'personal_confirmed': False, 'error': False}
    data.update(overrides)
    return data


@unittest.skipUnless(HAS_TK, 'tkinter is not installed')
class HotkeyParsingTests(unittest.TestCase):
    def test_empty_disables_the_shortcut(self):
        self.assertIsNone(app.parse_hotkey(''))
        self.assertIsNone(app.parse_hotkey('   '))
        self.assertIsNone(app.parse_hotkey(None))

    def test_modifier_combinations(self):
        mods, key = app.parse_hotkey('Ctrl+Alt+H')
        self.assertTrue(mods & app.MOD_CONTROL)
        self.assertTrue(mods & app.MOD_ALT)
        self.assertTrue(mods & app.MOD_NOREPEAT)
        self.assertEqual(key, ord('H'))
        self.assertEqual(app.parse_hotkey('strg+alt+h'), (mods, key))
        self.assertEqual(app.parse_hotkey('Ctrl-Alt-H'), (mods, key))

    def test_function_and_named_keys(self):
        self.assertEqual(app.parse_hotkey('Ctrl+Shift+F9')[1], 0x78)
        self.assertEqual(app.parse_hotkey('Alt+Space')[1], 0x20)
        self.assertEqual(app.parse_hotkey('Ctrl+Alt+Entf')[1], 0x2E)

    def test_a_bare_key_is_refused(self):
        """A plain key would be swallowed globally and break Fortnite input."""
        with self.assertRaisesRegex(ValueError, 'Strg'):
            app.parse_hotkey('H')
        with self.assertRaisesRegex(ValueError, 'Strg'):
            app.parse_hotkey('F5')

    def test_broken_input_is_reported(self):
        with self.assertRaises(ValueError):
            app.parse_hotkey('Ctrl+Alt')
        with self.assertRaises(ValueError):
            app.parse_hotkey('Ctrl+Alt+H+J')
        with self.assertRaises(ValueError):
            app.parse_hotkey('Ctrl+Alt+Nope')

    def test_defaults_parse_and_carry_a_modifier(self):
        for key in ('hud_hotkey_toggle', 'hud_hotkey_lock', 'hud_hotkey_mode'):
            combo = app.parse_hotkey(app.HUD_DEFAULTS[key])
            self.assertIsNotNone(combo, key)
            self.assertTrue(combo[0] & (app.MOD_CONTROL | app.MOD_ALT | app.MOD_SHIFT), key)

    def test_defaults_avoid_plain_game_keys(self):
        """Fortnite and ChestCounter use unmodified keys; we never take one."""
        for key in ('hud_hotkey_toggle', 'hud_hotkey_lock', 'hud_hotkey_mode'):
            text = app.HUD_DEFAULTS[key].lower()
            self.assertIn('ctrl', text)
            self.assertIn('alt', text)


@unittest.skipUnless(HAS_TK, 'tkinter is not installed')
class ConfigurationTests(unittest.TestCase):
    def test_defaults_are_shipped_in_client_core(self):
        config = client_core.default_config()
        for key, value in app.HUD_DEFAULTS.items():
            self.assertIn(key, config, key)
            self.assertEqual(config[key], value, key)

    def test_old_config_without_hud_keys_still_works(self):
        """Backward compatibility: 1.3/1.4 profiles have no hud_* keys at all."""
        legacy = {'client_id': 'x', 'server_url': '', 'token': '', 'name': 'Tester'}
        core = client_core.Core(config=legacy, state={'sent': {}, 'replay_rounds': {}})
        hud = app.Hud.__new__(app.Hud)
        hud.core = core
        for key, value in app.HUD_DEFAULTS.items():
            self.assertEqual(hud.opt(key), value, key)

    def test_scale_is_clamped_to_a_sane_range(self):
        hud = app.Hud.__new__(app.Hud)
        for raw, low, high in ((0.1, 0.79, 0.81), (9.0, 1.59, 1.61), ('bad', 0.99, 1.01)):
            hud.core = client_core.Core(config={'hud_scale': raw},
                                        state={'sent': {}, 'replay_rounds': {}})
            factor = hud.scale() / app.SCALE
            self.assertGreaterEqual(factor, low)
            self.assertLessEqual(factor, high)


@unittest.skipUnless(HAS_TK, 'tkinter is not installed')
class Win32FallbackTests(unittest.TestCase):
    def test_helpers_never_raise_off_windows(self):
        if os.name == 'nt':
            self.skipTest('this asserts the non-Windows fallback')
        self.assertFalse(app.Win32.available)
        self.assertEqual(app.Win32.handle(None), 0)
        self.assertFalse(app.Win32.set_overlay_styles(None, True))
        self.assertFalse(app.Win32.raise_topmost(None))
        self.assertIsNone(app.Win32.virtual_screen())

    def test_listener_without_bindings_exits_immediately(self):
        listener = app.HotkeyListener([], lambda name: None)
        listener.start()
        listener.join(3)
        self.assertFalse(listener.is_alive())
        listener.stop()          # must stay harmless after the thread ended


@unittest.skipUnless(HAS_TK and HAS_DISPLAY, 'needs tkinter and a display')
class HudWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        profile = Path(self.tmp.name)
        self.config_path = profile / 'config.json'
        client_core.CONFIG = self.config_path
        client_core.STATE = profile / 'state.json'
        config = dict(client_core.default_config())
        config.update({'name': 'Tester', 'hud_x': 60, 'hud_y': 60})
        client_core.save_json(self.config_path, config)
        self.core = client_core.Core()
        self.root = tk.Tk()
        self.root.geometry('200x80+0+0')
        self.hud = app.Hud(self.root, self.core)

    def tearDown(self):
        try:
            self.hud.hide()
            self.root.destroy()
        except tk.TclError:
            pass
        self.tmp.cleanup()

    def pump(self):
        for _ in range(3):
            self.root.update_idletasks()
            self.root.update()

    def test_01_compact_hud_matches_the_target_envelope(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        width, height = self.hud._size
        design_w = width / app.SCALE
        design_h = height / app.SCALE
        self.assertGreaterEqual(design_w, 180)
        self.assertLessEqual(design_w, 220)
        self.assertGreaterEqual(design_h, 55)
        self.assertLessEqual(design_h, 75)

    def test_02_expanded_adds_one_row_per_player(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        compact_h = self.hud._size[1]
        self.hud.set_mode('expanded')
        self.hud.update(demo_data())
        self.pump()
        expanded_h = self.hud._size[1]
        self.assertGreater(expanded_h, compact_h)
        self.hud.update(demo_data(members=demo_members(2)))
        self.pump()
        two_rows = self.hud._size[1]
        self.assertLess(two_rows, expanded_h)
        self.assertAlmostEqual(expanded_h - two_rows,
                               2 * self.hud.u(app.Hud.ROW_H), delta=2)

    def test_03_expanded_without_a_round_still_renders(self):
        self.hud.show()
        self.hud.set_mode('expanded')
        self.hud.update(demo_data(members=[], round=None, squad=0, personal=0,
                                  confirmed=0, estimated=0, connected=False))
        self.pump()
        self.assertGreater(self.hud._size[1], self.hud.u(app.Hud.HEAD_H))

    def test_04_long_values_grow_the_card_instead_of_clipping(self):
        self.hud.show()
        self.hud.update(demo_data(squad=1234, personal=999))
        self.pump()
        wide = self.hud._size[0]
        self.hud.update(demo_data(squad=7, personal=3))
        self.pump()
        self.assertLessEqual(self.hud._size[0], wide)
        # The number must still fit between the icon and the divider.
        text_w = self.hud.measure('1234', 25, 'bold')
        self.assertGreater(wide, text_w + self.hud.u(60))

    def test_05_geometry_scales_with_the_display(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        base = self.hud._size
        for factor in (1.25, 1.5, 1.6):          # slider range, see HUD settings
            self.core.config['hud_scale'] = factor
            self.hud.redraw(force=True)
            self.pump()
            scaled = self.hud._size
            self.assertAlmostEqual(scaled[0] / base[0], factor, delta=0.08)
            self.assertAlmostEqual(scaled[1] / base[1], factor, delta=0.08)
        self.core.config['hud_scale'] = 1.0
        # Beyond the slider range the factor is clamped rather than honoured.
        self.core.config['hud_scale'] = 4.0
        self.hud.redraw(force=True)
        self.pump()
        self.assertLess(self.hud._size[0] / base[0], 1.7)
        self.core.config['hud_scale'] = 1.0

    def test_06_position_is_clamped_onto_a_visible_monitor(self):
        box_x, box_y, box_w, box_h = self.hud.screen_box()
        x, y = self.hud.clamp(999999, -999999, 200, 60)
        self.assertLessEqual(x, box_x + box_w - 200)
        self.assertGreaterEqual(x, box_x)
        self.assertGreaterEqual(y, box_y)
        # A position saved on a monitor that no longer exists comes back on screen.
        self.core.config['hud_x'] = box_x + box_w + 4000
        self.core.config['hud_y'] = box_y + box_h + 4000
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        width, height = self.hud._size
        self.assertLessEqual(self.hud.win.winfo_x(), box_x + box_w - width)
        self.assertLessEqual(self.hud.win.winfo_y(), box_y + box_h - height)

    def test_07_position_survives_hide_and_show(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        self.hud.win.geometry('+320+240')
        self.pump()
        self.hud.hide()
        saved = json.loads(self.config_path.read_text(encoding='utf-8'))
        self.assertEqual((saved['hud_x'], saved['hud_y']), (320, 240))
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        self.assertEqual((self.hud.win.winfo_x(), self.hud.win.winfo_y()), (320, 240))

    def test_08_reset_position_moves_clear_of_the_recognition_region(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        self.hud.reset_position()
        self.pump()
        self.assertFalse(self.hud.overlaps_vision_region())
        self.assertIsNotNone(self.hud.vision_region())

    def test_09_overlap_with_the_recognition_region_is_detected(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        left, top, _right, _bottom = self.hud.vision_region()
        self.hud.win.geometry(f'+{left + 20}+{top + 20}')
        self.pump()
        self.assertTrue(self.hud.overlaps_vision_region())

    def test_10_repaints_only_when_a_value_changes(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        calls = []
        original = self.hud.canvas.delete
        self.hud.canvas.delete = lambda *a, **k: (calls.append(a), original(*a, **k))[1]
        for _ in range(5):
            self.hud.update(demo_data())
        self.assertEqual(calls, [])
        self.hud.update(demo_data(squad=65))
        self.assertTrue(calls)

    def test_10b_no_drawn_text_is_clipped_by_the_card(self):
        """Every label and number must stay inside the window at any scale."""
        self.hud.show()
        cases = (demo_data(),
                 demo_data(squad=1234, personal=999),
                 demo_data(members=[{'name': 'EinSehrLangerSpielername',
                                     'value': 128, 'confirmed': True, 'online': True}]))
        for mode in ('compact', 'expanded'):
            self.core.config['hud_mode'] = mode
            for factor in (1.0, 1.25, 1.5, 1.6):
                self.core.config['hud_scale'] = factor
                for data in cases:
                    self.hud.update(data)
                    self.hud.redraw(force=True)
                    self.pump()
                    width, height = self.hud._size
                    for item in self.hud.canvas.find_all():
                        if self.hud.canvas.type(item) != 'text':
                            continue
                        x1, y1, x2, y2 = self.hud.canvas.bbox(item)
                        text = self.hud.canvas.itemcget(item, 'text')
                        where = f'{mode} x{factor} "{text}"'
                        self.assertGreaterEqual(x1, 0, where)
                        self.assertGreaterEqual(y1, 0, where)
                        self.assertLessEqual(x2, width, where)
                        self.assertLessEqual(y2, height, where)
        self.core.config['hud_scale'] = 1.0
        self.core.config['hud_mode'] = 'compact'

    def test_11_colour_tells_estimated_from_confirmed(self):
        self.hud.show()
        self.hud.update(demo_data())
        squad, personal, status = self.hud.tones()
        self.assertEqual(squad, app.T.CYAN)
        self.assertEqual(personal, app.T.CYAN)
        self.assertEqual(status, app.T.OK)
        self.hud.update(demo_data(estimated=0, confirmed=4, personal_confirmed=True))
        squad, personal, _ = self.hud.tones()
        self.assertEqual(squad, app.T.OK)
        self.assertEqual(personal, app.T.OK)
        self.hud.update(demo_data(round=None, connected=False))
        squad, personal, status = self.hud.tones()
        self.assertEqual(squad, app.T.MUTE)
        self.assertEqual(personal, app.T.MUTE)
        self.assertEqual(status, app.T.MUTE)
        self.hud.update(demo_data(error=True))
        self.assertEqual(self.hud.tones()[2], app.T.BAD)

    def test_12_lock_and_mode_are_persisted(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.hud.set_locked(False)
        self.hud.set_mode('expanded')
        saved = json.loads(self.config_path.read_text(encoding='utf-8'))
        self.assertFalse(saved['hud_locked'])
        self.assertEqual(saved['hud_mode'], 'expanded')
        self.hud.toggle_lock()
        self.hud.toggle_mode()
        saved = json.loads(self.config_path.read_text(encoding='utf-8'))
        self.assertTrue(saved['hud_locked'])
        self.assertEqual(saved['hud_mode'], 'compact')

    def test_13_dragging_is_ignored_while_locked(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        before = (self.hud.win.winfo_x(), self.hud.win.winfo_y())

        class Event:
            x_root = before[0] + 120
            y_root = before[1] + 90

        self.core.config['hud_locked'] = True
        self.hud._drag_start(Event())
        self.assertIsNone(self.hud._drag_from)
        self.hud._drag_move(Event())
        self.pump()
        self.assertEqual((self.hud.win.winfo_x(), self.hud.win.winfo_y()), before)

    def test_14_dragging_moves_the_card_while_unlocked(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        self.core.config['hud_locked'] = False
        start_x, start_y = self.hud.win.winfo_x(), self.hud.win.winfo_y()

        class Down:
            x_root = start_x + 10
            y_root = start_y + 10

        class Move:
            x_root = start_x + 90
            y_root = start_y + 70

        self.hud._drag_start(Down())
        self.assertIsNotNone(self.hud._drag_from)
        self.hud._drag_move(Move())
        self.pump()
        self.assertEqual((self.hud.win.winfo_x(), self.hud.win.winfo_y()),
                         (start_x + 80, start_y + 60))
        self.hud._drag_end(Move())
        saved = json.loads(self.config_path.read_text(encoding='utf-8'))
        self.assertEqual(saved['hud_x'], start_x + 80)

    def test_15_window_has_no_titlebar_and_stays_on_top(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        self.assertTrue(self.hud.win.overrideredirect())
        self.assertTrue(bool(self.hud.win.attributes('-topmost')))

    def test_16_hide_tears_everything_down(self):
        self.hud.show()
        self.hud.update(demo_data())
        self.pump()
        window = self.hud.win
        self.hud.hide()
        self.assertIsNone(self.hud.win)
        self.assertIsNone(self.hud.canvas)
        self.assertFalse(window.winfo_exists())
        self.hud.hide()                 # idempotent
        self.hud.update(demo_data())    # must not raise once hidden

    def test_17_opacity_setting_is_applied_and_clamped(self):
        self.hud.show()
        self.core.config['hud_opacity'] = 5.0
        self.hud.apply_opacity()
        self.assertLessEqual(float(self.hud.win.attributes('-alpha')), 1.0)
        self.core.config['hud_opacity'] = 0.0
        self.hud.apply_opacity()
        self.assertGreaterEqual(float(self.hud.win.attributes('-alpha')), 0.34)


@unittest.skipUnless(HAS_TK and HAS_DISPLAY, 'needs tkinter and a display')
class HudInGuiTests(unittest.TestCase):
    """The HUD as wired into the real application window."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        profile = Path(cls.tmp.name)
        client_core.APPDIR = profile
        client_core.CONFIG = profile / 'config.json'
        client_core.STATE = profile / 'state.json'
        config = dict(client_core.default_config())
        config.update({'name': 'Tester', 'auto_update': False})
        client_core.save_json(client_core.CONFIG, config)
        app.CONFIG = client_core.CONFIG
        app.UNKNOWN_ICONS.clear()
        cls.gui = app.Gui()
        cls.gui.root.geometry('1200x760')
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

    def test_01_hud_is_off_until_the_user_asks_for_it(self):
        self.assertFalse(self.gui.hud.visible)
        self.assertFalse(self.gui.hud.opt('hud_enabled'))

    def test_02_quick_action_opens_and_closes_the_hud(self):
        self.gui.toggle_overlay()
        self.pump()
        self.assertTrue(self.gui.hud.visible)
        self.assertTrue(self.gui.hud.opt('hud_enabled'))
        self.gui.toggle_overlay()
        self.pump()
        self.assertFalse(self.gui.hud.visible)
        self.assertFalse(self.gui.hud.opt('hud_enabled'))

    def test_03_refresh_feeds_the_hud_without_errors(self):
        self.gui.toggle_overlay()
        self.gui.core.current_state = {
            'round': {'id': 9, 'created': 1762700000.0, 'chests_total': 44,
                      'members': [
                          {'name': 'Tester', 'live_chests': 18, 'ammo': 3, 'food': 1,
                           'destroyed': 1, 'verified_chests': None, 'online': True},
                          {'name': 'Mate', 'live_chests': 10, 'ammo': 1, 'food': 0,
                           'destroyed': 0, 'verified_chests': 26, 'online': True}]},
            'history': [], 'accounts': [], 'treasures': [], 'total_matches': 2}
        self.gui.core.connected = True
        self.gui.core.manual = 18
        self.gui.refresh()
        self.pump()
        self.assertEqual(self.gui.hud.data['squad'], 44)
        self.assertEqual(self.gui.hud.data['personal'], 18)
        self.assertEqual(len(self.gui.hud.data['members']), 2)
        self.assertEqual(app.UNKNOWN_ICONS, set())

    def test_04_hotkey_events_drive_the_hud(self):
        self.assertTrue(self.gui.hud.visible)
        self.gui.handle_events([('hotkey', 'mode')])
        self.assertEqual(self.gui.hud.opt('hud_mode'), 'expanded')
        self.gui.handle_events([('hotkey', 'lock')])
        self.assertFalse(self.gui.hud.opt('hud_locked'))
        self.gui.handle_events([('hotkey', 'toggle')])
        self.pump()
        self.assertFalse(self.gui.hud.visible)
        self.gui.handle_events([('hotkey', 'toggle')])
        self.pump()
        self.assertTrue(self.gui.hud.visible)

    def test_05_settings_panel_mirrors_the_hud_state(self):
        self.gui.show_page('settings')
        self.pump()
        self.gui.hud.set_mode('compact')
        self.gui.hud.set_locked(True)
        self.assertTrue(self.gui.hud_toggle.get())
        self.assertFalse(self.gui.hud_expanded.get())
        self.assertTrue(self.gui.hud_lock.get())
        self.gui.hud.set_enabled(False)
        self.pump()
        self.assertFalse(self.gui.hud_toggle.get())

    def test_06_bad_hotkey_is_rejected_without_touching_the_config(self):
        self.gui.show_page('settings')
        field = self.gui.hud_fields['hud_hotkey_toggle']
        previous = self.gui.hud.opt('hud_hotkey_toggle')
        field.set('H')
        self.gui.apply_hotkeys()
        self.assertIn('Strg', field.hint_var.get())
        self.assertEqual(self.gui.hud.opt('hud_hotkey_toggle'), previous)
        field.set('Ctrl+Alt+J')
        self.gui.apply_hotkeys()
        self.assertEqual(self.gui.hud.opt('hud_hotkey_toggle'), 'Ctrl+Alt+J')
        field.set(previous)
        self.gui.apply_hotkeys()

    def test_07_hud_survives_the_main_window_closing(self):
        self.gui.hud.set_enabled(True)
        self.pump()
        self.gui.stop_hotkeys()
        self.gui.hud.hide()
        self.assertIsNone(self.gui.hud.win)


if __name__ == '__main__':
    unittest.main()
