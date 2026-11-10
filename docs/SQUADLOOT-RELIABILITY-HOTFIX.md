# Replay-/Live-Hotfix – Diagnose und Praxistest

## Was wurde geändert?

1. Im Live-Tab über **Bildschirmquelle** den richtigen Monitor auswählen.
   Bei euch voraussichtlich **Monitor 2**. „Automatisch“ nimmt den Monitor,
   auf dem das sichtbare Fortnite-Fenster liegt; vor dem Start von Fortnite
   kann diese Erkennung auf Monitor 1 zurückfallen. Ein gesetzter Monitor
   bleibt pro PC in `%APPDATA%\\SquadLootClient\\config.json` erhalten.
   Mit **Vorschau aktualisieren** einen einmaligen Screenshot dieses Monitors
   anzeigen. Es handelt sich um eine lokale Vorschau, die weder auf Disk
   gespeichert noch zum Pi übertragen wird. Im exklusiven Vollbild kann
   Windows schwarze Vorschauen liefern: Fenstervollbild nutzen.
2. Bei einem Live-Fehler steht im Live-Reiter eine Diagnose. Zusätzlich bleibt
   ausschließlich lokal eine STDERR-Datei im verwalteten VisualCounter-Ordner.
   Diese Datei kann bei Bedarf vor dem Teilen auf private Pfade geprüft werden.
3. Im deutschen Fortnite ist die Truhen-XP-Worterkennung weiterhin nur nach
   echter TRUHE-Kalibrierung zuverlässig testbar. Das Programm kann ohne
   kalibrierte Vorlage nur alternative objektbezogene Hinweise schätzen.
   Es wird keine künstliche oder ungetestete Vorlage ausgeliefert.
4. Die Replay-Schnellaktion wartet auf laufende Analysen und sendet danach
   **alle** lokalen Matches erneut (sicher durch idempotente Server-Updates).
5. Der automatische Sync sendet weiterhin nur neue/geänderte Matches, bleibt
   bei Upload-Fehlern wiederholbar und hält die Live-Verbindung unabhängig.
   Gleichzeitig gestartete Replay-Synchronisierungen werden serialisiert.
6. Unter **Einstellungen → Replay-Diagnose** sieht jeder Spieler lokal
   Replay-Dateien, auswertbare und bereits übertragene Matches sowie letzte
   Analyse-/Upload-Fehler – ohne Squad-Token oder Cloudflare-Secret.
   Bei `/api/match: HTTP 403` Cloudflare Access und WAF-Regeln für diese
   konkrete POST-Route prüfen. Ein erfolgreicher GET auf `/api/state`
   beweist noch nicht, dass die POST-Route erlaubt ist.

## Test auf Windows/Fortnite

- Nach Client-Update vollständig neu starten; Replays in Fortnite aktivieren.
- Monitor 2 wählen, unter **Vorschau aktualisieren** prüfen, ob Fortnite zu
  sehen ist. Anschließend den Live-Test (neu) starten. Im Status muss
  `Live-Tracking aktiv · Monitor N` erscheinen, nicht nur `Startet`.
- In einem englischen Match mehrere Truhen öffnen und Live-Schätzung beobachten.
- In einem deutschen Match nur mit echter Vorlage die XP-Trefferquote bewerten.
  Ohne Vorlage ist 0 bei deutschen Popup-Wörtern kein Beweis eines Capture-Bugs.
- Match abschließen; mit `Replay auswerten` eine erneute Auswertung und
  anschließend vollständige Übertragung an den Pi auslösen.
- In der Pi-Historie prüfen, ob Spielername, Session-ID und Kisten stimmen.
- Bei weiterhin fehlenden Matches `%APPDATA%\\ChestCounter\\errors.log`
  und SquadLoot-Status (nur Fehlertext; **niemals Tokens/Secrets**) prüfen.

## Grenzen

Die externe v0.2.3-Engine nutzt bildbasierte Schätzungen und kann insbesondere
bei geänderter Fortnite-Benutzeroberfläche fehlschlagen. Eine funktionierende
technische Verbindung ist nicht dasselbe wie eine validierte Erkennungsrate.
Die passive Replay-Engine benötigt vollständige, unterstützte Replay-Dateien,
die Fortnite erst nach Matchende entschlüsselt. Die automatische Monitorauswahl
verändert keine Dateien oder Speicherbereiche von Fortnite.
