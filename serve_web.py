#!/usr/bin/env python3
"""serve_web.py - Kotassium as a plain website for fast iteration."""
import argparse, base64, hashlib, hmac, html, http.cookies, ipaddress, json, os, re, shutil, signal, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request

import updater
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def _base_dir():
    """Project root. Inside a py2app bundle __file__ lives several levels down
    (Contents/Resources/lib/python3.x), so walk up until web/index.html is
    found. KOTASSIUM_BASE wins: on Android the page is unpacked into app
    storage, so __file__ (inside the APK) says nothing about where it is."""
    env = os.environ.get("KOTASSIUM_BASE")
    if env:
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    cand = here
    for _ in range(6):
        if os.path.isfile(os.path.join(cand, "web", "index.html")):
            return cand
        cand = os.path.dirname(cand)
    return here


BASE = _base_dir()
HOME = os.path.expanduser("~")
LIB = os.path.expanduser(os.environ.get("KOTASSIUM_LIB", "~/Music/Kotassium"))
if LIB.startswith("~"):
    # Android has no home directory in the Unix sense. The shell always passes
    # KOTASSIUM_LIB, but never create a directory literally called "~".
    LIB = os.path.join(tempfile.gettempdir(), "Kotassium")
STATE = os.path.join(LIB, "webstate")
os.makedirs(LIB, exist_ok=True)
os.makedirs(STATE, exist_ok=True)
COVER_DIR = os.path.join(STATE, "covers")
os.makedirs(COVER_DIR, exist_ok=True)
COVERS_JSON = os.path.join(STATE, "covers.json")
PORT = 8421
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"

# --------------------------------------------------------------- audio files
# Desktop downloads are converted to mp3 by ffmpeg. Android has no ffmpeg, so
# it keeps whatever yt-dlp fetched (usually m4a). The library, the /lib/ route
# and the player all work off the extension rather than assuming mp3.
AUDIO_EXTS = (".mp3", ".m4a", ".webm", ".opus", ".ogg", ".aac", ".flac")
AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".webm": "audio/webm",
               ".opus": "audio/ogg", ".ogg": "audio/ogg", ".aac": "audio/aac",
               ".flac": "audio/flac"}

def audio_ext(path):
    return os.path.splitext(path)[1].lower()

def track_path(tid):
    """The file for a track id in any supported format, or None."""
    for ext in AUDIO_EXTS:
        p = os.path.join(LIB, tid + ext)
        if os.path.exists(p):
            return p
    return None

def track_name(path):
    """Track id for a library file, or None for previews and stray files."""
    base = os.path.basename(path)
    if base.startswith(".") or "_preview." in base:
        return None
    if audio_ext(base) not in AUDIO_EXTS:
        return None
    return os.path.splitext(base)[0]

# ------------------------------------------------------------------ auth
# Off by default (the desktop app is loopback-only). Set KOTASSIUM_PASSWORD
# when the server is exposed through a tunnel: the public URL then needs a
# cookie from /login, and every API/audio route is closed without one.
PASSWORD = os.environ.get("KOTASSIUM_PASSWORD", "")
AUTH = bool(PASSWORD)
PUBLIC_PATHS = ("/login", "/api/health", "/manifest.webmanifest", "/sw.js",
                "/icons/")

def _session_token():
    """HMAC of the password and a salt kept next to the library state, so
    sessions survive restarts but die when the password changes."""
    if not AUTH:
        return ""
    salt_file = os.path.join(STATE, "auth.salt")
    try:
        with open(salt_file, "rb") as f:
            salt = f.read()
    except Exception:
        salt = os.urandom(16)
        fd = os.open(salt_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(salt)
    key = hashlib.sha256(b"kotassium:" + PASSWORD.encode() + b":" + salt).digest()
    return hmac.new(key, b"session-v1", hashlib.sha256).hexdigest()

SESSION = _session_token()

_fails = {}
_fail_lock = threading.Lock()

def login_blocked(ip):
    now = time.time()
    with _fail_lock:
        n, until = _fails.get(ip, (0, 0))
    return n >= 5 and now < until

def login_note(ip, ok):
    with _fail_lock:
        if ok:
            _fails.pop(ip, None)
            return
        n, until = _fails.get(ip, (0, 0))
        now = time.time()
        if now >= until:
            n = 0
        _fails[ip] = (n + 1, now + 60)


EXTRA_BIN = ["/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin")]

