#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -f .env ] && grep -q '^CF_TUNNEL_TOKEN=eyJ' .env; then
  docker compose -f compose.yaml -f compose.tunnel.yaml ps
else
  docker compose ps
fi
printf '\nApp-Health: '
docker compose exec -T squadloot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=5).read().decode())"
