#!/usr/bin/env bash
# Serve the Ask Z-Bot UI preview harness in a normal browser tab.
# Usage: ./scripts/preview.sh [port]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-${PORT:-8765}}"
URL="http://127.0.0.1:${PORT}/preview.html"

cd "$ROOT"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use."
  echo "Stop the old preview server so you pick up latest JS/CSS/fonts:"
  echo "  kill \$(lsof -t -iTCP:$PORT -sTCP:LISTEN)"
  echo "Then run ./scripts/preview.sh again."
  echo "Open $URL (hard-refresh: Cmd+Shift+R)"
  if command -v open >/dev/null 2>&1; then
    open "$URL"
  fi
  exit 0
fi

echo "Ask Z-Bot UI preview"
echo "  $URL"
echo "  Stubbed agent (not Load unpacked). Ctrl+C to stop."
echo

if command -v open >/dev/null 2>&1; then
  (sleep 0.4 && open "$URL") &
fi

exec python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$ROOT"
