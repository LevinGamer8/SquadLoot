@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 bootstrap.py %*
  goto done
)
where python >nul 2>nul
if not errorlevel 1 (
  python bootstrap.py %*
  goto done
)
echo Python 3.11 oder neuer fehlt. https://www.python.org/downloads/windows/
:done
if errorlevel 1 pause