def which(name):
    """shutil.which, plus the places a GUI-launched app's PATH usually misses."""
    found = shutil.which(name)
    if found:
        return found
    for d in EXTRA_BIN:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None

def find_ytdlp():
    """Locate a usable yt-dlp: explicit env, bundled copy, project venv, PATH,
    then the module."""
    env = os.environ.get("KOTASSIUM_YTDLP")
    if env and env != "inproc":
        return [env]
    # Inside Kotassium.app the standalone binary ships next to the web assets.
    for rel in (("bin", "yt-dlp"), ("yt-dlp",)):
        p = os.path.join(BASE, *rel)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return [p]
    local = os.path.join(BASE, "venv", "bin", "yt-dlp")
    if os.path.exists(local):
        return [local]
    exe = which("yt-dlp")
    if exe:
        return [exe]
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        return None

YTDLP = find_ytdlp()
FFMPEG = which("ffmpeg")
# Android (Chaquopy) embeds CPython but cannot exec a yt-dlp binary, and has no
# ffmpeg. There the download runs in this process and keeps yt-dlp's own
# container. Desktops keep the subprocess + mp3 conversion path.
YTDLP_INPROC = (os.environ.get("KOTASSIUM_YTDLP") == "inproc"
                or (YTDLP is None and hasattr(sys, "getandroidapilevel")))
LINKS = os.path.join(STATE, "links.json")
_lock = threading.RLock()

_procs = set()
_procs_lock = threading.Lock()

def _kill_proc(p):
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        else:
            p.kill()
    except Exception:
        try:
            p.kill()
        except Exception:
            pass

def run_proc(cmd, timeout, **kw):
    """Run a child process, tracking it so a window close can kill it."""
    if os.name == "posix":
        kw.setdefault("start_new_session", True)
    p = subprocess.Popen(cmd, **kw)
    with _procs_lock:
        _procs.add(p)
    try:
        return p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_proc(p)
        raise
    finally:
        with _procs_lock:
            _procs.discard(p)

def stop_children():
    with _procs_lock:
        procs = list(_procs)
    for p in procs:
        _kill_proc(p)
        try:
            p.wait(timeout=2)
        except Exception:
            pass
        with _procs_lock:
            _procs.discard(p)

_jobs = {}
_jobs_lock = threading.Lock()
_job_seq = 0

# Optional hook, called with True when a download job starts and with False
# once none are left running. The Android shell holds a wake lock across a
# download through it; on every other platform it stays None.
JOB_HOOK = None

def jobs_active():
    """True while any download job is queued or running.

    The Android shell polls this to hold a wake lock: the downloads run in
    the same process, so Android freezes them with the screen off unless
    something keeps the CPU awake.
    """
    with _jobs_lock:
        return any(j["status"] in ("queued", "running") for j in _jobs.values())

def _job_hook_fire():
    if JOB_HOOK:
        try:
            JOB_HOOK(jobs_active())
        except Exception:
            pass

def job_new(label):
    global _job_seq
    now = time.time()
    with _jobs_lock:
        _job_seq += 1
        jid = str(_job_seq)
        _jobs[jid] = {"id": jid, "label": label, "status": "queued", "pct": 0.0,
                      "file": None, "error": None, "ts": now}
        for k in [k for k, v in _jobs.items() if now - v["ts"] > 3600]:
            _jobs.pop(k, None)
    return jid

def job_update(jid, **kw):
    with _jobs_lock:
        j = _jobs.get(jid)
        if j:
            j.update(kw)
            j["ts"] = time.time()

def job_get(jid):
    with _jobs_lock:
        j = _jobs.get(jid)
        return dict(j) if j else None

def job_running(label):
    with _jobs_lock:
        for j in _jobs.values():
            if j["label"] == label and j["status"] in ("queued", "running"):
                return j["id"]
    return None

def job_start_ytdl(vid):
    vid = re.sub(r"[^A-Za-z0-9_-]", "", vid or "")
    if not vid:
        raise RuntimeError("bad id")
    existing = job_running(vid)
    if existing:
        return existing
    jid = job_new(vid)
    _job_hook_fire()

    def work():
        try:
            job_update(jid, status="running")
            f = ytdl(vid, lambda p: job_update(jid, pct=round(p, 1)))
            job_update(jid, status="done", pct=100.0, file=f)
        except Exception as e:
            job_update(jid, status="error", error=str(e)[:200])
        finally:
            _job_hook_fire()

    threading.Thread(target=work, daemon=True).start()
    return jid

