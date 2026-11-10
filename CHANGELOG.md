# Changelog

## Unreleased – Live-Performance und Diagnose (Freigabe gesperrt)

- Optionale 10/15/20 fps im Live-Tab (Standard 15) und bessere Statusanzeige
  für die tatsächliche Engine-Frequenz, Verarbeitungszeit und Dropped Frames.
- Versionstreue, rücksetzbare Capture-Optimierung: FFmpeg `gdigrab`
  liest nicht mehr unnötig 30 volle Bildschirmbilder bei 10/15 fps ein.
- Wichtiger Cache-Fix: Der gepinnte VisualCounter bringt vorkompilierte
  `UNCHECKED_HASH`-Pythonmodule mit. Nach Änderungen an Capture-Quellcode
  und deutschen Vorlagen werden passende `.pyc` gezielt entfernt, sonst
  bliebe beim Start der alte Code trotz gepatchter Datei aktiv.
- Schnellerer, durch Live-Ereignisse weckbarer Netzwerkabgleich.
- Deutsche TRUHE-Popup-Kalibrierung direkt aus der SquadLoot-Oberfläche.
- Opt-in lokale Diagnose-Clips für übersehene Truhen, zerstörte Truhen,
  Munitions-, Obstkisten und sonstige Behälter (standardmäßig aus).
- Keine falsche Vollständigkeitsangabe für Live-Loot-Kategorien:
  Es fehlen echte beschriftete Testclips und ein validierter Mehrklassen-
  Erkenner. **VERSION bleibt 1.5.5**, bis die Freigabekriterien erfüllt sind.
  Siehe docs/LIVE-VALIDATION-1.5.6.md.


## 1.5.5 – Monitorvorschau und Replay-/Upload-Zuverlässigkeit

- Automatische Monitorauswahl anhand des sichtbaren Fortnite-Fensters statt
  stillschweigender Erkennung ausschließlich auf Monitor 1. Ein manuell
  gesetzter `live_monitor`-Wert (1–8) hat weiterhin Vorrang.
- Monitorauswahl als Dropdown im Live-Tab, mit Auflösung/Position je Display
  und lokaler, einmalig aufgenommener Bildvorschau. Einstellung wird direkt
  gespeichert; Änderungen werden beim nächsten Live-Start wirksam.
  Die Bildvorschau benötigt nur Windows-GDI und kein Pillow.
- Live-Erkennung prüft, ob sie tatsächlich eine Bildschirmquelle verbunden
  hat; der letzte Fehler der Erkennungsengine wird lokal in
  `%LOCALAPPDATA%\\SquadLoot\\engines\\VisualCounter-v0.2.3\\squadloot-live-errors.log`
  aufbewahrt, anstatt STDERR vollständig zu verwerfen.
- Englische Erkennung bleibt stets aktiv. Eine echte, zuvor kalibrierte
  deutsche TRUHE-Vorlage wird zusätzlich verwendet, sofern vorhanden.
  Ohne deutsche Vorlage bleibt die XP-Worterkennung für Deutsch experimentell;
  der sprachunabhängige Objekt-Hinweis ersetzt keine validierte DE-Vorlage.
- "Replay auswerten" wartet jetzt auf einen bereits laufenden Replay-Scan,
  anstatt sofort eine alte `data.json` hochzuladen.
- Erfolgscode 0 von einer *zweiten* ChestCounter-Instanz wird nicht mehr als
  abgeschlossene Auswertung fehlinterpretiert.
- Ein alter, abweichender Dateiname für `data_json` wird auf die tatsächliche
  ChestCounter-Ausgabe `data.json` normalisiert. Einzelne unlesbare
  Replays erscheinen als Warnung und blockieren keine anderen Uploads.
- Eine Replay-Diagnose zeigt lokale Dateien, auswertbare Matches, gesendete Daten und Fehler ohne Credentials.
- Replay-Upload, Live-Zähler und Serverstatus werden unabhängig abgefragt:
  ein Upload-Fehler blockiert nicht mehr alle weiteren Aktualisierungen.
