#!/usr/bin/env bash
# Build a Chrome Web Store zip of Ask Z-Bot (no node/npm required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="$(python3 -c "import json; print(json.load(open('manifest.json'))['version'])")"
OUT_DIR="$ROOT/dist"
mkdir -p "$OUT_DIR"
ZIP="$OUT_DIR/ask-zbot-${VERSION}.zip"
rm -f "$ZIP"

# Exclude packaging artifacts and local-only notes that are not needed at runtime.
zip -r "$ZIP" . \
  -x './dist/*' \
  -x './scripts/*' \
  -x './screenshots/*' \
  -x './.DS_Store' \
  -x './**/.DS_Store' \
  -x './store-listing.md' \
  -x './PUBLISH_CHECKLIST.md'

echo "Wrote $ZIP"
unzip -l "$ZIP" | head -40
