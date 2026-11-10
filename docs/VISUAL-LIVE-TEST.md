# SquadLoot – Live-Test mit visueller Truhenerkennung

## Deutsch im Fortnite-Spiel (SquadLoot v1.5.3 · experimentell)

Die externe Visual-Chest-Counter-App **v0.2.3** unterstützt ab Werk nur
englische und portugiesische XP-Popup-Bildvorlagen. Ein geänderter Anzeigetext
allein würde keine deutschen Truhen erkennen.

SquadLoot ergänzt deshalb eine **ausdrücklich bestätigte, lokale
Einmal-Kalibrierung**: Du erzeugst eine echte Vorlage direkt aus deinem
deutschen Fortnite-Screenshot. Dafür ist kein OCR-Modell nötig. Alle Bilder
bleiben lokal. *Deutsch ist noch nicht mit echten Matches validiert.*

**Einrichtung nach dem Update auf v1.5.3:**

1. Stelle Fortnite wieder auf **Deutsch**. Öffne eine gewöhnliche Truhe.
   Während der kleinen violetten **XP-Einblendung rechts vom Fadenkreuz**
   braucht SquadLoot ein **Screenshot-Bild mit dem Truhenwort** (z. B. TRUHE).
   Am einfachsten: einen kurzen Gameplay-Clip aufnehmen, bei der Einblendung
   pausieren und ein einzelnes PNG/JPG-Bild exportieren. Nicht das große
   goldene Belohnungs-Banner verwenden.
2. **Beende den externen Fortnite Visual Chest Counter vollständig**,
   einschließlich seines Zähl-Workers.
3. In **SquadLoot → Live-Tracking** muss wie bisher der **obs_output**-Ordner
   der **entpackten** externen App v0.2.3 ausgewählt sein.
4. Auf **Deutsch kalibrieren** klicken, Screenshot auswählen und auf dem
   angezeigten 1280×720-Bild ein **enges Rechteck um NUR das violette
   Truhenwort** ziehen. NICHT die XP-Zahl oder mehrere Zeilen markieren.
   Anschließend auf **Muster installieren** klicken.
5. SquadLoot hinterlegt die erstellte Float32-NPY-Bildvorlage in der externen
   App und fügt dort eine Sprachoption hinzu. Die bisherigen Python-Dateien
   der **externen** App werden vorher unter
   \`.squadloot-german-backup\` gesichert. Die Truhenzähler, Profile,
   \`config.toml\` und der Raspberry Pi bleiben unangetastet.
6. Starte den **externen** Zähler neu. Unter
   **Settings → Game language** jetzt **Deutsch (SquadLoot Beta)**
   auswählen. Danach **Start counting** starten.
7. In SquadLoot den gewohnten **Live-Test starten**. Bei neuen
   deutschen Kisten sollten APPROX/CERTAIN erhöht werden; SquadLoot
   überträgt wie bisher nur die neuen Änderungen an den Pi.
8. Vergleiche nach Matchende die geschätzte Anzahl mit ChestCounter/Replays.
   Bei Fehlern bitte eine **anonymisierte**, lokal gespeicherte Aufnahme des
   reinen XP-Bereichs zur Kalibrierung verwenden. Kein Token oder Profil teilen.

**Wichtig:** Dieser Schritt passt nur zur derzeit bekannten Ordnerstruktur
von Visual Chest Counter **v0.2.3**. Bei einer künftigen Aktualisierung der
externen App könnte die Anpassung verloren gehen; dann die neue Version
zuerst auf Kompatibilität prüfen. Auch ändert diese Beta **nicht** die
englischspezifischen Spezialerkennungen für kleine HUDs und gestapelte
Truhen-Popups: Deutsch kann vorerst weniger vollständig zählen als Englisch.
Das bedeutet auch, dass CERTAIN/APPROX **keine offiziellen Fortnite-Werte**
sind. Ein einzelner positiver Test beweist noch keine hohe Trefferquote.

Die Schaltfläche **Deutsch zurücksetzen** stellt die gesicherten
Originaldateien der externen App wieder her; auch dafür muss die externe App
beendet sein. Alte Backups werden **nicht** in eine inzwischen aktualisierte
Version kopiert. Das bestehende SquadLoot-GitHub-/Pi-/Client-Autoupdate
überträgt nur die neue Kalibrierungs-Oberfläche. Die externe,
ca. 155 MB große Anwendung selbst wird **nicht** mitgeliefert.

---


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
4. Ab v1.5.3 kann eine **deutsche Beta-Vorlage kalibriert** werden (siehe oben). Ohne diese Kalibrierung erkennt die Original-App weiterhin nur Englisch und Portugiesisch.
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
- **Keine Erkennung:** Richtigen Monitor, sauberes 16:9-Spielbild, passende Sprache (Deutsch nur nach Kalibrierung), HUD-Größe und Sichtbarkeit des XP-Texts prüfen.
- **0 beim Start:** Beabsichtigt. SquadLoot übernimmt ausschließlich die neuen Funde nach Betätigung von Live-Test starten.
- **Runde gewechselt, Zahl zurückgesetzt:** Beabsichtigt; neue Match-Baseline.
- **Zähler falsch:** Nach Matchende Replayvergleich dokumentieren. Nur diesen Vergleich als endgültige Statistik nehmen.

Keine Zugangstokens, Secrets oder vertraulichen Informationen in öffentlichen GitHub-Issues veröffentlichen.
