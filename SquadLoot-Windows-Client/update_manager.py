"""Opt-in-on-install automatic client updates from the user's own SquadLoot server.

The server runs behind Cloudflare Access; every update endpoint requires the same
service and bearer credentials as the normal API. Updates are verified with
SHA-256 and strictly restricted to application files. No user settings are touched.

Trust model: the owner's Pi is the update publisher. A compromised Pi could
replace both the manifest and ZIP; SHA-256 protects against transfer corruption,
not against a malicious publisher. Keep Cloudflare Access and SSH secured.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from client_core import Api, APPDIR, CONFIG, read_json

APP_ROOT=Path(__file__).resolve().parent
VERSION_FILE=APP_ROOT/'VERSION'
PENDING_DIR=APPDIR/'updates'
PENDING_FILE=PENDING_DIR/'pending.json'
ARCHIVE_FILE=PENDING_DIR/'pending.zip'
UPDATE_MAX_BYTES=4*1024*1024
UPDATE_MAX_UNCOMPRESSED=8*1024*1024
ALLOWED_FILES=frozenset({
    'VERSION','app.py','bootstrap.py','client_core.py','update_manager.py',
    'replay_reader.py','vision.py','STARTEN.cmd','AUSWERTEN.cmd',
    'ORIGINALPROGRAMM.cmd','SETUP_VISION.cmd','vision-requirements.txt',
    'README-CLIENT.txt'
})
REQUIRED_FILES=frozenset({'VERSION','app.py','client_core.py','bootstrap.py','update_manager.py','replay_reader.py','STARTEN.cmd'})
VERSION_RE=re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')
SHA_RE=re.compile(r'^[a-f0-9]{64}$')


def parse_version(s):
    if not isinstance(s,str) or len(s)>25 or not VERSION_RE.fullmatch(s):
        raise ValueError('Ungueltige Versionsnummer')
    return tuple(int(x) for x in s.split('.'))


def current_version(root=APP_ROOT):
    try:return (root/'VERSION').read_text(encoding='ascii').strip()
    except OSError:return '1.0.0'


def validate_manifest(m):
    if not isinstance(m,dict):raise ValueError('Update-Manifest ist ungueltig')
    if m.get('available') is False or m.get('version') is None:
        return None
    version=m.get('version')
    parse_version(version)
    checksum=m.get('archive_sha256')
    size=m.get('archive_size')
    if not isinstance(checksum,str) or not SHA_RE.fullmatch(checksum):
        raise ValueError('Update-Checksum fehlt oder ist ungueltig')
    if type(size) is not int or not (100<=size<=UPDATE_MAX_BYTES):
        raise ValueError('Unplausible Update-Groesse')
    notes=m.get('notes','')
    if not isinstance(notes,str) or len(notes)>600:
        raise ValueError('Ungueltige Release-Notizen')
    return {'version':version,'archive_size':size,'archive_sha256':checksum,'notes':notes}


def inspect_archive(raw,version):
    if len(raw)>UPDATE_MAX_BYTES:
        raise ValueError('Update zu gross')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos=z.infolist()
            names=[i.filename for i in infos]
            if len(names)!=len(set(names)) or not REQUIRED_FILES.issubset(set(names)):
                raise ValueError('Update-Dateiliste unvollstaendig oder doppelt')
            if not names or not set(names).issubset(ALLOWED_FILES):
                raise ValueError('Update enthaelt nicht erlaubte Dateien')
            total=0
            for i in infos:
                # Flat allowlist also forbids traversal, absolute paths, and directories.
                if i.is_dir() or i.file_size>2*1024*1024:
                    raise ValueError('Update enthaelt grosse oder ungueltige Dateien')
                # ZipInfo external mode symlink flag.
                if (i.external_attr>>16) & 0o170000 == 0o120000:
                    raise ValueError('Symbolische Links sind nicht erlaubt')
                total+=i.file_size
            if total>UPDATE_MAX_UNCOMPRESSED:
                raise ValueError('Entpacktes Update ist zu gross')
            if z.testzip() is not None:
                raise ValueError('ZIP-Checksum ungueltig')
            package_version=z.read('VERSION').decode('ascii').strip()
            if package_version!=version:
                raise ValueError('Manifest und Paket enthalten unterschiedliche Versionen')
            return {name:z.read(name) for name in names}
    except (zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise ValueError('Ungueltiges ZIP-Update') from exc


def get_credentials(config):
    return Api(config['server_url'],config['token'],config.get('cf_access_client_id',''),config.get('cf_access_client_secret',''))


def check_and_stage(config=None,root=APP_ROOT):
    """Fetch manifest and download a newer release. Safe to run on a background thread."""
    config=config or read_json(CONFIG,{})
    if not config.get('server_url') or not config.get('token'):
        return None
    api=get_credentials(config)
    manifest=validate_manifest(api.call('/api/client-update/manifest',timeout=5))
    if not manifest or parse_version(manifest['version'])<=parse_version(current_version(root)):
        return None
    cached=read_json(PENDING_FILE,{})
    if (cached.get('archive_sha256')==manifest['archive_sha256'] and
        cached.get('version')==manifest['version'] and ARCHIVE_FILE.is_file()):
        raw=ARCHIVE_FILE.read_bytes()
        if len(raw)==manifest['archive_size'] and hashlib.sha256(raw).hexdigest()==manifest['archive_sha256']:
            inspect_archive(raw,manifest['version'])
            return manifest['version']
    raw=api.download_update(max_bytes=UPDATE_MAX_BYTES)
    if len(raw)!=manifest['archive_size'] or hashlib.sha256(raw).hexdigest()!=manifest['archive_sha256']:
        raise ValueError('Update-Integritaetspruefung fehlgeschlagen')
    inspect_archive(raw,manifest['version'])
    PENDING_DIR.mkdir(parents=True,exist_ok=True)
    temp=ARCHIVE_FILE.with_suffix('.part')
    temp.write_bytes(raw)
    os.replace(temp,ARCHIVE_FILE)
    save_pending(manifest)
    return manifest['version']


def save_pending(manifest):
    PENDING_DIR.mkdir(parents=True,exist_ok=True)
    temp=PENDING_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    os.replace(temp,PENDING_FILE)


def apply_pending(root=APP_ROOT):
    """Apply only while the GUI is not running. Rolls back all files on error."""
    pending=read_json(PENDING_FILE,{})
    manifest=validate_manifest(pending) if pending else None
    if not manifest:
        return None
    if parse_version(manifest['version'])<=parse_version(current_version(root)):
        clear_pending()
        return None
    raw=ARCHIVE_FILE.read_bytes()
    if len(raw)!=manifest['archive_size'] or hashlib.sha256(raw).hexdigest()!=manifest['archive_sha256']:
        raise ValueError('Vorbereitetes Update ist nicht mehr gueltig')
    entries=inspect_archive(raw,manifest['version'])
    if not root.is_dir():
        raise OSError('Installationsordner fehlt')
    # Stage everything before changing a single live file.
    with tempfile.TemporaryDirectory(prefix='.squad-update-',dir=root) as tmp:
        stage=Path(tmp)
        old=stage/'backup'
        old.mkdir()
        for name,content in entries.items():
            (stage/name).write_bytes(content)
        originals={}
        replaced=[]
        try:
            for name in sorted(entries,key=lambda n:n=='VERSION'):
                dest=root/name
                originals[name]=dest.is_file()
                if dest.is_file():shutil.copy2(dest,old/name)
                os.replace(stage/name,dest)
                replaced.append(name)
        except Exception:
            for name in reversed(replaced):
                dest=root/name
                if originals[name] and (old/name).is_file():
                    os.replace(old/name,dest)
                elif not originals[name] and dest.is_file():
                    dest.unlink()
            raise
    clear_pending()
    return manifest['version']


def clear_pending():
    for p in (PENDING_FILE,ARCHIVE_FILE):
        try:p.unlink(missing_ok=True)
        except OSError:pass


def startup_update():
    """Best-effort: if offline/403, run the installed client normally."""
    try:
        config=read_json(CONFIG,{})
        if not config.get('auto_update',True):
            return None
        if config.get('server_url') and config.get('token'):
            try:check_and_stage(config)
            except Exception as ex:log_error(ex)
        return apply_pending()
    except Exception as exc:
        log_error(exc)



def log_error(exc):
        try:
            APPDIR.mkdir(parents=True,exist_ok=True)
            with (APPDIR/'updater.log').open('a',encoding='utf-8') as log:
                from datetime import datetime
                log.write(f'{datetime.now().isoformat(timespec="seconds")} {type(exc).__name__}: {str(exc)[:200]}\n')
        except OSError:
            pass
        return None
