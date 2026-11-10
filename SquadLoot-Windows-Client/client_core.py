"""UI-independent client logic: configuration, authenticated sync, match matching."""
from __future__ import annotations
import json
import ipaddress
import os
import sys
import time
import uuid
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from replay_reader import load_matches, fingerprint

APPDIR=Path(os.getenv('APPDATA') or str(Path.home()))/'SquadLootClient'
CONFIG=APPDIR/'config.json'
STATE=APPDIR/'state.json'
CHESTCOUNTER=Path(os.getenv('APPDATA') or str(Path.home()))/'ChestCounter'/'data.json'
REPLAYDIR=Path(os.getenv('LOCALAPPDATA') or str(Path.home()))/'FortniteGame'/'Saved'/'Demos'


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):
        return {} if default is None else default


def save_json(path, obj):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
    temp.replace(path)


def default_config():
    return {'client_id':str(uuid.uuid4()),'server_url':'','token':'','name':'',
            'data_json':str(CHESTCOUNTER),'replay_dir':str(REPLAYDIR),
            'chestcounter_exe':'','vision_template':'','vision_enabled':False,'interact_key':'E',
            'cf_access_client_id':'','cf_access_client_secret':'','auto_update':True,
            # In-game HUD. Older config.json files simply lack these keys; the UI
            # falls back to the same defaults, so nothing has to be migrated.
            'hud_enabled':False,'hud_mode':'compact','hud_opacity':0.92,'hud_scale':1.0,
            'hud_locked':True,'hud_x':None,'hud_y':None,
            'hud_hotkey_toggle':'Ctrl+Alt+H','hud_hotkey_lock':'Ctrl+Alt+L',
            'hud_hotkey_mode':'Ctrl+Alt+E'}


def validate_url(url):
    u=urlsplit(url.strip())
    if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('Server-URL muss z.B. https://loot.example.net oder http://127.0.0.1:8765 sein.')
    if u.scheme=='http':
        hostname=u.hostname.lower()
        private=hostname=='localhost'
        try:
            private=private or ipaddress.ip_address(hostname).is_private or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            pass
        if not private:
            raise ValueError('Für das Internet HTTPS verwenden. HTTP ist nur für private IPs/localhost erlaubt.')
    return url.strip().rstrip('/')


