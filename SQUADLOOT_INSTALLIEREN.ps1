# One-time installer. Run only after verifying this repository's official GitHub Release.
# Downloads the public client ZIP, extracts it to the current user's local profile.
$ErrorActionPreference = 'Stop'
$Base = Join-Path $env:LOCALAPPDATA 'SquadLoot'
$Dest = Join-Path $Base 'app'
$Uri = 'https://github.com/LevinGamer8/SquadLoot/releases/latest/download/SquadLoot-Windows-Client.zip'
# Stable alias: the release workflow also publishes versioned client files.
# GitHub does not create an unversioned alias by itself, so resolve the latest tag.
$Api = 'https://api.github.com/repos/LevinGamer8/SquadLoot/releases/latest'
try {
    $release = Invoke-RestMethod -Uri $Api -Headers @{'User-Agent'='SquadLoot-Installer'} -TimeoutSec 20
    $asset = $release.assets | Where-Object { $_.name -match '^SquadLoot-Windows-Client-v[0-9]+\.[0-9]+\.[0-9]+\.zip$' } | Select-Object -First 1
    if (-not $asset) { throw 'Kein Windows-Client als Release-Asset gefunden.' }
    $Uri = $asset.browser_download_url
    New-Item -ItemType Directory -Force -Path $Base | Out-Null
    $temp = Join-Path $Base 'client-download.zip'
    Write-Host "SquadLoot: lade $($asset.name) herunter ..."
    Invoke-WebRequest -Uri $Uri -OutFile $temp -TimeoutSec 90
    $stage = Join-Path $Base 'staging'
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    Expand-Archive -Path $temp -DestinationPath $stage -Force
    $source = Join-Path $stage 'SquadLoot-Windows-Client'
    foreach ($needed in @('STARTEN.cmd','bootstrap.py','app.py','VERSION')) {
        if (-not (Test-Path (Join-Path $source $needed))) { throw "Installationsdatei fehlt: $needed" }
    }
    if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Force -Path $Dest | Out-Null }
    # Does not change %APPDATA%\SquadLootClient\config.json or state.json.
    Copy-Item (Join-Path $source '*') -Destination $Dest -Recurse -Force
    $link = Join-Path ([Environment]::GetFolderPath('Desktop')) 'SquadLoot.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($link)
    $shortcut.TargetPath = (Join-Path $Dest 'STARTEN.cmd')
    $shortcut.WorkingDirectory = $Dest
    $shortcut.Save()
    Remove-Item $stage -Recurse -Force
    Remove-Item $temp -Force
    Write-Host "Fertig: $Dest" -ForegroundColor Green
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $py) {
        Write-Warning 'Python 3.11+ ist noch nicht installiert. Bitte zuerst Python von python.org installieren.'
        Start-Process 'https://www.python.org/downloads/windows/'
    }
    Write-Host 'Fortnite: Replays aktivieren. Zusätzlich ChestCounter.exe separat installieren.'
    Write-Host 'Danach SquadLoot.lnk auf dem Desktop starten und eigene Cloudflare-Token eintragen.'
} catch {
    Write-Host "Installation abgebrochen: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
