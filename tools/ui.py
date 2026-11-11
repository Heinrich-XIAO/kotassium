#!/usr/bin/env python3
"""Drive the real page in Chrome and print a short report.

    venv/bin/python tools/ui.py steps.json
    venv/bin/python tools/ui.py '[{"size": [390, 844]}, {"goto": "/"}, {"shot": "phone"}]'

A scenario is a JSON list. Each step has one key:

    {"size": [w, h]}        viewport for the steps after it (default 1440x900)
    {"goto": "/path"}       load a page from the server
    {"motion": "reduce"}    emulate prefers-reduced-motion ("no-preference" to undo)
    {"click": "css"}        click the first match
    {"hover": "css"}        hover the first match
    {"fill": ["css", "text"]}
    {"press": "Escape"}
    {"wait": 500}           milliseconds
    {"eval": "js"}          print the JavaScript value (trimmed)
    {"shot": "name"}        save artifacts/ui/<name>.png
    {"icons": true}         centring audit of every icon-only control ("all" lists each one)
    {"layout": true}        horizontal overflow, words and controls in view
    {"contrast": true}      WCAG AA text contrast against the composited background
    {"sheet": "name"}       one contact sheet of the shots since the last sheet: one image to read

Needs the venv with playwright and pillow (venv/bin/pip install playwright pillow)
and Google Chrome at /Applications, or KOT_CHROME pointing at a Chromium binary.
Scores for the page live in tools/ui_rubric.md.

Output is one line per step. Screenshots land in artifacts/ui/, which git
ignores. KOT_SEED picks the library: full (default), sparse or empty
(tools/ui_seed.py). Set KOT_URL to test a server that is already running. Set KOT_CHROME
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_seed  # noqa: E402
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "venv", "bin", "python")
OUT = os.path.join(ROOT, "artifacts", "ui")
SEED = os.environ.get("KOT_SEED", "full")
LIB = os.path.join(ROOT, "artifacts", "ui-lib-" + SEED)
TOLERANCE = 0.1  # CSS px an icon's ink box may sit off its control's centre
CHROME = os.environ.get(
    "KOT_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

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
    // A labelled control (a card, a pill with text) is not judged, but the
    // icon-only button inside it still is, so its glyph stays unclaimed.
    if (ctl.textContent.trim()) { skipped++; continue; }
    seen.add(svg);
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
    // Two glyphs are placed optically on purpose (OPTICAL_X / OPTICAL_Y in
    // tests/test_icons.py): the play triangle 0.75 units right, and the tick's
    // path box 0.15 units high so its stroked ink is centred. Hold them there.
    const play = !!svg.querySelector('path[d^="M3.533 2.569"]');
    const tick = !!svg.querySelector('path[d^="M20 6.35"]');
    const optical = play ? 0.75 * k : 0, opticalY = tick ? -0.15 * k : 0;
    out.push({ label: label.slice(0, 40), size: Math.round(c.width), optical, opticalY,
               dx: (s.x + s.width / 2 - (c.x + c.width / 2)) + ((x0 + x1) / 2 - (vb.x + vb.width / 2)) * k,
               dy: (s.y + s.height / 2 - (c.y + c.height / 2)) + ((y0 + y1) / 2 - (vb.y + vb.height / 2)) * k });
  }
  return { rows: out, skipped };
}
"""

CONTRAST_JS = """
() => {
  const parse = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const v = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [v[0], v[1], v[2], v.length > 3 ? v[3] : 1]; };
  const over = (top, under) => { const a = top[3]; return [0, 1, 2].map((i) => top[i] * a + under[i] * (1 - a)).concat(1); };
  const lum = (c) => { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const rows = []; let skipped = 0;
  for (const el of document.querySelectorAll('body *')) {
    if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility !== 'visible' || el.closest(':disabled')) continue;
    // A gradient is judged against its worst stop; a picture cannot be judged.
    let opacity = 1, layers = [], stops = [[0, 0, 0, 1]], unknown = false;
    for (let a = el; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      opacity *= Number(s.opacity);
      const bg = parse(s.backgroundColor);
      if (s.backgroundImage !== 'none') {
        if (s.backgroundImage.includes('url(')) { unknown = true; break; }
        const found = (s.backgroundImage.match(/rgba?\\([^)]+\\)/g) || []).map(parse);
        if (bg && bg[3] > 0) layers.push(bg);
        stops = found.map((c) => over(c, [0, 0, 0, 1]));
        break;
      }
      if (bg && bg[3] > 0) { layers.push(bg); if (bg[3] >= 1) break; }
    }
    if (unknown || opacity === 0) { skipped++; continue; }
    const fg0 = parse(cs.color); if (!fg0) continue;
    let ratio = Infinity;
    for (const stop of stops) {
      let bg = stop;
      for (const layer of [...layers].reverse()) bg = over(layer, bg);
      const fg = over([fg0[0], fg0[1], fg0[2], fg0[3] * opacity], bg);
      const L1 = lum(fg), L2 = lum(bg);
      ratio = Math.min(ratio, (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05));
    }
    const size = parseFloat(cs.fontSize), bold = Number(cs.fontWeight) >= 700;
    const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
    const text = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(' ').trim().slice(0, 32);
    rows.push({ text, ratio: Math.round(ratio * 100) / 100, need, size });
  }
  return { rows, skipped };
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
    ui_seed.build(LIB, SEED)
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
    bad = [r for r in rows if abs(r["dx"] - r["optical"]) > TOLERANCE or abs(r["dy"] - r["opticalY"]) > TOLERANCE]
    optical = sum(1 for r in rows if r["optical"] or r["opticalY"])
    print("icons: %d icon-only controls, %d off target by more than %.2fpx "
          "(%d play/tick glyphs held to their documented optical offset; %d labelled skipped)"
          % (len(rows), len(bad), TOLERANCE, optical, skipped))
    for r in (rows if every else bad)[:60]:
        target = " target dx=%+.2f dy=%+.2f" % (r["optical"], r["opticalY"]) if r["optical"] or r["opticalY"] else ""
        print("  %-40s dx=%+.2f dy=%+.2f%s  control=%dpx" % (r["label"], r["dx"], r["dy"], target, r["size"]))


def contact_sheet(paths, out, row_h=560, row_w=1840, gap=16):
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
                    elif key == "motion":
                        page.emulate_media(reduced_motion=val)
                        print("%d motion %s" % (n, val))
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
                        shots = []
                    elif key == "icons":
                        report_icons(*run_icons(page), every=(val == "all"))
                    elif key == "contrast":
                        found = page.evaluate(CONTRAST_JS)
                        bad = sorted((r for r in found["rows"] if r["ratio"] < r["need"]), key=lambda r: r["ratio"])
                        print("%d contrast: %d text elements, %d below WCAG AA, %d over pictures skipped"
                              % (n, len(found["rows"]), len(bad), found["skipped"]))
                        for r in bad[:12]:
                            print("  %-34s %.2f:1 (needs %.1f, %spx)" % (r["text"], r["ratio"], r["need"], r["size"]))
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
