SquadLoot 1.1.0 - Client mit Auto-Updater
========================================
1. ZIP vollstaendig nach C:\Tools\SquadLoot entpacken. Bei einem Update die
   vorhandenen Dateien ueberschreiben; deine Einstellungen bleiben in
   %APPDATA%\SquadLootClient\config.json erhalten.
2. Python 3.11+ installieren (mit tkinter); Original-ChestCounter behalten.
3. STARTEN.cmd doppelklicken.
4. Unter 'Verbindung' Server-URL, Squad-Token und bei Cloudflare Access die
   persoenlichen CF Access Zugangsdaten angeben.
5. Unter 'Uebersicht' Live-Zahlen anschauen, Replay-Auswertung starten.
6. Unter 'Updates' ist die automatische Update-Pruefung standardmaessig aktiv.
   Der Client fragt beim Start und ca. alle 20 Minuten am privaten Pi-Server
   nach der neuesten Version. Downloads werden geprueft und beim naechsten
   Start installiert. Das Spiel wird nicht unterbrochen.
7. AUSWERTEN.cmd ist der einmalige Replay-Abgleich ohne gestartete GUI.

WICHTIG: Beim ersten Wechsel vom alten Client auf diese neue Version muss
jeder einmal manuell die neue ZIP entpacken. Danach kommen Updates automatisch.
Der Serverbetreiber veroeffentlicht zukuenftige Client-ZIPs auf seinem Pi.

Sicherheit: Die Zugangsdaten werden im eigenen Windows-Nutzerprofil gespeichert.
Updates stammen ausschliesslich von der konfigurieren HTTPS-Serveradresse und
werden ueber Cloudflare Access + Squad-Token bezogen und mit SHA-256 geprueft.
SHA-256 beweist Integritaet, nicht die Vertrauenswuerdigkeit eines kompromittierten
Servers. Der Pi-Admin soll Updatepakete nur aus vertrauenswuerdigen Quellen
veroeffentlichen. Keine Screenshots und keine Replay-Rohdaten werden hochgeladen.

Fehler bei Updates: %APPDATA%\SquadLootClient\updater.log


SQUADLOOT 1.3.0 - LIVE & FREUNDE
==================================

Was live funktioniert
--------------------
1. Manuelle +Truhe Zaehler werden nach wenigen Sekunden an alle gesendet.
2. Optional unter 'Live-Erkennung': Eine selbst erstellte PNG-Vorlage der
   'Durchsuchen'-Aufforderung laden, Interaktionstaste (meist E) einstellen,
   'Erkennung starten' klicken. Nur aktives Fortnite wird aufgenommen.
3. Die automatische Erkennung ist ein VORLAEUFIGER SCHAETZWERT: Wegdrehen,
   FPS/Skalierung, andere Suchaktionen und verpasste Tastendruecke koennen
   Fehlzaehlungen verursachen. Es gibt KEINE garantierte 100% Live-Erkennung.
4. Nach Matchende gilt weiterhin die ChestCounter-Replay-Auswertung.

Performance: maximal ca. 2.5 Screenshots/Sekunde aus einem kleinen mittleren
Bildschirmbereich, nur wenn Fortnite im Vordergrund ist. Die Erkennung ist
standardmaessig AUS und benoetigt beim Einschalten SETUP_VISION.cmd.
Keine Bilder/keine Tastendruecke werden zum Pi uebertragen, nur Zaehler.

Fuer Freunde: Die Datei aus dem offiziellen GitHub Releases herunterladen,
Python 3.11+ und den Original ChestCounter installieren, Fortnite Replays
aktivieren, STARTEN.cmd starten. Jeder nutzt seinen eigenen CF Access
Service Token und Fortnite-Namen; gemeinsamer Squad-Token ist identisch.
Die Zugangsdaten NICHT auf GitHub hochladen und nicht in Gruppen-Chats posten.

GitHub: https://github.com/LevinGamer8/SquadLoot/releases/latest

