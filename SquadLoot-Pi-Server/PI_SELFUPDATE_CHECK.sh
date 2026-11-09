#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 server_selfupdate.py "$@"
