# Sourced by run.sh and test.sh. Creates .venv on first use and reinstalls
# whenever requirements.txt changes. Sets $PYTHON to the venv interpreter.
VENV="${VENV:-.venv}"
REQ_HASH="$(cksum requirements.txt | awk '{print $1}')"

if [ ! -x "$VENV/bin/python" ] || [ "$(cat "$VENV/.req-hash" 2>/dev/null)" != "$REQ_HASH" ]; then
  echo "setting up $VENV ..." >&2
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r requirements.txt
  echo "$REQ_HASH" > "$VENV/.req-hash"
fi

PYTHON="$VENV/bin/python"