class Api:
    def __init__(self, url, token, cf_access_client_id='', cf_access_client_secret=''):
        self.url=validate_url(url)
        self.token=token.strip()
        self.cf_access_client_id=(cf_access_client_id or '').strip()
        self.cf_access_client_secret=(cf_access_client_secret or '').strip()
        if len(self.token)<24:
            raise ValueError('Squad-Token fehlt oder ist zu kurz.')
        if bool(self.cf_access_client_id) != bool(self.cf_access_client_secret):
            raise ValueError('Cloudflare Access: Client-ID und Client-Secret muessen beide ausgefuellt oder beide leer sein.')

    def download_update(self, max_bytes=4*1024*1024):
        # Fixed endpoint; no server-controlled redirect URL. Use the same auth as the API.
        request=urllib.request.Request(self.url+'/api/client-update/package',method='GET')
        request.add_header('Authorization','Bearer '+self.token)
        request.add_header('User-Agent','SquadLootClient/1.1')
        request.add_header('Accept','application/zip')
        if self.cf_access_client_id:
            request.add_header('CF-Access-Client-Id',self.cf_access_client_id)
            request.add_header('CF-Access-Client-Secret',self.cf_access_client_secret)
        # Prevent redirection to a different host which could receive credentials.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise RuntimeError('Update-Download verweigert: unerwartete Weiterleitung')
        try:
            opener=urllib.request.build_opener(NoRedirect)
            with opener.open(request,timeout=15) as res:
                if res.status!=200 or 'zip' not in res.headers.get('Content-Type',''):
                    raise RuntimeError('Update-Download: unerwartete Antwort')
                content=res.read(max_bytes+1)
                if len(content)>max_bytes:
                    raise RuntimeError('Updatepaket ist zu gross')
                return content
        except urllib.error.HTTPError as err:
            raise RuntimeError(f'Update-Download: HTTP {err.code}') from err

    def call(self, path, body=None, timeout=9):
        request=urllib.request.Request(self.url+path,method='POST' if body is not None else 'GET')
        request.add_header('Authorization','Bearer '+self.token)
        # Identify this first-party client instead of the default Python-urllib user agent.
        # Some Cloudflare WAF/Bot rules discriminate based on the default Python UA.
        request.add_header('User-Agent','SquadLootClient/1.0')
        request.add_header('Accept','application/json')
        if self.cf_access_client_id:
            request.add_header('CF-Access-Client-Id', self.cf_access_client_id)
            request.add_header('CF-Access-Client-Secret', self.cf_access_client_secret)
        if body is not None:
            request.add_header('Content-Type','application/json')
            payload=json.dumps(body,ensure_ascii=False).encode('utf-8')
        else:
            payload=None
        try:
            with urllib.request.urlopen(request,data=payload,timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as err:
            # Report the path and response format: for example /api/match may be
            # blocked by a WAF even when /api/state works. Never print credentials.
            ctype=err.headers.get('Content-Type','') if err.headers else ''
            ray=err.headers.get('CF-Ray','') if err.headers else ''
            try:
                payload_error=json.loads(err.read().decode('utf-8','replace'))
                desc=payload_error.get('error','') if isinstance(payload_error,dict) else ''
            except (ValueError,UnicodeError):
                desc=''
            kind='HTML statt JSON (Access/WAF pruefen)' if 'html' in ctype.lower() else (ctype or 'unbekannter Antworttyp')
            location=f' - CF-Ray {ray[:80]}' if ray else ''
            message=f'{path}: HTTP {err.code} [{kind}]{location}'
            if desc: message+=f': {str(desc)[:250]}'
            raise RuntimeError(message) from err
        except urllib.error.URLError as err:
            raise RuntimeError(f'Verbindung fehlgeschlagen: {err.reason}') from err


def chestcounter_exe(config):
    candidates=[config.get('chestcounter_exe',''),
                str(Path.home()/'Documents'/'Fortnite-Loot-Tracker'/'dist'/'ChestCounter.exe'),
                str(Path(__file__).parent/'tools'/'ChestCounter.exe')]
    return next((Path(x) for x in candidates if x and Path(x).is_file()),None)


def newest_recent_replay(path):
    root=Path(path)
    if not root.is_dir():
        return None
    try:
        newest=max(root.glob('*.replay'),key=lambda f:f.stat().st_mtime,default=None)
        if newest is not None and time.time()-newest.stat().st_mtime<150:
            return newest.name
    except OSError:
        pass
    return None


class Core:
    """Thread-safe data model for a Tk UI or CLI. All network actions run outside Tk thread."""
    def __init__(self,config=None,state=None):
        self.config=config or read_json(CONFIG,default_config())
        self.state=state or read_json(STATE,{'sent':{},'replay_rounds':{}})
        self.config.setdefault('client_id',str(uuid.uuid4()))
        self.state.setdefault('sent',{})
        self.state.setdefault('replay_rounds',{})
        self.lock=threading.RLock()
        self.round_id=None
        self.local_replay=None
        self.manual=0;self.vision=0;self.ammo=0;self.food=0;self.destroyed=0
        self.current_state={}
        self.status='Nicht verbunden'
        self.last_push=0.0
        self.last_full_read=0.0
        self.last_state=0.0
        self.last_live=0.0
        self.last_replay_scan=0.0
        self.connected=False
        self.stop=threading.Event()
        self.vision_worker=None

    def credentials(self):
        return Api(self.config['server_url'],self.config['token'],
                   self.config.get('cf_access_client_id',''),self.config.get('cf_access_client_secret',''))

    def set_status(self,message):
        with self.lock: self.status=str(message)

    def set_config(self,updates):
        with self.lock:
            self.config.update(updates)
            save_json(CONFIG,self.config)

    def current_name(self):
        # Replay JSON is preferable for historical records; live names are user-editable.
        return self.config.get('name','') or 'Fortnite-Spieler'

    def adjust(self,kind,delta):
        with self.lock:
            old=getattr(self,kind)
            setattr(self,kind,max(0,min(100000,old+delta)))
            self.last_live=0.0

    def reset_local_counters(self):
        with self.lock:
            self.manual=0;self.vision=0;self.ammo=0;self.food=0;self.destroyed=0
            self.last_live=0.0

    def new_round(self):
        api=self.credentials()
        res=api.call('/api/round/next',{})
        with self.lock:
            self.round_id=res['round_id']
            self.reset_local_counters()
            self.set_status('Neue Runde gestartet (#'+str(self.round_id)+')')
        return self.round_id

    def watch_new_replay(self, api):
        name=newest_recent_replay(self.config.get('replay_dir',''))
        if name is None or name==self.local_replay:
            return
        res=api.call('/api/round/join',{'client_id':self.config['client_id'],'name':self.current_name(),'local_replay':name})
        with self.lock:
            self.local_replay=name
            self.round_id=res['round_id']
            self.state['replay_rounds'][name]=self.round_id
            # Keep only 200 historical names to avoid infinitely growing state.
            if len(self.state['replay_rounds'])>200:
                self.state['replay_rounds']=dict(list(self.state['replay_rounds'].items())[-200:])
            self.reset_local_counters()
            save_json(STATE,self.state)
            self.set_status('Replay erkannt – Squad-Runde #'+str(self.round_id))

    def sync_matches(self,api,max_items=1000):
        rows=load_matches(self.config.get('data_json',str(CHESTCOUNTER)),self.config['client_id'])
        count=0
        for item in sorted(rows,key=lambda m:m.get('started','')):
            key=item['session_id']
            rid=self.state['replay_rounds'].get(item['replay_file'])
            # A round_id is local context, not part of the durable match fingerprint.
            h=fingerprint(item)
            if self.state['sent'].get(key)==h:
                continue
            if rid:
                item['round_id']=rid
            api.call('/api/match',item)
            self.state['sent'][key]=h
            save_json(STATE,self.state)
            count+=1
            if count>=max_items:
                break
        return count

    def send_live(self,api):
        with self.lock:
            if not self.round_id: return
            data={'client_id':self.config['client_id'],'name':self.current_name(),'round_id':self.round_id,
                  'manual':self.manual,'vision':self.vision,'ammo':self.ammo,'food':self.food,'destroyed':self.destroyed}
        api.call('/api/live',data)

    def poll_once(self):
        """Background tick. Can be called repeatedly; 2-10s based on task."""
        api=self.credentials()
        now=time.monotonic()
        if now-self.last_replay_scan>=2:
            self.watch_new_replay(api)
            self.last_replay_scan=now
        if now-self.last_full_read>=8:
            n=self.sync_matches(api,max_items=30)
            self.last_full_read=now
            if n:self.set_status(f'{n} neue/aktualisierte Replays übertragen')
        if self.round_id and (now-self.last_live>=1.5 or now-self.last_push>=15):
            self.send_live(api)
            self.last_live=now
        if now-self.last_state>=2:
            state=api.call('/api/state')
            with self.lock:
                self.current_state=state
                rid=(state.get('round') or {}).get('id')
                # Someone on the squad pressed New Round: all clients join and reset.
                if rid and self.round_id and rid>self.round_id:
                    self.round_id=rid
                    self.reset_local_counters()
                if rid and not self.round_id:
                    self.round_id=rid
                self.last_state=now
                self.connected=True
                if self.status.startswith(('Fehler','Verbindung','Nicht verbunden')):
                    self.status='Verbunden'
        self.last_push=now

    def worker_loop(self):
        while not self.stop.is_set():
            try:
                self.poll_once()
                if self.status.startswith(('Fehler','Verbindung fehl')):
                    self.set_status('Verbunden')
            except Exception as ex:
                self.connected=False
                self.set_status('Fehler: '+str(ex)[:170])
            self.stop.wait(1.2)

    def start(self):
        if not self.config.get('server_url') or not self.config.get('token'):
            raise ValueError('Zuerst die Server-URL und den Token eintragen.')
        if self.stop.is_set():self.stop.clear()
        if not getattr(self,'worker',None) or not self.worker.is_alive():
            self.worker=threading.Thread(target=self.worker_loop,daemon=True)
            self.worker.start()

    def shutdown(self):
        self.stop.set()


def sync_once(config):
    core=Core(config=config)
    api=core.credentials()
    count=core.sync_matches(api,max_items=100000)
    state=api.call('/api/state')
    return count,state
