#!/usr/bin/env python3
"""Headless UI check: drive the real page in a real window and assert state.

    xvfb-run -a desktop-venv/bin/python tools/ui_check.py

Needs the library (~/Music/Kotassium) to contain at least one downloaded mp3;
it seeds the page's YouTube-id cache so the first playlist track resolves to a
local file instead of hitting the network.
"""
import json
import os
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import desktop  # noqa: E402
import serve_web  # noqa: E402

# Known-good mappings (playlist track -> already-downloaded YouTube id).
SEED = {"Hysterical|Lexica": "CxNVRduEljU",
        "Infernoplex|Dimrain47": "Cf5KOTB7Ew8"}

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (("  " + str(detail)) if detail else ""),
          flush=True)


def wait_js(w, expr, want, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if w.evaluate_js(expr) == want:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def nowplaying(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/nowplaying" % port, timeout=2) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}


def driver(port, w):
    try:
        if not wait_js(w, "document.readyState", "complete", 20):
            check("page loads", False)
            return
        check("page loads", True)
        w.evaluate_js("localStorage.setItem('kot_ytcache', %s); location.reload();"
                      % json.dumps(json.dumps(SEED)))
        time.sleep(2.5)
        if not wait_js(w, "document.readyState", "complete", 20):
            check("page reloads", False)
            return
        check("page reloads", True)
        time.sleep(1.0)

        # open the only playlist and play its first track
        n = w.evaluate_js("document.querySelectorAll('.cardgrid .card').length")
        check("playlist card rendered", n == 1, "cards=%s" % n)
        w.evaluate_js("openPlaylist(0)")
        time.sleep(1.2)
        rows = w.evaluate_js("document.querySelectorAll('#tbl .row').length")
        check("track list rendered", rows >= 10, "rows=%s" % rows)

        w.evaluate_js("playT(0,true)")
        time.sleep(7.0)
        t = w.evaluate_js("AU.currentTime") or 0
        paused = w.evaluate_js("AU.paused")
        check("audio is playing", t > 1.5 and not paused, "t=%.1f paused=%s" % (t, paused))
        check("full track swapped in", w.evaluate_js("(AU.src||'').indexOf('_preview')<0"),
              w.evaluate_js("AU.src"))
        check("now-playing title", (nowplaying(port).get("t") or "") == "Hysterical",
              nowplaying(port))

        w.evaluate_js("toggle()")
        time.sleep(1.0)
        check("pause works", bool(w.evaluate_js("AU.paused")))
        w.evaluate_js("toggle()")
        time.sleep(1.0)
        check("resume works", not w.evaluate_js("AU.paused"))

        w.evaluate_js("nx()")
        time.sleep(6.0)
        check("next track", (nowplaying(port).get("t") or "") == "Infernoplex",
              nowplaying(port).get("t"))

        w.evaluate_js("if(AU.duration)AU.currentTime=AU.duration*0.5")
        time.sleep(1.0)
        dur = w.evaluate_js("AU.duration") or 0
        cur = w.evaluate_js("AU.currentTime") or 0
        check("seek works", dur > 0 and abs(cur / dur - 0.5) < 0.12,
              "t=%.1f dur=%.1f" % (cur, dur))

        w.evaluate_js("AU.volume=0.25")
        check("volume works", abs((w.evaluate_js("AU.volume") or 0) - 0.25) < 0.01)
    except Exception as e:
        check("driver crashed", False, repr(e))
    finally:
        failed = [r for r in results if not r[1]]
        print("\n%d checks, %d failed" % (len(results), len(failed)), flush=True)
        try:
            w.destroy()
        except Exception:
            pass


def main():
    srv = serve_web.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    desktop.show_window(port, dev=False, notify_tracks=False,
                        on_start=lambda: driver(port, w_holder[0]))
    srv.shutdown()
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    # show_window creates the window itself; grab it from pywebview afterwards.
    import webview
    orig = webview.create_window
    w_holder = [None]

    def capture(*a, **k):
        w_holder[0] = orig(*a, **k)
        return w_holder[0]

    webview.create_window = capture
    sys.exit(main())
