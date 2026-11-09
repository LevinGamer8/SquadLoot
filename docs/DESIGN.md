# SquadLoot Design System (ab 1.4.0)

Ein gemeinsames visuelles System für den Windows-Client (Tkinter) und das
Raspberry-Pi-Dashboard (HTML). Beide Oberflächen verwenden dieselben Farben,
Radien, Abstände und dieselbe Typo-Skala, damit SquadLoot überall gleich wirkt.

## 1. Farbtokens

Dunkles Interface mit zurückhaltendem Indigo-/Cyan-Akzent. Die Werte stehen in
`SquadLoot-Windows-Client/app.py` (Klasse `T`) und in `dashboard.html` (`:root`).

| Rolle | Token | Wert |
|---|---|---|
| App-Hintergrund | `BG` / `--bg` | `#080B12` |
| Seitenleiste | `RAIL` / `--rail` | `#0B0F18` |
| Karte | `SURFACE` / `--surface` | `#111724` |
| Karte, verschachtelt | `SURFACE_2` / `--surface-2` | `#161E2E` |
| Eingabe / Chip | `SURFACE_3` / `--surface-3` | `#1C2638` |
| Eingabefeld | `FIELD` / `--field` | `#0C111B` |
| Trennlinie | `LINE` / `--line` | `#202B3D` |
| Text | `TEXT` / `--text` | `#E9EEF8` |
| Text, sekundär | `DIM` / `--dim` | `#97A3B8` |
| Text, tertiär | `MUTE` / `--mute` | `#64718A` |
| Primärakzent | `ACCENT` / `--accent` | `#5B78F0` |
| Akzent hell | `ACCENT_HI` / `--accent-hi` | `#7A92FF` |
| Live / Info | `CYAN` / `--cyan` | `#38BDF8` |
| Bestätigt | `OK` / `--ok` | `#34D399` |
| Schätzung / Beta | `WARN` / `--warn` | `#F0B429` |
| Fehler | `BAD` / `--bad` | `#F2787C` |
| Belohnung | `VIOLET` / `--violet` | `#A78BFA` |

**Farbsemantik, konsequent in beiden Clients:**

* **Cyan** = live übertragen, noch nicht bestätigt
* **Grün** = vom Replay bestätigt, verbindlich
* **Gelb** = Schätzung oder Beta-Funktion
* **Rot** = Fehler oder zerstörte Truhe
* **Violett** = Belohnungen / Loot
* **Indigo** = Primäraktion und Markenfarbe

## 2. Radien, Abstände, Typografie

* Radien: Karte 14 px, Bedienelement 10 px, Kachel 11 px, Chip voll gerundet.
* Abstandsskala: 4 / 8 / 12 / 16 / 20 / 24 / 32 px — keine freien Zwischenwerte.
* Schrift: Segoe UI (Windows) bzw. Segoe UI → system-ui (Web).
  Stufen in Pixeln: 28/26 Display, 20–21 Seitentitel, 15 Abschnitt, 13 Fließtext,
  11–12 sekundär, 10 Großbuchstaben-Label mit erweiterter Laufweite.
* Zahlen stehen immer in Tabellenziffern, damit Zähler beim Hochzählen nicht springen.

## 3. Komponenten

Windows (`app.py`) und Web (`dashboard.html`) bilden dieselben Bausteine ab:

| Baustein | Windows | Web |
|---|---|---|
| Karte | `Card` | `.card` |
| Aktion | `Button` (primary/secondary/ghost/danger/success) | `.btn`, `.btn.primary`, `.btn.ghost` |
| Icon-Aktion | `IconButton` | `.btn` mit nur einem `<svg>` |
| Statuschip | `Pill` | `.pill` + Tonvarianten |
| Fortschritt | `Meter` | `.meter` |
| Schalter | `Toggle` | – |
| Kennzahl | `StatCard` | `.stat` |
| Kompaktkennzahl | `MiniStat` | `.tile` |
| Spielerzeile | `Gui.member_row` | `.player` |
| Eingabefeld | `Field` | `input` |
| Navigation | `NavItem` | `.nav button` |
| Leerer Zustand | `Gui.empty_state` | `emptyState()` |

## 4. Icons

Keine Emojis in der Oberfläche. Beide Clients benutzen dasselbe Linien-Icon-Set
in einer 24×24-Box mit runden Enden:

* **Windows:** `ICONS` in `app.py` beschreibt jedes Icon als Liste aus Polylinien,
  Ellipsen, Punkten und Bögen; `draw_icon()` zeichnet sie auf ein `tk.Canvas`.
  Dadurch braucht der Client keine Bilddateien und bleibt bei jeder
  Anzeigeskalierung scharf. Unbekannte Namen landen in `UNKNOWN_ICONS` und
  lassen den UI-Smoke-Test fehlschlagen.
* **Web:** ein Inline-`<symbol>`-Sprite am Seitenanfang. Kein CDN, keine
  externen Dateien — die strenge CSP (`default-src 'self'`) bleibt unverändert.

Behälter haben eigene Symbole: Standardtruhe, seltene Truhe, vergrabener Schatz,
Munitionskiste, Obstkiste, zerstörte Truhe und erneut gefüllte Truhe.

## 5. Anzeigeskalierung

Der Windows-Client meldet sich per `SetProcessDpiAwareness` als DPI-fähig an,
liest die System-DPI noch vor dem ersten Widget und leitet daraus `SCALE` ab.
Jede Pixelangabe läuft durch `px()`, jede Schriftgröße durch `font()` mit
Pixelmaß. Dadurch skalieren Layout und Typo gemeinsam auf 125 %, 150 % und
200 %. `SQUADLOOT_UI_SCALE` erzwingt einen Wert für Tests.

## 6. Bewusste Entscheidungen

* **Kein CustomTkinter, kein Electron.** Das Designsystem ist mit `tk.Canvas`
  gebaut. Das hält die Installation (`SQUADLOOT_INSTALLIEREN.ps1`), den
  ZIP-Auto-Updater, Startzeit und Speicherbedarf unverändert — wichtig, weil
  SquadLoot neben Fortnite läuft.
* **Eine einzige `app.py`.** Der Updater prüft das Paket gegen eine feste
  Dateiliste (`update_manager.ALLOWED_FILES`). Jede neue Datei würde von bereits
  installierten Clients abgelehnt. Das Designsystem lebt deshalb als klar
  getrennter Abschnitt in `app.py`, nicht in neuen Modulen.
* **Eine einzige `dashboard.html`.** Das Pi-Release-Paket erlaubt nur
  `app/dashboard.html`; CSS, JavaScript und Icons sind deshalb inline.
* **Kein `innerHTML` für Serverdaten.** Das Dashboard baut jede Zeile über
  `createElement`/`textContent`.
