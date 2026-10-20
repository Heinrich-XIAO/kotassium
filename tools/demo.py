#!/usr/bin/env python3
"""Record a demo video of the real desktop app (Linux, headless).

    KOTASSIUM_LIB=/tmp/kot-demo \
    xvfb-run -a -s "-screen 0 1200x800x24" \
    dbus-run-session -- desktop-venv/bin/python tools/demo.py out.mp4

Drives the page through pywebview's evaluate_js while ffmpeg grabs the X
display. It also proves the desktop integration live: MPRIS status/controls via
gdbus from a separate process, and the notification payload the watcher sent.
Uses a throwaway library so the user's music is never written to.
"""
import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import desktop  # noqa: E402
import serve_web  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/opencode/kotassium-demo.mp4"
FFMPEG = os.environ.get("DEMO_FFMPEG", "ffmpeg")
W, H = 1200, 800

SEED = {"Hysterical|Lexica": "CxNVRduEljU",
        "Infernoplex|Dimrain47": "Cf5KOTB7Ew8",
        "Daydreamer|meganeko": "UzHZPWZctiQ"}

notes = []
proof = []
ff = [None]

OVERLAY_JS = r"""
window.__proof=function(lines){
  var d=document.getElementById('__proof');
  if(!d){
    d=document.createElement('div');d.id='__proof';
    d.style.cssText='position:fixed;left:16px;bottom:104px;z-index:9999;background:#000000e0;color:#b3ffcc;font:12px/1.55 ui-monospace,Menlo,monospace;padding:10px 14px;border:1px solid #1ed76066;border-radius:8px;max-width:560px;white-space:pre-wrap';
    var h=document.createElement('div');h.textContent='desktop integration (live)';
    h.style.cssText='color:#1ed760;font-weight:700;margin-bottom:4px';
    d.appendChild(h);
    var b=document.createElement('div');b.id='__proofbody';d.appendChild(b);
    document.body.appendChild(d);
  }
  document.getElementById('__proofbody').textContent=lines.join('\n');
};
"""


def js(w, code, default=None):
    try:
        return w.evaluate_js(code)
    except Exception as e:
        print("js error: %r" % (e,), flush=True)
        return default


def wait_js(w, expr, want, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if js(w, expr) == want:
            return True
        time.sleep(0.25)
    return False


def show_proof(w):
    if proof:
        js(w, "window.__proof&&window.__proof(%s)" % json.dumps(proof))


def gdbus(*args):
    r = subprocess.run(["gdbus", "call", "--session",
                        "--dest", "org.mpris.MediaPlayer2.kotassium",
                        "--object-path", "/org/mpris/MediaPlayer2",
                        "--method"] + list(args),
                       capture_output=True, text=True, timeout=10)
    return (r.stdout or r.stderr).strip()


def status():
    return gdbus("org.freedesktop.DBus.Properties.Get",
                 "org.mpris.MediaPlayer2.Player", "PlaybackStatus")


def click(w, sel):
    js(w, "document.querySelector(%s).click()" % json.dumps(sel))


def state(w):
    return js(w, "[AU.currentTime.toFixed(1),AU.paused,(AU.src||'').split('/').pop()].join(' ')")


def wait_playing(w, min_t, timeout=45):
    end = time.time() + timeout
    while time.time() < end:
        t = js(w, "AU.currentTime") or 0
        if t > min_t:
            return True
        time.sleep(0.5)
    return False


def driver(port, w):
    try:
        if not wait_js(w, "document.readyState", "complete", 25):
            print("page never loaded", flush=True)
            return
        js(w, "localStorage.setItem('kot_ytcache', %s); location.reload();"
           % json.dumps(json.dumps(SEED)))
        time.sleep(3.0)
        if not wait_js(w, "document.readyState", "complete", 25):
            print("reload failed", flush=True)
            return
        js(w, OVERLAY_JS)
        time.sleep(1.5)

        ff[0] = subprocess.Popen(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "x11grab",
             "-framerate", "15", "-video_size", "%dx%d" % (W, H),
             "-i", os.environ.get("DISPLAY", ":0"),
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             OUT],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        # x11grab needs a moment before it writes frames; start the story only
        # once recording is actually running.
        end = time.time() + 15
        while time.time() < end:
            if os.path.exists(OUT) and os.path.getsize(OUT) > 2000:
                break
            time.sleep(0.2)
        time.sleep(2.0)
        t0 = time.time()

        def mark(name):
            print("%6.1f %-14s %s" % (time.time() - t0, name, state(w)), flush=True)

        # home -> playlist -> play (cached: starts instantly)
        click(w, ".cardgrid .card")
        time.sleep(3.0)
        click(w, "#bigplay")
        time.sleep(7.0)
        mark("played")

        # seek by clicking the progress bar at 45%
        js(w, """(function(){var p=document.getElementById('prog');
              var r=p.getBoundingClientRect();
              p.dispatchEvent(new MouseEvent('click',{clientX:r.left+r.width*0.45,bubbles:true}));})()""")
        time.sleep(2.5)
        mark("seek")
        click(w, "#playb")
        time.sleep(2.0)
        click(w, "#playb")
        time.sleep(2.0)

        # next track
        click(w, "[title=Next]")
        time.sleep(6.0)
        time.sleep(1.5)
        if notes:
            proof.append("notification: %s — %s" % notes[-1])
            show_proof(w)
        time.sleep(2.0)

        # a track that isn't cached yet: real search + download with progress
        js(w, "var rows=document.querySelectorAll('#tbl .row'); if(rows[8]) rows[8].click();")
        print("fresh track:", wait_playing(w, 8), flush=True)
        mark("fresh")
        for _ in range(10):
            time.sleep(1.0)
            mark("playing")

        # desktop integration, from another process on the session bus
        mark("mpris")
        proof.append("MPRIS: " + status())
        show_proof(w)
        time.sleep(2.5)
        gdbus("org.mpris.MediaPlayer2.Player.PlayPause")
        time.sleep(1.5)
        proof.append("media key PlayPause -> " + status())
        show_proof(w)
        time.sleep(3.5)
        gdbus("org.mpris.MediaPlayer2.Player.PlayPause")
        time.sleep(2.5)
        proof.append("media key PlayPause -> " + status())
        show_proof(w)
        time.sleep(2.5)

        # search lane
        js(w, "document.getElementById('q').value='meganeko daydreamer';doSearch()")
        time.sleep(5.0)
    except Exception as e:
        print("driver error: %r" % (e,), flush=True)
    finally:
        time.sleep(1.0)
        if ff[0]:
            try:
                ff[0].stdin.write(b"q")
                ff[0].stdin.flush()
                ff[0].wait(20)
            except Exception:
                ff[0].kill()
        print("recorded %s" % OUT, flush=True)
        try:
            w.destroy()
        except Exception:
            pass


def main():
    orig_notify = desktop.notify_mod.notify

    def record_notify(title, body):
        notes.append((title, body))
        orig_notify(title, body)

    desktop.notify_mod.notify = record_notify

    srv = serve_web.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    desktop.show_window(port, dev=False, notify_tracks=True,
                        on_start=lambda: driver(port, holder[0]))
    srv.shutdown()
    return 0


if __name__ == "__main__":
    import webview
    orig = webview.create_window
    holder = [None]

    def capture(*a, **k):
        holder[0] = orig(*a, **k)
        return holder[0]

    webview.create_window = capture
    sys.exit(main())