- Parallele GUI-/Hintergrund-Uploads verwenden ein gemeinsames Lock, sodass dieselbe Match-Datei nicht mehrfach gesendet wird.
- Replay-Schnellaktion und "Alle Replays synchronisieren" können bereits
  übertragene, unveränderte Matches bewusst erneut senden, falls dem Pi
  Daten fehlen; Server-Upserts bleiben idempotent.
- Kein Eingriff in vorhandene Match-Historie, Tokens, Update-Formate oder
  Fortnite-Prozessspeicher. Windows-/Fortnite-Praxistests für beide Sprachen
  sind weiterhin erforderlich.


## 1.5.4 – Live-Tracking mit nur einem Button + automatische Replay-Auswertung

- Vereinfachter Live-Tab: persönliche, Squad- und Replay-Zähler sowie
  **Live-Test starten / stoppen**, ohne separate Bildvorlagen, Tasten,
  OBS-Ordnerwahl, Fremdprogrammkonfiguration oder Kalibrierungsassistent.
- Die bewährte Visual-Chest-Counter-Engine startet headless als intern
  verwalteter Worker (JSON-Events), ohne zweites Bedienfenster.
- Die bewährte Replay-Engine wird ebenfalls intern verwaltet und startet
  nach stabilen/abgeschlossenen Replays automatisch. Der alte
  ChestCounter.exe-Pfad ist nicht mehr erforderlich.
- Erste Anwendung lädt die beiden originalen Release-Artefakte bei Bedarf
  mit fest hinterlegten SHA256-Checksummen in den privaten
  %LOCALAPPDATA%-Komponentenordner (38 MB Replay, 156 MB Live).
- Update-Format, Pi, Cloudflare, SQLite/Matcharchiv, bestehende Tokens,
  Replay-Protokoll und GitHub-Release-Pipeline bleiben kompatibel.
- Bereits vorhandene deutsche Vorlagen aus v1.5.3 werden migriert;
  neue deutsche Installationen bleiben bis zur Verifikation des
  Original-Popup-Musters eingeschränkt. Keine fälschliche Vollgarantie.
- Regressionstests für Pfadsicherheit, ZIP-Extraktion, JSON-Events,
  Replay-Worker, Rundengrenzen und Update-Allowlist.
- Keine Anti-Cheat-Freigabe; vor produktivem Windows/Fortnite-Einsatz
  müssen Performance und Trefferquote praktisch überprüft werden.


## 1.5.3 – Deutsches Truhen-XP-Popup kalibrieren (Beta)

- Einmalige, vollständig lokale Erstellung eines echten deutschen
  TRUHE-Wortmusters aus einem Gameplay-Screenshot; wahlweise Deutsch
  im separat installierten Visual Chest Counter v0.2.3 aktivieren.
- Keine neue OCR-/KI- oder Video-Abhängigkeit im SquadLoot-Client.
  Normalisierung auf 1280×720 mit dem FFmpeg der externen Anwendung,
  anschließende Maskenselektion und NumPy-kompatibles NPY-Vorlagenformat.
- Explizit bestätigte Anpassung der externen MIT-App mit Originaldatei-Backup,
  idempotenter Aktualisierung und Wiederherstellungsoption.
- Kein automatischer Eingriff beim normalen Windows-Start; die bestehende
  visuelle Live-Synchronisierung, das HUD und die Replay-Historie bleiben gleich.
- Vorhandene englische/portugiesische Erkennung bleibt verwendbar.
- Keine Genauigkeitsbehauptung: echtes deutsches Truhenbild und Testmatch nötig;
  englischspezifische Zusatzmechanismen sind in Deutsch noch nicht angepasst.
- Automatisierte NPY-, Masken-, Quellpatch-, Rollback- und GUI-Regressionstests.


## 1.5.2 – Automatische Erkennung statt manueller Plus/Minus-Zähler

- Entfernt die manuellen Truhe+/Truhe−, Munitions-, Obstkisten- und Zerstört-
  Schnellbuttons aus Dashboard und Live-Tracking.
