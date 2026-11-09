#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -f .env ] && grep -q '^CF_TUNNEL_TOKEN=eyJ' .env; then
  docker compose -f compose.yaml -f compose.tunnel.yaml down
else
  docker compose down
fi
printf 'SquadLoot gestoppt. SQLite-Daten im benannten Docker-Volume bleiben erhalten.\n'
