#!/bin/sh
set -eu
BASE="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SERVICE=/etc/systemd/system/squadloot-selfupdate.service
TIMER=/etc/systemd/system/squadloot-selfupdate.timer
CONF="$BASE/server-update.conf"
EXAMPLE="$BASE/server-update.conf.example"

if [ ! -f "$CONF" ]; then
  cp "$EXAMPLE" "$CONF"
  echo "server-update.conf wurde angelegt: $CONF"
  echo "Bitte MANIFEST_URL eintragen und danach dieses Skript erneut ausfuehren oder den Timer starten."
fi
INTERVAL=$(awk -F= '/^CHECK_INTERVAL=/{print $2}' "$CONF" | tr -d '[:space:]')
[ -n "$INTERVAL" ] || INTERVAL="6h"
cat > "$SERVICE" <<EOF
[Unit]
Description=SquadLoot Raspberry Pi Self-Update
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$BASE
ExecStart=/usr/bin/python3 $BASE/server_selfupdate.py --quiet
EOF

cat > "$TIMER" <<EOF
[Unit]
Description=Check for SquadLoot Pi updates periodically

[Timer]
OnBootSec=15min
OnUnitActiveSec=$INTERVAL
Persistent=true
Unit=squadloot-selfupdate.service

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now squadloot-selfupdate.timer
systemctl list-timers squadloot-selfupdate.timer --all || true
echo "Fertig. Aktuelle Konfiguration: $CONF"
