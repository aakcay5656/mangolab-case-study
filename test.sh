#!/usr/bin/env bash
# Runs the tests. They never touch the network: the upstream is faked in-process,
# so this passes with FX_UPSTREAM_BASE pointing at a closed port (the default here).
set -euo pipefail
cd "$(dirname "$0")"
source ./_venv.sh

export FX_UPSTREAM_BASE="${FX_UPSTREAM_BASE:-http://127.0.0.1:9}"
exec "$PYTHON" -m pytest -q "$@"
