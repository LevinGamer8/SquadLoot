#!/bin/sh
# Publish future Windows client ZIPs to the Pi for automatic installation by friends.
set -eu
cd "$(dirname "$0")"
if [ "$#" -lt 1 ]; then echo 'Aufruf: sudo sh PI_CLIENT_RELEASE.sh /pfad/Client-Release.zip [Notizen]';exit 1;fi
python3 update_publish.py "$@"
