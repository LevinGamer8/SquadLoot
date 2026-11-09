# SquadLoot – Pi-Server mit GitHub Auto-Updates

SquadLoot hostet eure Fortnite-Truhenstatistiken lokal auf dem Raspberry Pi.
Der Code ist als öffentliche Release-Quelle gedacht; **keine echten Zugangsdaten
werden in Git gespeichert**.

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