- Der Live-Bereich zeigt nun automatische Erkennung, Squad-Zähler und
  Replay-bestätigte Werte im Mittelpunkt; die Verbindung zu Visual Chest
  Counter v0.2.x bleibt unverändert.
- „Neue Squad-Runde“, „Replay auswerten“ und „Live-Schätzung zurücksetzen“
  bleiben vorhanden. Keine manuellen Buchungen mehr in der Oberfläche.
- Das Web-Dashboard weist auf automatische Schätzungen und spätere
  Replay-Bestätigung statt manuelle Klicks hin.
- Historische SQLite-Daten und API-Felder bleiben unverändert, sodass
  ältere Clients nicht plötzlich Fehler erhalten. Keine Datenmigration.
- Windows- und Pi-Version über den bestehenden GitHub/Pi Auto-Updater.
- Regressionstest verhindert, dass manuelle Zählbuttons wieder erscheinen.


## 1.5.1 – HUD-Anzeige auf Windows stabilisiert

* Windows-HUD wird nach dem Erstellen erst sichtbar eingeblendet und danach
  mit Win32-Fensterstilen versehen; Vorschau kann ein verdecktes Fenster
  wieder nach vorne holen.
* Robuste 64-Bit-HWND-Zugriffe auf Windows, insbesondere GetParent und
  SetWindowPos.
* Startposition wird auf dem Hauptmonitor statt am linken Rand des gesamten
  virtuellen Desktops berechnet. Zuruecksetzen speichert keine veraltete Position.
* Voruebergehend keine potenziell problematische Tk-Farbschluesseltransparenz
  fuer abgerundete Ecken. Die kompakte Karte bleibt halbtransparent und
  klickdurchlaessig, aber der aeussere Hintergrund ist rechteckig.
* Neue Schaltflaeche **HUD pruefen** in den Einstellungen, um Fensterstatus,
  Position, Groesse, Deckkraft und Monitor-Koordinaten ohne Zugangsdaten
  anzuzeigen.
* Vier weitere Regressionstests fuer Remapping, Startposition,
  Hintergrund und Positionsreset.

**Windows-Sichtbarkeit muss noch auf einem echten Windows-PC verifiziert werden.**
Es gibt keine Fortnitespeicher-Zugriffe oder Anti-Cheat-Manipulation.


## 1.5.0 — Kompaktes HUD und optionaler visueller Live-Test

Das alte Overlay war ein kleines Anwendungsfenster (330 × 220 px) mit
Überschrift, Spielerliste und Buttons. Es ist durch ein echtes Spiel-HUD
ersetzt.

### Kompaktmodus (Standard)

* **188 × 60 px** bei 100 % Anzeigeskalierung statt 330 × 220 px — rund 84 %
  weniger Fläche.
* Nur noch drei Dinge: Squad-Truhen groß, eigene Truhen kleiner daneben, ein
  kleiner Statuspunkt. Keine Überschrift, kein Spielername, keine Buttons.
* Cyan für Live-Schätzungen, Grün für replay-bestätigte Werte, gedämpft wenn
  keine Runde läuft. Der Statuspunkt zeigt Verbindung, Fehler oder „nicht
  eingerichtet“ ohne Textwarnung.
* Die Karte wächst mit vierstelligen Zahlen, statt Text abzuschneiden.

### Erweiterter Modus

* Zusätzlich eine Zeile je Spieler: Punkt, Name, Zahl und ein Marker
  (Haken = Replay bestätigt, Blitz = Schätzung).
* Umschalten per Tastenkürzel, Rechtsklick-Menü oder Einstellungen — ohne das
  Spiel zu verlassen.

### Overlay-Verhalten (Windows)

* Randloses Fenster ohne Titelleiste und ohne Taskleisten-Eintrag
  (`overrideredirect` + `WS_EX_TOOLWINDOW`).
* Echte Transparenz um die Karte über einen Farbschlüssel, konfigurierbare
  Deckkraft (35–100 %) und Größe (80–160 %).
* **Gesperrt:** Mausklicks gehen durch das HUD ins Spiel
  (`WS_EX_LAYERED | WS_EX_TRANSPARENT`). **Entsperrt:** Akzentrahmen,
  Griffpunkte, mit der Maus verschiebbar.
