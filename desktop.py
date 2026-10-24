#!/usr/bin/env python3
"""desktop.py - Kotassium in a native window (Linux + macOS).

Starts the existing local server on loopback and shows web/index.html in a
native webview (WebKitGTK on Linux, WKWebView on macOS) via pywebview. The web
edition (`serve_web.py`) is unchanged; this file is only a shell plus the OS
integration that a browser tab cannot do:

  * MPRIS v2 on Linux (media keys, GNOME media widget, lock screen)
  * track-change notifications (notify-send / osascript)
  * a single instance and remembered window geometry
  * macOS: the native title bar folded into the page's top bar
    (Spotify-style, see titlebar_macos)

The page reports what it is playing to the server (/api/nowplaying); this
process polls that and feeds the OS. Media-key presses are queued to a worker
thread because calling evaluate_js on the GTK main loop would deadlock.
"""
import argparse, json, os, queue, sys, threading, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import serve_web
import notify as notify_mod
import updater

STATE = serve_web.STATE
WIN_FILE = os.path.join(STATE, "window.json")
LOCK_FILE = os.path.join(STATE, "desktop.lock")
DEFAULT_PORT = serve_web.PORT
DEFAULT_SIZE = (1200, 800)
MIN_SIZE = (900, 600)
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"


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


def selftest():
    """Report what this installation can do. Used by CI and for support."""
    from importlib.metadata import version as pkg_version

    ok = True
    print("python  %s" % sys.version.split()[0])
    print("frozen  %s" % bool(getattr(sys, "frozen", False)))
    print("base    %s" % serve_web.BASE)
    for rel in ("web/index.html", "assets/kotassium.svg"):
        p = os.path.join(serve_web.BASE, rel)
        print("%-7s %s" % ("ok" if os.path.isfile(p) else "MISSING", p))
        ok = ok and os.path.isfile(p)
    try:
        import webview  # noqa: F401
        try:
            ver = pkg_version("pywebview")
        except Exception:
            ver = getattr(webview, "__version__", "unknown")
        print("webview %s" % ver)
    except Exception as e:
        ok = False
        print("webview MISSING (%s)" % e)
    if IS_MAC:
        try:
            import WebKit  # noqa: F401
            print("webkit  ok")
        except Exception as e:
            ok = False
            print("webkit  MISSING (%s)" % e)
    print("yt-dlp  %s" % (serve_web.YTDLP or "MISSING"))
    print("ffmpeg  %s" % (serve_web.FFMPEG or "MISSING"))
    print("update  %s" % ("supported (%s, can install: %s)" % (
        updater.current_version(), updater.can_install())
        if updater.SUPPORTED else "unavailable (not a macOS app bundle)"))
    print("remote  %s" % (normalize_url(os.environ.get("KOTASSIUM_URL") or baked_url()) or "local"))
    print("RESULT  %s" % ("ok" if ok else "incomplete"))
    return 0 if ok else 1


def normalize_url(u):
    u = (u or "").strip()
    if not u:
        return None
    if "://" not in u:
        u = "https://" + u
    return u.rstrip("/") + "/"


def baked_url():
    """A shared-server URL shipped inside the app bundle (build-macos.sh)."""
    try:
        with open(os.path.join(serve_web.BASE, "default-url.txt")) as f:
            return f.read().strip() or None
    except Exception:
        return None


def run(host, port, dev=False, no_window=False, notify_tracks=True, remote=None):
    lock = acquire_lock()
    if not lock:
        if health(port):
            print("Kotassium is already running on port %d" % port)
            return 0
        print("Another Kotassium instance holds %s" % LOCK_FILE)
        return 1

    # The app bundle updates itself from GitHub Releases; a source checkout or
    # the Linux build reports unsupported and the UI hides it.
    if updater.SUPPORTED:
        updater.check_async()

    try:
        if remote:
            # Thin-client mode: the shared server is the product, this process
            # only owns the window (and the app's own updater).
            print("[kotassium] remote %s" % remote, flush=True)
            if no_window:
                try:
                    with urllib.request.urlopen(remote + "api/health", timeout=5) as r:
                        print("[kotassium] health: %s" % r.read().decode("utf-8", "replace")[:200])
                except Exception as e:
                    print("[kotassium] unreachable: %s" % e)
                    return 1
                return 0
            try:
                return show_window(dev=dev, notify_tracks=notify_tracks, url=remote)
            finally:
                lock.close()

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
            return show_window(port, dev, notify_tracks)
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
    gesture, so the app must opt out. pywebview does not expose this setting.
    WKWebView (macOS) allows this after the first user gesture, so it is a
    Linux-only fix."""
    if not IS_LINUX:
        return False
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


class WindowChromeAPI:
    """Small JS bridge for the native macOS titlebar interactions."""

    def __init__(self):
        self.window = None

    def toggle_maximized(self):
        if self.window is None:
            return False
        try:
            if IS_MAC:
                import titlebar_macos
                return titlebar_macos.toggle_maximized(
                    getattr(self.window, "native", None))
            if self.window.maximized:
                self.window.restore()
            else:
                self.window.maximize()
            return True
        except Exception as e:
            print("[kotassium] maximize window: %s" % e, flush=True)
            return False

    def close_window(self):
        if self.window is None:
            return False
        self.window.destroy()
        return True

    def minimize_window(self):
        if self.window is None:
            return False
        self.window.minimize()
        return True


def start_nowplaying_watch(port, mpris, notify_tracks):
    """Poll the page's now-playing report; drive MPRIS and notifications."""
    url = "http://127.0.0.1:%d/api/nowplaying" % port
    last = {"title": None}

    def loop():
        while True:
            time.sleep(1.0)
            try:
                with urllib.request.urlopen(url, timeout=1.0) as r:
                    np = json.loads(r.read().decode("utf-8", "replace"))
            except Exception:
                continue
            try:
                if mpris:
                    mpris.update(np)
            except Exception:
                pass
            title = (np.get("t") or "").strip()
            artist = (np.get("a") or "").strip()
            if title and title != last["title"]:
                if last["title"] is not None and notify_tracks and np.get("state") == "playing":
                    notify_mod.notify(title, artist or "Kotassium",
                                      icon=notify_mod.default_icon())
                last["title"] = title

    threading.Thread(target=loop, daemon=True).start()


