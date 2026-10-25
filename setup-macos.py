"""py2app configuration for a real Kotassium.app (run on macOS).

    ./build-macos.sh

produces dist/Kotassium.app. Not testable from Linux - see README.
"""
import os

from setuptools import setup

VERSION = os.environ.get("KOTASSIUM_VERSION", "2.1.0").lstrip("v")

APP = ["desktop.py"]
ICON = "web/icons/kotassium.icns"
DATA_FILES = [
    ("web", ["web/index.html", "web/app.js", "web/manifest.webmanifest", "web/sw.js"]),
    ("web/icons", ["web/icons/icon-192.png", "web/icons/icon-512.png",
                   "web/icons/icon-maskable-512.png",
                   "web/icons/apple-touch-icon.png"]),
    ("assets", ["assets/kotassium.svg"]),
]
OPTIONS = {
    "argv_emulation": False,
    # pywebview >=5.4 includes the py2app bridge-resource fix.
    "packages": ["webview"],
    "includes": ["serve_web", "spotify_get", "notify", "updater", "titlebar_macos"],
    "iconfile": ICON,
    # Linux-only modules: don't try to bundle PyGObject / MPRIS on macOS.
    "excludes": ["gi", "mpris_linux"],
    "plist": {
        "CFBundleName": "Kotassium",
        "CFBundleDisplayName": "Kotassium",
        "CFBundleIdentifier": "app.kotassium.desktop",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "CFBundleIconFile": "kotassium.icns",
        "LSMinimumSystemVersion": "11.0",
    },
}

setup(
    app=APP,
    name="Kotassium",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
