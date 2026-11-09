from __future__ import annotations
import csv
import importlib.util
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'SquadLoot-Pi-Server/app/server.py'
spec = importlib.util.spec_from_file_location('squadloot_server_test', FILE)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(self.temp.name) / 'statistik.db'
        server.TOKEN = 'unit-test-secret-' + 'x'*30
        server.init_database()
        self.http = ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_address[1]}'

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self,path,auth=True):
        hdr={'Authorization':'Bearer '+server.TOKEN} if auth else {}
        req=urllib.request.Request(self.base+path,headers=hdr)
        with urllib.request.urlopen(req,timeout=4) as resp:
            return resp.read()

    def seed(self,n=65):
        with server.database() as db:
            for i in range(n):
                db.execute('''INSERT INTO matches(client_id,session_id,account_id,name,started,mode,
                        chests,destroyed,reopened,ammo,food,other,treasure_count,treasure_names,kinds,round_id,updated)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    ('pc1',f'session{i}','account1','=1+1' if i==0 else 'Player',1780000000+i,
                     'ZeroBuild',12,2,0,5,1,0,1,'["Shop Token"]','{}',None,1780000000))

    def test_history_keeps_all_rows_beyond_last_twenty(self):
        self.seed(65)
        result=json.loads(self.request('/api/matches?limit=30&offset=0'))
        self.assertEqual(result['total'],65)
        self.assertEqual(len(result['matches']),30)
        self.assertEqual(result['matches'][0]['session_id'],'session64')
        last=json.loads(self.request('/api/matches?limit=30&offset=60'))
        self.assertEqual(len(last['matches']),5)
        self.assertEqual(last['matches'][-1]['session_id'],'session0')
        self.assertEqual(len(server.get_state()['history']),20)
        self.assertEqual(sum(row['matches'] for row in server.get_state()['accounts']),65)
        with sqlite3.connect(server.DB_PATH) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM matches').fetchone()[0],65)

    def test_csv_includes_all_matches_and_is_not_spreadsheet_injection(self):
        self.seed(65)
        raw=self.request('/api/export/matches.csv')
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(rows),65)
        self.assertEqual(rows[0]['session_id'],'session0')
        self.assertEqual(rows[0]['name'], "'=1+1")

    def test_auth_required_for_archive_and_export(self):
        self.seed(1)
        for path in ['/api/matches','/api/export/matches.csv']:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.request(path,auth=False)
            self.assertEqual(ctx.exception.code,401)

    def test_reject_bad_pagination(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request('/api/matches?limit=-1')
        self.assertEqual(ctx.exception.code,400)

if __name__ == '__main__':
    unittest.main()
