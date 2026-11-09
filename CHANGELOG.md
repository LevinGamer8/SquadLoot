# Changelog

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
