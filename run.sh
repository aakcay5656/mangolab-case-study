#!/usr/bin/env bash
# Starts the service on $PORT (default 8080). The upstream base URL comes from
# $FX_UPSTREAM_BASE; nothing here knows the real host.
set -euo pipefail
cd "$(dirname "$0")"
source ./_venv.sh

exec "$PYTHON" -m uvicorn fxtool.main:app \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8080}"
