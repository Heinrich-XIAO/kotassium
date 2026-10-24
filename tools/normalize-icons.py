#!/usr/bin/env python3
"""Regenerate every platform icon with larger, optically centered artwork."""
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "web", "icons", "icon-512.png")


def main():
    source = Image.open(SOURCE).convert("RGBA")
    bg = source.getpixel((0, 0))
    mask = Image.new("L", source.size)
    pixels = source.load()
    mp = mask.load()
    for y in range(source.height):
        for x in range(source.width):
            r, g, b, alpha = pixels[x, y]
            mp[x, y] = max(abs(r - bg[0]), abs(g - bg[1]), abs(b - bg[2])) * alpha // 255
    bbox = mask.getbbox()
    if not bbox:
        raise SystemExit("logo artwork not found in " + SOURCE)

    # Crop to the visible mark before scaling. The original mark uses only
    # ~63% of the canvas width, which is why it reads undersized on launchers.
    mark = source.crop(bbox)
    mark_mask = mask.crop(bbox)
    destinations = {
        "web/icons/icon-512.png": (512, 0.82),
        "web/icons/icon-192.png": (192, 0.82),
        "web/icons/apple-touch-icon.png": (180, 0.82),
        "web/icons/icon-maskable-512.png": (512, 0.64),
        "android/app/src/main/res/mipmap-mdpi/ic_launcher.png": (48, 0.82),
        "android/app/src/main/res/mipmap-hdpi/ic_launcher.png": (72, 0.82),
        "android/app/src/main/res/mipmap-xhdpi/ic_launcher.png": (96, 0.82),
        "android/app/src/main/res/mipmap-xxhdpi/ic_launcher.png": (144, 0.82),
        "android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png": (192, 0.82),
    }
    for rel, (size, fill) in destinations.items():
        target = size * fill
        scale = min(target / mark.width, target / mark.height)
        width, height = round(mark.width * scale), round(mark.height * scale)
        resized = mark.resize((width, height), Image.Resampling.LANCZOS)
        resized_mask = mark_mask.resize((width, height), Image.Resampling.LANCZOS)
        # Visual centroid balancing accounts for the heavier, broad play
        # triangle so geometric centering does not make the mark feel leftward.
        weights = list(resized_mask.get_flattened_data())
        mass = sum(weights)
        cx = sum((x + 0.5) * sum(weights[y * width + x] for y in range(height))
                 for x in range(width)) / mass
        cy = sum((y + 0.5) * sum(weights[y * width + x] for x in range(width))
                 for y in range(height)) / mass
        left = round(size / 2 - cx)
        top = round(size / 2 - cy)
        canvas = Image.new("RGBA", (size, size), bg)
        canvas.alpha_composite(resized, (left, top))
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        canvas.save(path)
        print("wrote %s (%dx%d, %d%% canvas fill)" % (rel, size, size, round(fill * 100)))


if __name__ == "__main__":
    main()
