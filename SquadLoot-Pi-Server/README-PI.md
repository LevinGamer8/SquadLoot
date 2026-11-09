# SquadLoot auf Raspberry Pi 5 / Debian 13 (arm64)

Diese Variante ist extra fuer **deinen Pi mit vorhandener Docker-Installation**. Sie veraendert **nicht** deinen vorhandenen `reverse-proxy`-Container. Die drei neuen Container laufen in einem eigenen Docker-Compose-Projekt:

- `squadloot`: Python-HTTP-API + SQLite-Datenbank
- `squadloot-nginx`: ausschliesslich interner Reverse-Proxy auf Port 8080
- `cloudflared`: ausgehender Cloudflare Tunnel; Hostname in Cloudflare auf `http://squadloot-nginx:8080` leiten

Es werden **keine Host-Ports** publiziert und keine FRITZ!Box-Portfreigaben benoetigt. Nur `cloudflared` hat Netzwerk-Egress. Die Website unter dem selbst gewaelten Hostnamen ist dennoch aus dem Internet ueber Cloudflare erreichbar, sofern sie nicht zusaetzlich durch Cloudflare Access eingeschraenkt ist.

## 1. Download und auf den Pi kopieren

Das ZIP `SquadLoot-RaspberryPi-Server.zip` **auf deinem PC** herunterladen und entpacken. In WinSCP mit SFTP auf deinen Pi unter `192.168.178.100` verbinden und **den gesamten Ordner** `SquadLoot-Pi-Server` nach `/home/DEIN-PI-USER/` kopieren (deinen SSH-Benutzernamen einsetzen). Die Windows-Client-ZIP **nicht** auf den Pi kopieren.

Auf deinem PC PowerShell oder SSH-Terminal starten:

```sh
ssh DEIN-PI-USER@192.168.178.100
```

Dann auf dem Pi:

```sh
sudo mkdir -p /opt/squadloot
sudo cp -a "$HOME/SquadLoot-Pi-Server/." /opt/squadloot/
cd /opt/squadloot
sudo sh PI_INSTALLIEREN.sh
```

Der letzte Befehl legt `/opt/squadloot/.env` an, generiert darin einen zufaelligen `SQUAD_TOKEN` und startet **nur** API+internen Nginx. Erwartet wird zweimal eine Antwort `{"status": "ok"}`. Das kann beim allerersten Docker-Image-Build etwas dauern. Bereits vorhandene `.env` wird NICHT ueberschrieben.

Mit folgenden Befehlen kannst du pruefen:

```sh
sudo docker compose ps
sudo docker compose logs --tail=50 squadloot
sudo docker compose logs --tail=50 squadloot-nginx
```

Falls `docker compose` auf dem Pi nicht vorhanden ist, musst du das Docker Compose Plugin nachinstallieren. Es wird **nicht** automatisch in deine bestehende Docker-Umgebung eingegriffen.

## 2. Cloudflare Tunnel im Web-Dashboard anlegen

Du benoetigst eine Domain in deinem Cloudflare-Konto. Wir verwenden `squadloot.megacraft.de` als Beispiel; nimm einen anderen freien Namen, falls er bereits existiert.

1. Cloudflare-Dashboard -> **Networking -> Tunnels -> Create Tunnel** (die Menuebezeichnungen koennen sich aendern).
2. Tunnelname z. B. `squadloot-pi`, Tunneltyp **Cloudflared**.
3. Beim Connector-Setup **Docker** waehlen. Den angezeigten `docker run ... --token eyJ...`-Befehl **nicht** ausfuehren. Stattdessen nur die lange Zeichenfolge nach `--token` kopieren. **Das ist ein sensibles Geheimnis.**
4. Auf dem Pi im Verzeichnis `/opt/squadloot`:

```sh
sudo nano .env
```

Aendere NUR diese Zeile:

```text
CF_TUNNEL_TOKEN=HIER_EINTRAGEN
```

zu:

```text
CF_TUNNEL_TOKEN=DEIN_ECHTER_LANGER_TOKEN
```

Der bereits generierte `SQUAD_TOKEN=` bleibt unveraendert. Editor speichern: `Strg+O`, Enter, `Strg+X`. Den Token niemals im Chat, Screenshot oder Git committen.

