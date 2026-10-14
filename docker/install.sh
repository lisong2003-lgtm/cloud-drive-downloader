#!/bin/sh
# pan-downloader skill Docker installer: generic NAS/server/local.
set -e
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$DIR"
PAN_WEB_PORT="${PAN_WEB_PORT:-17890}"
port_free() { ! (command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 "$1" >/dev/null 2>&1); }
while ! port_free "$PAN_WEB_PORT"; do PAN_WEB_PORT=$((PAN_WEB_PORT + 1)); done
export PAN_WEB_PORT
command -v docker >/dev/null 2>&1 || { echo '❌ Docker not installed' >&2; exit 1; }
mkdir -p "${PAN_STATE_DIR:-$DIR/state}" "${PAN_DOWNLOAD_DIR:-$DIR/download}"
docker compose up -d --build
IP="${PAN_PUBLIC_HOST:-$(ip route get 1 2>/dev/null | awk '{print $7; exit}' || true)}"
[ -z "$IP" ] && IP="127.0.0.1"
echo "✅ Web UI: http://$IP:$PAN_WEB_PORT/"
echo "✅ API:   http://$IP:$PAN_WEB_PORT/api/status"
echo "Browser extension: set the Web/API URL above."
