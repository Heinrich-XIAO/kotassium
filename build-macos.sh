#!/bin/sh
# Build dist/Kotassium.app. Run this ON macOS (py2app cannot cross-compile).
set -eu
cd "$(dirname "$0")"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This must run on macOS." >&2
    exit 1
fi

VERSION="${KOTASSIUM_VERSION:-2.1.0}"
YTDLP_URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"

T0=$(date +%s)
phase() { echo "== $1: $(( $(date +%s) - T0 ))s elapsed"; }

./setup.sh
if command -v npm >/dev/null 2>&1; then
    npm ci
    npm run build
else
    echo "npm is required to build the React player bundle." >&2
    exit 1
fi
phase "venv and the page bundle"

# The venv is cached in CI, so only pay for pip when it is actually missing
# something (a new dependency, or a cold cache).
if ! desktop-venv/bin/python -c 'import py2app, PIL' 2>/dev/null; then
    desktop-venv/bin/python -m pip install --quiet -r requirements-macos-build.txt
fi
./desktop-venv/bin/python tools/normalize-icons.py
./desktop-venv/bin/python tools/make-macos-icon.py
phase "icons"

# Ship yt-dlp inside the app so a PKG install needs no Homebrew for downloads.
mkdir -p vendor
if [ ! -x vendor/yt-dlp ]; then
    echo "fetching yt-dlp..."
    curl -fL --retry 3 -o vendor/yt-dlp "$YTDLP_URL"
    chmod +x vendor/yt-dlp
fi

# py2app does not depend on our own sources - it packages the interpreter,
# pyobjc and pywebview - so CI caches the bundle it produced and only the files
# that come from this checkout are replaced (tools/update-macos-bundle.py). The
# helper checks the layout and exits 3 when it does not recognise it; then, and
# on a cold cache, this is a normal full build.
REUSED=
if [ -n "${KOTASSIUM_REUSE_BUNDLE:-}" ] && [ -d dist/Kotassium.app ]; then
    if KOTASSIUM_VERSION="$VERSION" desktop-venv/bin/python tools/update-macos-bundle.py; then
        REUSED=1
    else
        echo "rebuilding the bundle from scratch" >&2
        rm -rf build dist
    fi
fi

if [ -z "$REUSED" ]; then
    rm -rf build dist
    KOTASSIUM_VERSION="$VERSION" desktop-venv/bin/python setup-macos.py py2app
    mkdir -p dist/Kotassium.app/Contents/Resources/bin
fi
phase "the app bundle"

# The server looks for BASE/bin/yt-dlp first (BASE is Contents/Resources).
cp vendor/yt-dlp dist/Kotassium.app/Contents/Resources/bin/yt-dlp
chmod +x dist/Kotassium.app/Contents/Resources/bin/yt-dlp

# A shared-server build opens that URL on launch (desktop.py --local overrides).
if [ -n "${KOTASSIUM_URL:-}" ]; then
    printf '%s\n' "$KOTASSIUM_URL" > dist/Kotassium.app/Contents/Resources/default-url.txt
    echo "baked remote URL: $KOTASSIUM_URL"
else
    rm -f dist/Kotassium.app/Contents/Resources/default-url.txt
fi

# Ad-hoc signature: enough for local use, not notarized (see README).
codesign --force --deep --sign - dist/Kotassium.app
phase "signature"

echo
echo "built: $(pwd)/dist/Kotassium.app (version $VERSION)"
if [ -n "$REUSED" ]; then
    echo "bundle: reused the cached py2app output, py2app skipped"
fi
echo "install locally with: ./install-macos.sh"
