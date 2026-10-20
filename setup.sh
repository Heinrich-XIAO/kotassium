#!/bin/sh
# Create desktop-venv (pywebview) for Linux or macOS.
#
# Linux needs the distro's GTK/WebKit bindings (python3-gobject, gtk3,
# webkit2gtk), so the venv is built with --system-site-packages. macOS gets
# everything from pip (pywebview pulls in pyobjc).
set -eu
cd "$(dirname "$0")"
PY=${PYTHON:-python3}

command -v "$PY" >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }

if [ ! -x desktop-venv/bin/python ]; then
    if [ "$(uname -s)" = "Darwin" ]; then
        "$PY" -m venv desktop-venv
    else
        "$PY" -m venv --system-site-packages desktop-venv
    fi
fi

desktop-venv/bin/python -m pip install --quiet --upgrade pip
desktop-venv/bin/python -m pip install --quiet pywebview

if [ "$(uname -s)" = "Darwin" ]; then
    echo "macOS: pywebview installed (Cocoa/WKWebView backend)"
else
    if ! desktop-venv/bin/python -c "import gi" 2>/dev/null; then
        echo "warning: PyGObject is missing. Install your distro's python3-gobject," >&2
        echo "         gtk3 and webkit2gtk packages, then rerun ./setup.sh" >&2
    fi
fi

desktop-venv/bin/python -c "import webview; print('pywebview', webview.__version__)"