Updates: Nach dieser Version aktualisiert der Pi-Server ueber GitHub Releases
sowohl sich selbst als auch den client.zip-Feed fuer die bestehenden PCs.
Die PCs installieren die geprueften Clientupdates beim naechsten App-Start.


SQUADLOOT 1.4.0 - NEUE OBERFLAECHE
==================================

Die Oberflaeche wurde komplett neu gestaltet. Die Funktionen sind dieselben,
nur anders sortiert. Die Seitenleiste hat jetzt sechs Bereiche:

1. Dashboard        Verbindung, aktuelle Runde, deine und die Squad-Truhen,
                    bestaetigte Matches, Munition, Obst, zerstoerte Truhen,
                    Belohnungen und die Squad-Uebersicht mit Beitragsbalken.
2. Live-Tracking    Manuelle Zaehler, Beta-Bildschirmerkennung, Erkennungs-
                    qualitaet und das zuletzt erkannte Ereignis.
3. Match-Historie   Alle vom Replay bestaetigten Runden.
4. Squad            Beitrag je Spieler und Statistik je Epic-Account.
5. Einstellungen    Frueher 'Verbindung'. Server, Cloudflare Access,
                    Epic-Account, Replay-Ordner, ChestCounter, Live-Erkennung
                    und Updates in getrennten Abschnitten. Token und Secret
                    bleiben maskiert; das Augensymbol zeigt sie kurz an.
6. Updates          Installierte und verfuegbare Version, letzte Pruefung,
                    Status und Fortschritt.

Farbbedeutung, ueberall gleich:
  Cyan   = live uebertragen, noch nicht bestaetigt
  Gruen  = vom Replay bestaetigt (verbindlich)
  Gelb   = Schaetzung oder Beta-Funktion
  Rot    = Fehler oder zerstoerte Truhe

Einstellungen und Datenbank bleiben unveraendert; es ist keine Neueinrichtung
noetig. Das Update kommt wie gewohnt automatisch vom Pi.


SQUADLOOT 1.5.0 - HUD + VISUELLER LIVE-TEST
===========================================

1. Kompaktes In-Game-HUD von Claude (188 x 60 px bei 100 % DPI), standardmaessig
   AUS, optional erweiterbar; Einstellungen -> In-Game-HUD.
2. Optional: Fortnite Visual Chest Counter v0.2.3 separat starten,
   dort Screen 1/2 und Start counting waehlen.
3. In SquadLoot -> Live-Tracking -> Visueller Kistenzaehler: Den
   obs_output-Ordner der externen Anwendung waehlen, Live-Test starten.
4. SquadLoot liest certain_chests.txt und approximate_chests.txt, zaehlt nur
   neue APPROX-Aenderungen ab Teststart, nie die alten Gesamtsummen.
5. CERTAIN steckt bereits in APPROX und wird NICHT addiert. Neue Runde
   setzt die Baseline zurueck. Replaydaten bleiben verbindlich.
6. Der externe Zaehler erkennt derzeit vor allem englische/portugiesische
   XP-Texte, DEUTSCH ist noch nicht unterstuetzt. Fuer den Test Englisch nutzen.
7. Alte PNG-basierte SquadLoot-Erkennung kann alternativ weiter verwendet
   werden. Beide Scanner laufen nie parallel.
8. Ausfuehrliche Anleitung auf GitHub unter docs/VISUAL-LIVE-TEST.md.

Der Test startet nie ungefragt und fuegt dem Windows-Paket keine weiteren
Dateien hinzu. Die exakte Fortnite-Erkennung und Anti-Cheat-Vertraeglichkeit
sind nicht offiziell garantiert. Bitte zuerst mit Video testen.


SQUADLOOT 1.5.1 - HUD-SICHTBARKEITSFIX
====================================

