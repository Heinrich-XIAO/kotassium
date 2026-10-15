#!/usr/bin/env python3
"""serve_pwa.py - phone-accessible PWA for the local music engine.
Open http://<tailscale-ip>:8420 on your phone -> install as PWA -> search/stream/download.
Audio is fetched by THIS machine (residential trust) and served to your phone."""
import json, os, re, subprocess, sys, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from spotify_get import norm, spotify_search, search_and_pick, TokenProvider, YTDLP, log

LIB = os.path.expanduser("~/Music/searches")
os.makedirs(LIB, exist_ok=True)
PORT = 8420
PROVIDER = TokenProvider()

INDEX = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel=manifest href=/manifest.json><meta name=theme-color content=#191414>
<title>Kotassium</title><style>
body{background:#191414;color:#fff;font-family:system-ui;margin:0;padding:12px}
input{width:100%;padding:12px;font-size:16px;border-radius:8px;border:0;box-sizing:border-box}
button{padding:10px 16px;font-size:15px;border-radius:8px;border:0;background:#1db954;color:#000;font-weight:600;margin:4px 2px}
li{padding:6px 0;list-style:none}ul{padding:0}
small{color:#b3b3b3}</style></head><body>
<h2>Kotassium</h2><input id=q placeholder="search a song..."><button onclick=go()>Search</button>
<ul id=r></ul><div id=s></div>
<script>
async function go(){const q=document.getElementById('q').value;if(!q)return;
document.getElementById('r').innerHTML='<li>searching...</li>';
const r=await fetch('/api/search?q='+encodeURIComponent(q));const j=await r.json();
const ul=document.getElementById('r');ul.innerHTML='';
(j.results||[]).forEach((c,i)=>{const li=document.createElement('li');
li.innerHTML=`<b>${c.artist||'?'} - ${c.title}</b><br><small>${c.album||''} [${Math.round(c.dur/60)}:${String(Math.round(c.dur%60)).padStart(2,'0')}]</small><br>
<button onclick="dl(${i})">Download to phone</button> <button onclick="st(${i})">Stream</button>`;
li.dataset.i=i;ul.appendChild(li)});
window.C=j.results;}
async function dl(i){const c=C[i];document.getElementById('s').textContent='fetching '+c.title+'...';
const r=await fetch('/api/download?q='+encodeURIComponent(c.artist+' - '+c.title));
if(r.ok){const b=await r.blob();const u=URL.createObjectURL(b);const a=document.createElement('a');
a.href=u;a.download=c.artist+' - '+c.title+'.mp3';document.body.appendChild(a);a.click();a.remove();
document.getElementById('s').textContent='saved: '+c.title;}else{document.getElementById('s').textContent='failed: '+r.status;}}
async function st(i){const c=C[i];window.open('/api/stream?q='+encodeURIComponent(c.artist+' - '+c.title));}
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js');
</script></body></html>"""

SW = """self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => { /* passthrough; shell is online-first */ });"""

MANIFEST = {"name": "Kotassium", "short_name": "Kotassium", "start_url": "/",
            "display": "standalone", "background_color": "#191414", "theme_color": "#191414",
            "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]}
ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#1db954"/><circle cx="50" cy="50" r="28" fill="none" stroke="#191414" stroke-width="10"/><rect x="26" y="66" width="48" height="8" fill="#191414"/></svg>'

def resolve_pick(q):
    cands = spotify_search(PROVIDER, q, limit=6)
    if not cands:
        return None
    chosen = cands[0]
    ladder = search_and_pick(chosen["artist"], chosen["title"], chosen["dur"])
    if not ladder:
        return None
    vid, _ = ladder[0]
    r = subprocess.run([YTDLP, "--get-url", "-f", "bestaudio[ext=m4a]/bestaudio", "--no-playlist",
                        "--quiet", "--no-warnings", f"https://www.youtube.com/watch?v={vid}"],
                       capture_output=True, text=True, timeout=60)
    url = (r.stdout or "").strip().splitlines()[0] if r.stdout else None
    return {"chosen": chosen, "url": url}

def cached_or_fetch(artist, title, dur, album):
    key = norm(f"{artist} {title}")
    for f in os.listdir(LIB):
        if norm(f.rsplit(".", 1)[0]) == key:
            return os.path.join(LIB, f)
    ladder = search_and_pick(artist, title, dur)
    if not ladder:
        return None
    vid, _ = ladder[0]
    tmp = os.path.join(LIB, f".ph_{vid}.%(ext)s")
    subprocess.run([YTDLP, "-f", "bestaudio[ext=m4a]/bestaudio", "--no-playlist", "--quiet",
                    "--no-warnings", "-o", tmp, f"https://www.youtube.com/watch?v={vid}"],
                   timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    src = None
    for f in os.listdir(LIB):
        if f.startswith(f".ph_{vid}."):
            src = os.path.join(LIB, f)
    if not src:
        return None
    safe = re.sub(r'[/\\:*?"<>|]', "", f"{artist} - {title}").strip()
    out = os.path.join(LIB, safe + ".mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-codec:a", "libmp3lame", "-b:a", "192k",
                    "-metadata", f"title={title}", "-metadata", f"artist={artist}",
                    "-metadata", f"album={album or ''}", out], timeout=180)
    os.remove(src)
    return out if os.path.exists(out) else None

class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/":
            self.send(200, INDEX.encode())
        elif p.path == "/manifest.json":
            self.send(200, json.dumps(MANIFEST).encode(), "application/manifest+json")
        elif p.path == "/sw.js":
            self.send(200, SW.encode(), "text/javascript")
        elif p.path == "/icon.svg":
            self.send(200, ICON.encode(), "image/svg+xml")
        elif p.path == "/api/search":
            q = urllib.parse.unquote(p.query.replace("q=", ""))
            try:
                cands = spotify_search(PROVIDER, q, limit=8)
                slim = [{k: c.get(k) for k in ("artist", "title", "album", "dur")} for c in cands]
                self.send(200, json.dumps({"results": slim}).encode(), "application/json")
            except Exception as e:
                self.send(502, json.dumps({"error": str(e)[:120]}).encode(), "application/json")
        elif p.path == "/api/download":
            q = urllib.parse.unquote(p.query.replace("q=", ""))
            if " - " not in q:
                self.send(400, b"expected 'artist - title'"); return
            artist, title = q.split(" - ", 1)
            try:
                cands = spotify_search(PROVIDER, f"{artist} {title}", limit=3)
                dur = next((c["dur"] for c in cands if norm(c["title"]) == norm(title)), 0)
                album = next((c.get("album") for c in cands if norm(c["title"]) == norm(title)), "")
            except Exception:
                dur, album = 0, ""
            path = cached_or_fetch(artist, title, dur, album)
            if not path:
                self.send(404, b"no source found"); return
            data = open(path, "rb").read()
            self.send(200, data, "audio/mpeg",
                      {"Content-Disposition": f'attachment; filename="{os.path.basename(path)}"'})
        elif p.path == "/api/stream":
            q = urllib.parse.unquote(p.query.replace("q=", ""))
            if " - " not in q:
                self.send(400, b"expected 'artist - title'"); return
            artist, title = q.split(" - ", 1)
            try:
                cands = spotify_search(PROVIDER, f"{artist} {title}", limit=3)
                dur = next((c["dur"] for c in cands if norm(c["title"]) == norm(title)), 0)
            except Exception:
                dur = 0
            info = resolve_pick(f"{artist} {title}")
            if not info or not info["url"]:
                self.send(404, b"no stream"); return
            self.send_response(302)
            self.send_header("Location", info["url"])
            self.end_headers()
        else:
            self.send(404, b"nope")
    def log_message(self, *a): pass

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    log(f"PWA on http://0.0.0.0:{PORT} - open via tailscale IP from your phone")
    srv.serve_forever()
