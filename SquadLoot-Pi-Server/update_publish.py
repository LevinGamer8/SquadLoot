#!/usr/bin/env python3
"""Publish a client-only ZIP to this Pi. Existing DB and credentials are untouched."""
from __future__ import annotations
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
UPDATES=HERE/'updates'
ALLOWED={
    'VERSION','app.py','bootstrap.py','client_core.py','update_manager.py',
    'replay_reader.py','vision.py','STARTEN.cmd','AUSWERTEN.cmd',
    'ORIGINALPROGRAMM.cmd','SETUP_VISION.cmd','vision-requirements.txt',
    'README-CLIENT.txt'
}
REQUIRED={'VERSION','app.py','bootstrap.py','client_core.py','update_manager.py','replay_reader.py','STARTEN.cmd'}


def publish(source,notes=''):
    package=Path(source).read_bytes()
    if not (100<=len(package)<=4*1024*1024):
        raise ValueError('Update ZIP muss zwischen 100 Bytes und 4 MB gross sein.')
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        files=archive.namelist()
        if len(files)!=len(set(files)) or not REQUIRED.issubset(files) or not set(files).issubset(ALLOWED):
            raise ValueError('Update ZIP hat unbekannte oder fehlende Dateien.')
        if sum(f.file_size for f in archive.infolist())>8*1024*1024 or archive.testzip():
            raise ValueError('Ungueltiges ZIP.')
        version=archive.read('VERSION').decode('ascii').strip()
        if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)',version):
            raise ValueError('VERSION muss z.B. 1.2.0 enthalten.')
    latest=UPDATES/'latest.json'
    if latest.exists():
        try:
            previous=json.loads(latest.read_text(encoding='utf-8'))['version']
            if tuple(map(int,version.split('.'))) < tuple(map(int,previous.split('.'))):
                raise ValueError('Ein Downgrade ist nicht erlaubt.')
        except (KeyError,TypeError,ValueError) as err:
            if str(err)=='Ein Downgrade ist nicht erlaubt.': raise
    UPDATES.mkdir(parents=True,exist_ok=True)
    manifest={'version':version,'archive_sha256':hashlib.sha256(package).hexdigest(),
              'archive_size':len(package),'notes':str(notes)[:600]}
    tmp=UPDATES/'client.zip.new'
    tmp.write_bytes(package)
    os.replace(tmp,UPDATES/'client.zip')
    mt=UPDATES/'latest.json.new'
    mt.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(mt,latest)
    print('Client-Release',version,'veroeffentlicht; ZIP:',len(package),'Bytes; SHA256:',manifest['archive_sha256'])


if __name__=='__main__':
    if len(sys.argv)<2:
        sys.exit('Aufruf: python3 update_publish.py /pfad/Client-Release.zip [Release-Notizen]')
    publish(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else '')
