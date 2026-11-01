#!/bin/sh
# Print the version this run publishes.
#
#   tools/next-version.sh [version]
#
# A tag release and a manual run pass the version in; a rolling release to main
# passes nothing and gets the patch bump of the newest tag, which is the same
# answer .github/next_version.py gives the `version` job. Both the job and the
# macOS build call this, so a build can start without waiting for that job and
# still stamp the same number into its bundle.
set -eu
cd "$(dirname "$0")/.."

if [ -n "${1:-}" ]; then
    printf '%s\n' "$1"
    exit 0
fi

TAGS=$(git ls-remote --tags --refs origin 'v*' | awk -F/ '{print $NF}')
test -n "$TAGS" || { echo "no tags found on origin" >&2; exit 1; }
python3 .github/next_version.py $TAGS