_now_lock = threading.Lock()
_now = {"t": "", "a": "", "album": "", "cover": "", "ms": 0, "pos": 0,
        "state": "stopped", "ts": 0}

def set_now(d):
    with _now_lock:
        for k in ("t", "a", "album", "cover", "ms", "pos", "state"):
            if k in d:
                _now[k] = d[k]
        _now["ts"] = int(time.time())

def get_now():
    with _now_lock:
        return dict(_now)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}

# Public names this server answers to when it sits behind a tunnel or
# `tailscale serve` (comma separated, e.g. "fedora-1.tail8e937f.ts.net").
# The guard still rejects every other hostname, so DNS rebinding stays dead.
EXTRA_HOSTS = tuple(h.strip().lower()
                    for h in os.environ.get("KOTASSIUM_HOSTS", "").split(",")
                    if h.strip())
def _hostname(host_header):
    try:
        return (urllib.parse.urlsplit("//" + (host_header or "").strip()).hostname or "").lower()
    except Exception:
        return ""

def host_allowed(host_header):
    """Allow loopback names, IP literals and the configured tunnel names;
    reject every other hostname (DNS rebinding)."""
    h = _hostname(host_header)
    if h in LOCAL_HOSTS or h in EXTRA_HOSTS:
        return True
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False

def origin_allowed(origin, host_header):
    """Same-origin only. Requests without an Origin (curl, tests) are allowed."""
    if not origin:
        return True
    try:
        o = urllib.parse.urlsplit(origin)
    except Exception:
        return False
    if o.scheme not in ("http", "https"):
        return False
    return o.netloc.lower() == (host_header or "").lower()

def read_links():
    with _lock:
        try:
            return json.load(open(LINKS))
        except Exception:
            return []

def write_links(data):
    with _lock:
        tmp = LINKS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, LINKS)

def find_link(url):
    for e in read_links():
        if e.get("url") == url:
            return e
    return None

def save_link(url, jr):
    with _lock:
        links = read_links()
        links = [e for e in links if e.get("url") != url]
        e = dict(jr)
        e["url"] = url
        e["ts"] = int(time.time())
        links.insert(0, e)
        write_links(links)

def drop_link(url):
    with _lock:
        write_links([e for e in read_links() if e.get("url") != url])