5. Im Cloudflare Tunnel unter **Routes -> Add route -> Published application** eintragen:
   - Hostname: `squadloot.megacraft.de`
   - Service Type: `HTTP`
   - **Service URL: `http://squadloot-nginx:8080`**
   - Speichern. Cloudflare erzeugt/verwaltet normalerweise den zugehoerigen proxied CNAME-Record. Falls bereits ein A/CNAME-Eintrag mit diesem Namen existiert, vorab Konflikt klaeren; bestehende Services nicht ueberschreiben.
6. Auf dem Pi Tunnel starten:

```sh
cd /opt/squadloot
sudo sh PI_TUNNEL_STARTEN.sh
```

7. Status:

```sh
sudo docker compose -f compose.yaml -f compose.tunnel.yaml ps
sudo docker compose -f compose.yaml -f compose.tunnel.yaml logs --tail=50 cloudflared
```

Die Container sollten `Up` bzw. `healthy` anzeigen. Teste im Browser `https://squadloot.megacraft.de` -- du siehst die SquadLoot-Tokenabfrage. Der Login funktioniert erst, wenn du den unter Schritt 1 erzeugten Squad-Token eintraegst.

**Wichtig:** Keine Weiterleitung von 8765, 8080 oder 80/443 in der FRITZ!Box einrichten. Vorhandene andere Freigaben / Services sind ein separates Thema und werden hier nicht geaendert.

## 3. Zugang mit Cloudflare Access absichern (empfohlen)

Ein Cloudflare Tunnel ist **kein Zugangslogin**: ohne Access kann jeder den oeffentlichen Hostnamen aufrufen, auch wenn die Daten-API weiterhin den Squad-Token verlangt. Fuer eine zweite Schranke vor der Website:

1. Cloudflare **Zero Trust -> Access controls -> Service credentials -> Service tokens**: fuer jeden Client ein **eigenes** Service-Token erstellen (`SquadLoot-PC-1`, `SquadLoot-PC-2` usw.). Client-ID und Client-Secret sicher speichern; das Secret wird oft nur bei Erstellung angezeigt.
2. **Zero Trust -> Access controls -> Applications -> Add application -> Self-hosted/public application**. Hostname exakt `squadloot.megacraft.de`.
3. Policy **Allow**: nur deine und die E-Mail-Adressen der Mitspieler erlauben (oder nur deine Mail, wenn nur du das Browserdashboard nutzt). Fuer die Browseranmeldung z. B. One-time PIN aktivieren.
4. Eine **separate Policy `Service Auth`** mit *Include -> Service Token* und den erstellten Service Tokens einrichten. `Allow` allein reicht fuer Service-Token-Zugriff nicht aus.
5. Nun fordert das Browserdashboard erst eine Cloudflare Access-Anmeldung an. Danach muss dort zusaetzlich der Squad-Token eingegeben werden.
6. In jedem Windows-SquadLoot-Client zusaetzlich die Felder **CF Access Client-ID** und **CF Access Client-Secret** ausfuellen (die im hier mitgelieferten Pi-Windows-Client vorhanden sind). Jeder Spieler nimmt nach Moeglichkeit seine **eigenen** Zugangsdaten. Ohne Access bleiben **beide Felder leer**.
7. Teste erst mit deinem eigenen Windows-PC; danach den Zugang fuer die drei Freunde freigeben.

Der Squadtokenschutz (`SQUAD_TOKEN`) bleibt trotz Access erhalten. Wenn dein Access-App-Setup nur einen Browser-Login erlaubt und keine Service-Auth-Policy hat, wird der Windows-Client mit HTTP 302/403/JSON-Fehler scheitern. **Nicht auf `Bypass` stellen**, nur um das zu umgehen.

## 4. Auf Windows einrichten

