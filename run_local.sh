#!/usr/bin/env bash
# Convenience launcher for the local Procurement Agent POC.
# This starts the FastAPI service only. The MCP server and the Chainlit UI
# are started in their own terminals (see README).
set -euo pipefail

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a && source .env && set +a
fi

exec uvicorn app.main:app --host 127.0.0.1 --port "${API_PORT:-9000}" --reload
