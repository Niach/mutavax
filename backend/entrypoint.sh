#!/usr/bin/env bash
# Entrypoint for the combined cancerstudio image.
#
# Starts the FastAPI backend on loopback (127.0.0.1:8000) and the Next.js
# standalone server on 0.0.0.0:3000. Next.js proxies /backend/* to the loopback
# backend via the rewrite in next.config.ts, so only port 3000 is exposed.
#
# Exits when either process dies so Docker's restart policy can bring the
# whole thing back cleanly. Forwards SIGTERM/SIGINT to both children.

set -euo pipefail

uvicorn app.main:app --host 127.0.0.1 --port 8000 &
backend_pid=$!

cd /app/web
HOSTNAME=0.0.0.0 PORT=3000 node server.js &
frontend_pid=$!

term() {
  kill -TERM "$backend_pid" "$frontend_pid" 2>/dev/null || true
}
trap term TERM INT

wait -n "$backend_pid" "$frontend_pid"
exit_code=$?
term
wait 2>/dev/null || true
exit "$exit_code"
