#!/usr/bin/env python3
"""spotify_port.py - port your entire Spotify account to local files.

  python3 spotify_port.py auth      # one-time: opens your browser, you log in, tokens saved locally
  python3 spotify_port.py port      # enumerates ALL playlists + liked songs + saved albums,
                                    # snapshots the manifest, downloads everything into ~/Music
Tokens are OAuth-only (your password never touches this script) and stay on disk.
"""
import base64, hashlib, json, os, re, secrets, subprocess, sys, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

VENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin")
SPOTIFY_GET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spotify_get.py")
if not os.path.exists(SPOTIFY_GET):
    SPOTIFY_GET = os.path.expanduser("~/Downloads/spotify_get.py")
CLIENT_ID = "5f573c9620494bae87890c0f08a60293"   # spotdl's public app id (localhost redirect registered)
PORT = 5588
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
SCOPES = "user-library-read playlist-read-private playlist-read-collaborative"
TOKEN_FILE = os.path.expanduser("~/.cache/spotify_port_tokens.json")

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def http_json(url, data=None, headers=None, timeout=30, form=False):
    body = urllib.parse.urlencode(data).encode() if (data and form) else (json.dumps(data).encode() if data else None)
    h = {"User-Agent": "Mozilla/5.0"}
    if form: h["Content-Type"] = "application/x-www-form-urlencoded"
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

# ---------------- OAuth (PKCE) ----------------

def _load_tokens():
    try: return json.load(open(TOKEN_FILE))
    except Exception: return None

def _save_tokens(d): 
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    json.dump(d, open(TOKEN_FILE, "w"))

def auth():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    url = ("https://accounts.spotify.com/authorize?response_type=code&client_id=" + CLIENT_ID +
           f"&redirect_uri={urllib.parse.quote(REDIRECT)}&scope={urllib.parse.quote(SCOPES)}"
           f"&code_challenge={challenge}&code_challenge_method=S256&state={state}")
    got = {}
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q and q.get("state", [None])[0] == state:
                got["code"] = q["code"][0]
                self.send_response(200); self.end_headers()
                self.wfile.write(b"<h1>Port authorized - you can close this tab.</h1>")
            else:
                self.send_response(400); self.end_headers()
                self.wfile.write(b"<h1>Missing code/state.</h1>")
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Opening your browser - log in and approve (read-only scopes).")
    print(f"If it doesn't open, paste this:\n  {url}")
    try:
        subprocess.run(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    t0 = time.time()
    while "code" not in got and time.time() - t0 < 300: time.sleep(0.5)
    if "code" not in got: sys.exit("timed out waiting for authorization")
    tok = http_json("https://accounts.spotify.com/api/token", data={
        "grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT,
        "client_id": CLIENT_ID, "code_verifier": verifier}, form=True)
    if "access_token" not in tok: sys.exit(f"token exchange failed: {tok}")
    _save_tokens({"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token", ""),
                  "t": time.time(), "expires_in": tok.get("expires_in", 3600)})
    print("tokens saved locally. Done - run `port` next.")

def api_get(url, tries=8):
    d = _load_tokens()
    if not d: sys.exit("no tokens - run `auth` first")
    if time.time() - d["t"] > d["expires_in"] - 120 and d.get("refresh_token"):
        try:
            t = http_json("https://accounts.spotify.com/api/token", data={
                "grant_type": "refresh_token", "refresh_token": d["refresh_token"],
                "client_id": CLIENT_ID}, form=True)
            d["access_token"] = t["access_token"]; d["t"] = time.time()
            if t.get("refresh_token"): d["refresh_token"] = t["refresh_token"]
            _save_tokens(d)
        except Exception as e:
            log(f"refresh failed ({e}) - rerun `auth`")
    for attempt in range(tries):
        try:
            return http_json(url, headers={"Authorization": f"Bearer {d['access_token']}"})
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404): raise
            if e.code == 429:
                wait = min(20 + attempt * 20, 120)
                log(f"throttled, waiting {wait}s")
                time.sleep(wait); continue
            raise
        except Exception:
            time.sleep(5)
    raise RuntimeError(f"api failed: {url}")

def paged(url, key):
    out, off = [], 0
    while True:
        sep = "&" if "?" in url else "?"
        d = api_get(f"{url}{sep}limit=50&offset={off}")
        items = d.get(key, [])
        out.extend(items)
        if len(items) < 50 or off >= d.get("total", 0): break
        off += 50
    return out

# ---------------- Enumeration ----------------

