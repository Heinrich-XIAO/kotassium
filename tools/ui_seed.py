"""Throwaway libraries for tools/ui.py, so reviews see a page that looks used.

    full    eight playlists with generated cover art and album names (default)
    sparse  three playlists, no covers, no albums: the thin case
    empty   no playlists: the first-run state

Covers are drawn here with Pillow and registered in the server's cover cache
(webstate/covers + covers.json), exactly where a real library keeps the
thumbnails it fetched from Spotify. Every track carries a library id with a
silent file behind it (one ffmpeg clip per length, hard-linked per track), so
pressing play answers from disk: without that the page searched YouTube for
the made-up titles and downloaded real songs into the throwaway library.
"""
import hashlib
import json
import os
import random
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFilter

VERSION = "4"  # bump to rebuild cached seed libraries

PLAYLISTS = [
    ("Late Night Drive", 24), ("Kitchen Radio", 36), ("Deep Focus", 48),
    ("Morning Run", 18), ("Sunday Records", 30), ("Synthwave 84", 27),
    ("Road Trip", 42), ("Rainy Window", 15),
]
ARTISTS = ["Nova Hart", "The Lanterns", "Kito Blue", "Mira Vale", "Hollow Pines",
           "Sable Coast", "Orbit Club", "June Arcade", "Lowtide", "Ana Reyes"]
ALBUMS = ["Neon Weather", "Paper Moons", "Slow Signal", "Glasshouse", "Northbound",
          "After Hours", "Field Notes", "Static Bloom", "Coastlines", "Velvet Rooms",
          "Low Orbit", "Small Hours"]
LENGTHS = [149, 186, 204, 221, 252, 309]  # seconds; one silent clip each
WORDS = ["Golden", "Hour", "Echo", "Static", "Satellite", "Ember", "Coast", "Signal",
         "Velvet", "Midnight", "Paper", "Rivers", "Glass", "Bloom", "Northern", "Lights",
         "Slow", "Motion", "Neon", "Rain", "Summer", "Ghost", "Fever", "Harbour"]


def _rng(name):
    return random.Random(int(hashlib.sha1(name.encode()).hexdigest(), 16))


def _cover(name, path, size=320):
    """Abstract album art: a two-tone gradient, a sun and a few soft bands."""
    r = _rng(name)
    h1, h2 = r.random(), r.random()

    def hsv(h, s, v):
        import colorsys
        return tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h % 1, s, v))

    a, b = hsv(h1, 0.65, 0.85), hsv(h1 + 0.25 + h2 * 0.3, 0.7, 0.35)
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            px[x, y] = tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))
    draw = ImageDraw.Draw(img, "RGBA")
    cx, cy, rad = r.randint(80, 240), r.randint(70, 200), r.randint(50, 110)
    draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=hsv(h2, 0.4, 1.0) + (200,))
    for i in range(r.randint(3, 6)):
        y = r.randint(size // 2, size)
        draw.rectangle((0, y, size, y + r.randint(6, 22)), fill=hsv(h1 + 0.5, 0.5, 0.2) + (90,))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img.save(path)


def _tracks(name, count, albums, r):
    out = []
    for i in range(count):
        title = " ".join(r.sample(WORDS, r.choice([1, 2, 2, 3])))
        album = r.choice(albums)
        out.append({"t": title, "a": r.choice(ARTISTS), "al": album, "album": album,
                    "ms": r.choice(LENGTHS) * 1000, "source": "youtube",
                    "id": "seed-%s-%d" % (hashlib.md5(name.encode()).hexdigest()[:6], i),
                    "cover": "https://i.scdn.co/image/kot-seed-album-" + album.lower().replace(" ", "-")})
    return out


def _audio(lib, tracks):
    """Give each track a silent file named by its id, so playback never downloads."""
    if not shutil.which("ffmpeg"):
        print("ui_seed: no ffmpeg, so play steps will search YouTube for real audio")
        return
    clips = os.path.join(lib, "webstate", "clips")
    os.makedirs(clips, exist_ok=True)
    for t in tracks:
        sec = t["ms"] // 1000
        clip = os.path.join(clips, "%d.mp3" % sec)
        if not os.path.exists(clip):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "anullsrc=r=8000:cl=mono", "-t", str(sec), "-b:a", "8k", clip], check=True)
        dest = os.path.join(lib, t["id"] + ".mp3")
        if not os.path.exists(dest):
            os.link(clip, dest)


def build(lib, seed):
    """Create the library for `seed` under `lib` unless it already exists."""
    state = os.path.join(lib, "webstate")
    marker = os.path.join(state, ".seed")
    if os.path.exists(marker) and open(marker).read() == seed + VERSION:
        return
    covers_dir = os.path.join(state, "covers")
    os.makedirs(covers_dir, exist_ok=True)
    links, cover_map = [], {}
    if seed == "sparse":
        tracks = [{"t": "Song One", "a": "Artist A", "ms": 221000, "id": "seed-yt1", "source": "youtube"},
                  {"t": "Song Two", "a": "Artist B", "ms": 186000, "id": "seed-yt2", "source": "youtube"},
                  {"t": "Song Three", "a": "Artist C", "ms": 252000, "id": "seed-yt3", "source": "youtube"}]
        links = [{"url": "https://open.spotify.com/playlist/demo", "name": "Late Night Drive",
                  "count": 3, "ts": 0, "tracks": tracks},
                 {"url": "https://open.spotify.com/playlist/demo2", "name": "Kitchen Radio",
                  "count": 3, "total": 3, "ts": 0, "tracks": tracks},
                 {"url": "https://open.spotify.com/playlist/demo3", "name": "Long Player",
                  "count": 3, "total": 20, "partial": True, "ts": 0, "tracks": tracks}]
    elif seed == "full":
        for album in ALBUMS:
            url = "https://i.scdn.co/image/kot-seed-album-" + album.lower().replace(" ", "-")
            fname = "seed-album-%s.png" % album.lower().replace(" ", "-")
            _cover("album " + album, os.path.join(covers_dir, fname))
            cover_map[url] = fname
        for n, (name, count) in enumerate(PLAYLISTS):
            r = _rng(name)
            slug = name.lower().replace(" ", "-")
            url = "https://i.scdn.co/image/kot-seed-playlist-" + slug
            fname = "seed-playlist-%s.png" % slug
            _cover("playlist " + name, os.path.join(covers_dir, fname))
            cover_map[url] = fname
            links.append({"url": "https://open.spotify.com/playlist/seed%d" % n, "name": name,
                          "count": count, "total": count, "ts": n, "cover": url,
                          "tracks": _tracks(name, count, ALBUMS, r)})
    elif seed != "empty":
        raise SystemExit("unknown KOT_SEED %r (full, sparse, empty)" % seed)
    _audio(lib, [t for link in links for t in link["tracks"]])
    with open(os.path.join(state, "links.json"), "w") as fh:
        json.dump(links, fh)
    with open(os.path.join(state, "covers.json"), "w") as fh:
        json.dump(cover_map, fh)
    with open(marker, "w") as fh:
        fh.write(seed + VERSION)
