#!/bin/sh
# Run after copying the new server files into /opt/squadloot.
set -eu
cd "$(dirname "$0")"
if [ ! -f .env ]; then echo 'Bestehende .env nicht gefunden!' >&2;exit 1;fi
mkdir -p updates
# Explicitly keep existing database, env and Cloudflare tunnel configuration.
docker compose -f compose.yaml -f compose.tunnel.yaml up -d --build squadloot squadloot-nginx cloudflared
printf '\nStatus:\n'
docker compose -f compose.yaml -f compose.tunnel.yaml ps
printf '\nAktuelle Update-Version:\n'
cat updates/latest.json 2>/dev/null || true
