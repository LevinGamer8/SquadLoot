# SquadLoot v1.5.4 – Live mit einem Klick, Replays automatisch

## So funktioniert es

**Passiv (immer aktiv):** SquadLoot überwacht lokal Fortnite-Replays und
wertet abgeschlossene Matches selbstständig aus. Du brauchst keinen
separaten ChestCounter.exe-Download, keinen Pfad und keinen extra Start.
Die Replay-Analyse wird nach Matchende im Hintergrund angestoßen,
die Ergebnisse anschließend zum Pi synchronisiert.

**Live (optional):** Im Reiter **Live-Tracking** auf **Live-Test starten**
drücken. Das startet die bewährte visuelle XP-Popup-Erkennung ohne
zweites Programmfenster. Zum Beenden: **Live-Test stoppen**.
Das Live-Ergebnis ist zunächst eine Schätzung; Replaydaten bestätigen
es erst nach Ende des Matches.

## Installation v1.5.4

1. Pi aktualisieren: cd /opt/squadloot && sudo sh PI_SELFUPDATE_CHECK.sh
2. Windows-Client unter Updates aktualisieren und neu starten.
3. Fortnite: Einstellungen → Spiel → Replays aufnehmen aktivieren.
4. SquadLoot läuft. Passiv-Replays werden automatisch verarbeitet.
5. Optional Live-Tracking öffnen und Live-Test starten klicken.
6. Die App kann beim allerersten Mal nach dem Update zwei geprüfte,
   größere Original-Downloads benötigen. Alle folgenden Starts nutzen
   die bereits vorhandene lokale Laufzeit.

## Warum läuft da im Hintergrund trotzdem ein Analyseprogramm?

Die hochentwickelten Erkennungsalgorithmen bleiben die originalen
MIT-lizenzierten Open-Source-Engines. SquadLoot verwaltet sie nun selbst,
sodass niemand separat etwas installieren, bedienen oder konfigurieren muss:

- Replay: LED-N/Fortnite-ChestCounter v1.4.0 – ca. 38 MB, erster Scan
- Live: GabrielGzS/fortnite-visual-chest-counter v0.2.3 – ca. 156 MB,
  erster Live-Start

Beide werden ausschließlich von einem fest definierten offiziellen
GitHub-Release heruntergeladen und anhand der exakten SHA-256-Prüfsumme
und Dateigröße geprüft. Speicherort:
%LOCALAPPDATA%\SquadLoot\engines

Das normale SquadLoot-Windows-Update bleibt klein und kompatibel.
Ausführliche Quellen: docs/THIRD_PARTY_COMPONENTS.md.

## Deutsche Sprache und Genauigkeit

- Die Replay-Auswertung arbeitet unabhängig von der Fortnite-Sprache.
- Wurde unter v1.5.3 bereits eine echte deutsche Truhenwort-Vorlage
  kalibriert, übernimmt SquadLoot sie automatisch in die interne Engine.
- Bei einer frischen Installation ohne deutsche Vorlage ist der
  deutsche XP-Popup-Text noch nicht zuverlässig erkennbar. Andere
  visuelle Truhensignale können trotzdem eine ungefähre Schätzung liefern.
  Für eine geprüfte deutsche Vorlage benötigen wir einen echten
  Screenshot eines deutschen Truhen-XP-Popups.
- Live ist eine Beta-Schätzung und kann Kisten übersehen oder falsch
  zählen. Nach Matchende ist der Replay-Wert maßgeblich.

## Fehlerbehebung

**Replay nach Matchende nicht erkannt?**
Ist Fortnite Replay-Aufnahme aktiviert und erscheinen Dateien unter
%LOCALAPPDATA%\FortniteGame\Saved\Demos? SquadLoot scannt automatisch
und analysiert nach einer kurzen Stabilisierungszeit. Notfalls kann die
Schnellaktion Replay auswerten neu scannen. Die erste Analyse benötigt
Internet, um die interne Replay-Engine zu laden. Alte separat gestartete
ChestCounter-Instanzen bitte schließen, um konkurrierende Auswertungen
zu vermeiden.

**Live startet nicht?**
Beim ersten Klick lädt SquadLoot ca. 156 MB. Prüfe Internet, Firewall,
Antivirenprogramm und die Meldung im Live-Tab. Ein zweites Fenster
erscheint nicht.

**Es wird der falsche Monitor erfasst?**
Aktuell ist Bildschirm 1 der Standard. Für Spezial-Setups kann man
SquadLoot schließen und in der vorhandenen Datei
%APPDATA%\SquadLootClient\config.json den optionalen Schlüssel
live_monitor auf die gewünschte Monitornummer (z.B. 2) setzen.

**Fortnite auf Deutsch?**
Auf frischen PCs ohne v1.5.3-Kalibrierung fehlen noch geprüfte deutsche
Textmuster. Das wird nicht als vollständig gelöste Spracherkennung
ausgegeben.

## Sicherheit und Privatsphäre

Kein Prozessspeicherzugriff, keine Injection und keine Veränderung
von Fortnite-Dateien. Es gehen nur dieselben SquadLoot-Zählwerte und
Replay-Zusammenfassungen an den Pi; Spielbilder verlassen den PC nicht.
Der Einsatz der Drittprogramme ist nicht offiziell von Epic freigegeben
und kann bei Wettkämpfen zusätzlichen Regeln unterliegen. Für einen
vorsichtigen ersten Test nur lokal aufgezeichnetes Gameplay verwenden.

Bereits gespeicherte Matches, Cloudflare-Token und Einstellungen
bleiben erhalten.
