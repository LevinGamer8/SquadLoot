"""The 1.5.2 client no longer offers manual +1/-1 loot entry.

Keep wire/API compatibility with older clients and all historic SQLite matches.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / 'SquadLoot-Windows-Client'
APP = (WINDOWS / 'app.py').read_text(encoding='utf-8')
CORE = (WINDOWS / 'client_core.py').read_text(encoding='utf-8')
WEB = (ROOT / 'SquadLoot-Pi-Server' / 'app' / 'dashboard.html').read_text(encoding='utf-8')
SERVER = (ROOT / 'SquadLoot-Pi-Server' / 'app' / 'server.py').read_text(encoding='utf-8')


class AutomaticOnlyInterfaceTests(unittest.TestCase):
    def test_manual_increment_buttons_and_handlers_removed(self):
        for old in ("core.adjust('manual'", "core.adjust('ammo'",
                    "core.adjust('food'", "Manuelle Steuerung",
                    "'manual', 'Manuell'", "def destroyed(self):",
                    "self.live_tiles['manual']"):
            self.assertNotIn(old, APP, old)

    def test_detection_and_replay_controls_preserved(self):
        for needed in ('Live-Test starten', 'Live-Test stoppen',
                       'Replay auswerten',
                       "self.live_tiles['vision'].set(",
                       "self.live_tiles['squad'].set(squad_total)",
                       'def toggle_integrated_live(self):',
                       'self.live_engine = ManagedLiveEngine(self.core)',
                       'self.core.replay_engine.start()'):
            self.assertIn(needed, APP, needed)

    def test_no_manual_stat_card_or_manual_live_caption(self):
        for banned in ("'0 manuell · 0 erkannt'",
                       "f'{manual} manuell",
                       'Manuelle Zählung ist immer eine Schätzung.'):
            self.assertNotIn(banned, APP)
        self.assertIn('visuell erkannt', APP)

    def test_older_clients_and_match_history_remain_compatible(self):
        self.assertIn("'manual':self.manual", CORE)
        self.assertIn("'manual',l['manual']", SERVER) if "'manual',l['manual']" in SERVER else self.assertIn("l['manual']", SERVER)
        self.assertIn('def submit_match(data):', SERVER)
        self.assertIn('def get_match_archive(', SERVER)
        self.assertIn('def export_matches_csv(', SERVER)

    def test_web_describes_visual_estimates_not_manual_clicks(self):
        self.assertNotIn('Schätzungen aus manuellen Klicks', WEB)
        self.assertIn('aus der visuellen Erkennung', WEB)
        self.assertIn('id="archiveCard"', WEB)
        self.assertIn('/api/export/matches.csv', WEB)

    def test_single_button_ui_and_passive_replay_are_visible(self):
        for forbidden in ('PNG-Vorlage', 'OBS-Ordner wählen',
                          'Deutsch zurücksetzen',
                          'Erkennung starten', 'self.vision_meter',
                          "'chestcounter_exe', 'Pfad zur"):
            self.assertNotIn(forbidden, APP)
        self.assertIn('self.core.replay_sync_all(force=True)', APP)
        self.assertIn('def configure_german_live(self):', APP)
        self.assertIn('def choose_live_rate(self, title):', APP)
        self.assertIn('self.core.replay_engine.start()', APP)

    def test_version_pair_stays_in_sync(self):
        win = (WINDOWS / 'VERSION').read_text(encoding='ascii').strip()
        pi = (ROOT / 'SquadLoot-Pi-Server' / 'VERSION').read_text(encoding='ascii').strip()
        self.assertEqual(win, pi)
        self.assertEqual(len(win.split('.')), 3)
        self.assertTrue(all(part.isdigit() for part in win.split('.')))


if __name__ == '__main__':
    unittest.main()