Wenn das Mini-HUD trotz aktivem Schalter unsichtbar war, wurde der
Windows-Tk-Fensterpfad ueberarbeitet. Das HUD oeffnet sich nun auf dem
Hauptmonitor, und Vorschau kann das Fenster nach vorne holen.
Unter Einstellungen -> In-Game-HUD -> HUD pruefen erscheint ein
Fensterdiagnose-Dialog mit sichtbarem Status und Koordinaten (ohne Tokens).
Auf einigen Systemen bleiben die Ecken voruebergehend rechteckig, damit
das kleine HUD nicht durch transparente Fensterschichten verschwindet.
Wenn es im Spiel nicht sichtbar ist, Windowed Fullscreen testen.


SQUADLOOT 1.5.2 - NUR AUTOMATISCHE KISTENZAEHLUNG
=================================================

Manuelle Kiste+/Kiste-, Zerstört+, Munition+ und Obstbox+ wurden aus
Dashboard und Live-Tracking entfernt. Der optionale Visual Chest Counter
(v1.5.0) und das kleine HUD (v1.5.1) bleiben erhalten. Die Live-Zaehler
zeigen automatisch erkannte Werte und werden nach dem Match vom Replay
bestaetigt. Neue Runde, Replay-Auswertung und Zuruecksetzen der
vorlaeufigen Live-Schaetzung sind weiterhin moeglich.
Historische Daten und alte API-Felder bleiben fuer aeltere Clients
kompatibel. Das Update erfolgt weiterhin ueber den Raspberry Pi.


SQUADLOOT 1.5.3 - DEUTSCHE XP-POPUP-KALIBRIERUNG (BETA)
======================================================

Fortnite darf wieder auf Deutsch gestellt werden. Der externe Visual
Chest Counter v0.2.3 muss fuer deutsche Truhen aber erst eine echte
XP-Wortvorlage bekommen. Unter Live-Tracking -> Deutsch kalibrieren
einen Screenshot von einer deutschen Truhen-XP-Einblendung auswaehlen,
nur das violette Truhen-WORT markieren und Muster installieren.
Der externe Counter muss beendet sein. Anschliessend neu starten und
Settings -> Game language -> Deutsch (SquadLoot Beta) waehlen.
Die alte englische Erkennung bleibt unveraendert. Der Patch sichert
die Originaldateien des externen Programms und ist rueckgaengig machbar.
Nach Updates des externen Counters muss die Kompatibilitaet neu geprueft
werden. Der deutsche Modus ist noch nicht mit echten Matches validiert.
Mehr in docs/VISUAL-LIVE-TEST.md auf GitHub.


SQUADLOOT 1.5.4 – EIN KNOPF FÜR LIVE + AUTOMATISCHE REPLAYS
==========================================================
Keine fremde Anwendung und keine ChestCounter.exe manuell installieren:
SquadLoot lädt bei Bedarf im Hintergrund die unveränderten, SHA-256-
geprüften Analyse-Laufzeiten der beiden MIT-Projekte in
%LOCALAPPDATA%\SquadLoot\engines.
Replay (passiv): ca. 38 MB beim ersten Analysevorgang;
Live: ca. 156 MB beim ersten Klick auf "Live-Test starten".
Diese Komponenten sind KEIN Teil des 4-MB-SquadLoot-Updatepakets.

Die Replay-Analyse läuft automatisch, auch wenn Live ausgeschaltet ist.
Unter Live-Tracking gibt es nur noch Zähler und Start/Stopp.
Die alte PNG/Tasten-Erkennung, OBS-Ordnerauswahl und der manuelle
ChestCounter.exe-Pfad werden nicht mehr als Optionen angezeigt.
Alle Zugangsdaten und bereits ausgewerteten Replays bleiben erhalten.

Einschränkung: Eine unter v1.5.3 kalibrierte deutsche Popup-Vorlage
wird übernommen. Neue deutsche Bildvorlagen sind noch nicht validiert;
die Replay-Auswertung arbeitet unabhängig von der Fortnite-Sprache.
Bei Problemen: docs/VISUAL-LIVE-TEST.md auf GitHub.
