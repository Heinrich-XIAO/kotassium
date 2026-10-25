#!/bin/sh
# Portable pre-ship checks for agents. No external services or optional UI
# system packages are required; the MPRIS unittest self-skips without a bus.
set -eu
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-python3}

"$PYTHON" -m unittest discover -s tests -v
"$PYTHON" -m py_compile desktop.py mpris_linux.py notify.py serve_web.py spotify_get.py titlebar_macos.py updater.py

if command -v npm >/dev/null 2>&1; then
    npm ci
    npm run build
    node --check web/app.js
else
    echo "npm not installed; skipped React build and JavaScript syntax check" >&2
fi

echo "Preflight passed."