def show_window(port=None, dev=False, notify_tracks=True, on_start=None, url=None):
    try:
        import webview
    except Exception as e:
        print("pywebview unavailable: %s" % e)
        print("Run ./setup.sh (Linux) or ./setup-macos.sh to create desktop-venv.")
        return 1

    geom = load_geometry()
    kwargs = dict(geom) if geom else {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1]}
    url = normalize_url(url) if url else "http://127.0.0.1:%d/" % port
    params = []
    if not dev:
        # desktop=1 stops the page from polling /api/mtime every 2s: that
        # reload-on-change behaviour is only wanted while editing the UI.
        params.append("desktop=1")
    if IS_MAC:
        # The app page supplies frameless window controls in its top bar.
        params.append("tb=mac")
    if params:
        url += ("&" if "?" in url else "?") + "&".join(params)
    if IS_MAC:
        # Only blank bar background is draggable; controls and search remain interactive.
        try:
            webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
        except Exception:
            pass
    chrome_api = WindowChromeAPI()
    w = webview.create_window(
        "Kotassium",
        url,
        min_size=MIN_SIZE,
        background_color="#000000",
        frameless=IS_MAC,
        easy_drag=False,
        js_api=chrome_api,
        **kwargs
    )
    chrome_api.window = w
    if IS_MAC:
        # Native titlebar removed: the page draws the three controls and calls
        # this JS bridge for close/minimize/maximize.
        try:
            import titlebar_macos
            w.events.before_show += lambda: titlebar_macos.integrate(w)
        except Exception as e:
            print("[kotassium] title bar: %s" % e, flush=True)

    # updater.py runs the swap script once this process is gone; closing the
    # window is what ends it.
    def quit_for_update():
        try:
            w.destroy()
        except Exception:
            pass
    updater.on_installed = quit_for_update

    missing = preflight() if port is not None else []

    # Media keys arrive on the GTK main loop; evaluate_js there would deadlock,
    # so hand every command to a worker thread.
    cmds = queue.Queue()

    def control(name):
        cmds.put(name)

    def control_worker():
        js = {"playpause": "toggle()", "play": "AU.play()", "pause": "AU.pause()",
              "next": "nx()", "previous": "pv()", "stop": "AU.pause()"}
        while True:
            name = cmds.get()
            code = js.get(name)
            if not code:
                continue
            try:
                w.evaluate_js(code)
            except Exception:
                pass

    mpris = None
    if port is not None:
        # Remote mode has no local server to feed MPRIS from, so media keys
        # stay a local-mode feature for now.
        threading.Thread(target=control_worker, daemon=True).start()
        if IS_LINUX:
            try:
                from mpris_linux import MprisLinux
                mpris = MprisLinux(
                    "http://127.0.0.1:%d" % port,
                    {"playpause": lambda: control("playpause"),
                     "play": lambda: control("play"),
                     "pause": lambda: control("pause"),
                     "next": lambda: control("next"),
                     "previous": lambda: control("previous"),
                     "stop": lambda: control("stop"),
                     "quit": lambda: control("stop")},
                )
                if not mpris.conn:
                    mpris = None
            except Exception as e:
                print("[kotassium] MPRIS unavailable: %s" % e)

        start_nowplaying_watch(port, mpris, notify_tracks)

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
    # gui is auto-detected: gtk on Linux, cocoa on macOS. Forcing "gtk" here
    # is what would break macOS. on_start is pywebview's own hook for running
    # a function once the GUI loop is up (used by tools/demo.py).
    # private_mode=True (pywebview's default) makes localStorage null, which
    # would throw away the YouTube-id cache, volume and shuffle every launch.
    webview.start(func=on_start, debug=dev, private_mode=False)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Kotassium desktop app")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--lan", action="store_true",
                    help="bind 0.0.0.0 so phones can connect too")
    ap.add_argument("--dev", action="store_true", help="open the WebKit inspector")
    ap.add_argument("--no-window", action="store_true", help="server only")
    ap.add_argument("--no-notify", action="store_true",
                    help="don't send a notification on track change")
    ap.add_argument("--selftest", action="store_true",
                    help="print what this installation can do, then exit")
    ap.add_argument("--remote", metavar="URL",
                    help="load a shared Kotassium server instead of starting one")
    ap.add_argument("--local", action="store_true",
                    help="ignore the baked-in shared URL and run locally")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    remote = None if a.local else (a.remote or os.environ.get("KOTASSIUM_URL") or baked_url())
    return run(host, a.port, dev=a.dev, no_window=a.no_window,
               notify_tracks=not a.no_notify, remote=normalize_url(remote))


if __name__ == "__main__":
    sys.exit(main())
