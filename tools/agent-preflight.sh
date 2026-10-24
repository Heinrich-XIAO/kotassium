#!/bin/sh
# Portable pre-ship checks for agents. No external services or optional UI
# system packages are required; the MPRIS unittest self-skips without a bus.
set -eu
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-python3}

"$PYTHON" -m unittest discover -s tests -v
"$PYTHON" -m py_compile desktop.py mpris_linux.py notify.py serve_web.py spotify_get.py titlebar_macos.py updater.py

if command -v node >/dev/null 2>&1; then
    "$PYTHON" - <<'PY' | node --check
from pathlib import Path
page = Path("web/index.html").read_text(encoding="utf-8")
print(page.rsplit("<script>", 1)[1].split("</script>", 1)[0])
PY
else
    echo "node not installed; skipped JavaScript syntax check" >&2
fi

echo "Preflight passed."
