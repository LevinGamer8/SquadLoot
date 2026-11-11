#!/usr/bin/env python3
"""Package a separate, local-only Windows beta for manual Fortnite validation.

This ZIP is a short-lived CI artifact, NEVER a public GitHub Release or Pi update.
No credentials, user config, stored replays or screen recordings are packaged.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'SquadLoot-Windows-Client'
FOLDER = 'SquadLoot-Live-Beta'
FILES = ('VERSION', 'app.py', 'bootstrap.py', 'client_core.py',
         'replay_reader.py', 'update_manager.py', 'vision.py')
LAUNCHER = r"""@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "SQUADLOOT_BETA_TEST=1"
set "APPDATA=%~dp0_testdaten\Roaming"
set "LOCALAPPDATA=%~dp0_testdaten\Local"
if not exist "%APPDATA%" mkdir "%APPDATA%"
if not exist "%LOCALAPPDATA%" mkdir "%LOCALAPPDATA%"
echo.
echo SquadLoot Live-Beta - NUR LOKALER TEST
echo Alle Beta-Daten bleiben in: %~dp0_testdaten
echo Die normale Installation und deren Einstellungen bleiben unangetastet.
echo Bitte nie gleichzeitig mit der normalen SquadLoot-Live-Erkennung starten.
echo.
where py >nul 2>nul
if not errorlevel 1 (
  py -3 bootstrap.py
  goto done
)
where python >nul 2>nul
if not errorlevel 1 (
  python bootstrap.py
  goto done
)
echo Python 3.11 oder neuer ist nicht installiert.
:done
if errorlevel 1 pause
endlocal
"""
README = """SquadLoot - ISOLIERTE LIVE-BETA (KEIN RELEASE)

1. Normales SquadLoot 1.5.5 beenden; keine zwei Bildschirmrekorder starten.
2. Fortnite im Fenstervollbild starten, FPS-Anzeige im Spiel anschalten.
3. TEST-STARTEN.cmd doppelklicken. Nur diese START-Datei verwenden.
4. Links Live-Tracking waehlen; Bildschirm 2 + Vorschau kontrollieren.
5. Fortnite-Sprache Englisch, Analysegeschwindigkeit Sparsam (10 fps).
6. Live-Test starten. Ungefaehr zehn Truhen, zehn Munitionskisten und
   moeglichst einige Lebensmittelkisten im Match oeffnen.
7. Die drei lokalen Testzaehler in SquadLoot mit den echten Aktionen
   vergleichen. Zerstoerte Truhen zaehlen nur spaeter ueber Replays.
8. Fortnite-FPS mit und ohne laufenden Live-Test vergleichen.
9. Auf Lokalen Testbericht speichern klicken. Die Datei liegt unter
   _testdaten\\Local\\SquadLoot\\LiveBetaTestbericht.txt.
10. Testbericht + Beobachtungen an ChatGPT schicken.

Ohne Eingabe von Pi-Zugangsdaten laeuft die Beta vollstaendig lokal.
APPDATA und LOCALAPPDATA sind nur fuer diesen Prozess in _testdaten
umgeleitet; der normale SquadLoot-Client bleibt unveraendert.
Die private Visual-Engine (~155 MB) wird beim ersten Start heruntergeladen
und anhand des bekannten SHA256-Wertes verifiziert.

Die Beta ist eine experimentelle englische Popup-Erkennung.
Sie ist NICHT SquadLoot v1.5.6 und kein Nachweis allgemeiner Genauigkeit.
Du kannst diesen gesamten Beta-Ordner nach dem Test loeschen.
"""


def build(output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as zip_file:
        for name in FILES:
            path = CLIENT / name
            if not path.is_file():
                raise FileNotFoundError(path)
            zip_file.write(path, FOLDER + '/' + name)
        zip_file.writestr(FOLDER + '/TEST-STARTEN.cmd', LAUNCHER)
        zip_file.writestr(FOLDER + '/LIES-MICH-ZUERST.txt', README)
    with ZipFile(output) as z:
        actual = set(z.namelist())
        expected = {FOLDER + '/' + x for x in FILES} | {
            FOLDER + '/TEST-STARTEN.cmd', FOLDER + '/LIES-MICH-ZUERST.txt'
        }
        if actual != expected or z.testzip():
            raise ValueError('Beta-ZIP unvollstaendig oder fehlerhaft')
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path,
                   default=ROOT / 'dist' / 'SquadLoot-Live-Beta.zip')
    args = p.parse_args()
    print('Built unpublished test ZIP:', build(args.output))
