# SquadLoot – GitHub Releases und Pi-Auto-Update

Diese Anleitung gilt für das GitHub-Konto **LevinGamer8** und ein noch neu zu
errichtendes öffentliches Repository **SquadLoot**.

## Einmalig: neues GitHub-Repository

1. Öffne https://github.com/new
2. Owner: `LevinGamer8`
3. Repository Name: `SquadLoot`
4. Sichtbarkeit: **Public** (die Downloads sollen ohne GitHub-Zugangstoken möglich sein)
5. **Kein** automatisches README, `.gitignore` oder License erzeugen: ist bereits im Paket.
6. **Create repository** anklicken.

## GitHub-Quellcode hochladen

Das ZIP `SquadLoot-GitHub-Repository.zip` auf dem Windows-PC entpacken.
Terminal im entpackten Ordner öffnen (dort liegen `README.md` und `.github/`).

```powershell
git init -b main
git remote add origin https://github.com/LevinGamer8/SquadLoot.git
git add .
git commit -m "SquadLoot Pi Server und automatisches Release"
git push -u origin main
git tag v1.2.1
git push origin v1.2.1
```

Bei GitHub ggf. anmelden. Falls Git Name/E-Mail nicht gesetzt sind, `git config
--global user.name ...` und `git config --global user.email ...` einmalig setzen.

Dann https://github.com/LevinGamer8/SquadLoot/actions öffnen.
Der Workflow **Release SquadLoot Pi Server** sollte für `v1.2.1` laufen.

Im Bereich https://github.com/LevinGamer8/SquadLoot/releases kontrollieren,
ob im Release `v1.2.1` **`latest.json` und die Server-ZIP** liegen.
Falls das Workflow-Publishing wegen fehlenden Rechten fehlschlägt:
Repository → Settings → Actions → General → Workflow permissions prüfen.
`contents: write` ist bereits im Workflow gesetzt; Organisationseinstellungen
können es trotzdem einschränken.

## Pi: Einmaliges Bootstrap auf v1.2.1

Das separat bereitgestellte ZIP `SquadLoot-RaspberryPi-Update-v1.2.1.zip` auf
Windows entpacken und den Ordner `SquadLoot-Pi-Server` über WinSCP/SFTP nach
`/home/levin/` auf den Pi kopieren.

```bash
sudo cp -a "$HOME/SquadLoot-Pi-Server/." /opt/squadloot/
cd /opt/squadloot
sudo sh PI_UPDATE_AKTIVIEREN.sh
```

**Nicht** `/opt/squadloot/.env` löschen oder `docker compose down -v` ausführen.
Der vorhandene Cloudflare Tunnel samt Access-Policies bleibt unverändert.

## Pi: Automatische Updates einschalten

```bash
cd /opt/squadloot
sudo cp -n server-update.conf.example server-update.conf
sudo nano server-update.conf
```

Die Datei muss enthalten:

```ini
MANIFEST_URL=https://github.com/LevinGamer8/SquadLoot/releases/latest/download/latest.json
CHECK_INTERVAL=6h
```

Dann:

```bash
sudo sh PI_SELFUPDATE_INSTALL.sh
sudo systemctl status squadloot-selfupdate.timer --no-pager
sudo sh PI_SELFUPDATE_CHECK.sh --check-only
```

Solange `v1.2.1` die neuste Version ist, meldet der Check **keine neuen Updates**.

Spätere Veröffentlichungen werden alle sechs Stunden geprüft und bei einer
höheren Version heruntergeladen und installiert. Die SQLite-Datenbank im
Docker-Volume, die `/opt/squadloot/.env` und die lokale
`server-update.conf` werden nicht ersetzt.

**Hinweis:** Bei einem Update werden `squadloot` und `squadloot-nginx` neu
gebaut/gestartet. Kurze Unterbrechungen sind dabei möglich.

## Nachkontrolle

```bash
cd /opt/squadloot
sudo docker compose -f compose.yaml -f compose.tunnel.yaml ps
sudo journalctl -u squadloot-selfupdate.service -n 40 --no-pager
sudo systemctl list-timers squadloot-selfupdate.timer --all
```

## Später ein neues Update veröffentlichen

Beispiel v1.2.2:

1. Update im GitHub-Repository programmieren und testen.
2. `SquadLoot-Pi-Server/VERSION` auf `1.2.2` setzen.
3. Änderungen committen und pushen.
4. `git tag v1.2.2` und `git push origin v1.2.2` ausführen.
5. GitHub Actions erzeugt Release-ZIP und `latest.json` automatisch.
6. Der Pi installiert die neue Version innerhalb des konfigurierten Intervalls.

Sicherheit: Jeder, der ein Release in diesem Repo veröffentlichen kann, kann
Code auf dem Pi aktualisieren. GitHub-Konto mit 2FA absichern; Rechte auf
wenige Personen beschränken. Updates nur von vertrauenswürdigen Branches/Tags.

## Nicht verwechseln

Der Pi-Self-Updater aktualisiert **SquadLoot**, nicht Debian, Docker,
Cloudflared und nicht den separat betriebenen Original-ChestCounter.
Der Windows-Client hat seinen eigenen Updater via SquadLoot API.
