"""Regressions for the redesigned Raspberry Pi dashboard.

The dashboard ships as a single self-contained HTML file because the Pi release
allowlist (server_selfupdate.RELEASE_FILES) only carries app/dashboard.html and
the page is served with a strict CSP and explicitly allowed Fortnite-image hosts.
These tests pin both properties plus the XSS-safe rendering style.
"""
import importlib.util
import json
import re
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'SquadLoot-Pi-Server' / 'app' / 'dashboard.html'
HTML = PAGE.read_text(encoding='utf-8')

spec = importlib.util.spec_from_file_location(
    'squadloot_web_server', ROOT / 'SquadLoot-Pi-Server' / 'app' / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

selfupdate_spec = importlib.util.spec_from_file_location(
    'squadloot_pi_selfupdate', ROOT / 'SquadLoot-Pi-Server' / 'server_selfupdate.py')
selfupdate = importlib.util.module_from_spec(selfupdate_spec)
selfupdate_spec.loader.exec_module(selfupdate)

TOKEN = 'unittest-supersecret-long-key-12345678'


class SelfContainedTests(unittest.TestCase):
    def test_only_whitelisted_external_image_hosts(self):
        """No external script/style; reviewed Fortnite imagery is permitted."""
        from urllib.parse import urlsplit
        self.assertNotIn('<link rel="stylesheet"', HTML)
        self.assertNotIn('@import', HTML)
        self.assertNotRegex(HTML, r'<script[^>]+src=')
        allowed = {
            'www.vice.com', 'fortnite-api.com',
            'ik.imagekit.io', 'cdn.mos.cms.futurecdn.net'
        }
        images = re.findall(r'<img[^>]+src="(https?://[^"]+)"', HTML)
        self.assertGreaterEqual(len(images), 3)
        for url in images:
            self.assertEqual(urlsplit(url).scheme, 'https')
            self.assertIn(urlsplit(url).hostname, allowed)
        self.assertNotRegex(HTML, r'<iframe[^>]+src=')

    def test_v131_archive_csv_and_fortnite_images_survived_redesign(self):
        """A visual redesign must not silently remove existing features."""
        for text in ('id="archiveCard"', 'id="archiveRows"',
                     'id="archivePrev"', 'id="archiveNext"',
                     'id="downloadCsv"', '/api/matches?limit=',
                     '/api/export/matches.csv', 'function loadArchive',
                     'function exactFortniteImage', 'fortnite-api.com',
                     'fortnite-pirate-shop-token-item.jpg'):
            self.assertIn(text, HTML, text)
        self.assertIn('image.addEventListener(\'error\'', HTML)
        self.assertNotIn('innerHTML', HTML)

    def test_still_a_single_release_file(self):
        self.assertIn('app/dashboard.html', selfupdate.RELEASE_FILES)
        self.assertIn('app/dashboard.html', selfupdate.REQUIRED)
        # Comfortably below the Pi package limits even after the redesign.
        self.assertLess(len(HTML.encode('utf-8')), 300 * 1024)

    def test_every_referenced_icon_symbol_exists(self):
        defined = set(re.findall(r'<symbol id="(s-[a-z-]+)"', HTML))
        # Scan everything except the sprite itself: markup references icons with
        # href="#s-x", the script passes bare 's-x' strings.
        body = HTML[HTML.index('</defs>'):]
        used = set(re.findall(r"""['"#](s-[a-z-]+)""", body))
        self.assertTrue(defined)
        self.assertEqual(used - defined, set(), 'icon referenced but not defined')
        self.assertEqual(defined - used, set(), 'icon defined but never used')

    def test_chest_and_container_icons_are_present(self):
        for name in ('s-chest', 's-chest-rare', 's-chest-buried', 's-ammo',
                     's-food', 's-burst', 's-refresh', 's-gem'):
            self.assertIn(f'<symbol id="{name}"', HTML)

    def test_api_values_are_never_written_as_raw_html(self):
        """Rendering goes through textContent / createElement, so no innerHTML."""
        self.assertNotIn('innerHTML', HTML)
        self.assertNotIn('outerHTML', HTML)
        self.assertNotIn('document.write', HTML)
        self.assertNotIn('insertAdjacentHTML', HTML)
        self.assertNotIn('eval(', HTML)

    def test_token_handling_stays_private(self):
        self.assertIn("sessionStorage.getItem('squad-token')", HTML)
        self.assertNotIn('localStorage', HTML)
        # The token must travel in the Authorization header, never in a URL.
        self.assertIn("'Authorization': 'Bearer ' + secret", HTML)
        self.assertNotIn('?token=', HTML)
        for line in HTML.splitlines():
            if 'console.' in line:
                self.assertNotIn('secret', line)

    def test_polling_is_throttled_and_pauses_in_background_tabs(self):
        self.assertIn('document.hidden', HTML)
        self.assertIn('visibilitychange', HTML)
        interval = int(re.search(r'const BASE_INTERVAL = (\d+);', HTML).group(1))
        ceiling = int(re.search(r'const MAX_INTERVAL = (\d+);', HTML).group(1))
        self.assertGreaterEqual(interval, 2000)
        self.assertGreater(ceiling, interval)

    def test_offline_and_empty_states_exist(self):
        self.assertIn('errorBanner', HTML)
        self.assertIn('function emptyState', HTML)
        self.assertIn('skel', HTML)
        self.assertIn('Erneut versuchen', HTML)

    def test_responsive_breakpoints_present(self):
        self.assertIn('@media (max-width:900px)', HTML)
        self.assertIn('@media (max-width:620px)', HTML)
        self.assertIn('prefers-reduced-motion', HTML)

    def test_shares_the_desktop_colour_tokens(self):
        for token in ('--accent:#5B78F0', '--cyan:#38BDF8', '--ok:#34D399',
                      '--bad:#F2787C', '--surface:#111724', '--bg:#080B12'):
            self.assertIn(token, HTML)


class ServedPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(cls.tmp.name) / 'web.sqlite3'
        server.TOKEN = TOKEN
        server.init_database()
        cls.http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.http.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(2)
        cls.tmp.cleanup()

    def test_page_is_served_with_security_headers(self):
        with urllib.request.urlopen(self.url + '/', timeout=5) as response:
            body = response.read().decode('utf-8')
            policy = response.headers['Content-Security-Policy']
        self.assertEqual(body, HTML)
        self.assertIn("default-src 'self'", policy)
        self.assertIn("img-src 'self'", policy)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_state_endpoint_exposes_confirmed_and_estimated_fields(self):
        request = urllib.request.Request(self.url + '/api/round/join', method='POST',
                                         data=json.dumps({'client_id': 'pc0', 'name': 'Tester',
                                                          'local_replay': 'r0'}).encode())
        request.add_header('Authorization', 'Bearer ' + TOKEN)
        request.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(request, timeout=5) as response:
            rid = json.load(response)['round_id']
        match = {'client_id': 'pc0', 'session_id': 'web-1', 'name': 'Tester',
                 'account_id': 'a0', 'started': '2026-11-09T18:30:00Z', 'mode': 'x',
                 'chests': 12, 'destroyed': 2, 'reopened': 1, 'ammo': 5, 'food': 3,
                 'other': 0, 'treasure_count': 1, 'treasure_names': ['Shop-Token'],
                 'round_id': rid, 'kinds': {}}
        request = urllib.request.Request(self.url + '/api/match', method='POST',
                                         data=json.dumps(match).encode())
        request.add_header('Authorization', 'Bearer ' + TOKEN)
        request.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(request, timeout=5).read()
        request = urllib.request.Request(self.url + '/api/state')
        request.add_header('Authorization', 'Bearer ' + TOKEN)
        with urllib.request.urlopen(request, timeout=5) as response:
            state = json.load(response)
        member = state['round']['members'][0]
        for key in ('verified_chests', 'verified_ammo', 'verified_food',
                    'verified_destroyed', 'verified_reopened', 'verified_treasures'):
            self.assertIn(key, member)
        self.assertEqual(member['verified_ammo'], 5)
        self.assertEqual(member['verified_destroyed'], 2)
        self.assertEqual(member['verified_reopened'], 1)


if __name__ == '__main__':
    unittest.main()