* Immer im Vordergrund, ohne dem Spiel den Fokus zu nehmen
  (`WS_EX_NOACTIVATE`, periodisches `SetWindowPos(HWND_TOPMOST)`).
* Position wird gespeichert und beim Start gegen die aktuelle Bildschirmfläche
  aller Monitore geklemmt — eine Position auf einem entfernten Monitor kommt
  zurück ins Bild.
* DPI-bewusst: skaliert mit 100 %, 125 %, 150 % und 200 % mit.
* Optionale globale Tastenkürzel (`RegisterHotKey`), Standard
  `Strg+Alt+H` (anzeigen), `Strg+Alt+L` (sperren), `Strg+Alt+E` (Modus).
  Kürzel ohne Modifikator werden abgelehnt, damit keine Spieltaste belegt wird.
* Keine Code-Injektion, kein DirectX-Hook, kein Zugriff auf den
  Fortnite-Prozess — ausschließlich dokumentierte Fenster-APIs.

### Einstellungen

* Neuer Abschnitt „In-Game-HUD“: anzeigen, kompakt/erweitert, Deckkraft,
  Größe, Sperre, Position zurücksetzen, Vorschau und die drei Tastenkürzel.
* Warnt, wenn das HUD im Bereich liegt, den die Bildschirmerkennung abtastet.
* Sagt auf Nicht-Windows-Systemen klar, welche Funktionen dort ohne Wirkung
  bleiben.
* Neues `Slider`-Bedienelement im bestehenden Designsystem.

### Performance

* Gezeichnet wird nur bei einer echten Wertänderung. Gemessen über 20 Sekunden
  mit laufender Runde und unveränderten Zahlen: **0 Neuzeichnungen**.
* Kein eigener Timer; das HUD hängt am bestehenden Sekundentakt.
* Zusätzlicher Speicherbedarf rund **0,3 MB**.

### Kompatibilität

* Keine neuen Client-Dateien — die Update-Dateiliste bleibt unverändert, schon
  installierte Clients aktualisieren weiterhin automatisch.
* Neue `hud_*`-Einstellungen sind optional; bestehende `config.json`-Dateien
  ohne diese Schlüssel verwenden dieselben Standardwerte.
* Das HUD ist standardmäßig **aus** und erscheint erst, wenn man es einschaltet.
* Server-API, Replay-Synchronisierung, Match-Historie, Cloudflare Access und
  beide Auto-Updater sind unverändert.

### Visual-Chest-Counter-Integration (Beta)

* Optionaler 1-Sekunden-Dateiadapter fuer die CERTAIN-/APPROX-Livezaehler des externen Open-Source-Detektors.
* Kein Reimport alter kumulativer Zaehler; neue Rundengrenzen und externe Resets werden abgefangen.
* Keine Videodatenuebertragung und kein zusätzlicher Screen-Scanner im SquadLoot-Prozess.
* Neue Tests fuer Dateiparsing, Rundengrenzen, Reset, Deduplizierung und Fehlerpfade.
* Externe Anwendung bleibt separat (kein 155-MB-Update-ZIP); siehe docs/VISUAL-LIVE-TEST.md.

### Tests

* Neu: `tests/test_hud_overlay.py` (36 Tests) — Tastenkürzel-Parsing,
  Konfigurationsstandards und Abwärtskompatibilität, Geometrie bei 100–160 %,
  Klemmen auf sichtbare Monitore, Positionspersistenz, Ziehen gesperrt/entsperrt,
  Neuzeichnen nur bei Änderung, Farbsemantik, sauberes Beenden und die
  Windows-Fallbacks.

## 1.4.0 — Komplett neu gestaltete Oberfläche

### Windows-Client

* **Neues Designsystem** direkt auf `tk.Canvas`: gerundete Karten, echte
  Hover-, Fokus-, Press- und Deaktiviert-Zustände, einheitliche Radien,
  Abstandsskala und Typo-Stufen. Keine Standard-Tkinter-Widgets mehr im Layout.
