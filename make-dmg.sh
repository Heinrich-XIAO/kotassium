#!/bin/sh
# Wrap dist/Kotassium.app in a drag-to-Applications disk image. Run on macOS.
#   ./make-dmg.sh [output.dmg]
set -eu
cd "$(dirname "$0")"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This must run on macOS." >&2
    exit 1
fi

VERSION="${KOTASSIUM_VERSION:-2.1.0}"
OUT="${1:-Kotassium-$VERSION.dmg}"

if [ ! -d dist/Kotassium.app ]; then
    echo "dist/Kotassium.app is missing - run ./build-macos.sh first." >&2
    exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -R dist/Kotassium.app "$STAGE/Kotassium.app"
ln -s /Applications "$STAGE/Applications"

rm -f "$OUT"
df -h / | tail -1
# No -quiet: if hdiutil fails, its reason is the only useful output there is.
if ! hdiutil create -volname Kotassium -srcfolder "$STAGE" -ov -format UDZO "$OUT"; then
    echo "hdiutil failed (stage=$STAGE, out=$OUT)" >&2
    exit 1
fi

echo "built: $(pwd)/$OUT"
