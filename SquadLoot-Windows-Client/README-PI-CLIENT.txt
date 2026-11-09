SquadLoot fuer Cloudflare Tunnel + Raspberry Pi

1. Python 3.11+ fuer Windows installieren, py -3 --version pruefen.
2. Replays in Fortnite aktivieren.
3. Original ChestCounter.exe von https://github.com/LED-N/Fortnite-ChestCounter/releases/latest beziehen, starten und konfigurieren.
4. STARTEN.cmd doppelklicken.
5. Verbindung & Accounts: https://squadloot.megacraft.de (nur wenn du diesen Hostnamen in Cloudflare angelegt hast),
   Squad-Token aus /opt/squadloot/.env, eigenen Fortnite-Anzeigenamen.
6. Falls Cloudflare Access auf der Domain aktiv: zusaetzlich CF Access Client-ID und Client-Secret eintragen,
   die vom Pi-Admin fuer DICH erzeugt wurden. Sonst BEIDE Felder leer lassen.
7. Speichern & verbinden.
8. ChestCounter und SquadLoot waehrend dem Match fuer automatische Nach-Match-Synchronisation laufen lassen.
   Fuer NUR nachtraegliche Analyse: erst Originalprogramm auswerten, dann AUSWERTEN.cmd.
9. Experimentelle Bildschirmerkennung nur ueber SETUP_VISION.cmd. Sie ist nicht praezise und NICHT fuer
   automatische echte Kistenerkennung verifiziert.

WICHTIG: Keine Windows-PCs muessen als Server fungieren; keine Ports freigeben.
Zugaenge nicht oeffentlich teilen, nicht in Screenshots posten. Keine Epic-Passwoerter angeben.
