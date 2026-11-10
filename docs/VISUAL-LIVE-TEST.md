# SquadLoot v1.5.0 - Visueller Live-Test (optional)

## Was wird getestet?

SquadLoot übernimmt Änderungen aus den Ausgabedateien von **Fortnite Visual Chest Counter**. Die beiden Anwendungen laufen getrennt. Der Original-ChestCounter (LED-N), der Replays nach Matchende auswertet, bleibt unverändert nötig.

Externer MIT-lizenzierter Open-Source-Detektor:
https://github.com/GabrielGzS/fortnite-visual-chest-counter

Windows-Beta v0.2.3:
https://github.com/GabrielGzS/fortnite-visual-chest-counter/releases/tag/v0.2.3

**Die große Fremdsoftware wird nicht mit SquadLoot ausgeliefert.**
Nur zwei kleine lokale Textdateien werden gelesen. Dein GitHub-/Pi-/Windows-Auto-Updater bleibt gleich.

## Schritt für Schritt

1. Auf dem Raspberry Pi SquadLoot aktualisieren und dann den Windows-Client über den Update-Reiter auf v1.5.0 bringen.
2. Vom obigen Original-GitHub-Release die Datei **Fortnite-Visual-Chest-Counter-v0.2.3.zip** (ca. 156 MB) herunterladen, entpacken und **Fortnite Visual Chest Counter.exe** starten.
3. Im Visual Chest Counter bei **Video source** deinen Fortnite-Bildschirm **Screen 1 oder Screen 2** auswählen und **Start counting** klicken. Dazu brauchst du kein OBS. In der Vorschau prüfen, ob 16:9-Gameplay samt XP-Popup sichtbar ist.
4. **WICHTIG: Aktuell funktionieren englische und brasilianisch-portugiesische Popups, aber keine deutschen.** Für den Test Fortnite vorübergehend auf Englisch stellen.
5. Visual Chest Counter erstellt in seinem entpackten Verzeichnis den Ordner **obs_output** mit **certain_chests.txt** und **approximate_chests.txt**. Das Standardformat sieht etwa so aus: CERTAIN OPENED CHESTS: 5 und APPROX. OPENED CHESTS: 7.
6. In **SquadLoot > Live-Tracking > Visueller Kistenzähler - Live-Test** auf **OBS-Ordner wählen** gehen, genau den **obs_output**-Ordner auswählen und **Live-Test starten** klicken.
7. Neue Fortnite-Runde starten, Kisten öffnen und LIVE die Zahlen beobachten. SquadLoot übernimmt nur neue Änderungen von **APPROX** (enthält CERTAIN bereits). Der Client synchronisiert diese vorläufigen Ergebnisse automatisch mit dem Pi.
8. Nach dem Match wie bisher ChestCounter die Replays auswerten lassen. Dessen bestätigte Werte ersetzen die vorläufigen Zahlen. Vergleiche die erreichten CERTAIN-/APPROX-Zahlen mit dem Replay und notiere verpasste / falsch gezählte Kisten.
9. Zum Beenden in SquadLoot **Live-Test stoppen** drücken.

## Alternativ: Funktionstest ohne laufendes Fortnite

Spiele ein englisches Fortnite-Gameplay-Video im Vollbild auf dem ausgewählten Monitor ab, wähle im fremden Counter die **Screen**-Quelle, starte dort die Zählung und in SquadLoot den Live-Test. Starte davor gegebenenfalls manuell eine neue Squad-Runde. Die externe Funktion **Analyse a recording** schreibt Ergebnisse in ein anderes Verzeichnis; sie aktualisiert den Live-OBS-Zähler nicht.

## Technik und Schutz

- Der externe Counter zählt visuelle XP-Popups. Die Genauigkeit ist nicht 100 % garantiert.
- Die zwei Dateien werden höchstens im vorhandenen GUI-Intervall (ca. einmal/Sekunde) gelesen.
- Beim Start nimmt SquadLoot den alten kumulativen Stand nur als Baseline, ohne alte Kisten zu übernehmen.
- Nach Wechsel der SquadLoot-Runde wird automatisch eine neue Baseline gewählt.
- APPROX ist die gesamte Schätzung einschließlich CERTAIN. **Nicht addieren.**
- Wenn der externe Counter zurückgesetzt oder das Profil gewechselt wird, entstehen keine künstlichen negativen Werte.
- Die bisherige SquadLoot-Bildschirmerkennung wird beim Wechsel deaktiviert, sodass nicht beide gleichzeitig zählen.
- Kein weiterer Screenshot durch SquadLoot, keine neue ML-Bibliothek im Client, keine Screenshots oder Videodaten auf dem Pi.
- Der Test ist standardmäßig AUS und wird nach jedem SquadLoot-Neustart bewusst erneut eingeschaltet.
- Bestehende SQLite-Matchdaten, Cloudflare-Tokens und Replay-Synchronisierung werden nicht verändert.

## Performance und Anti-Cheat

Die Dateiübernahme belastet den PC kaum. Die externe Videobild-Erkennung verarbeitet jedoch ungefähr 15 Bilder/Sekunde und kann CPU-/GPU-Last verursachen: Fortnite-FPS und Task-Manager beobachten. Das Programm ist ein unabhängiges, nicht offiziell von Epic Games bestätigtes Tool; Anti-Cheat-Kompatibilität kann nicht garantiert werden. Der konservativste Test erfolgt mit Videoaufzeichnungen oder einer externen Streaming-Maschine. Besonders in Wettbewerben gelten zusätzliche Regeln.

HUD: Ein Overlay darf den XP-Popup-Bereich nicht verdecken. Verwende gegebenenfalls den randlosen Fenstermodus statt exklusivem Vollbild.

## Fehlerbehebung

- **Quelle nicht lesbar:** Sind beide .txt-Dateien vorhanden und startet der externe Counter die Zählung?
- **Keine Erkennung:** Richtigen Monitor, sauberes 16:9-Spielbild, englische Popups und Sichtbarkeit des XP-Textes überprüfen.
- **0 beim Start:** Beabsichtigt. SquadLoot übernimmt ausschließlich die neuen Funde nach Betätigung von Live-Test starten.
- **Runde gewechselt, Zahl zurückgesetzt:** Beabsichtigt; neue Match-Baseline.
- **Zähler falsch:** Nach Matchende Replayvergleich dokumentieren. Nur diesen Vergleich als endgültige Statistik nehmen.

Keine Zugangstokens, Secrets oder vertraulichen Informationen in öffentlichen GitHub-Issues veröffentlichen.
