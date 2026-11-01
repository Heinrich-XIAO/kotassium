#!/bin/sh
# Attach one built artifact to this version's release, creating the release
# when this is the first artifact of the run.
#
#   tools/publish-release.sh <version> <file>
#
# Needs GH_TOKEN with contents: write and a checkout of the repository (the
# release notes come from .github/release-body.md). Shared by the macOS build
# job, the Android publish job and the tag release, so every artifact is
# attached the same way and SHA256SUMS stays one file rather than one per
# platform.
set -eu
cd "$(dirname "$0")/.."

VERSION=${1:?version}
FILE=${2:?file}
TAG="v$VERSION"
NAME=$(basename "$FILE")

[ -f "$FILE" ] || { echo "nothing to publish: $FILE is missing" >&2; exit 1; }

WORK=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/release.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
cp "$FILE" "$WORK/$NAME"

if command -v sha256sum >/dev/null 2>&1; then
    SUM=$(sha256sum "$WORK/$NAME" | awk '{print $1}')
else
    SUM=$(shasum -a 256 "$WORK/$NAME" | awk '{print $1}')
fi
printf '%s  %s\n' "$SUM" "$NAME" > "$WORK/new-checksum"

if gh release view "$TAG" >/dev/null 2>&1; then
    mkdir -p "$WORK/existing"
    if gh release download "$TAG" --pattern SHA256SUMS --dir "$WORK/existing" 2>/dev/null; then
        awk -v name="$NAME" '$2 != name { print }' "$WORK/existing/SHA256SUMS" > "$WORK/SHA256SUMS"
    else
        : > "$WORK/SHA256SUMS"
    fi
    cat "$WORK/new-checksum" >> "$WORK/SHA256SUMS"
    gh release upload "$TAG" "$WORK/$NAME" "$WORK/SHA256SUMS" --clobber
else
    mv "$WORK/new-checksum" "$WORK/SHA256SUMS"
    gh release create "$TAG" "$WORK/$NAME" "$WORK/SHA256SUMS" \
        --title "$TAG" \
        --notes-file .github/release-body.md \
        --target "${TARGET:-${GITHUB_SHA:-HEAD}}"
fi

echo "published $NAME on $TAG"
