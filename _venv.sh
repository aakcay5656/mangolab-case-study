# Sourced by run.sh and test.sh. Sets $PYTHON to an interpreter that has the
# dependencies, preferring one that is already there over one it has to build:
# creating a venv needs a package index, and the review may well be offline.
VENV="${VENV:-.venv}"
REQ_HASH="$(cksum requirements.txt | awk '{print $1}')"
DEPS="import fastapi, httpx, pytest, uvicorn"

if [ -x "$VENV/bin/python" ] && [ "$(cat "$VENV/.req-hash" 2>/dev/null)" = "$REQ_HASH" ]; then
  PYTHON="$VENV/bin/python"
elif python3 -c "$DEPS" >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "setting up $VENV ..." >&2
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r requirements.txt
  echo "$REQ_HASH" > "$VENV/.req-hash"
  PYTHON="$VENV/bin/python"
fi
