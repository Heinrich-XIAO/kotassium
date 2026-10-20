#!/bin/sh
# Build dist/Kotassium.app. Run this ON macOS (py2app cannot cross-compile).
set -eu
cd "$(dirname "$0")"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This must run on macOS." >&2
    exit 1
fi

./setup.sh
desktop-venv/bin/python -m pip install --quiet py2app
rm -rf build dist
desktop-venv/bin/python setup-macos.py py2app
echo
echo "built: $(pwd)/dist/Kotassium.app"
echo "install with: ./install-macos.sh"