def follow(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")

def yt_search(q):
    # Scrape YouTube's public results page for video ids (no API key).
    UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    try:
        req = urllib.request.Request(
            "https://www.youtube.com/results?search_query=" + urllib.parse.quote(q) + "&hl=en&gl=US",
            headers={"User-Agent": UA, "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
        m = re.search(r"var ytInitialData = (\{.*?\});</script>", html, re.S)
        if not m:
            return {"results": []}
        d = json.loads(m.group(1))
        out = []

        def walk(o):
            if isinstance(o, dict):
                v = o.get("videoRenderer")
                if isinstance(v, dict) and v.get("videoId"):
                    title = ""
                    tit = v.get("title") or {}
                    runs = tit.get("runs") or []
                    if runs and isinstance(runs[0], dict):
                        title = runs[0].get("text", "")
                    if not title:
                        title = tit.get("simpleText") or ""
                    if title:
                        dur = 0
                        parts = ((v.get("lengthText") or {}).get("simpleText") or "").split(":")
                        try:
                            if len(parts) == 3: dur = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                            elif len(parts) == 2: dur = int(parts[0]) * 60 + int(parts[1])
                        except Exception:
                            dur = 0
                        author = ""
                        orr = (v.get("ownerText") or {}).get("runs") or []
                        if orr and isinstance(orr[0], dict):
                            author = orr[0].get("text", "YouTube")
                        out.append({"source": "youtube", "title": title, "artist": author,
                                    "dur": dur, "id": v.get("videoId"), "full": True})
                for x in o.values():
                    walk(x)
            elif isinstance(o, list):
                for x in o:
                    walk(x)

        walk(d)
        return {"results": out[:12]}
    except Exception:
        return {"results": []}

def dz_search(q):
    try:
        url = "https://api.deezer.com/search?q=" + urllib.parse.quote(q) + "&limit=25"
        _, body = follow(url)
        j = json.loads(body)
        out = []
        for tk in (j.get("data") or []):
            out.append({"source": "deezer", "title": tk.get("title", ""),
                        "artist": tk.get("artist", {}).get("name", ""), "dur": tk.get("duration", 0),
                        "id": str(tk.get("id", "")), "preview": tk.get("preview", ""),
                        "full": False, "cover": tk.get("album", {}).get("cover", "")})
        return {"results": out}
    except Exception:
        return {"results": []}

def sc_search(q):
    return {"results": []}

def ia_search(q):
    return {"results": []}

def dl_file(src, tid, url):
    f = os.path.join(LIB, tid + ".mp3")
    if os.path.exists(f):
        return f
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(f, "wb") as out:
        out.write(r.read())
    return f

def sc_resolve(tid):
    return ""

def _make_preview(out, vid):
    """A 5s clip so playback starts instantly. Needs ffmpeg; without it the
    /lib/ route redirects the preview to the full track instead."""
    if not FFMPEG:
        return
    prev = os.path.join(LIB, vid + "_preview.mp3")
    try:
        run_proc([FFMPEG, "-y", "-i", out, "-t", "5", "-c", "copy", prev],
                 timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def _take_download(vid, progress=None):
    """Move the finished .yt_<id>.<ext> into place and return its basename."""
    for f in sorted(os.listdir(LIB)):
        if f.startswith(".yt_" + vid + "."):
            src = os.path.join(LIB, f)
            if os.path.exists(src):
                out = os.path.join(LIB, vid + audio_ext(f))
                os.replace(src, out)
                _make_preview(out, vid)
                if progress:
                    progress(100.0)
                return os.path.basename(out)
    return None

def _ytdl_inproc(vid, progress=None):
    """Download without a subprocess (Android).

    ffmpeg is optional here: with it the track becomes mp3 like on desktop,
    without it yt-dlp's own audio container (usually m4a) is kept. The page
    plays either one.
    """
    import yt_dlp

    last = [0.0]

    def hook(d):
        if not progress:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            if total:
                last[0] = max(last[0], min(99.0, got * 100.0 / total))
                progress(round(last[0], 1))
        elif d.get("status") == "finished":
            progress(99.0)

    opts = {
        "outtmpl": os.path.join(LIB, ".yt_" + vid + ".%(ext)s"),
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "noplaylist": True,
        "nooverwrites": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "socket_timeout": 30,
        "retries": 3,
    }
    if FFMPEG:
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                   "preferredcodec": "mp3",
                                   "preferredquality": "128"}]
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download(["https://www.youtube.com/watch?v=" + vid])
    name = _take_download(vid, progress)
    if not name:
        raise RuntimeError("yt-dlp failed")
    return name

def ytdl(vid, progress=None):
    vid = re.sub(r"[^A-Za-z0-9_-]", "", vid or "")
    existing = track_path(vid)
    if existing:
        if progress:
            progress(100.0)
        return os.path.basename(existing)
    if YTDLP_INPROC:
        return _ytdl_inproc(vid, progress)
    if not YTDLP:
        raise RuntimeError("yt-dlp not found")
    if not FFMPEG:
        raise RuntimeError("ffmpeg not found - needed to convert downloads to mp3")
    tmp = os.path.join(LIB, ".yt_" + vid + ".%(ext)s")
    cmd = YTDLP + ["-x", "--audio-format", "mp3", "--audio-quality", "128K",
                   "--no-overwrites", "--newline", "-o", tmp,
                   "https://www.youtube.com/watch?v=" + vid]
    if os.name == "posix":
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, start_new_session=True)
    else:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
    with _procs_lock:
        _procs.add(p)
    watchdog = threading.Timer(300, _kill_proc, [p])
    watchdog.start()
    try:
        for line in p.stdout:
            if progress:
                m = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
                if m:
                    progress(float(m.group(1)))
        p.wait()
    finally:
        watchdog.cancel()
        with _procs_lock:
            _procs.discard(p)
    name = _take_download(vid, progress)
    if not name:
        raise RuntimeError("yt-dlp failed")
    return name

def cover_local(url):
    if not url or url.startswith("/cover/"):
        return url
    try:
        m = json.load(open(COVERS_JSON))
    except Exception:
        m = {}
    if url in m:
        return "/cover/" + m[url]
    return url

def handle_post(path, params, raw, hdr):
    pp = urllib.parse.parse_qs(params, keep_blank_values=True)
    if path == "/api/links/drop":
        drop_link(pp.get("url", [""])[0])
        return 200, "application/json", b'{"ok":true}', None, False
    if path == "/api/nowplaying":
        try:
            set_now(json.loads(raw.decode("utf-8", "replace") or "{}"))
        except Exception:
            pass
        return 200, "application/json", b'{"ok":true}', None, False
    if path == "/api/update":
        try:
            st = updater.start_install()
        except Exception as e:
            st = dict(updater.status(), error=str(e)[:200])
        return 200, "application/json", json.dumps(st).encode(), None, False
    if path == "/api/cover/cache":
        try:
            j = json.loads(raw.decode("utf-8", "replace"))
            url = j.get("url") or ""
            data = j.get("data") or ""
            if not url or not data:
                return 400, "application/json", b'{"error":"missing"}', None, False
            b = base64.b64decode(data.split(",")[-1])
            ext = "jpg"
            low = url.lower()
            if ".png" in low or b.startswith(b"\x89PNG"):
                ext = "png"
            elif ".webp" in low or b.startswith(b"RIFF"):
                ext = "webp"
            elif ".gif" in low or b.startswith(b"GIF"):
                ext = "gif"
            elif ".jpg" in low or ".jpeg" in low or b.startswith(b"\xff\xd8"):
                ext = "jpg"
            key = hashlib.sha256(url.encode()).hexdigest()[:16]
            out = os.path.join(COVER_DIR, key + "." + ext)
            with open(out, "wb") as f:
                f.write(b)
            try:
                m = json.load(open(COVERS_JSON))
            except Exception:
                m = {}
            m[url] = key + "." + ext
            with open(COVERS_JSON, "w") as f:
                json.dump(m, f)
            return 200, "application/json", json.dumps({"ok": True, "key": key, "file": key + "." + ext}).encode(), None, False
        except Exception as e:
            return 400, "application/json", json.dumps({"error": str(e)[:200]}).encode(), None, False
    return 404, "text/plain", b"nope", None, False

def handle(path, params, hdr):
    pp = urllib.parse.parse_qs(params, keep_blank_values=True)
    def one(k, d=""):
        return pp.get(k, [d])[0]
    if path.startswith("/cover/"):
        name = os.path.basename(urllib.parse.unquote(path[len("/cover/"):]))
        f = os.path.join(COVER_DIR, name)
        if os.path.exists(f):
            ext = name.rsplit(".", 1)[-1].lower()
            ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                     "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")
            return 200, ctype, open(f, "rb").read(), None, False
        return 404, "text/plain", b"nope", None, False
    if path == "/login":
        q = urllib.parse.parse_qs(params)
        nxt = safe_next((q.get("next") or ["/"])[0])
        return 200, "text/html; charset=utf-8", login_page(next_url=nxt).encode(), None, False
    if path == "/manifest.webmanifest":
        return 200, "application/manifest+json", open(os.path.join(BASE, "web", "manifest.webmanifest"), "rb").read(), None, False
    if path == "/sw.js":
        return 200, "application/javascript", open(os.path.join(BASE, "web", "sw.js"), "rb").read(), {"Cache-Control": "no-cache"}, False
    if path.startswith("/icons/"):
        name = os.path.basename(path)
        f = os.path.join(BASE, "web", "icons", name)
        if os.path.isfile(f) and name.lower().endswith(".png"):
            return 200, "image/png", open(f, "rb").read(), {"Cache-Control": "max-age=86400"}, False
        return 404, "text/plain", b"nope", None, False
    if path in ("/", "/index.html"):
        html = open(os.path.join(BASE, "web", "index.html"), "rb").read().decode("utf-8", "replace")
        return 200, "text/html; charset=utf-8", html.encode(), None, False
    if path == "/api/search":
        q, src = one("q"), one("src", "all")
        out, errs = [], {}
        lanes = []
        if src not in ("deezer", "archive"):
            lanes.append(("youtube", yt_search))
        if src not in ("youtube", "archive"):
            lanes.append(("deezer", dz_search))
        if src in ("all", "soundcloud"):
            lanes.append(("soundcloud", sc_search))
        if src in ("all", "archive"):
            lanes.append(("archive", ia_search))
        for name, fn in lanes:
            try:
                j = fn(q)
                out.extend(j.get("results", []))
            except Exception as e:
                errs[name] = str(e)[:90]
        return 200, "application/json", json.dumps({"results": out, "errors": errs}).encode(), None, False
    if path == "/api/play":
        src, tid = one("src"), one("id")
        if src == "deezer":
            f = dl_file("deezer", tid, one("preview"))
            return 200, "audio/mpeg", open(f, "rb").read(), None, False
        if src == "soundcloud":
            f = dl_file("soundcloud", tid, sc_resolve(tid))
            return 200, "audio/mpeg", open(f, "rb").read(), None, False
        if src == "archive":
            return 302, None, b"", {"Location": "https://archive.org/download/" + tid + "/" + tid + "_vbr.mp3"}, False
        return 400, "text/plain", b"bad src", None, False
    if path == "/api/download":
        src, tid = one("src"), one("id")
        return 200, "application/json", b'{"error":"youtube downloads need the extractor lane"}', None, False
    if path == "/api/recommend":
        return 200, "application/json", b'{"results":[]}', None, False
    if path == "/api/spot/resolve":
        link = one("url")
        try:
            if not re.match(r"(?i)https?://\S+", link or "") or len(link) > 2000:
                raise RuntimeError("need an http(s) link")
            # Only spotify hosts get this far: resolve() follows short links
            # (spotify.link/...) by fetching them, so a bare URL must not turn
            # the server into a fetch-any-URL proxy.
            if not re.search(r"(?i)spotify\.com/|spotify\.link/", link):
                raise RuntimeError("need a spotify playlist, album, or track link")
            import spotify_get
            m = re.search(r"(?:open\.)?spotify\.com/(?:intl-[a-z]{2}/)?(playlist|album|track)/([A-Za-z0-9]+)", link)
            name, tracks = spotify_get.resolve(link)
            fmt = [{"t": t["title"], "a": t["artist"], "ms": int(round(t.get("dur", 0) * 1000)),
                    "album": t.get("album") or "", "cover": cover_local(t.get("cover") or "")} for t in tracks]
            # Short links (spotify.link/...) never match the regex above, so
            # fall back to a guess from the track count rather than crashing
            # on a resolve that actually succeeded.
            kind = m.group(1) if m else ("track" if len(fmt) == 1 else "playlist")
            jr = {"type": kind, "name": name, "tracks": fmt, "count": len(fmt),
                  "total": len(fmt), "truncated": False, "partial": False}
            save_link(link, jr)
            return 200, "application/json", json.dumps(jr).encode(), None, False
        except Exception as e:
            return 200, "application/json", json.dumps({"error": "resolve_failed", "error_description": str(e)[:200]}).encode(), None, False
    if path == "/api/spot/playlist":
        return 200, "application/json", b'{"tracks":[]}', None, False
    if path == "/api/links":
        slim = []
        for e in read_links():
            o = {k: e[k] for k in ("url", "name", "count", "ts") if k in e}
            if "total" in e:
                o["total"] = e["total"]
            o["partial"] = bool(e.get("partial"))
            slim.append(o)
        return 200, "application/json", json.dumps({"links": slim}).encode(), None, False
    if path == "/api/links/get":
        e = find_link(one("url"))
        if not e:
            return 200, "application/json", b'{"error":"not_found"}', None, False
        for t in (e.get("tracks") or []):
            if isinstance(t, dict) and t.get("cover"):
                t["cover"] = cover_local(t["cover"])
        return 200, "application/json", json.dumps(e).encode(), None, False
    if path == "/api/health":
        return 200, "application/json", json.dumps({"ok": True, "app": "kotassium", "pid": os.getpid()}).encode(), None, False
    if path == "/api/ytdl":
        try:
            return 200, "application/json", json.dumps({"job": job_start_ytdl(one("id"))}).encode(), None, False
        except Exception as e:
            return 200, "application/json", json.dumps({"error": str(e)[:200]}).encode(), None, False
    if path == "/api/job":
        j = job_get(one("id"))
        if not j:
            return 200, "application/json", b'{"error":"not_found"}', None, False
        return 200, "application/json", json.dumps(j).encode(), None, False
    if path == "/api/nowplaying":
        return 200, "application/json", json.dumps(get_now()).encode(), None, False
    if path == "/api/update":
        return 200, "application/json", json.dumps(updater.status()).encode(), None, False
    if path == "/api/manifest":
        try:
            return 200, "application/json", open(os.path.join(STATE, "manifest.json"), "rb").read(), None, False
        except Exception:
            return 200, "application/json", b"{}", None, False
    if path == "/api/library":
        out = []
        for f in sorted(os.listdir(LIB)):
            name = track_name(f)
            if name:
                out.append({"name": name, "size": os.path.getsize(os.path.join(LIB, f))})
        return 200, "application/json", json.dumps({"library": out}).encode(), None, False
    if path.startswith("/lib/"):
        base = os.path.basename(urllib.parse.unquote(path[5:]))
        f = os.path.join(LIB, base)
        # on-demand preview clip generation
        if (not os.path.exists(f)) and base.endswith("_preview.mp3"):
            vid = base[:-len("_preview.mp3")]
            src = track_path(vid)
            if src and FFMPEG:
                try:
                    run_proc([FFMPEG, "-y", "-i", src, "-t", "5", "-c", "copy", f],
                             timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            elif src:
                # No ffmpeg (Android): there is no preview clip, so point the
                # player straight at the full track instead of a 404.
                return 302, None, b"", {"Location": "/lib/" + urllib.parse.quote(os.path.basename(src))}, False
        if os.path.exists(f):
            ctype = AUDIO_TYPES.get(audio_ext(base), "application/octet-stream")
            size = os.path.getsize(f)
            rng = (hdr.get("Range") or "").replace("bytes=", "")
            start, end = 0, size - 1
            code = 200
            extra = {"Accept-Ranges": "bytes"}
            if rng and "-" in rng:
                s, e = (rng.split("-") + [""])[:2]
                if s:
                    start = int(s)
                if e:
                    end = min(int(e), size - 1)
                start = max(0, min(start, size - 1))
                code = 206
                extra["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
            end = min(end, size - 1)
            with open(f, "rb") as fh:
                fh.seek(start)
                body = fh.read(end - start + 1)
            return code, ctype, body, extra, False
        return 404, "text/plain", b"nope", None, False
    if path == "/api/mtime":
        try:
            return 200, "application/json", json.dumps({"mtime": os.path.getmtime(os.path.join(BASE, "web", "index.html"))}).encode(), None, False
        except Exception:
            return 200, "application/json", b'{"mtime":0}', None, False
    return 404, "text/plain", b"nope", None, False

def login_page(error="", next_url="/"):
    msg = ('<p class=err>%s</p>' % error) if error else ""
    return ("""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Kotassium</title><style>
*{box-sizing:border-box}body{margin:0;height:100vh;display:grid;place-items:center;
background:#121212;color:#fff;font:14px system-ui,sans-serif}
form{background:#181818;border:1px solid #ffffff1f;border-radius:12px;padding:28px;
width:min(360px,90vw);display:flex;flex-direction:column;gap:12px}
h1{font-size:18px;margin:0 0 4px}p{margin:0;color:#b3b3b3;font-size:13px}
input{background:#242424;border:1px solid #ffffff26;color:#fff;border-radius:8px;
padding:10px 12px;font:inherit}
button{background:#1ed760;color:#000;border:0;border-radius:999px;padding:10px;
font:inherit;font-weight:700;cursor:pointer}
.err{color:#ff6b6b}</style></head><body>
<form method=post action=/login>
<h1>Kotassium</h1><p>This library is private. Enter the family password.</p>{MSG}
<input type=hidden name=next value="{NEXT}">
<input type=password name=password placeholder=Password autofocus autocomplete=current-password>
<button type=submit>Open library</button>
</form></body></html>""").replace("{MSG}", msg).replace("{NEXT}", html.escape(next_url, quote=True))


def safe_next(value):
    """Only local paths: `next` comes from the URL and must not become an
    open redirect."""
    value = (value or "").strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


class H(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body, extra=None):
        self._code = code
        self.send_response(code)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        if not AUTH:
            return True
        try:
            jar = http.cookies.SimpleCookie(self.headers.get("Cookie") or "")
            morsel = jar.get("kot_session")
            return bool(morsel) and hmac.compare_digest(morsel.value, SESSION)
        except Exception:
            return False

    def _guard(self, mutating):
        """Reject DNS-rebinding hosts, cross-origin writes and, when a
        password is configured, requests without a session cookie."""
        if not host_allowed(self.headers.get("Host")):
            return "forbidden host"
        if mutating and not origin_allowed(self.headers.get("Origin"), self.headers.get("Host")):
            return "forbidden origin"
        if not self._authed():
            path = urllib.parse.urlsplit(self.path).path
            if not any(path == p or (p.endswith("/") and path.startswith(p))
                       for p in PUBLIC_PATHS):
                return "auth"
        return None

    def _handle_login(self, raw):
        ip = self.client_address[0]
        form = urllib.parse.parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
        nxt = safe_next((form.get("next") or ["/"])[0])
        if login_blocked(ip):
            return self._send(429, "text/html; charset=utf-8",
                              login_page("Too many attempts - wait a minute.", nxt).encode())
        given = (form.get("password") or [""])[0]
        if not hmac.compare_digest(given.encode(), PASSWORD.encode()):
            login_note(ip, False)
            return self._send(401, "text/html; charset=utf-8",
                              login_page("Wrong password.", nxt).encode())
        login_note(ip, True)
        # A tunnel terminates TLS and forwards plain HTTP, so the cookie is
        # Secure whenever a proxy is in front, whether or not it says so.
        secure = ((self.headers.get("X-Forwarded-Proto") or "").lower() == "https"
                  or _hostname(self.headers.get("Host")) in EXTRA_HOSTS)
        cookie = "kot_session=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000%s" % (
            SESSION, "; Secure" if secure else "")
        self._send(303, "text/plain", b"", {"Location": nxt, "Set-Cookie": cookie})

    def do_GET(self):
        try:
            bad = self._guard(False)
            if bad == "auth":
                path = urllib.parse.urlsplit(self.path).path
                if path.startswith(("/api/", "/lib/", "/cover/")):
                    return self._send(401, "application/json", b'{"error":"auth"}')
                # Keep the destination (and ?desktop=1) across the login form.
                want = path + (("?" + urllib.parse.urlsplit(self.path).query)
                               if urllib.parse.urlsplit(self.path).query else "")
                return self._send(303, "text/plain", b"", {
                    "Location": "/login?next=" + urllib.parse.quote(want, safe="")})
            if bad:
                return self._send(403, "text/plain", bad.encode())
            parts = urllib.parse.urlsplit(self.path)
            code, ctype, body, extra, _ = handle(parts.path, parts.query, self.headers)
            self._send(code, ctype, body, extra)
        except Exception:
            try:
                self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except Exception:
                pass

    def do_POST(self):
        try:
            bad = self._guard(True)
            if bad == "auth":
                return self._send(401, "application/json", b'{"error":"auth"}')
            if bad:
                return self._send(403, "text/plain", bad.encode())
            parts = urllib.parse.urlsplit(self.path)
            n = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(n) if n else b""
            if parts.path == "/login":
                return self._handle_login(raw)
            if parts.path == "/logout":
                self._send(303, "text/plain", b"", {
                    "Location": "/login",
                    "Set-Cookie": "kot_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"})
                return
            code, ctype, body, extra, _ = handle_post(parts.path, parts.query, raw, self.headers)
            self._send(code, ctype, body, extra)
        except Exception:
            try:
                self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except Exception:
                pass

    def log_message(self, fmt, *a):
        try:
            print("[%s] %s %s -> %s" % (time.strftime("%H:%M:%S"), self.client_address[0], self.path, getattr(self, "_code", "?")), flush=True)
        except Exception:
            pass

def make_server(host="0.0.0.0", port=PORT):
    """Build (but do not start) the HTTP server. Import-safe for desktop.py."""
    return ThreadingHTTPServer((host, port), H)

_local_server = None
_local_lock = threading.Lock()

def serve_local(port=PORT):
    """Start the server on loopback in a background thread and return the port.

    This is what the Android shell calls: same page, same server, no window
    manager and no shell loop to block. Calling it twice is a no-op, so an
    activity restart does not fight over the port.
    """
    global _local_server
    with _local_lock:
        if _local_server is None:
            _local_server = make_server("127.0.0.1", port)
            threading.Thread(target=_local_server.serve_forever, daemon=True).start()
        return _local_server.server_address[1]

def main(argv=None):
    ap = argparse.ArgumentParser(description="Kotassium local server")
    ap.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args(argv)
    if not a.host.startswith("127.") and not a.host.startswith("::1") and a.host != "localhost":
        print("[kotassium-web] WARNING: bound to %s - anyone who can reach this port can read and delete playlists" % a.host, flush=True)
    srv = make_server(a.host, a.port)
    print("[kotassium-web] UI: " + os.path.join(BASE, "web", "index.html"))
    print("[kotassium-web] lib: " + LIB)
    print("[kotassium-web] http://%s:%d/" % (a.host, a.port), flush=True)
    if YTDLP:
        print("[kotassium-web] yt-dlp: " + " ".join(YTDLP), flush=True)
    else:
        print("[kotassium-web] yt-dlp missing - youtube full tracks disabled (deezer previews only)", flush=True)
    if not FFMPEG:
        print("[kotassium-web] ffmpeg missing - downloads and preview clips disabled", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_children()
        srv.server_close()

if __name__ == "__main__":
    main()
