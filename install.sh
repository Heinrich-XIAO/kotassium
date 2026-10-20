#!/bin/sh
# Install the Kotassium desktop launcher for the current user.
#
# Prerequisite (once):
#   python3 -m venv --system-site-packages desktop-venv
#   desktop-venv/bin/pip install pywebview
set -eu
cd "$(dirname "$0")"
ROOT=$(pwd)
PY="$ROOT/desktop-venv/bin/python"

if [ ! -x "$PY" ]; then
    echo "desktop-venv is missing. Create it first:" >&2
    echo "  python3 -m venv --system-site-packages desktop-venv" >&2
    echo "  desktop-venv/bin/pip install pywebview" >&2
    exit 1
fi

APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$APPS" "$ICONS"
install -m 644 assets/kotassium.svg "$ICONS/kotassium.svg"

cat > "$APPS/kotassium.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Kotassium
Comment=Music player
Exec=$PY $ROOT/desktop.py
Path=$ROOT
Icon=kotassium
Terminal=false
Categories=AudioVideo;Audio;Player;
StartupNotify=true
EOF
chmod 644 "$APPS/kotassium.desktop"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "installed $APPS/kotassium.desktop"
echo "Kotassium should now appear in your app grid."
