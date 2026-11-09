#!/bin/sh
# Installs the local-only app and dedicated internal nginx. Tunnel is configured later.
set -eu
cd "$(dirname "$0")"
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo 'Docker Engine / Docker Compose Plugin nicht gefunden.' >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3 wird nur auf dem Pi fuer die Token-Erzeugung benoetigt.' >&2
  exit 1
fi
if [ ! -f .env ]; then
  umask 077
  token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')
  printf 'SQUAD_TOKEN=%s\nCF_TUNNEL_TOKEN=HIER_EINTRAGEN\n' "$token" > .env
  echo 'Neuer zufaelliger Squad-Token in .env erzeugt (wird nicht ausgegeben).'
else
  echo 'Bestehende .env wird unveraendert verwendet.'
fi
chmod 600 .env
squad_token=$(sed -n 's/^SQUAD_TOKEN=//p' .env | head -n 1)
if [ "${#squad_token}" -lt 24 ] || [ "${squad_token#GENERIERT}" != "$squad_token" ]; then
  echo 'SQUAD_TOKEN fehlt oder ist zu kurz. Pruefe .env.' >&2
  exit 1
fi
docker compose up -d --build squadloot squadloot-nginx
printf '\nLokaler App-Test (ohne Freigaben):\n'
docker compose exec -T squadloot python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=5).read().decode())"
printf '\nInterner Nginx-Test:\n'
docker compose exec -T squadloot-nginx wget -qO- http://127.0.0.1:8080/health
printf '\n\nDanach Cloudflare-Tunnel-Token in .env eintragen und PI_TUNNEL_STARTEN.sh aufrufen.\n'