Alle vier PCs verwenden `SquadLoot-Windows-Client-Pi.zip` und das [Original-ChestCounter](https://github.com/LED-N/Fortnite-ChestCounter/releases/latest). Das Original verarbeitet die Replay-Dateien nach dem Match und schreibt `%APPDATA%\\ChestCounter\\data.json`. Der SquadLoot-Windows-Client liest nur diese Statistikdatei.

1. Fortnite -> Einstellungen -> Spiel -> Wiederholungen: `Wiederholungen aufzeichnen = EIN`.
2. Python 3.11+ installieren und `py -3 --version` testen.
3. Client-ZIP vollstaendig in einen dauerhaften Ordner (z. B. `C:\\Tools\\SquadLoot`) entpacken.
4. Original-ChestCounter `ChestCounter.exe` bereits installiert? Verwende diesen. Sonst von der Original-GitHub-Releases-Seite beziehen, **einmal** starten und Replay-Ordner konfigurieren. Am besten im ersten Test parallel zu Fortnite laufen lassen; NACH Match-Ende bestaetigt das Original die Zaehlungen.
5. `STARTEN.cmd` doppelklicken, Tab `Verbindung & Accounts`:
   - **Server-URL**: `https://squadloot.megacraft.de`
   - **Squad-Token**: Zeile `SQUAD_TOKEN=...` aus deiner `/opt/squadloot/.env` (**nur der Wert, ohne `SQUAD_TOKEN=`**).
   - **CF Access Client-ID / Client-Secret**: nur wenn Schritt 3 eingerichtet wurde, sonst leer.
   - **Dein Anzeigename**: der eigene Fortnite-Name, ggf. bei Accountwechsel aktualisieren.
   - **ChestCounter data.json**: Standardpfad beibehalten.
   - **Replay-Ordner**: Standardpfad beibehalten.
   - **ChestCounter.exe**: den Pfad zum Originalprogramm eintragen oder die EXE in den Unterordner `tools` kopieren.
6. `Speichern & verbinden` anklicken, bei Erfolg `Web-Dashboard` ausprobieren.
7. Je ein Windows-Client und Original ChestCounter auf jedem der vier PCs, wenn automatische Synchronisierung nach jeder Runde gewuenscht ist.

**Ohne Hintergrundprogramme:** Replay-Aufzeichnung bleibt an. Nach dem Spielen das Originalprogramm per `--once` auswerten lassen und `AUSWERTEN.cmd` starten. Keine Livezahlen waehrend der Runde. **Manuelle** +1-Buttons funktionieren live, solange SquadLoot laeuft. Der experimentelle Bildschirmmodus ist **keine verifizierte Kistenerkennung**.

### Was du an die drei Freunde gibst

- Windows-Client-ZIP
- `https://squadloot.megacraft.de`
- gemeinsamen **SQUAD_TOKEN** (nur ueber privaten vertrauenswuerdigen Kanal)
- wenn Access aktiviert: pro Freund eigene CF-Access Client-ID und Secret
- Link zu Original-ChestCounter + Hinweis auf Replay-Aufzeichnung

**Nicht** weitergeben: Cloudflare **Tunnel** Token (`CF_TUNNEL_TOKEN`), komplette Pi-`.env`, Pi-SSH-Zugang oder Dashboard-Adminrechte.

## 5. Betrieb und Probleme

```sh
cd /opt/squadloot
sudo sh PI_STATUS.sh
sudo docker compose -f compose.yaml -f compose.tunnel.yaml logs --tail=100 cloudflared
sudo docker compose -f compose.yaml -f compose.tunnel.yaml logs --tail=100 squadloot
sudo docker compose -f compose.yaml -f compose.tunnel.yaml logs --tail=100 squadloot-nginx
```

- **Cloudflare Error 1033 / Tunnel offline**: Container-Status und Tunnel-Logs pruefen, Token in `.env` pruefen, ausgehende Verbindungen zu Cloudflare (u. a. Port 7844) beachten.
- **Cloudflare 502**: Hostname-Route muss exakt `http://squadloot-nginx:8080` sein; intern pruefen: `sudo docker compose exec -T squadloot-nginx wget -qO- http://127.0.0.1:8080/health`.
- **401**: `SQUAD_TOKEN` falsch oder fehlt.
- **403 / Cloudflare Access HTML statt JSON**: `Service Auth`-Policy und Windows-Client CF Access Client-ID/Secret pruefen.
- **Keine Replays**: In Fortnite Aufnahme an? Hat ChestCounter seine `%APPDATA%\\ChestCounter\\data.json` neu geschrieben? Beide Programme laufen? Manuell `AUSWERTEN.cmd`.
- **Schnell Folge-Matches direkt nach dem Ready-up**: Spielzuordnung ist heuristisch; bei Fehler im Client `Neue Squad-Runde` auf **einem** PC druecken und pruefen, ob alle folgen.
- **Kein sofortiges automatisches Zaehlen**: Fortnites aktuelles Replay bleibt bis Matchende verschluesselt; Livewerte sind manuell oder experimentell visuell, nicht verbindlich.
- **Sicheres Beenden** (behaelt Daten): `sudo sh PI_STOPPEN.sh`.
- **Backup**: Das Docker-Volume `squadloot-pi_squadloot_data` enthaelt SQLite; vor Updates/Loeschen sichern. Nicht `docker compose down -v` ausfuehren, wenn Daten erhalten bleiben sollen.

### Sicherheitsregeln

- Niemand bekommt eine 100%ige Sicherheitsgarantie von Cloudflare. Tunnel ersetzt NICHT Tokens oder Zugriffskontrolle.
- Beide Token-Arten sind Geheimnisse: `CF_TUNNEL_TOKEN` bleibt nur auf Pi, `SQUAD_TOKEN` wird den vier Mitspielern mitgeteilt. Access-Service-Tokens wenn aktiviert moeglichst pro PC.
- `.env` mit Modus 600 und nur root lesbar. `docker compose config` gibt die eingesetzten Tokens aus; Ausgabe nicht teilen.
- HTTPS und CF-Tunnel benoetigen **keine** Portfreigabe an der FRITZ!Box. Der Stack veroeffentlicht **keine** Docker-Host-Ports.
- Container, Pi und Cloudflared regelmaessig aktualisieren; Tests zuerst an einer Runde.

**Teststatus:** Die Python-API, der Windows-Client und Token-Header wurden mit simulierten Tests geprueft. Die Ausfuehrung auf deinem Pi/Cloudflare-Konto ist ohne dortigen Zugang nicht testbar. Deshalb ist dies eine erste Testversion, keine produktive Freigabe.

## SquadLoot 1.1 - Auto-Updater fuer Windows Clients

Die Erweiterung benutzt **denselben Cloudflare Tunnel, dieselbe Access-Policy
und denselben Squad-Token** wie bisher. Es sind keine neuen Ports notwendig.

### Server-Upgrade auf deinem vorhandenen Raspberry Pi

1. Neue `SquadLoot-Pi-Server` ZIP auf dem PC entpacken.
2. Ordner mit WinSCP ins Home-Verzeichnis des Pi kopieren.
3. Per SSH folgende Befehle ausfuehren (im Beispiel Pi-User `levin`):

```
cd /opt/squadloot
sudo cp -a "$HOME/SquadLoot-Pi-Server/." /opt/squadloot/
sudo sh PI_UPDATE_AKTIVIEREN.sh
```

Die bestehende `/opt/squadloot/.env` und Docker-Datenbank bleiben erhalten.
Die neuen Update-Endpunkte sind `/api/client-update/manifest` (JSON) und
`/api/client-update/package` (ZIP). Beide verlangen den Squad-Token und,
sofern eingeschaltet, Cloudflare Access Client-ID/Secret.

### Erstes Client-Update anbieten

Das Serverpaket enthaelt `updates/client.zip` und `updates/latest.json` bereits.
Die neue Windows-Version muss von allen Clients **einmal manuell** installiert
werden, weil die alte Version noch keinen Auto-Updater hatte. Danach reicht es,
einfach `STARTEN.cmd` aufzurufen.

### Zukuenftige neue Client-Version veroeffentlichen

Wenn du einen neuen Client-Build erhalten hast, kopiere dessen **flache
Update-ZIP** (Dateien ohne Oberordner; VERSION und .py/.cmd) per WinSCP auf den Pi.
Beispiel: `/home/levin/SquadLoot-Windows-1.2.0-update.zip`.

```
cd /opt/squadloot
sudo sh PI_CLIENT_RELEASE.sh /home/levin/SquadLoot-Windows-1.2.0-update.zip "Neue Version"
```

**Kein Docker-Neustart noetig:** Der laufende Server liest ZIP und Manifest
bei jeder Anfrage aus dem read-only gemounteten `updates`-Ordner. Die Dateien
werden atomar veroeffentlicht. Client-Downloads bleiben hinter Token + Access.
Pruefung mit den bereits im Client eingetragenen Zugangsdaten:

```
# Windows PowerShell im bisher konfigurierten Nutzerprofil:
$c = Get-Content "$env:APPDATA\SquadLootClient\config.json" -Raw | ConvertFrom-Json
$h = @{ Authorization = "Bearer $($c.token)"; 'CF-Access-Client-Id' = $c.cf_access_client_id; 'CF-Access-Client-Secret' = $c.cf_access_client_secret }
Invoke-RestMethod ($c.server_url.TrimEnd('/') + '/api/client-update/manifest') -Headers $h
```

Achtung: Es werden keine Passwoerter oder Tokens als Releasedateien abgelegt.
Die Update-ZIP muss vor dem Veroeffentlichen vom Serverbetreiber geprueft werden.
SHA-256 verhindert defekte Downloads, aber signiert noch nicht den Herausgeber.
Der Pi/Cloudflare-Account ist deshalb die Vertrauensbasis fuer Updates.


## SquadLoot 1.2 - Dashboard mit Icons + Raspberry-Pi-Self-Update

### Neu im Web-Panel

- visuelle **Loot-Galerie** mit Icons fuer seltene Belohnungen
- **Kisten-Uebersicht** fuer Gesamt-, Munitions-, Obst- und zerstoerte Kisten
- cleaneres, moderneres Layout fuer Browser-Ansicht und Handy

### Raspberry-Pi-Self-Update (kein manuelles Entpacken auf dem Pi mehr)

Die neue Version kann sich auf dem Pi **selbst aktualisieren**, sobald du einmal eine
**Manifest-URL** hinterlegt hast. Wichtig: Der Pi braucht dafuer eine **externe HTTPS-Quelle**,
auf der zwei Dateien liegen:

1. `latest.json` - Manifest mit Version, SHA256 und Paket-URL
2. `SquadLoot-RaspberryPi-Update-v1.2.0.zip` - das eigentliche Server-Update

Die Dateien kannst du z. B. auf **GitHub Releases**, **GitHub Pages**, deinem **Hetzner-Webspace**
oder einem anderen statischen HTTPS-Speicher ablegen.

#### Einmalig auf dem Pi aktivieren

```sh
cd /opt/squadloot
sudo cp server-update.conf.example server-update.conf
sudo nano server-update.conf
```

Dort `MANIFEST_URL=` auf deine echte HTTPS-Adresse setzen, speichern und dann:

```sh
sudo sh PI_SELFUPDATE_INSTALL.sh
```

Damit wird ein systemd-Timer angelegt, der standardmaessig alle 6 Stunden nach einer neuen Version schaut.

#### Manuell pruefen

```sh
cd /opt/squadloot
sudo sh PI_SELFUPDATE_CHECK.sh --check-only
sudo sh PI_SELFUPDATE_CHECK.sh
```

Die bestehende `.env`, dein `SQUAD_TOKEN`, der Cloudflare-Tunnel und die SQLite-Daten bleiben erhalten.
Nur die eigentlichen Server-Dateien werden ersetzt und der Stack danach neu gebaut/gestartet.

#### Format des Manifests

```json
{
  "version": "1.2.0",
  "package_url": "SquadLoot-RaspberryPi-Update-v1.2.0.zip",
  "package_sha256": "...",
  "package_size": 123456,
  "notes": "Dashboard-Icons und Pi-Self-Update"
}
```

`package_url` darf relativ zur Manifest-URL oder absolut angegeben werden.

## Matcharchiv und echte Fortnite-Bilder (Entwurf / naechstes Release)

### Aufbewahrung

- Die SQLite-Datenbank bleibt im Docker-Named-Volume `squadloot-pi_squadloot_data` gespeichert.
- **Es gibt keine automatische Ablaufzeit und keine Loeschroutine fuer Matches.**
- Die Hauptansicht listet zur besseren Ladezeit weiterhin die letzten 20 Runden, das neue **vollstaendige Matcharchiv** kann aber durch alle Eintraege blaettern.
- `Alle Matches als CSV exportieren` laedt eine CSV mit **allen** Eintraegen herunter; die API `/api/export/matches.csv` ist nur mit Bearer-Token und, falls aktiviert, Cloudflare Access erreichbar.
- Neue API: `/api/matches?offset=0&limit=30` (maximal 100 pro Seite) zum Blaettern.
- Keine Produktivdaten mit `docker compose down -v` loeschen. Bei Docker-Volume-Loeschung oder SSD-Defekt koennen Daten sonst verloren gehen.

### Automatische Backups auf dem Pi

Nach Installation dieses Updates auf dem Pi **einmal** ausfuehren:

```sh
cd /opt/squadloot
sudo sh PI_BACKUP_AUTOMATISCH.sh
sudo sh PI_BACKUP.sh
sudo systemctl list-timers squadloot-backup.timer
```

- Täglich ab 03:20 Uhr (mit zufaelliger Verzoegerung bis zu 10 Minuten) wird ein konsistenter SQLite-Snapshot erstellt.
- Backup-Verzeichnis: `/opt/squadloot/backups/`, nur fuer root lesbar.
- Backups werden 30 Tage aufbewahrt. **Dies betrifft nur alte Backup-Dateien, niemals die aktuelle Datenbank oder Matches.**
- Backup auch auf einen zweiten Datentraeger kopieren (z. B. deine externe HDD). Backups auf derselben NVMe schuetzen nicht gegen deren Ausfall.
- In Logs keine Tokens ausgeben. Die Backup-Datei enthaelt Spielerstatistiken und sollte vertraulich behandelt werden.

### Authentische Fortnite-Bilder

Das Web-Dashboard zeigt statt frei erfundener Emoji-Grafiken echte Fortnite-Bildbeispiele fuer:

- Pirate Shop Access (Original-Token-Symbol, Quelle: VICE / Epic Games Screenshot)
- Treasure Hunters Truhe (Quelle: VICE / Epic Games Screenshot)
- Munitionskiste (Quelle: PlayStation Competition Center Screenshot)
- Mercedes-AMG G 63, Solid Gold Gauntlets und Plunder in Paradise (Originalicons aus Fortnite-API)
- NOMS-Lebensmittelkiste (Quelle: GamesRadar+ Screenshot)

Bei Cosmetic-Drops wird zusaetzlich versucht, **nur bei exakter Namensuebereinstimmung** ein echtes Icon ueber die oeffentliche Fortnite-API zu laden (`fortnite-api.com`, API v2). Bei nicht verifizierbarem Namen bleibt der neutrale Hinweis "Bild nicht verfuegbar" statt einem falschen Item-Bild.

**Hinweis:** Bilder werden extern im Browser geladen. Damit koennen die Bildanbieter die IP-Adresse des Browsers sehen; bei einer fehlenden Internetverbindung oder blockierten Drittanbieteranfragen erscheint ein neutraler Platzhalter. Es werden keine Tokens oder Replaydaten an Bildanbieter gesendet. Die Screenshots sind echte Fortnite-Aufnahmen, aber teilweise aus aelteren Spielversionen und nicht immer exakt dieselbe Behältervariante.

Epic Games Fan Content Policy: https://legal.epicgames.com/epicgames/fan-art-policy


## v1.3.1: Automatisches Upgrade von 1.3.0

Dieses Release ist mit der strengen Dateiliste des Pi-Updaters aus v1.3.0
kompatibel. Es liefert das Matcharchiv, den CSV-Export, die Fortnite-Bilder
und einen vorbereiteten Updater mit Unterstuetzung fuer neue Backup-Skripte.

**Wichtig:** Die neuen Dateien `PI_BACKUP.sh` und
`PI_BACKUP_AUTOMATISCH.sh` sind zwar im GitHub-Quellcode, werden aber
**noch nicht in der 1.3.1-Update-ZIP ausgeliefert**, damit der bisherige
Pi-Updater nicht das gesamte Update ablehnt. Fuer automatische SQLite-Backups
muss der Betreiber diese beiden Dateien vorerst getrennt installieren.
Daten werden durch das Update nicht geloescht; der SQLite-Container nutzt
weiterhin dasselbe benannte Docker-Volume.

Der automatische Updatecheck auf dem Pi:

```sh
cd /opt/squadloot
sudo sh PI_SELFUPDATE_CHECK.sh --check-only
sudo sh PI_SELFUPDATE_CHECK.sh
sudo docker compose -f compose.yaml -f compose.tunnel.yaml ps
```


## SquadLoot 1.4.0 – Claude-Redesign und Daten-Erhalt

Das Windows-Fenster und das Web-Dashboard wurden mit einheitlichem Designsystem
neu aufgebaut. Alle vorhandenen Matchdaten bleiben im Docker-Volume erhalten.
Die Match-Historie zeigt weiterhin die 20 jüngsten Runden als Kurzansicht;
über **Vollständiges Matcharchiv** und **CSV exportieren** sind alle
historischen Matchdaten verfügbar. Originale Fortnite-Bilder werden nur für
verifizierte Itemnamen über feste HTTPS-Bildquellen geladen; unbekannte Items
haben einen neutralen Fallback.

**Kein manuelles Übertragen nötig:** Nach GitHub Release v1.4.0 führt auf dem Pi
`sudo sh /opt/squadloot/PI_SELFUPDATE_CHECK.sh` den sicheren Updateablauf
inklusive automatischer Clientpaket-Veröffentlichung aus. Bereits konfigurierte
Windows-Clients erhalten das neue Design über die bestehende Update-API beim
nächsten Neustart. Ein Eingriff in SQLite oder Cloudflare ist nicht notwendig.
