#!/bin/sh
set -eu
BASE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
cat > /etc/systemd/system/squadloot-backup.service <<EOF
[Unit]
Description=SquadLoot SQLite backup
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/bin/sh $BASE/PI_BACKUP.sh
EOF
cat > /etc/systemd/system/squadloot-backup.timer <<'EOF'
[Unit]
Description=Daily SquadLoot SQLite backup

[Timer]
OnCalendar=*-*-* 03:20:00
Persistent=true
RandomizedDelaySec=10min
Unit=squadloot-backup.service

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now squadloot-backup.timer
printf 'Taegliches Backup ist aktiviert. Einmal direkt testen mit: sudo sh %s/PI_BACKUP.sh\n' "$BASE"
