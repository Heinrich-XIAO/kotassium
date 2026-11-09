#!/usr/bin/env python3
"""Drive the real page in Chrome and print a short report.

    venv/bin/python tools/ui.py steps.json
    venv/bin/python tools/ui.py '[{"size": [390, 844]}, {"goto": "/"}, {"shot": "phone"}]'

A scenario is a JSON list. Each step has one key:

    {"size": [w, h]}        viewport for the steps after it (default 1440x900)
    {"goto": "/path"}       load a page from the server
    {"click": "css"}        click the first match
    {"hover": "css"}        hover the first match
    {"fill": ["css", "text"]}
    {"press": "Escape"}
    {"wait": 500}           milliseconds
    {"eval": "js"}          print the JavaScript value (trimmed)
    {"shot": "name"}        save artifacts/ui/<name>.png
    {"icons": true}         centring audit of every icon-only control ("all" lists each one)
    {"layout": true}        horizontal overflow, words and controls in view
    {"sheet": "name"}       one contact sheet of every shot so far: a single image to read

Needs the venv with playwright and pillow (venv/bin/pip install playwright pillow)
and Google Chrome at /Applications, or KOT_CHROME pointing at a Chromium binary.
Scores for the page live in tools/ui_rubric.md.

Output is one line per step. Screenshots land in artifacts/ui/, which git
ignores. Set KOT_URL to test a server that is already running. Set KOT_CHROME
to pick another browser binary.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "venv", "bin", "python")
OUT = os.path.join(ROOT, "artifacts", "ui")
LIB = os.path.join(ROOT, "artifacts", "ui-lib")
TOLERANCE = 0.1  # CSS px an icon's ink box may sit off its control's centre
CHROME = os.environ.get(
    "KOT_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

# A library with three playlists, so the home page and the list views have
# content. The same seed as tools/page_shot.sh.
SEED_TRACKS = [{"t": "Song One", "a": "Artist A", "ms": 214000, "id": "yt1"},
               {"t": "Song Two", "a": "Artist B", "ms": 187000, "id": "yt2"},
               {"t": "Song Three", "a": "Artist C", "ms": 249000, "id": "yt3"}]
SEED_LINKS = [{"url": "https://open.spotify.com/playlist/demo", "name": "Late Night Drive",
               "count": 3, "ts": 0, "tracks": SEED_TRACKS},
              {"url": "https://open.spotify.com/playlist/demo2", "name": "Kitchen Radio",
               "count": 12, "total": 12, "ts": 0, "tracks": SEED_TRACKS},
              {"url": "https://open.spotify.com/playlist/demo3", "name": "Long Player",
               "count": 8, "total": 20, "partial": True, "ts": 0, "tracks": SEED_TRACKS}]

ICON_JS = """
() => {
  const seen = new Set(), out = [];
  let skipped = 0;
  const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const ctls = [...document.querySelectorAll('button, a, [role=button], [tabindex], .aicon, .pcover, .card-play')];
  for (const ctl of ctls) {
    if (!visible(ctl)) continue;
    const svg = [...ctl.querySelectorAll('svg')].find((s) => visible(s) && !seen.has(s));
    if (!svg) continue;
    seen.add(svg);
    if (ctl.textContent.trim()) { skipped++; continue; }
    // The glyph's own box, from its shapes: getBBox is exact for arcs and
    // ignores the stroke, which is symmetric about the path.
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const el of svg.querySelectorAll('path,line,polyline,polygon,circle,ellipse,rect')) {
      const b = el.getBBox();
      if (!b.width && !b.height) continue;
      x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y);
      x1 = Math.max(x1, b.x + b.width); y1 = Math.max(y1, b.y + b.height);
    }
    const vb = svg.viewBox.baseVal;
    const c = ctl.getBoundingClientRect(), s = svg.getBoundingClientRect();
    const label = ctl.getAttribute('aria-label') || ctl.getAttribute('title') || ctl.id ||
      (ctl.className && String(ctl.className.baseVal ?? ctl.className)) || ctl.tagName.toLowerCase();
    const k = s.width / vb.width;  // css px per glyph unit
    out.push({ label: label.slice(0, 40), size: Math.round(c.width),
               dx: (s.x + s.width / 2 - (c.x + c.width / 2)) + ((x0 + x1) / 2 - (vb.x + vb.width / 2)) * k,
               dy: (s.y + s.height / 2 - (c.y + c.height / 2)) + ((y0 + y1) / 2 - (vb.y + vb.height / 2)) * k });
  }
  return { rows: out, skipped };
}
"""

LAYOUT_JS = """
() => {
  const vw = innerWidth, vh = innerHeight;
  const wide = [...document.querySelectorAll('body *')].filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.right > vw + 1 && getComputedStyle(el).position !== 'fixed';
  }).length;
  const words = [...document.querySelectorAll('body *')].filter((el) => {
    if (!el.childNodes.length) return false;
    return [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  }).filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
  }).map((el) => [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(' '))
    .join(' ').trim().split(/\\s+/).filter(Boolean).length;
  const controls = document.querySelectorAll('button, a, [role=button]').length;
  return { scrollX: document.documentElement.scrollWidth > vw + 1, wideElements: wide, visibleWords: words, controls };
}
"""


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server():
    """Start serve_web.py on a throwaway library unless KOT_URL points at one."""
    if os.environ.get("KOT_URL"):
        return os.environ["KOT_URL"].rstrip("/"), None
    os.makedirs(os.path.join(LIB, "webstate"), exist_ok=True)
    links = os.path.join(LIB, "webstate", "links.json")
    if not os.path.exists(links):
        with open(links, "w") as fh:
            json.dump(SEED_LINKS, fh)
    port = free_port()
    log = open(os.path.join(LIB, "server.log"), "w")
    env = dict(os.environ, KOTASSIUM_LIB=LIB)
    proc = subprocess.Popen([PY, os.path.join(ROOT, "serve_web.py"), "--host", "127.0.0.1",
                             "--port", str(port)], env=env, stdout=log, stderr=log)
    url = "http://127.0.0.1:%d" % port
    for _ in range(80):
        try:
            urllib.request.urlopen(url + "/api/health", timeout=1).read()
            return url, proc
        except Exception:
            time.sleep(0.25)
    proc.kill()
    raise SystemExit("server did not start; see %s" % os.path.join(LIB, "server.log"))


def run_icons(page):
    found = page.evaluate(ICON_JS)
    return found["rows"], found["skipped"]


def report_icons(rows, skipped, every=False):
    bad = [r for r in rows if abs(r["dx"]) > TOLERANCE or abs(r["dy"]) > TOLERANCE]
    print("icons: %d icon-only controls, %d off-centre by more than %.2fpx "
          "(glyph box and control centre; labelled controls skipped: %d)"
          % (len(rows), len(bad), TOLERANCE, skipped))
    for r in (rows if every else bad)[:60]:
        print("  %-40s dx=%+.2f dy=%+.2f  control=%dpx" % (r["label"], r["dx"], r["dy"], r["size"]))


def contact_sheet(paths, out, row_h=560, row_w=1800, gap=16):
    """Lay the shots out in rows of equal height, so one image shows every view."""
    images = [Image.open(p).convert("RGB") for p in paths]
    images = [im.resize((round(im.width * row_h / im.height), row_h)) for im in images]
    rows, row, width = [], [], 0
    for im in images:
        if row and width + gap + im.width > row_w:
            rows.append(row)
            row, width = [], 0
        width += (gap if row else 0) + im.width
        row.append(im)
    if row:
        rows.append(row)
    sheet_w = max(sum(im.width for im in r) + gap * (len(r) - 1) for r in rows)
    sheet = Image.new("RGB", (sheet_w, len(rows) * row_h + gap * (len(rows) - 1)), (40, 40, 40))
    y = 0
    for r in rows:
        x = 0
        for im in r:
            sheet.paste(im, (x, y))
            x += im.width + gap
        y += row_h + gap
    sheet.save(out)
    return out


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    arg = argv[1]
    steps = json.load(open(arg)) if os.path.exists(arg) else json.loads(arg)
    os.makedirs(OUT, exist_ok=True)
    url, proc = start_server()
    failed = False
    try:
        with sync_playwright() as p:
            launch = {"headless": True, "args": ["--autoplay-policy=no-user-gesture-required"]}
            if os.path.exists(CHROME):
                launch["executable_path"] = CHROME
            browser = p.chromium.launch(**launch)
            size = [1440, 900]
            shots = []
            context = browser.new_context(viewport={"width": size[0], "height": size[1]})
            page = context.new_page()
            for n, step in enumerate(steps, 1):
                key, val = next(iter(step.items()))
                try:
                    if key == "size":
                        size = list(val)
                        page.set_viewport_size({"width": size[0], "height": size[1]})
                        print("%d size %dx%d" % (n, size[0], size[1]))
                    elif key == "goto":
                        page.goto(url + val, wait_until="load")
                        page.wait_for_timeout(600)
                        print("%d goto %s" % (n, val))
                    elif key == "click":
                        page.click(val, timeout=5000)
                        print("%d click %s" % (n, val))
                    elif key == "hover":
                        page.hover(val, timeout=5000)
                        print("%d hover %s" % (n, val))
                    elif key == "fill":
                        page.fill(val[0], val[1], timeout=5000)
                        print("%d fill %s" % (n, val[0]))
                    elif key == "press":
                        page.keyboard.press(val)
                        print("%d press %s" % (n, val))
                    elif key == "wait":
                        page.wait_for_timeout(int(val))
                        print("%d wait %s" % (n, val))
                    elif key == "eval":
                        value = page.evaluate("() => (%s)" % val)
                        text = json.dumps(value)
                        print("%d eval %s" % (n, text[:400]))
                    elif key == "shot":
                        path = os.path.join(OUT, val + ".png")
                        page.screenshot(path=path)
                        shots.append(path)
                        print("%d shot %s (%dx%d)" % (n, os.path.relpath(path, ROOT), size[0], size[1]))
                    elif key == "sheet":
                        path = contact_sheet(shots, os.path.join(OUT, val + ".png"))
                        print("%d sheet %s (%d shots)" % (n, os.path.relpath(path, ROOT), len(shots)))
                    elif key == "icons":
                        report_icons(*run_icons(page), every=(val == "all"))
                    elif key == "layout":
                        print("%d layout %s" % (n, json.dumps(page.evaluate(LAYOUT_JS))))
                    else:
                        raise ValueError("unknown step %r" % key)
                except Exception as exc:  # report the step, keep the browser for the next one
                    failed = True
                    print("%d FAIL %s: %s" % (n, key, str(exc).splitlines()[0]))
            browser.close()
    finally:
        if proc:
            proc.terminate()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
