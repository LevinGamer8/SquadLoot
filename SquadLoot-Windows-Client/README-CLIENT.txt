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
