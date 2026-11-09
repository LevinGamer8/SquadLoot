#!/bin/sh
# Consistent SQLite snapshot of SquadLoot's Docker named volume.
# Root-only backups survive container recreation and server self-updates.
set -eu
umask 077
BASE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
cd "$BASE"
BACKUPS="$BASE/backups"
mkdir -p "$BACKUPS"
chmod 700 "$BACKUPS"

COMPOSE='docker compose -f compose.yaml'
if [ -f compose.tunnel.yaml ]; then
    COMPOSE="$COMPOSE -f compose.tunnel.yaml"
fi
# shellcheck disable=SC2086
CID=$($COMPOSE ps -q squadloot)
if [ -z "$CID" ]; then
    echo 'SquadLoot container not running; no backup made.' >&2
    exit 1
fi
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
IN_CONTAINER="/tmp/squadloot-backup-$$.sqlite3"
TMP="$BACKUPS/.squadloot-$STAMP-$$.tmp"
OUT="$BACKUPS/squadloot-$STAMP.sqlite3"
cleanup() {
    rm -f "$TMP"
    docker exec "$CID" rm -f "$IN_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

docker exec "$CID" python -c '
import sqlite3, sys
src=sqlite3.connect("file:/data/squadloot.sqlite3?mode=ro",uri=True)
dst=sqlite3.connect(sys.argv[1])
try:
    src.backup(dst)
finally:
    dst.close()
    src.close()
' "$IN_CONTAINER"
docker cp "$CID:$IN_CONTAINER" "$TMP"
python3 - "$TMP" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as db:
    result = db.execute('PRAGMA integrity_check').fetchone()[0]
    if result != 'ok':
        raise SystemExit('SQLite backup integrity failed: ' + str(result))
PY
chmod 600 "$TMP"
mv "$TMP" "$OUT"
# Only old backup files are removed, not the active database. Keep 30 days.
find "$BACKUPS" -maxdepth 1 -type f -name 'squadloot-*.sqlite3' -mtime +30 -delete
printf 'Backup erstellt: %s\n' "$OUT"
