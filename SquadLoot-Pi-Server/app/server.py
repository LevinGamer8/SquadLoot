#!/usr/bin/env python3
"""SquadLoot private HTTP JSON server. Standard library only; run behind HTTPS proxy.

Clients send counts only, never replay bytes, screenshots, or game credentials.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOST = os.getenv('SQUAD_BIND', '127.0.0.1')
PORT = int(os.getenv('SQUAD_PORT', '8765'))
DB_PATH = Path(os.getenv('SQUAD_DB', './squadloot.sqlite3'))
TOKEN = os.getenv('SQUAD_TOKEN', '')
WEB_PATH = Path(__file__).parent / 'dashboard.html'
UPDATE_DIR = Path(os.getenv('SQUAD_UPDATES_DIR', '/updates'))
UPDATE_ZIP = UPDATE_DIR / 'client.zip'
UPDATE_MANIFEST = UPDATE_DIR / 'latest.json'
MAX_UPDATE_BYTES = 4 * 1024 * 1024
LOCK = threading.RLock()
MAX_BODY = 64 * 1024
TIMEOUT_LIVE = 150
ROUND_JOIN_WINDOW = 75


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=20000')
        db.execute('PRAGMA journal_mode=WAL')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_database():
    with LOCK, database() as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created REAL NOT NULL,
            label TEXT NOT NULL DEFAULT ''
          );
          CREATE TABLE IF NOT EXISTS participants (
            client_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            last_round INTEGER,
            local_replay TEXT,
            last_seen REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS live (
            round_id INTEGER NOT NULL,
            client_id TEXT NOT NULL,
            name TEXT NOT NULL,
            manual INTEGER NOT NULL DEFAULT 0,
            vision INTEGER NOT NULL DEFAULT 0,
            ammo INTEGER NOT NULL DEFAULT 0,
            food INTEGER NOT NULL DEFAULT 0,
            destroyed INTEGER NOT NULL DEFAULT 0,
            last_seen REAL NOT NULL,
            PRIMARY KEY(round_id, client_id)
          );
          CREATE TABLE IF NOT EXISTS matches (
            client_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            name TEXT NOT NULL,
            started REAL NOT NULL,
            mode TEXT NOT NULL,
            chests INTEGER NOT NULL,
            destroyed INTEGER NOT NULL,
            reopened INTEGER NOT NULL,
            ammo INTEGER NOT NULL,
            food INTEGER NOT NULL,
            other INTEGER NOT NULL,
            treasure_count INTEGER NOT NULL,
            treasure_names TEXT NOT NULL,
            kinds TEXT NOT NULL,
            round_id INTEGER,
            updated REAL NOT NULL,
            PRIMARY KEY(client_id, session_id)
          );
          CREATE INDEX IF NOT EXISTS match_time ON matches(started DESC);
        ''')


def limited_text(value, n=100, default=''):
    if not isinstance(value, str):
        return default
    # No control characters or newlines in names, token identifiers.
    return re.sub(r'[\x00-\x1f\x7f]', ' ', value).strip()[:n] or default


def integer(value, max_value=100000):
    if isinstance(value, bool):
        return 0
    try:
        return max(0, min(max_value, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


def timestamp(value):
    try:
        if isinstance(value, (int, float)):
            n = float(value)
        elif isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            n = dt.timestamp()
        else:
            n = time.time()
        if 1577836800 <= n <= time.time() + 60 * 60 * 24 * 2:
            return n
    except (ValueError, OverflowError, OSError, TypeError):
        pass
    return time.time()


def upsert_participant(db, client_id, name, now):
    db.execute('''INSERT INTO participants (client_id,name,last_seen)
      VALUES (?,?,?) ON CONFLICT(client_id) DO UPDATE SET name=excluded.name,last_seen=excluded.last_seen''', (client_id,name,now))


def latest_round(db):
    return db.execute('SELECT id, created FROM rounds ORDER BY id DESC LIMIT 1').fetchone()


def create_round(db, now):
    cur = db.execute('INSERT INTO rounds (created) VALUES (?)', (now,))
    return cur.lastrowid


def join_round(data):
    client = limited_text(data.get('client_id'), 80)
    name = limited_text(data.get('name'), 60)
    replay = limited_text(data.get('local_replay'), 130)
    if not client or not name or not replay:
        raise ValueError('client_id, name und local_replay sind erforderlich')
    now = time.time()
    with LOCK, database() as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT last_round,local_replay FROM participants WHERE client_id=?', (client,)).fetchone()
        upsert_participant(db,client,name,now)
        if prior and prior['local_replay'] == replay and prior['last_round']:
            rid = prior['last_round']
        else:
            latest = latest_round(db)
            # Do not re-join this client's previous round if a second match began quickly.
            can_join = (latest and now - latest['created'] <= ROUND_JOIN_WINDOW
                        and not (prior and latest['id'] == prior['last_round']))
            rid = latest['id'] if can_join else create_round(db,now)
        db.execute('UPDATE participants SET last_round=?,local_replay=? WHERE client_id=?',(rid,replay,client))
        db.execute('''INSERT INTO live (round_id,client_id,name,last_seen)
             VALUES (?,?,?,?) ON CONFLICT(round_id,client_id) DO UPDATE SET name=excluded.name,last_seen=excluded.last_seen''',(rid,client,name,now))
    return {'round_id':rid}


def new_round():
    with LOCK, database() as db:
        db.execute('BEGIN IMMEDIATE')
        rid=create_round(db,time.time())
    return {'round_id':rid}


def submit_live(data):
    client=limited_text(data.get('client_id'),80)
    name=limited_text(data.get('name'),60)
    rid=integer(data.get('round_id'),100000000)
    if not client or not name or not rid:
        raise ValueError('client_id, name und round_id sind erforderlich')
    now=time.time()
    with LOCK, database() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM rounds WHERE id=?', (rid,)).fetchone():
            raise ValueError('Runde nicht gefunden')
        upsert_participant(db,client,name,now)
        db.execute('''INSERT INTO live (round_id,client_id,name,manual,vision,ammo,food,destroyed,last_seen)
          VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(round_id,client_id) DO UPDATE SET
          name=excluded.name,manual=excluded.manual,vision=excluded.vision,ammo=excluded.ammo,
          food=excluded.food,destroyed=excluded.destroyed,last_seen=excluded.last_seen''',
          (rid,client,name,integer(data.get('manual')),integer(data.get('vision')),
           integer(data.get('ammo')),integer(data.get('food')),integer(data.get('destroyed')),now))
    return {'ok':True,'round_id':rid}


def submit_match(data):
    client=limited_text(data.get('client_id'),80)
    sid=limited_text(data.get('session_id'),180)
    name=limited_text(data.get('name'),60)
    if not client or not sid or not name:
        raise ValueError('client_id, session_id und name sind erforderlich')
    raw_names=data.get('treasure_names')
    names=[limited_text(n,110) for n in raw_names[:20]] if isinstance(raw_names,list) else []
    kinds=data.get('kinds',{})
    if not isinstance(kinds,dict):
        kinds={}
    kinds={limited_text(k,80):integer(v) for k,v in list(kinds.items())[:30]}
    now=time.time()
    rid=integer(data.get('round_id'),100000000) or None
    with LOCK, database() as db:
        db.execute('BEGIN IMMEDIATE')
        if rid and not db.execute('SELECT 1 FROM rounds WHERE id=?',(rid,)).fetchone():
            rid=None
        upsert_participant(db,client,name,now)
        db.execute('''INSERT INTO matches(client_id,session_id,account_id,name,started,mode,chests,destroyed,reopened,
          ammo,food,other,treasure_count,treasure_names,kinds,round_id,updated)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(client_id,session_id) DO UPDATE SET
          account_id=excluded.account_id,name=excluded.name,started=excluded.started,mode=excluded.mode,
          chests=excluded.chests,destroyed=excluded.destroyed,reopened=excluded.reopened,ammo=excluded.ammo,
          food=excluded.food,other=excluded.other,treasure_count=excluded.treasure_count,
          treasure_names=excluded.treasure_names,kinds=excluded.kinds,
          round_id=COALESCE(excluded.round_id,matches.round_id),updated=excluded.updated''',
           (client,sid,limited_text(data.get('account_id'),95),name,timestamp(data.get('started')),
            limited_text(data.get('mode'),115),integer(data.get('chests')),integer(data.get('destroyed')),
            integer(data.get('reopened')),integer(data.get('ammo')),integer(data.get('food')),
            integer(data.get('other')),integer(data.get('treasure_count')),
            json.dumps(names,ensure_ascii=False),json.dumps(kinds,ensure_ascii=False),rid,now))
    return {'ok':True,'session_id':sid}


def get_state():
    now=time.time()
    with LOCK, database() as db:
        active=latest_round(db)
        current=None
        if active:
            rid=active['id']
            live=db.execute('SELECT * FROM live WHERE round_id=? ORDER BY name COLLATE NOCASE',(rid,)).fetchall()
            actual=db.execute('SELECT * FROM matches WHERE round_id=?',(rid,)).fetchall()
            verified_by_client={a['client_id']:dict(a) for a in actual}
            members=[]
            for l in live:
                a=verified_by_client.pop(l['client_id'],None)
                provisional=max(l['manual'],l['vision'])
                # verified_* fields are additive: older clients simply ignore them,
                # newer UIs use them to separate confirmed from estimated values.
                member={'name':l['name'],'live_chests':provisional,'manual':l['manual'],'vision':l['vision'],
                        'ammo':l['ammo'],'food':l['food'],'destroyed':l['destroyed'],
                        'verified_chests':a['chests'] if a else None,'verified_treasures':a['treasure_count'] if a else None,
                        'verified_ammo':a['ammo'] if a else None,'verified_food':a['food'] if a else None,
                        'verified_destroyed':a['destroyed'] if a else None,
                        'verified_reopened':a['reopened'] if a else None,
                        'online':now-l['last_seen']<=TIMEOUT_LIVE}
                members.append(member)
            for a in verified_by_client.values():
                members.append({'name':a['name'],'live_chests':0,'manual':0,'vision':0,'ammo':0,'food':0,'destroyed':0,
                                'verified_chests':a['chests'],'verified_treasures':a['treasure_count'],
                                'verified_ammo':a['ammo'],'verified_food':a['food'],
                                'verified_destroyed':a['destroyed'],'verified_reopened':a['reopened'],
                                'online':False})
            total=sum((m['verified_chests'] if m['verified_chests'] is not None else m['live_chests']) for m in members)
            current={'id':rid,'created':active['created'],'members':members,'chests_total':total,
                     'confirmed_members':sum(m['verified_chests'] is not None for m in members),
                     'provisional':any(m['verified_chests'] is None for m in members)}
        lastrows=db.execute('''SELECT session_id, MAX(started) AS started, COUNT(*) AS players,
            SUM(chests) AS chests,SUM(destroyed) AS destroyed,SUM(reopened) AS reopened,
            SUM(ammo) AS ammo,SUM(food) AS food,SUM(treasure_count) AS treasures,
            GROUP_CONCAT(name || ': ' || chests, ' / ') AS breakdown
            FROM matches GROUP BY session_id ORDER BY started DESC LIMIT 20''').fetchall()
        # Individual histories (and multiple accounts) are kept distinct on disk.
        individual=db.execute('''SELECT name,account_id,COUNT(*) AS matches,SUM(chests) AS chests,
           SUM(ammo) AS ammo,SUM(food) AS food,SUM(treasure_count) AS treasures
           FROM matches GROUP BY client_id,account_id,name ORDER BY chests DESC''').fetchall()
        recent=db.execute('''SELECT session_id,name,started,treasure_names FROM matches
            WHERE treasure_count>0 ORDER BY started DESC LIMIT 15''').fetchall()
        total_matches=db.execute('SELECT COUNT(DISTINCT session_id) FROM matches').fetchone()[0]
        history=[dict(r) for r in lastrows]
        accounts=[dict(r) for r in individual]
        treasures=[{'name':r['name'],'started':r['started'],'items':json.loads(r['treasure_names'])}
                   for r in recent]
        return {'time':now,'round':current,'history':history,'accounts':accounts,'treasures':treasures,'total_matches':total_matches}


class Handler(BaseHTTPRequestHandler):
    server_version='SquadLoot/1.0'
    def log_message(self, fmt, *args):
        # Do not log bearer tokens or body payloads.
        print('[http]', self.address_string(), fmt % args, flush=True)

    def answer(self, status, obj):
        data=json.dumps(obj,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        token=self.headers.get('Authorization','')
        expected='Bearer '+TOKEN
        if not token or not hmac.compare_digest(token,expected):
            self.answer(401,{'error':'Ungültiger Squad-Token'})
            return False
        return True

    def send_update_file(self):
        if not self.authorized():
            return
        try:
            raw = UPDATE_ZIP.read_bytes()
            meta = json.loads(UPDATE_MANIFEST.read_text(encoding='utf-8'))
            if not (0 < len(raw) <= MAX_UPDATE_BYTES):
                raise ValueError('invalid update package size')
            if len(raw) != meta.get('archive_size') or hashlib.sha256(raw).hexdigest() != meta.get('archive_sha256'):
                raise ValueError('update package integrity failure')
        except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError):
            self.answer(503, {'error':'Updatepaket nicht verfuegbar'})
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Disposition', 'attachment; filename="SquadLoot-Windows-Client.zip"')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def update_manifest(self):
        if not self.authorized():
            return
        try:
            raw = UPDATE_MANIFEST.read_text(encoding='utf-8')
            meta = json.loads(raw)
            if not (isinstance(meta, dict) and meta.get('version') and meta.get('archive_sha256')):
                raise ValueError('bad manifest')
            self.answer(200, meta)
        except (OSError, ValueError, TypeError):
            self.answer(200, {'version': None, 'available': False})

    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/health':
            self.answer(200,{'status':'ok'})
        elif path=='/':
            page=WEB_PATH.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'")
            self.send_header('Content-Length',str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        elif path=='/api/client-update/manifest':
            self.update_manifest()
        elif path=='/api/client-update/package':
            self.send_update_file()
        elif path=='/api/state':
            if self.authorized():
                self.answer(200,get_state())
        else:
            self.answer(404,{'error':'Unbekannter Pfad'})

    def do_POST(self):
        path=urlsplit(self.path).path
        if path not in ('/api/round/join','/api/round/next','/api/live','/api/match'):
            self.answer(404,{'error':'Unbekannter Pfad'});return
        if not self.authorized():
            return
        length=self.headers.get('Content-Length','')
        try:
            size=int(length)
        except ValueError:
            size=-1
        if not (0<=size<=MAX_BODY):
            self.answer(413,{'error':'Payload zu groß'});return
        try:
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):
                raise ValueError('JSON-Objekt erwartet')
            if path=='/api/round/join':result=join_round(data)
            elif path=='/api/round/next':result=new_round()
            elif path=='/api/live':result=submit_live(data)
            else:result=submit_match(data)
            self.answer(200,result)
        except (ValueError,TypeError) as exc:
            self.answer(400,{'error':str(exc)[:250]})
        except sqlite3.Error:
            self.answer(500,{'error':'Datenbankfehler'})


def main():
    if len(TOKEN)<24 or TOKEN.startswith(('HIER_', 'CHANGE_', 'Bitte_')):
        raise SystemExit('SQUAD_TOKEN fehlt oder ist zu kurz (mind. 24 Zeichen).')
    init_database()
    with ThreadingHTTPServer((HOST,PORT),Handler) as server:
        server.daemon_threads=True
        print(f'SquadLoot server listening on {HOST}:{PORT}; DB={DB_PATH}; local dashboard http://127.0.0.1:{PORT}',flush=True)
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass


if __name__=='__main__':
    main()
