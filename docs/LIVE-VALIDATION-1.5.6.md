# SquadLoot – Live-Qualität vor v1.5.6 nachweisen

**Status: Entwicklung / noch keine 1.5.6-Freigabe.**

## Was wir technisch tatsächlich können

- Live v0.2.3 erkennt derzeit Truhen hauptsächlich über das CHEST-XP-Popup
  und weitere visuelle Hinweise. Es ist **kein universeller Behälterdetektor**.
- Ein echtes deutsches TRUHE-Wortmuster kann im SquadLoot-Live-Tab
  aus einem Gameplay-Screenshot kalibriert werden. Die Qualität des Musters
  und der gesamten Erkennung ist noch nicht durch deutsche Matches geprüft.
- Das Replay-Modul liest nach Matchende echte Containerinformationen:
  `ChestsOpened`, `Chests[].Destroyed`, `AmmoBoxesOpened`,
  `OtherContainersOpened` und `OtherInteractions` mit FoodBox.
  Diese Werte bestätigen die Live-Schätzung.
- **Munitions-/Obstkisten, zerstörte Truhen und sonstige Behälter können
  während des Matches noch nicht nachweislich korrekt klassifiziert werden.**
  Nie generische Suchhinweise als sichere Beweise für einen bestimmten
  Behälter ausgeben: Das würde Falschzählungen produzieren.

## Performance-Änderungen auf dem Entwicklungsbranch

- Bei `gdigrab` wird die Zahl der Desktop-Aufnahmen aus dem konfigurierten
  `process_fps` abgeleitet. Statt immer 30 volle Bildschirmkopien pro
  Sekunde zu erstellen, nimmt die Engine jetzt 10, 15 oder 20 auf.
- Die originale Source-Datei der SHA256-geprüften Engine wird für ein
  sicheres Rollback aufbewahrt. Unbekannte Engines werden nicht modifiziert.
- **Wichtiges Fix:** Die externe App legt `UNCHECKED_HASH`-Python-`.pyc`
  an. Ohne gezielte Invalidierung bleibt selbst nach dem Code-Patch die
  *alte* 30-fps-Version aktiv. Dasselbe Problem betrifft das frühere
  deutsche XP-Popup-Muster. Betroffene Modul-Caches werden vor dem Start
  neu generieren gelassen, keine anderen Module/Spieldateien verändert.
- Die Live-UI bietet 10/15/20 fps; 15 fps bleibt Standard.
  10 fps kann die Erkennungsrate senken; 20 fps kann wieder mehr Leistung
  benötigen. Keine automatische Aussage über tatsächliche Spiel-FPS.
- Live-Events wecken den Netzwerk-Poller; der Client aktualisiert schneller.
  Die Anzeige zeigt Echtzeit-Detector-FPS, Bildverarbeitungszeit und
  übersprungene Frames. Diese Kennzahlen sind **nicht** die Fortnite-FPS.

## Diagnosetest auf echten PCs

1. Fortnite in **Fenstervollbild** öffnen, die korrekte Monitorquelle
   auswählen; separat den FPS-Counter des Spiels beobachten.
2. Drei vergleichbare Matches mit ausgeschaltetem Live-Tracking, 10 fps,
   15 fps und 20 fps durchführen. Spiel-FPS (Median und 1%-Low) und
   Detector `ms/Bild`/Dropped notieren.
3. Mit Englisch und Deutsch jeweils Truhen, Munitionskisten, Obstkisten,
   sonstige Container sowie **zerstörte statt geöffnete Truhen** testen.
   Für Deutsch zuerst ein echtes sichtbares TRUHE-XP-Wort kalibrieren.
4. Für **übersehene** Aktionen die optionalen lokalen Diagnose-Clips
   einschalten und mit Kategorie markieren. Aufnahme später wieder
   ausschalten. Nach Prüfung auf private Inhalte kann der Besitzer
   selbst entscheiden, ob er ein kurzes Beispiel teilen möchte.
5. Nach Matchende die Replay-Werte für jeden Spieler mit der manuell
   notierten Ground Truth vergleichen. Unvollständige Replays nicht
   als fehlgeschlagene Erkennung zählen, sondern gesondert erfassen.
6. Unter Replay-Diagnose API/Uploadfehler getrennt von der
   ursprünglichen Erkennung untersuchen.

## Freigabekriterien

- Ein **echtes, beschriftetes Testset** für Englisch und Deutsch, mehrere
  HUD-Skalierungen und sowohl 1080p als auch 1440p. Aufzeichnungen von
  mindestens zwei unterschiedlichen PCs.
- Nachgewiesene Erkennung jeder geforderten Loot-Kategorie (Truhen,
  zerstörte Truhen, Munition, Lebensmittel/Obstkisten, weitere bekannte
  Container), inklusive getrenntem Wert im Live-Squad-Protokoll.
- Für jede Kategorie: dokumentierte Treffer- und Fehlalarmrate, mit
  vorab festgelegten Grenzen (Ziel: mindestens 95 % Recall und höchstens
  2 % Fehlalarme auf bislang ungesehenen Szenen). Bis dahin keine
  Genauigkeitsbehauptung für diese Kategorie.
- Reproduzierbarer Performancevergleich mit ausgeschaltetem Tracking,
  realistischen großen Monitoren und dokumentiertem FPS-Abfall.
- Erfolgreiche End-to-End-Tests: abgeschlossene Replay-Datei ->
  lokale data.json -> authenticated POST -> Pi-Datenbank -> UI.
- Alle automatischen Tests grün; Windows-/Fortnite-Gegenprobe erfolgreich.
  Erst dann werden beide VERSION-Dateien auf **1.5.6** gesetzt
  und ein Release erstellt.

**Datenschutz:** Gameplay-Clips enthalten eventuell Bildschirmdaten.
Sie bleiben lokal, werden nie automatisch an den Server geschickt und
sollten nur nach freiwilliger, bewusster Prüfung geteilt werden.
