#!/usr/bin/env bash
# Run pakka on http://localhost:8000 from a fresh clone. No keys needed for the demo.
#
#   ./run_local.sh            # install (first time) and start
#   PORT=8080 ./run_local.sh  # another port
#
# Live agent for typed jobs: put PAKKA_MODEL=google:gemini-3.6-flash and GOOGLE_API_KEY=… in pakka.env (gitignored).
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for candidate in python3.12 python3.13 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    PY="$candidate"; break
  fi
done
if [ -z "$PY" ]; then
  echo "pakka needs Python 3.12+. On a Mac: brew install python@3.12" >&2
  exit 1
fi

if [ ! -x .venv/bin/uvicorn ]; then
  echo "» creating .venv with $PY and installing pakka"
  "$PY" -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -e ".[dev]"
fi

PORT="${PORT:-8000}"
URL="http://localhost:$PORT"
echo "» pakka on $URL  (Ctrl-C to stop)"
if [ -f pakka.env ] || [ -f .env ]; then echo "» keys: reading pakka.env / .env"; else echo "» no pakka.env: demo mode, replay agent only"; fi
( sleep 2; command -v open >/dev/null 2>&1 && open "$URL" || command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL" || true ) &
exec .venv/bin/uvicorn pakka.app:fastapi_app --port "$PORT"
