@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Optionale Bibliotheken fuer den experimentellen Bildschirmmodus werden installiert.
echo Dies ist NICHT fuer normale Replay-Statistiken noetig.
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m pip install -r vision-requirements.txt
  goto done
)
python -m pip install -r vision-requirements.txt
:done
if errorlevel 1 pause