* **Vektor-Icons statt Emojis.** 29 Linien-Icons werden gezeichnet statt geladen.
* **Sechs Bereiche** in einer Seitenleiste: Dashboard, Live-Tracking,
  Match-Historie, Squad, Einstellungen, Updates.
* **Dashboard** mit Verbindungsstatus, aktueller Runde, persönlichen und
  Squad-Truhen, bestätigten Matches, Munitions-, Obst-, Zerstörungs- und
  Belohnungszählern, Squad-Übersicht mit Beitragsbalken und Schnellaktionen.
* **Squad-Ansicht** mit Online-/Offline-Status, bestätigt-gegen-geschätzt,
  prozentualem Beitrag und getrennter Account-Statistik.
* **Live-Tracking** zeigt Tracking-Zustand, manuelle Steuerung,
  Erkennungsqualität als Messbalken, das zuletzt erkannte Ereignis mit Zeit
  und eine Legende „geschätzt oder bestätigt“.
* **Einstellungen** in benannten Abschnitten (Server, Cloudflare Access,
  Epic-Account, Replays/ChestCounter, Live-Erkennung, Updates) mit
  Inline-Validierung, Ordner-/Dateiauswahl, maskierten Geheimnissen inklusive
  Anzeigen-Schalter und nicht blockierendem Verbindungstest.
* **Updates** zeigt installierte Version, verfügbare Version, Zeitpunkt der
  letzten Prüfung, Status, Fortschritt und verständliche Fehlermeldungen.
  Das Verhalten bleibt unverändert: Installation beim nächsten Start.
* **Anzeigeskalierung:** DPI-bewusst, Layout und Schrift skalieren gemeinsam.
* **Scrollbare Seiten** mit schlanker eigener Scrollleiste; die Fenster-Mindest-
  größe (1060 × 680) bleibt ohne Abschneiden nutzbar.
* **Überarbeitetes Live-HUD** im selben Stil.
* Der Hintergrund-Refresh läuft weiter im Sekundentakt und schaltet auf 2,5 s
  herunter, solange das Fenster minimiert ist.

### Web-Dashboard (Raspberry Pi)

* Vollständig neu aufgebaut, im Designsystem des Windows-Clients.
* Seitenleiste mit fünf Ansichten (Übersicht, Squad, Match-Historie, Accounts,
  Loot-Galerie), die auf Mobilgeräten zu einer scrollbaren Tab-Leiste wird.
* Spielerkarten mit Beitragsbalken, Behälter-Legende, Detailtabellen,
  Account-Karten und einer Loot-Galerie mit Kategorie-Erkennung.
* Inline-SVG-Icon-Set inklusive Standard-, seltener und vergrabener Truhe,
  Munitions- und Obstkiste, zerstörter und erneut gefüllter Truhe.
* Lade-Skelette, aussagekräftige leere Zustände, Offline-Banner mit
  „Erneut versuchen“; zuletzt empfangene Werte bleiben bei Ausfall sichtbar.
* Polling pausiert in Hintergrund-Tabs und fällt bei Fehlern auf bis zu 30 s
  zurück statt alle 2 s weiterzufragen.
* Rendering ausschließlich über `createElement`/`textContent`; kein `innerHTML`.

### Server

* `/api/state` liefert zusätzlich `verified_ammo`, `verified_food`,
  `verified_destroyed` und `verified_reopened` je Spieler. Rein additiv —
  ältere Clients ignorieren die Felder.

### Tests

* Neu: `tests/test_ui_design.py` (Designsystem, Aggregation, Tk-Smoke-Test über
  alle sechs Seiten, Validierung, Geheimnis-Maskierung, Fenstergrößen).
* Neu: `tests/test_web_dashboard.py` (keine externen Ressourcen, Icon-Integrität,
  kein `innerHTML`, Token-Handhabung, Polling-Grenzen, Security-Header,
  additive Serverfelder).
* Neu: Regression, die die Update-Dateiliste festnagelt, damit bereits
  installierte Clients weiter automatisch aktualisieren können.
* Bestehende Release-Tests lesen die Version jetzt aus `VERSION`.
