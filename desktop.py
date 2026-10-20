#!/usr/bin/env python3
"""desktop.py - Kotassium in a native window.

Starts the existing local server on loopback and shows web/index.html in a
WebKitGTK window (pywebview). The web edition (`serve_web.py`) is unchanged;
this file is only a shell.
"""
import argparse, json, os, sys, threading, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import serve_web

STATE = serve_web.STATE
WIN_FILE = os.path.join(STATE, "window.json")
LOCK_FILE = os.path.join(STATE, "desktop.lock")
DEFAULT_PORT = serve_web.PORT
DEFAULT_SIZE = (1200, 800)
MIN_SIZE = (900, 600)


def health(port, timeout=0.5):
    """True if a Kotassium server answers on this loopback port."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace")).get("app") == "kotassium"
    except Exception:
        return False


def acquire_lock():
    """Single instance. Returns an open lock file, or None if already running."""
    import fcntl
    fh = open(LOCK_FILE, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def load_geometry():
    try:
        g = json.load(open(WIN_FILE))
        return {k: int(g[k]) for k in ("width", "height", "x", "y")
                if isinstance(g.get(k), int)}
    except Exception:
        return {}


def save_geometry(w):
    try:
        g = {}
        for k in ("width", "height", "x", "y"):
            v = getattr(w, k, None)
            if isinstance(v, int):
                g[k] = v
        if not g:
            return
        tmp = WIN_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(g, f)
        os.replace(tmp, WIN_FILE)
    except Exception:
        pass


def preflight():
    """Human-readable list of missing optional dependencies."""
    missing = []
    if not serve_web.YTDLP:
        missing.append("yt-dlp (full tracks)")
    if not serve_web.FFMPEG:
        missing.append("ffmpeg (mp3 conversion + previews)")
    return missing


def run(host, port, dev=False, no_window=False):
    lock = acquire_lock()
    if not lock:
        if health(port):
            print("Kotassium is already running on port %d" % port)
            return 0
        print("Another Kotassium instance holds %s" % LOCK_FILE)
        return 1

    try:
        try:
            srv = serve_web.make_server(host, port)
        except OSError as e:
            if health(port):
                print("Kotassium is already running on port %d" % port)
            else:
                print("Could not bind %s:%d - %s" % (host, port, e))
            return 1

        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print("[kotassium] %s:%d  lib=%s" % (host, port, serve_web.LIB), flush=True)

        try:
            if no_window:
                while True:
                    time.sleep(3600)
            return show_window(port, dev)
        finally:
            srv.shutdown()
            serve_web.stop_children()
            lock.close()
    except KeyboardInterrupt:
        serve_web.stop_children()
        return 0


def relax_autoplay():
    """WebKitGTK rejects programmatic play() by default (reported as
    NotSupportedError). The preview -> full-track swap calls play() without a
    gesture, so the app must opt out. pywebview does not expose this setting."""
    try:
        from webview.platforms.gtk import BrowserView
    except Exception:
        return False
    for _ in range(50):
        try:
            views = list(BrowserView.instances.values())
            if views:
                for b in views:
                    b.webview.get_settings().set_property(
                        "media-playback-requires-user-gesture", False)
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def show_window(port, dev):
    try:
        import webview
    except Exception as e:
        print("pywebview unavailable: %s" % e)
        print("Run ./install.sh to create desktop-venv, or use ./kotassium-app.sh (Epiphany).")
        return 1

    geom = load_geometry()
    kwargs = dict(geom) if geom else {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1]}
    w = webview.create_window(
        "Kotassium",
        "http://127.0.0.1:%d/" % port,
        min_size=MIN_SIZE,
        background_color="#000000",
        **kwargs
    )

    missing = preflight()

    def on_loaded():
        relax_autoplay()
        if missing:
            try:
                w.evaluate_js("toast(%s)" % json.dumps("missing: " + ", ".join(missing)))
            except Exception:
                pass

    def on_closed():
        save_geometry(w)
        serve_web.stop_children()

    w.events.loaded += on_loaded
    w.events.closed += on_closed
    webview.start(debug=dev, gui="gtk")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Kotassium desktop app")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--lan", action="store_true",
                    help="bind 0.0.0.0 so phones can connect too")
    ap.add_argument("--dev", action="store_true", help="open the WebKit inspector")
    ap.add_argument("--no-window", action="store_true", help="server only")
    a = ap.parse_args(argv)
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    return run(host, a.port, dev=a.dev, no_window=a.no_window)


if __name__ == "__main__":
    sys.exit(main())
