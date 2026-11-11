#!/usr/bin/env bash
# Build the frontend (if needed) and serve the whole app from one process.
#   ./run.sh            -> http://<this-computer>:8000
#   PORT=9000 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi
if [ ! -d frontend/node_modules ]; then (cd frontend && npm ci); fi
if [ ! -f frontend/out/index.html ] || [ "${REBUILD:-0}" = "1" ]; then (cd frontend && npm run build); fi

cd backend
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" --proxy-headers
