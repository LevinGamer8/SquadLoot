#!/usr/bin/env python3
"""Package Pi + Windows client releases from one tag. Never package secrets."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, pathlib, zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PI = ROOT/'SquadLoot-Pi-Server'
CLIENT = ROOT/'SquadLoot-Windows-Client'
spec=importlib.util.spec_from_file_location('squadloot_server_update',PI/'server_selfupdate.py')
updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)
spec_client=importlib.util.spec_from_file_location('squadloot_client_publish',PI/'update_publish.py')
publisher=importlib.util.module_from_spec(spec_client);spec_client.loader.exec_module(publisher)


def make_zip(path,entries):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as out:
        for name,src in sorted(entries.items()):
            if not src.is_file():
                raise ValueError('Release-Datei fehlt: '+str(src))
            out.write(src,arcname=name)
    return path.read_bytes()


def build(version:str,repository:str,output:pathlib.Path):
    if updater.parse_version(version)<=(0,0,0):raise ValueError('Version zu niedrig')
    if not repository or '/' not in repository or any(x.isspace() for x in repository):
        raise ValueError('OWNER/REPO erwartet')
    for directory in (PI,CLIENT):
        actual=(directory/'VERSION').read_text().strip()
        if actual!=version:
            raise ValueError(f'Git tag v{version} passt nicht zu {directory.name} VERSION={actual}')
    output.mkdir(parents=True,exist_ok=True)
    prefix=f'https://github.com/{repository}/releases/download/v{version}/'
    pi_filename=f'SquadLoot-RaspberryPi-Update-v{version}.zip'
    pi_zip=output/pi_filename
    pi_data=make_zip(pi_zip,{f'SquadLoot-Pi-Server/{rel}':PI/rel for rel in updater.RELEASE_FILES})
    # Full portable source distribution for first-time setup.
    client_filename=f'SquadLoot-Windows-Client-v{version}.zip'
    client_zip=output/client_filename
    client_files={name:CLIENT/name for name in publisher.ALLOWED if (CLIENT/name).is_file()}
    client_data=make_zip(client_zip,{f'SquadLoot-Windows-Client/{name}':p for name,p in client_files.items()})
    # Flat update ZIP is consumed by the client updater on every Windows PC.
    update_filename=f'SquadLoot-Windows-{version}-update.zip'
    update_zip=output/update_filename
    update_data=make_zip(update_zip,client_files)
    with zipfile.ZipFile(update_zip) as z:
        names=set(z.namelist())
        if not publisher.REQUIRED.issubset(names) or not names.issubset(publisher.ALLOWED):
            raise ValueError('Client Update-Paket unvollständig')
        if z.read('VERSION').decode('ascii').strip()!=version:
            raise ValueError('Client VERSION stimmt nicht')
    manifest={
        'version':version,'package_url':prefix+pi_filename,
        'package_sha256':hashlib.sha256(pi_data).hexdigest(),'package_size':len(pi_data),
        'client_version':version,'client_package_url':prefix+update_filename,
        'client_package_sha256':hashlib.sha256(update_data).hexdigest(),
        'client_package_size':len(update_data),
        'notes':f'SquadLoot {version}: Live-Schätzungen, neues Desktop-Design, gemeinsame Updates für Pi und Windows',
    }
    (output/'latest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    installer=ROOT/'SQUADLOOT_INSTALLIEREN.ps1'
    if installer.exists():
        (output/'SQUADLOOT_INSTALLIEREN.ps1').write_bytes(installer.read_bytes())
    if (ROOT/'SQUADLOOT_INSTALLIEREN.cmd').is_file():
        (output/'SQUADLOOT_INSTALLIEREN.cmd').write_bytes((ROOT/'SQUADLOOT_INSTALLIEREN.cmd').read_bytes())
    setup_files={f.name:f for f in (ROOT/'SQUADLOOT_INSTALLIEREN.cmd', ROOT/'SQUADLOOT_INSTALLIEREN.ps1', ROOT/'FREUNDE-START.txt')}
    make_zip(output/f'SquadLoot-Freunde-Setup-v{version}.zip',setup_files)
    print('Generated release:',*[x.name for x in output.iterdir()],sep='\n - ')
    return pi_zip


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--version',required=True)
    ap.add_argument('--repository',default=os.getenv('GITHUB_REPOSITORY','LevinGamer8/SquadLoot'))
    ap.add_argument('--output',default=str(ROOT/'dist'))
    a=ap.parse_args()
    build(a.version.removeprefix('v'),a.repository,pathlib.Path(a.output))

if __name__=='__main__':main()
