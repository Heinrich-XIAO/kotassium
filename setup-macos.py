"""py2app configuration for a real Kotassium.app (run on macOS).

    ./build-macos.sh

produces dist/Kotassium.app. Not testable from Linux - see README.
"""
import os

from setuptools import setup

VERSION = os.environ.get("KOTASSIUM_VERSION", "2.0.0").lstrip("v")

APP = ["desktop.py"]
DATA_FILES = [
    ("web", ["web/index.html"]),
    ("assets", ["assets/kotassium.svg"]),
]
OPTIONS = {
    "argv_emulation": False,
    "packages": ["webview"],
    "includes": ["serve_web", "spotify_get", "notify"],
    # Linux-only modules: don't try to bundle PyGObject / MPRIS on macOS.
    "excludes": ["gi", "mpris_linux"],
    "plist": {
        "CFBundleName": "Kotassium",
        "CFBundleDisplayName": "Kotassium",
        "CFBundleIdentifier": "app.kotassium.desktop",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
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
