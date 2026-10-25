#!/bin/sh
# Build an installable macOS package from dist/Kotassium.app.
#   ./make-pkg.sh [output.pkg]
set -eu
cd "$(dirname "$0")"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This must run on macOS." >&2
    exit 1
fi

VERSION="${KOTASSIUM_VERSION:-2.1.0}"
OUT="${1:-Kotassium-$VERSION.pkg}"
APP="dist/Kotassium.app"

if [ ! -d "$APP" ]; then
    echo "$APP is missing - run ./build-macos.sh first." >&2
    exit 1
fi
if [ ! -x "$APP/Contents/MacOS/Kotassium" ]; then
    echo "$APP does not contain an executable Kotassium app." >&2
    exit 1
fi

chmod +x macos-pkg-scripts/preinstall
rm -f "$OUT"
pkgbuild \
    --component "$APP" \
    --install-location /Applications \
    --identifier app.kotassium.desktop \
    --version "$VERSION" \
    --scripts macos-pkg-scripts \
    "$OUT"

echo "built: $(pwd)/$OUT"
