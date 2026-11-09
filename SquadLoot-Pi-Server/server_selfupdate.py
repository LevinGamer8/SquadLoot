#!/usr/bin/env python3
"""SquadLoot Raspberry Pi update client.

Only trusted GitHub Releases should be configured as the manifest source.
A release is downloaded and hash-checked before a staged update with backups.
The Pi retains .env, Docker data, and Cloudflare settings; it can publish clients from the same release.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
VERSION_FILE = BASE / 'VERSION'
CONF = BASE / 'server-update.conf'
STATE = BASE / '.server_update_state.json'
LOCK_FILE = BASE / '.selfupdate.lock'
BACKUPS = BASE / '.server_backups'
MAX_ZIP_BYTES = 12 * 1024 * 1024
MAX_CLIENT_ZIP_BYTES = 4 * 1024 * 1024
MAX_UNPACKED_BYTES = 24 * 1024 * 1024

# Strict allowlist: never replace .env, locally configured endpoint, or client update payloads.
RELEASE_FILES = frozenset({
    'VERSION', 'README-PI.md', '.env.example',
    'app/Dockerfile', 'app/dashboard.html', 'app/server.py',
    'nginx/squadloot.conf',
    'compose.yaml', 'compose.tunnel.yaml',
    'PI_INSTALLIEREN.sh', 'PI_UPDATE_AKTIVIEREN.sh',
    'PI_TUNNEL_STARTEN.sh', 'PI_STATUS.sh', 'PI_STOPPEN.sh',
    'PI_CLIENT_RELEASE.sh', 'update_publish.py',
    'server_selfupdate.py', 'server-update.conf.example',
    'PI_SELFUPDATE_CHECK.sh', 'PI_SELFUPDATE_INSTALL.sh',
    'PI_BACKUP.sh', 'PI_BACKUP_AUTOMATISCH.sh',
})
REQUIRED = frozenset({
    'VERSION', 'compose.yaml', 'compose.tunnel.yaml', 'app/Dockerfile',
    'app/dashboard.html', 'app/server.py', 'nginx/squadloot.conf',
    'server_selfupdate.py', 'PI_SELFUPDATE_INSTALL.sh',
})
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')


def parse_version(v: str) -> tuple[int, int, int]:
    if not VERSION_RE.fullmatch(v):
        raise ValueError('Version muss dem Format 1.2.3 entsprechen')
    return tuple(map(int, v.split('.')))  # type: ignore[return-value]


def read_config() -> dict[str, str]:
    config: dict[str, str] = {}
    if CONF.exists():
        for line in CONF.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                config[k.strip()] = v.strip()
    return config


def download(url: str, max_bytes: int) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise ValueError('Nur HTTPS-Update-URLs sind erlaubt')
    req = urllib.request.Request(url, headers={'User-Agent': 'SquadLootPiUpdater/1.2'})
    with urllib.request.urlopen(req, timeout=35) as response:
        final_url = urllib.parse.urlparse(response.geturl())
        if final_url.scheme != 'https':
            raise ValueError('Update umgeleitet auf ungesicherten Kanal')
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError('Download überschreitet maximale Größe')
    return data


def parse_manifest(raw: bytes) -> dict:
    manifest = json.loads(raw.decode('utf-8'))
    if not isinstance(manifest, dict) or not {'version', 'package_url', 'package_sha256', 'package_size'} <= manifest.keys():
        raise ValueError('Update-Manifest unvollständig')
    parse_version(manifest['version'])
    if (not isinstance(manifest['package_url'], str) or
            not re.fullmatch(r'[0-9a-f]{64}', str(manifest['package_sha256']))):
        raise ValueError('Ungültiges Update-Manifest')
    size = manifest['package_size']
    if type(size) is not int or not 100 <= size <= MAX_ZIP_BYTES:
        raise ValueError('Ungültige Update-Paketgröße')
    return manifest


def get_client_package(manifest: dict) -> bytes | None:
    """Fetch the optional Windows client from the SAME trusted GitHub release."""
    required={'client_version','client_package_url','client_package_sha256','client_package_size'}
    if not required.issubset(manifest):
        return None
    version=manifest['client_version']
    parse_version(version)
    if version != manifest['version']:
        raise ValueError('Server- und Client-Release-Version unterschiedlich')
    sha=manifest['client_package_sha256']
    size=manifest['client_package_size']
    if not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{64}',sha):
        raise ValueError('Client-Release SHA ungueltig')
    if type(size) is not int or not 100 <= size <= MAX_CLIENT_ZIP_BYTES:
        raise ValueError('Client-Release Groesse ungueltig')
    # If already on the Pi, skip the client download.
    local=BASE/'updates'/'latest.json'
    if local.is_file():
        try:
            old=json.loads(local.read_text(encoding='utf-8')).get('version','0.0.0')
            if parse_version(old)>=parse_version(version):
                return None
        except (ValueError,KeyError,TypeError):
            pass
    url=manifest['client_package_url']
    raw=download(url,MAX_CLIENT_ZIP_BYTES)
    if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=sha:
        raise ValueError('Client-Release Integritaetspruefung fehlgeschlagen')
    return raw


def publish_client_package(raw: bytes, notes: str):
    import update_publish
    with tempfile.TemporaryDirectory(prefix='squadloot-client-',dir=str(BASE)) as d:
        source=Path(d)/'client.zip'
        source.write_bytes(raw)
        update_publish.publish(source,notes)


def extract_release(package: bytes, destination: Path, wanted_version: str) -> list[Path]:
    extracted: list[Path] = []
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        infos = archive.infolist()
        if len(infos) > len(RELEASE_FILES) + 2:
            raise ValueError('Zu viele Dateien im Update-Paket')
        if sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES:
            raise ValueError('Paket zu groß nach dem Entpacken')
        seen: set[str] = set()
        for info in infos:
            if info.is_dir():
                continue
            name = info.filename.replace('\\', '/')
            prefix = 'SquadLoot-Pi-Server/'
            if name.startswith(prefix):
                name = name[len(prefix):]
            # Absolute paths, duplicate entries, symlinks and arbitrary files are rejected.
            if name not in RELEASE_FILES or name in seen:
                raise ValueError(f'Nicht erlaubte oder doppelte Datei im Update: {name}')
            mode = (info.external_attr >> 16)
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                raise ValueError('Symbolische Links sind nicht erlaubt')
            seen.add(name)
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            if mode & 0o111:
                target.chmod(0o755)
            else:
                target.chmod(0o644)
            extracted.append(Path(name))
        if not REQUIRED.issubset(seen):
            raise ValueError('Erforderliche Dateien fehlen im Update')
        actual_version = (destination / 'VERSION').read_text(encoding='utf-8').strip()
        if actual_version != wanted_version:
            raise ValueError('Paketversion stimmt nicht mit Manifest überein')
    return extracted


def compose_up() -> None:
    cmd = ['docker', 'compose', '-f', 'compose.yaml']
    if (BASE / 'compose.tunnel.yaml').exists():
        cmd.extend(['-f', 'compose.tunnel.yaml'])
    cmd.extend(['up', '-d', '--build', 'squadloot', 'squadloot-nginx'])
    # cloudflared need not be restarted: same network, same token, same tunnel.
    subprocess.run(cmd, cwd=BASE, check=True, timeout=360)


def apply_release(package: bytes, manifest: dict) -> None:
    BACKUPS.mkdir(exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='squadloot-stage-', dir=str(BACKUPS)) as td:
        staged = Path(td) / 'new'
        staged.mkdir()
        files = extract_release(package, staged, manifest['version'])
        # Preserve the previous files for rollback and retain a compact backup folder.
        version_before = VERSION_FILE.read_text(encoding='utf-8').strip()
        backup = BACKUPS / f'{version_before}-{int(time.time())}'
        backup.mkdir(mode=0o700)
        existing: list[Path] = []
        created: list[Path] = []
        for relative in files:
            current = BASE / relative
            if current.exists():
                destination = backup / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current, destination)
                existing.append(relative)
            else:
                created.append(relative)
        changed: list[Path] = []
        try:
            for relative in files:
                target = BASE / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(target.name + '.squadloot-new')
                shutil.copy2(staged / relative, temp)
                os.replace(temp, target)
                changed.append(relative)
            compose_up()
        except Exception:
            for relative in reversed(changed):
                target = BASE / relative
                previous = backup / relative
                if previous.exists():
                    shutil.copy2(previous, target)
                elif relative in created:
                    target.unlink(missing_ok=True)
            # Bring the previously working stack back, if Docker itself works.
            try:
                compose_up()
            except Exception as recovery_error:
                print(f'WARNUNG: Rollback-Docker-Neustart fehlgeschlagen: {recovery_error}', file=sys.stderr)
            raise
        state = {
            'version': manifest['version'],
            'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'backup': str(backup),
            'notes': str(manifest.get('notes', ''))[:400],
        }
        tmp_state = STATE.with_suffix('.tmp')
        tmp_state.write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        os.replace(tmp_state, STATE)


def run(check_only: bool = False, quiet: bool = False) -> bool:
    cfg = read_config()
    manifest_url = cfg.get('MANIFEST_URL', '')
    if not manifest_url or 'example.com' in manifest_url:
        raise ValueError('Bitte MANIFEST_URL in server-update.conf auf dein GitHub Release setzen')
    manifest = parse_manifest(download(manifest_url, 1024 * 64))
    current = VERSION_FILE.read_text(encoding='utf-8').strip()
    server_new = parse_version(manifest['version']) > parse_version(current)
    package = None
    if server_new:
        package_url = urllib.parse.urljoin(manifest_url, manifest['package_url'])
        package = download(package_url, MAX_ZIP_BYTES)
        if len(package) != manifest['package_size'] or hashlib.sha256(package).hexdigest() != manifest['package_sha256']:
            raise ValueError('Server-Update-Checksum oder Paketgröße stimmt nicht')
    # Fetch/verify both packages before we change installed files.
    client_data = get_client_package(manifest)
    if check_only:
        if server_new:
            with tempfile.TemporaryDirectory(prefix='squadloot-check-') as td:
                extract_release(package, Path(td), manifest['version'])
        if not quiet:
            print('Verfuegbar: Serverupdate' if server_new else 'Server aktuell',
                  '+ Clientupdate' if client_data else '')
        return server_new or client_data is not None
    if server_new:
        apply_release(package, manifest)
    if client_data is not None:
        publish_client_package(client_data, manifest.get('notes',''))
    if not quiet:
        print(f'SquadLoot Version {current} -> {manifest["version"]}; Clientupdate: {"ja" if client_data is not None else "nein"}')
    return server_new or client_data is not None


def main():
    ap = argparse.ArgumentParser(description='Update SquadLoot Pi server from GitHub Releases')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--check-only', action='store_true')
    args = ap.parse_args()
    # flock only on Linux/Pi. Prevent overlapping timer and interactive updates.
    import fcntl
    with LOCK_FILE.open('w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(check_only=args.check_only, quiet=args.quiet)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'SquadLoot Selfupdate fehlgeschlagen: {exc}', file=sys.stderr)
        sys.exit(1)