def enumerate_all():
    me = api_get("https://api.spotify.com/v1/me")
    log(f"account: {me.get('display_name') or me.get('id')}")
    pls = paged("https://api.spotify.com/v1/me/playlists", "items")
    mine = [p for p in pls if (p.get("owner") or {}).get("display_name") == me.get("display_name")
            or (p.get("owner") or {}).get("id") == me.get("id")]
    log(f"playlists: {len(pls)} total, {len(mine)} owned by you")
    liked = paged("https://api.spotify.com/v1/me/tracks", "items")
    log(f"liked songs: {len(liked)}")
    albums = paged("https://api.spotify.com/v1/me/albums", "items")
    log(f"saved albums: {len(albums)}")
    manifest = {"account": me.get("id"), "generated": time.time(),
                "playlists": [], "liked": [], "albums": []}
    for p in mine:
        items = paged(f"https://api.spotify.com/v1/playlists/{p['id']}/tracks", "items")
        tracks = []
        for it in items:
            t = it.get("track") or {}
            if t.get("name") and t.get("artists"):
                tracks.append({"a": ", ".join(x["name"] for x in t["artists"]),
                               "t": t["name"], "ms": t.get("duration_ms") or 0})
        manifest["playlists"].append({"name": p["name"], "id": p["id"], "tracks": tracks})
        log(f"  playlist '{p['name']}': {len(tracks)} tracks")
    manifest["liked"] = [{"a": ", ".join(x["name"] for x in it["track"]["artists"]),
                          "t": it["track"]["name"], "ms": it["track"].get("duration_ms") or 0}
                         for it in liked if it.get("track") and it["track"].get("name")]
    for al in albums:
        a = al.get("album") or {}
        items = paged(f"https://api.spotify.com/v1/albums/{a['id']}/tracks", "items")
        manifest["albums"].append({"name": a.get("name", ""), "id": a["id"],
                                   "tracks": [{"a": ", ".join(x["name"] for x in t["artists"]),
                                               "t": t["name"], "ms": t.get("duration_ms") or 0}
                                              for t in items if t.get("name")]})
        log(f"  album '{a.get('name')}': {len(manifest['albums'][-1]['tracks'])} tracks")
    return manifest

def write_m3u(folder, name):
    files = sorted(f for f in os.listdir(folder) if f.endswith(".mp3"))
    if files:
        with open(os.path.join(folder, f"{re.sub(r'[/\\:*?<>|]', '', name)[:60]}.m3u"), "w") as f:
            f.write("\n".join(files) + "\n")

def port(out_root):
    manifest = enumerate_all()
    mpath = os.path.join(out_root, ".port_manifest.json")
    json.dump(manifest, open(mpath, "w"), indent=1)
    log(f"manifest snapshot: {mpath} (survives Spotify's death)")
    jobs = [(f"Liked Songs", manifest["liked"])]
    jobs += [(p["name"], p["tracks"]) for p in manifest["playlists"] if p["tracks"]]
    jobs += [(f"Albums/{a['name']}", a["tracks"]) for a in manifest["albums"] if a["tracks"]]
    ok = fail = 0
    for name, tracks in jobs:
        if not tracks: continue
        safe = re.sub(r'[/\\:*?"<>|]', "", name).strip() or "unnamed"
        tf = os.path.join(out_root, f".truth_{abs(hash(name))}.json")
        json.dump(tracks, open(tf, "w"))
        log(f"=== porting '{name}' ({len(tracks)} tracks) ===")
        env = dict(os.environ)
        env["PATH"] = os.path.expanduser("~/.deno/bin") + ":" + env.get("PATH", "")
        r = subprocess.run([os.path.join(VENV, "python"), SPOTIFY_GET, "https://x/playlist/PORT",
                            "--truth-file", tf, "--name", safe, "--out", out_root,
                            "--threads", "3", "--report", os.path.join(out_root, f".report_{abs(hash(name))}.json")],
                           env=env)
        try: os.remove(tf)
        except Exception: pass
        rep = os.path.join(out_root, f".report_{abs(hash(name))}.json")
        if os.path.exists(rep):
            d = json.load(open(rep))
            ok += d.get("ok", 0); fail += len(d.get("results", {})) - d.get("ok", 0)
        else:
            fail += 1
    log(f"PORT COMPLETE: {ok} ok, {fail} not-ok across {len(jobs)} collections")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "auth": auth()
    elif cmd == "port": port(sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/Music"))
    else: print("usage: spotify_port.py auth | port [out_dir]")
