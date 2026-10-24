#!/usr/bin/env python3
"""Build the macOS app icon from the shared Kotassium launcher artwork."""
import os
import shutil
import subprocess
import tempfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "web", "icons", "icon-512.png")
OUTPUT = os.path.join(ROOT, "web", "icons", "kotassium.icns")


def main():
    if not os.path.isfile(SOURCE):
        raise SystemExit("missing shared logo: %s" % SOURCE)
    with tempfile.TemporaryDirectory(prefix="kotassium-icon-") as temp:
        iconset = os.path.join(temp, "kotassium.iconset")
        os.mkdir(iconset)
        image = Image.open(SOURCE).convert("RGBA")
        for size in (16, 32, 128, 256, 512):
            resized = image.resize((size, size), Image.Resampling.LANCZOS)
            resized.save(os.path.join(iconset, "icon_%dx%d.png" % (size, size)))
            if size < 512:
                doubled = image.resize((size * 2, size * 2), Image.Resampling.LANCZOS)
                doubled.save(os.path.join(iconset, "icon_%dx%d@2x.png" % (size, size)))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", OUTPUT], check=True)
    print("created %s" % OUTPUT)


if __name__ == "__main__":
    main()
