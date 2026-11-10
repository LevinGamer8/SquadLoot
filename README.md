# SquadLoot – Pi-Server mit GitHub Auto-Updates

SquadLoot hostet eure Fortnite-Truhenstatistiken lokal auf dem Raspberry Pi.
Der Code ist als öffentliche Release-Quelle gedacht; **keine echten Zugangsdaten
werden in Git gespeichert**.

## Oberfläche

Ab 1.4.0 teilen Windows-Client und Pi-Dashboard ein gemeinsames Designsystem
(dunkles Theme, Indigo-/Cyan-Akzent, Vektor-Icons statt Emojis).
Details: [docs/DESIGN.md](docs/DESIGN.md) · Änderungen: [CHANGELOG.md](CHANGELOG.md)

| Windows-Client | Pi-Dashboard |
|---|---|
| ![Dashboard](docs/screenshots/windows-dashboard.png) | ![Web-Übersicht](docs/screenshots/web-overview.png) |
| ![Live-Tracking](docs/screenshots/windows-live.png) | ![Loot-Galerie](docs/screenshots/web-loot.png) |
| ![Einstellungen](docs/screenshots/windows-settings.png) | ![Match-Historie](docs/screenshots/web-history.png) |

Weitere Ansichten: [Squad](docs/screenshots/windows-squad.png) ·
[Match-Historie](docs/screenshots/windows-history.png) ·
[Updates](docs/screenshots/windows-updates.png) ·
[Mobil](docs/screenshots/web-mobile.png)

### In-Game-HUD

Ab 1.5.0 gibt es ein eigenes Overlay fürs Spiel: 188 × 60 Pixel bei 100 %
Anzeigeskalierung, nur Squad-Truhen, eigene Truhen und ein Statuspunkt.

![HUD kompakt](docs/screenshots/hud-compact.png)
![HUD erweitert](docs/screenshots/hud-expanded.png)

Oben kompakt (Standard), darunter erweitert mit einer Zeile je Spieler — beide
in Originalgröße. [Entsperrt](docs/screenshots/hud-unlocked.png) ·
[Skalierung 100–200 %](docs/screenshots/hud-dpi.png) ·
[Einstellungen](docs/screenshots/hud-settings.png) ·
[Größenvergleich auf 1920 × 1080](docs/screenshots/hud-in-context.png)

Einschalten unter *Einstellungen → In-Game-HUD* oder über die Schnellaktion
*In-Game-HUD* auf dem Dashboard. Fortnite muss im randlosen Fenstermodus
laufen; exklusives Vollbild zeigt keine Windows-Overlays an.

## GitHub Release veröffentlichen

Der GitHub Actions Workflow `.github/workflows/server-release.yml` erstellt bei
jedem Tag `vMAJOR.MINOR.PATCH` automatisch zwei Release-Dateien:

- `SquadLoot-RaspberryPi-Update-vX.Y.Z.zip`
- `latest.json` (mit Paket-URL, SHA-256 und Dateigröße)

Für ein neues Release die Version in `SquadLoot-Pi-Server/VERSION` anpassen,
Änderungen committen und anschließend einen neuen Tag pushen:

```bash
git add .
git commit -m "SquadLoot server v1.2.2"
git push
git tag v1.2.2
git push origin v1.2.2
```

[Installationsanleitung für GitHub und Raspberry Pi](GITHUB-ANLEITUNG.md)

**Sicherheit:** Updates werden über HTTPS aus deinem GitHub-Repository bezogen.
Der Pi prüft Paket-Hash, Dateiliste, ZIP-Inhalte und Version. Die SHA-256-Prüfung
ist jedoch keine zusätzliche kryptografische Signatur des Herausgebers.
Schütze das GitHub-Konto mit 2FA, veröffentliche nur überprüfte Tags und
verwende keine untrusted Pull-Requests als Release-Quelle.


## Windows Clients – drei Spieler

Die Freunde brauchen **keine GitHub-Zugangsdaten**. Sie laden den
[Windows-Client aus dem neuesten Release](https://github.com/LevinGamer8/SquadLoot/releases/latest)
oder einmal `SquadLoot-Freunde-Setup-vX.Y.Z.zip` und führen das enthaltene `SQUADLOOT_INSTALLIEREN.cmd` aus. Python 3.11+, ChestCounter und eingeschaltete
Fortnite-Replays sind erforderlich.

Zum Einrichten benötigt jeder Spieler:
- `https://squadloot.megacraft.de` als Serveradresse
- einen **gemeinsamen Squad-Token** (privat übermittelt)
- eine eigene **Cloudflare Access Service Client-ID und Secret** (privat)
- den eigenen Fortnite-Spielernamen

Live-Erkennung: Nur als **experimentelle Schätzung** durch optische
Erkennung + lokal abgefragte Interaktionstaste. Keine Speicherzugriffe,
keine Fortnite-Paketmanipulation oder Entschlüsselung von Live-Replays.
Bildschirmmodus standardmäßig ausgeschaltet, wenige ROI-Screenshots/Sekunde.
Für reale Daten muss jedes Match mit ChestCounter nachträglich ausgewertet werden.

### Updates

Ein Release-Tag oder ein manueller Start des Workflows erstellt
Pi-Server-ZIP, Windows-Client-ZIP, internes Windows-Update-ZIP und `latest.json`
**aus demselben Commit**. Der Pi lädt beide Pakete und stellt das Windows-
Update über die bestehende geschützte Update-API zur Verfügung. Die Apps
installieren es beim nächsten Start.
