#!/usr/bin/env bash
# Screenshot the real page in this sandbox, and measure it.
#
#     tools/page_shot.sh out.png                 # home page, 1440x900
#     tools/page_shot.sh out.png '/?desktop=1' 900 1200
#
# The agent sandbox ships with no browser, no fonts and no root - which is why
# visual work used to be guesswork here. This installs a headless Chromium and
# the handful of shared libraries it wants into private directories, points
# fontconfig at a real font, runs serve_web.py against a throwaway library, and
# leaves the PNG for tools/measure_shot.py or a person to look at. Everything
# is cached, so the second run starts in a second.
set -euo pipefail

OUT=${1:-artifacts/page.png}
PATH_PART=${2:-/}
W=${3:-1440}
H=${4:-900}
PORT=${PORT:-8777}
LIB=${KOTASSIUM_LIB:-/tmp/kotassium-shot}

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-$ROOT/venv/bin/python}
SYSROOT=$HOME/sysroot
APT_DIR=$HOME/.apt

# ---------------------------------------------------------------- libraries
if ! ls "$SYSROOT"/usr/lib/x86_64-linux-gnu/libnss3.so >/dev/null 2>&1; then
  echo "fetching the libraries Chromium needs (no root needed)"
  mkdir -p "$APT_DIR/lists/partial" "$APT_DIR/cache/archives/partial" "$SYSROOT"
  cat > "$APT_DIR/sources.list" <<'EOF'
deb http://archive.ubuntu.com/ubuntu noble main universe
deb http://archive.ubuntu.com/ubuntu noble-updates main universe
EOF
  apt_opts=(-o "Dir::State::lists=$APT_DIR/lists" -o "Dir::Cache=$APT_DIR/cache"
            -o "Dir::Etc::sourcelist=$APT_DIR/sources.list"
            -o "Dir::Etc::sourceparts=/dev/null" -o APT::Get::List-Cleanup=0)
  apt-get "${apt_opts[@]}" -qq update
  # fonts-liberation matters as much as the libraries: with no font installed
  # every glyph renders as an empty box and the screenshot is worthless.
  pkgs="libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64
        libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libasound2t64
        libxkbcommon0 libxrender1 libxi6 libxext6 libx11-6 libxcb1
        fonts-liberation"
  work=$(mktemp -d)
  ( cd "$work" && apt-get "${apt_opts[@]}" -qq download $pkgs >/dev/null 2>&1 || true
    for f in *.deb; do dpkg -x "$f" "$SYSROOT"; done )
  rm -rf "$work"
  mkdir -p "$HOME/.local/share/fonts"
  find "$SYSROOT" -name '*.ttf' -exec cp {} "$HOME/.local/share/fonts/" \;
fi

export LD_LIBRARY_PATH="$SYSROOT/usr/lib/x86_64-linux-gnu:$SYSROOT/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# ---------------------------------------------------------------- chromium
SHELL_BIN=$(find "$HOME/.cache/ms-playwright" -name chrome-headless-shell -type f 2>/dev/null | sort | tail -1)
if [ -z "$SHELL_BIN" ]; then
  echo "installing chromium headless shell"
  npx --yes playwright@latest install --only-shell chromium >/dev/null 2>&1
  SHELL_BIN=$(find "$HOME/.cache/ms-playwright" -name chrome-headless-shell -type f | sort | tail -1)
fi
missing=$("$SHELL_BIN" --version 2>&1 | grep -c "error while loading" || true)
if [ "$missing" != "0" ]; then
  echo "chromium still missing a library: $("$SHELL_BIN" --version 2>&1)" >&2
  echo "add the package that owns it to the list above and delete $SYSROOT" >&2
  exit 1
fi

# ---------------------------------------------------------------- a library
# Never point this at the real library: it writes webstate files.
mkdir -p "$LIB/webstate"
if [ ! -f "$LIB/webstate/links.json" ]; then
  "$PY" - "$LIB/webstate/links.json" <<'PY'
import json, sys
tracks = [{"t": "Song One", "a": "Artist A", "ms": 214000, "id": "yt1"},
          {"t": "Song Two", "a": "Artist B", "ms": 187000, "id": "yt2"},
          {"t": "Song Three", "a": "Artist C", "ms": 249000, "id": "yt3"}]
links = [{"url": "https://open.spotify.com/playlist/demo", "name": "Late Night Drive",
          "count": 3, "ts": 0, "tracks": tracks},
         {"url": "https://open.spotify.com/playlist/demo2", "name": "Kitchen Radio",
          "count": 12, "total": 12, "ts": 0, "tracks": tracks},
         {"url": "https://open.spotify.com/playlist/demo3", "name": "Long Player",
          "count": 8, "total": 20, "partial": True, "ts": 0, "tracks": tracks}]
json.dump(links, open(sys.argv[1], "w"))
PY
fi

# ---------------------------------------------------------------- the page
KOTASSIUM_LIB=$LIB "$PY" "$ROOT/serve_web.py" --host 127.0.0.1 --port "$PORT" \
  > "$LIB/server.log" 2>&1 &
server_pid=$!
trap 'kill $server_pid 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do
  curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null && break
  sleep 0.25
done
curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/health" || {
  echo "server did not come up; see $LIB/server.log" >&2; exit 1; }

mkdir -p "$(dirname "$OUT")"
profile=$(mktemp -d)
"$SHELL_BIN" --no-sandbox --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=1 --window-size="$W,$H" --virtual-time-budget=6000 \
  --user-data-dir="$profile" --screenshot="$OUT" \
  "http://127.0.0.1:$PORT$PATH_PART" 2>/dev/null | tail -1
rm -rf "$profile"
[ -s "$OUT" ] || { echo "no screenshot written" >&2; exit 1; }
echo "wrote $OUT ($(stat -c%s "$OUT") bytes)"
