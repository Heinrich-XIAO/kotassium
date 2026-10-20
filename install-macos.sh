#!/bin/sh
# Install Kotassium.app into /Applications. Run this ON macOS.
#
# Two paths:
#   1. py2app bundle (default) - real .app with its own icon/identity.
#   2. --wrapper: a tiny AppleScript app that runs desktop.py from this folder.
#      Use it if py2app fails on your machine.
set -eu
cd "$(dirname "$0")"
ROOT=$(pwd)

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This must run on macOS." >&2
    exit 1
fi

if [ "${1:-}" = "--wrapper" ]; then
    ./setup.sh
    mkdir -p "$HOME/Applications"
    APP="$HOME/Applications/Kotassium.app"
    rm -rf "$APP"
    osacompile -o "$APP" -e "do shell script \"cd '$ROOT' && exec '$ROOT/desktop-venv/bin/python' '$ROOT/desktop.py' >> /tmp/kotassium.log 2>&1\""
    echo "installed $APP (wrapper mode; logs in /tmp/kotassium.log)"
    exit 0
fi

./build-macos.sh
rm -rf /Applications/Kotassium.app
cp -R dist/Kotassium.app /Applications/
echo "installed /Applications/Kotassium.app"
echo "First launch: right-click > Open (the app is unsigned)."
