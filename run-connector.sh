#!/usr/bin/env bash
# Claude connector (remote MCP + OAuth) as its own process, listening on localhost only.
# Expose it to the internet with Tailscale Funnel (see docs/CONNECTOR.md):
#   tailscale funnel --bg --https=8443 http://127.0.0.1:8001
# The main app (./run.sh) stays private on your tailnet.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${CONNECTOR_PORT:-8001}"

if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi
cd backend
exec .venv/bin/uvicorn app.connector:app --host 127.0.0.1 --port "$PORT"
