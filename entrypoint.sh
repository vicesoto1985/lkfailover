#!/bin/sh
set -eu

mkdir -p /var/cache/failover

python3 /app/failover_watcher.py --once

nginx -g "daemon off;" &
NGINX_PID="$!"

python3 /app/failover_watcher.py --watch &
WATCHER_PID="$!"

_term() {
  echo "[entrypoint] Deteniendo servicios..."
  kill "$WATCHER_PID" 2>/dev/null || true
  nginx -s quit 2>/dev/null || true
  wait "$NGINX_PID" 2>/dev/null || true
  exit 0
}

trap _term TERM INT

while true; do
  if ! kill -0 "$NGINX_PID" 2>/dev/null; then
    echo "[entrypoint] Nginx se detuvo."
    kill "$WATCHER_PID" 2>/dev/null || true
    exit 1
  fi

  if ! kill -0 "$WATCHER_PID" 2>/dev/null; then
    echo "[entrypoint] Watcher de failover se detuvo."
    nginx -s quit 2>/dev/null || true
    exit 1
  fi

  sleep 2
done
