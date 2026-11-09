#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo '.env fehlt. Zuerst PI_INSTALLIEREN.sh ausfuehren.' >&2
  exit 1
fi
token=$(sed -n 's/^CF_TUNNEL_TOKEN=//p' .env | head -n 1)
if [ "${#token}" -lt 60 ] || [ "$token" = 'HIER_EINTRAGEN' ]; then
  echo 'CF_TUNNEL_TOKEN fehlt. In der Cloudflare Tunnel-Konfiguration den eyJ... Token kopieren und in .env setzen.' >&2
  exit 1
fi
chmod 600 .env
docker compose -f compose.yaml -f compose.tunnel.yaml up -d --build
printf '\nStatus:\n'
docker compose -f compose.yaml -f compose.tunnel.yaml ps
printf '\nTunnel-Logs (ohne Token):\n'
docker compose -f compose.yaml -f compose.tunnel.yaml logs --tail=20 cloudflared
printf '\nDie Cloudflare-Route muss http://squadloot-nginx:8080 als Service URL haben.\n'
