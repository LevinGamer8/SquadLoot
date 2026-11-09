#!/usr/bin/env python3
"""Reproducible server release artifacts for GitHub Actions.

Only the same allowlisted server files that the self updater accepts are packed.
Secrets, live data, client ZIPs, the configured manifest endpoint and backups
are never part of a GitHub release.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / 'SquadLoot-Pi-Server'
spec = importlib.util.spec_from_file_location('pi_updater', SRC / 'server_selfupdate.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def build(version: str, repository: str, output: pathlib.Path):
    if updater.parse_version(version) <= (0, 0, 0):
        raise ValueError('Version zu niedrig')
    src_version = (SRC / 'VERSION').read_text(encoding='utf-8').strip()
    if src_version != version:
        raise ValueError(f'Git Tag v{version} stimmt nicht mit Server VERSION={src_version} überein')
    if not repository or '/' not in repository or any(c.isspace() for c in repository):
        raise ValueError('GITHUB_REPOSITORY fehlt: OWNER/REPO erwartet')
    output.mkdir(parents=True, exist_ok=True)
    filename = f'SquadLoot-RaspberryPi-Update-v{version}.zip'
    target = output / filename
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in sorted(updater.RELEASE_FILES):
            file = SRC / rel
            if not file.is_file():
                raise ValueError(f'Fehlende Release-Datei: {file}')
            zf.write(file, arcname=f'SquadLoot-Pi-Server/{rel}')
    raw = target.read_bytes()
    meta = {
        'version': version,
        'package_url': f'https://github.com/{repository}/releases/download/v{version}/{filename}',
        'package_sha256': hashlib.sha256(raw).hexdigest(),
        'package_size': len(raw),
        'notes': f'SquadLoot Pi v{version} – Updates via GitHub Releases',
    }
    (output / 'latest.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Self-verify release contents and hashes, without starting Docker.
    with zipfile.ZipFile(target) as zf:
        names = {name.replace('SquadLoot-Pi-Server/', '', 1) for name in zf.namelist()}
        if not updater.REQUIRED.issubset(names):
            raise ValueError('Release unvollständig')
    print(f'Created {target} ({len(raw)} bytes)')
    print(f'Created {output / "latest.json"}')
    return target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--version', required=True)
    ap.add_argument('--repository', default=os.getenv('GITHUB_REPOSITORY', 'LevinGamer8/SquadLoot'))
    ap.add_argument('--output', default=str(ROOT / 'dist'))
    a = ap.parse_args()
    build(a.version.removeprefix('v'), a.repository, pathlib.Path(a.output))

if __name__ == '__main__':
    main()
