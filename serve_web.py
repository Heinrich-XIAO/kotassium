#!/usr/bin/env python3
"""serve_web.py - Kotassium as a plain website for fast iteration."""
import json, os, re, subprocess, sys, threading, time, urllib.parse, urllib.request, hashlib, base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(BASE, "app", "assets", "index.html")
HOME = os.path.expanduser("~")
LIB = os.path.join(HOME, "Music", "Kotassium")
STATE = os.path.join(LIB, "webstate")
os.makedirs(LIB, exist_ok=True)
os.makedirs(STATE, exist_ok=True)
COVER_DIR = os.path.join(STATE, "covers")
os.makedirs(COVER_DIR, exist_ok=True)
COVERS_JSON = os.path.join(STATE, "covers.json")
PORT = 8421
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"

YTDLP = os.path.join(BASE, "venv", "bin", "yt-dlp")
LINKS = os.path.join(STATE, "links.json")
_lock = threading.RLock()

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
    # minimal: delegate to youtubei not implemented; return []
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

def ytdl(vid):
    vid = re.sub(r"[^A-Za-z0-9_-]", "", vid or "")
    out = os.path.join(LIB, vid + ".mp3")
    if os.path.exists(out):
        return os.path.basename(out)
    # use yt-dlp
    tmp = os.path.join(LIB, ".yt_" + vid + ".%(ext)s")
    subprocess.run([YTDLP, "-x", "--audio-format", "mp3", "--audio-quality", "128K",
                    "--no-overwrites", "-o", tmp, "https://www.youtube.com/watch?v=" + vid],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    for f in os.listdir(LIB):
        if f.startswith(".yt_" + vid + "."):
            src = os.path.join(LIB, f)
            if os.path.exists(src):
                os.replace(src, out)
                return os.path.basename(out)
    raise RuntimeError("yt-dlp failed")

def fetch_song_count(link):
    return 0

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

def handle_post(path, raw, hdr):
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
    if path in ("/", "/index.html"):
        html = open(os.path.join(BASE, "web", "index.html"), "rb").read().decode("utf-8", "replace")
        return 200, "text/html; charset=utf-8", html.encode(), None, False
    if path == "/api/search":
        q, src = one("q"), one("src", "all")
        out, errs = [], {}
        lanes = []
        if src not in ("deezer", "archive"):
            lanes.append(("youtube", None))
        if src not in ("youtube", "archive"):
            lanes.append(("deezer", dz_search))
        if src in ("all", "soundcloud"):
            lanes.append(("soundcloud", sc_search))
        if src in ("all", "archive"):
            lanes.append(("archive", ia_search))
        # youtube lane: try yt search via youtubei not available; skip
        for name, fn in lanes:
            if fn is None:
                continue
            try:
                j = fn(q)
                out.extend(j.get("results", []))
            except Exception as e:
                errs[name] = str(e)[:90]
        return 200, "application/json", json.dumps({"results": out, "errors": errs}).encode(), None, False
    if path == "/api/play":
        src, tid = one("src"), one("id")
        if src == "youtube":
            body = ("<html><body style='background:#000;margin:0;display:grid;place-items:center;height:100vh'>"
                    "<iframe width='100%' height='60%' src='https://www.youtube-nocookie.com/embed/" + re.sub(r'[^A-Za-z0-9_-]', "", tid)
                    + "?autoplay=1' style='border:0' allow='autoplay; encrypted-media' allowfullscreen></iframe></body></html>")
            return 200, "text/html", body.encode(), None, False
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
            m = re.search(r"(?:open\.)?spotify\.com/(?:intl-[a-z]{2}/)?(playlist|album|track)/([A-Za-z0-9]+)", link)
            if m:
                try:
                    import spotify_get
                    name, tracks = spotify_get.resolve(link)
                    fmt = [{"t": t["title"], "a": t["artist"], "ms": int(round(t.get("dur", 0) * 1000)),
                            "album": t.get("album") or "", "cover": cover_local(t.get("cover") or "")} for t in tracks]
                    jr = {"type": m.group(1), "name": name, "tracks": fmt, "count": len(fmt),
                          "total": len(fmt), "truncated": False, "partial": False}
                    save_link(link, jr)
                    return 200, "application/json", json.dumps(jr).encode(), None, False
                except Exception:
                    pass
            _, r = follow("https://kotassium-auth.vercel.app/api/spot/resolve?url=" + urllib.parse.quote(link, safe=""))
            jr = json.loads(r)
            if "error" not in jr and "tracks" in jr:
                if jr.get("partial") and jr.get("total") is None and jr.get("type") == "playlist":
                    t = fetch_song_count(link)
                    if t > 0:
                        jr["total"] = t
                for tr in (jr.get("tracks") or []):
                    if isinstance(tr, dict) and tr.get("cover"):
                        tr["cover"] = cover_local(tr["cover"])
                save_link(link, jr)
                r = json.dumps(jr)
            return 200, "application/json", r.encode(), None, False
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
    if path == "/api/links/drop":
        drop_link(one("url"))
        return 200, "application/json", b'{"ok":true}', None, False
    if path == "/api/ytdl":
        try:
            return 200, "application/json", json.dumps({"file": ytdl(one("id"))}).encode(), None, False
        except Exception as e:
            return 200, "application/json", json.dumps({"error": str(e)[:200]}).encode(), None, False
    if path == "/api/manifest":
        try:
            return 200, "application/json", open(os.path.join(STATE, "manifest.json"), "rb").read(), None, False
        except Exception:
            return 200, "application/json", b"{}", None, False
    if path == "/api/library":
        out = []
        for f in os.listdir(LIB):
            if f.endswith(".mp3"):
                out.append({"name": f[:-4], "size": os.path.getsize(os.path.join(LIB, f))})
        return 200, "application/json", json.dumps({"library": out}).encode(), None, False
    if path.startswith("/lib/"):
        base = os.path.basename(urllib.parse.unquote(path[5:]))
        f = os.path.join(LIB, base)
        if os.path.exists(f):
            ctype = "audio/mp4" if base.endswith(".m4a") else "audio/mpeg"
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
    return 404, "text/plain", b"nope", None, False

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            parts = urllib.parse.urlsplit(self.path)
            code, ctype, body, extra, _ = handle(parts.path, parts.query, self.headers)
            self._code = code
            self.send_response(code)
            if ctype:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            try:
                self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except Exception:
                pass

    def do_POST(self):
        try:
            parts = urllib.parse.urlsplit(self.path)
            n = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(n) if n else b""
            code, ctype, body, extra, _ = handle_post(parts.path, raw, self.headers)
            self._code = code
            self.send_response(code)
            if ctype:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
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

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("[kotassium-web] UI: " + os.path.join(BASE, "web", "index.html"))
    print("[kotassium-web] lib: " + LIB)
    print("[kotassium-web] http://0.0.0.0:" + str(PORT) + " - open via tailscale IP", flush=True)
    if os.path.exists(YTDLP):
        print("[kotassium-web] yt-dlp found - youtube download lane enabled", flush=True)
    else:
        print("[kotassium-web] yt-dlp missing - youtube tracks are embed-only", flush=True)
    srv.serve_forever()
PY