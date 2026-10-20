#!/bin/sh
# Build dist/Kotassium.app. Run this ON macOS (py2app cannot cross-compile).
set -eu
cd "$(dirname "$0")"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This must run on macOS." >&2
    exit 1
fi

VERSION="${KOTASSIUM_VERSION:-2.0.0}"
YTDLP_URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"

./setup.sh
desktop-venv/bin/python -m pip install --quiet py2app

# Ship yt-dlp inside the app so a DMG install needs no Homebrew for downloads.
mkdir -p vendor
if [ ! -x vendor/yt-dlp ]; then
    echo "fetching yt-dlp..."
    curl -fL --retry 3 -o vendor/yt-dlp "$YTDLP_URL"
    chmod +x vendor/yt-dlp
fi

rm -rf build dist
KOTASSIUM_VERSION="$VERSION" desktop-venv/bin/python setup-macos.py py2app

# The server looks for BASE/bin/yt-dlp first (BASE is Contents/Resources).
mkdir -p dist/Kotassium.app/Contents/Resources/bin
cp vendor/yt-dlp dist/Kotassium.app/Contents/Resources/bin/yt-dlp
chmod +x dist/Kotassium.app/Contents/Resources/bin/yt-dlp

# Ad-hoc signature: enough for local use, not notarized (see README).
codesign --force --deep --sign - dist/Kotassium.app

echo
echo "built: $(pwd)/dist/Kotassium.app (version $VERSION)"
echo "make a disk image with: ./make-dmg.sh"
echo "install locally with: ./install-macos.sh"
