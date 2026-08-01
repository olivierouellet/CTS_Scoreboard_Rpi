#!/usr/bin/env bash
# Copy the canonical shared panel assets (server static/) into the cloud static
# dir so both operator panels stay byte-identical. Run this after editing
# static/css/panel.css or static/js/panel.js. See the header comments in those
# files for what belongs in the shared layer.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for f in css/panel.css js/panel.js; do
    cp "$ROOT/static/$f" "$ROOT/cloud/static/$f"
    echo "synced static/$f -> cloud/static/$f"
done
