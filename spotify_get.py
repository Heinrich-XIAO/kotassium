#!/usr/bin/env python3
"""spotify_get.py - download any Spotify track/album/playlist as tagged MP3s.

Strategy: resolve ground truth (title/artist/album/duration/art) from Spotify's
API, then for each track search YouTube, pick the upload whose duration matches
Spotify's within tolerance (the strongest signal for the right version), download
via yt-dlp, convert with ffmpeg, and tag with Spotify's metadata + cover art.

Usage:
  python3 spotify_get.py <spotify_url> [--out DIR] [--threads N] [--quality 192|320]
                         [--format mp3|m4a] [--report FILE] [--overwrite skip|force]
"""
import argparse, base64, hashlib
import threading, hmac, json, os, re, struct, subprocess, sys, time, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request as urlreq
from urllib.parse import quote, urlencode

SPOTDL_CLIENT_ID = "5f573c9620494bae87890c0f08a60293"
SPOTDL_CLIENT_SECRET = "212476d9b0f3472eaa762d90b19b0ba8"
YTDLP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "yt-dlp")
if not os.path.exists(YTDLP):
    YTDLP = "yt-dlp"

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def http_json(url, data=None, headers=None, timeout=30):
    req = urlreq.Request(url, data=json.dumps(data).encode() if data else None,
                         headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def http_post_form(url, body, headers=None, timeout=30):
    req = urlreq.Request(url, data=body.encode(),
                         headers={"Content-Type": "application/x-www-form-urlencoded", **(headers or {})})
    with urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())



# ---------------- Anonymous token + pathfinder (Spotify-side search/recs) ----------------
#
# The web player mints an anonymous access token with a TOTP. It takes four
# plain HTTP requests - no browser, no Selenium, no cookies required:
#
#   1. GET https://open.spotify.com/                 -> the player bundle URL
#   2. GET <that bundle>                             -> {secret, version}
#   3. GET https://open.spotify.com/api/server-time  -> Spotify's own clock
#   4. GET https://open.spotify.com/api/token?...     -> accessToken
#
# The HMAC key is the bundle secret, XOR-obfuscated: every character's code is
# XORed with (index % 33 + 9), and the *decimal strings* of those numbers are
# concatenated - that string's utf8 bytes are the key. Using the raw secret
# bytes (or the char codes) instead produces a TOTP the server rejects with
# "400 totpVerExpired", which is what used to make this lane look dead.

_TOTP_SECRET_RE = re.compile(r"\{\s*secret:\s*(['\"])((?:\\.|(?!\1).)*)\1\s*,\s*version:\s*(\d+)\s*\}")
# A hand-pasted bearer (devtools on any logged-out player page) wins over the
# anonymous mint - it is the escape hatch when Spotify blocks the mint.
_token_override = os.environ.get("KOTASSIUM_SPOTIFY_TOKEN") or None
_api_get_tries = 12

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_SPOTIFY_HEADERS = {"User-Agent": _UA, "Referer": "https://open.spotify.com/", "Accept": "*/*"}

def _fetch(url, headers=None, timeout=20):
    req = urlreq.Request(url, headers=headers or _SPOTIFY_HEADERS)
    with urlreq.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def _totp_key(secret: str) -> bytes:
    """Un-obfuscate the bundle secret into the HMAC key (see the note above)."""
    return "".join(str(ord(c) ^ (i % 33 + 9)) for i, c in enumerate(secret)).encode("utf-8")

def _totp(key: bytes, ts_ms: int) -> str:
    counter = int(ts_ms // 1000 // 30)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 15
    return str(((h[o] & 127) << 24 | (h[o + 1] & 255) << 16 | (h[o + 2] & 255) << 8 | h[o + 3]) % 1000000).zfill(6)

def _server_time_ms() -> int:
    """Spotify's clock, so a skewed local clock cannot break the TOTP."""
    try:
        d = json.loads(_fetch("https://open.spotify.com/api/server-time"))
        return int(float(d["serverTime"]) * 1000)
    except Exception:
        return int(time.time() * 1000)

def _player_secret(force=False):
    """The {secret, version} pair from the live web-player bundle."""
    if not force:
        try:
            d = json.load(open(SECRET_CACHE))
            if d.get("secret") and d.get("version"):
                return d["secret"], int(d["version"])
        except Exception:
            pass
    html = _fetch("https://open.spotify.com/")
    m = re.search(r'https://open\.spotifycdn\.com/cdn/build/web-player/web-player\.[a-f0-9]+\.js', html)
    if not m:
        raise RuntimeError("could not find the web-player bundle")
    js = _fetch(m.group(0))
    hit = _TOTP_SECRET_RE.search(js)
    if not hit:
        raise RuntimeError("no totp secret in the web-player bundle")
    secret = hit.group(2).replace("\\'", "'").replace('\\"', '"')
    version = int(hit.group(3))
    try:
        os.makedirs(os.path.dirname(SECRET_CACHE), exist_ok=True)
        json.dump({"secret": secret, "version": version}, open(SECRET_CACHE, "w"))
    except Exception:
        pass
    return secret, version

def get_anon_token(force_secret=False):
    """Mint an anonymous web-player token (no account, no browser).
    Returns (accessToken, expiration_ms)."""
    secret, version = _player_secret(force=force_secret)
    key = _totp_key(secret)
    now = _server_time_ms()
    params = {"reason": "init", "productType": "web-player",
              "totp": _totp(key, now), "totpServer": _totp(key, now),
              "totpVer": str(version)}
    url = "https://open.spotify.com/api/token?" + urlencode(params)
    try:
        d = json.loads(_fetch(url))
    except urlreq.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code in (400, 401, 403) and not force_secret:
            # Spotify rotated the secret (or rejected our clock): scrape the
            # bundle again and retry exactly once.
            log(f"anon mint rejected ({e.code}) - rescraping the totp secret")
            return get_anon_token(force_secret=True)
        raise RuntimeError(f"anon mint rejected ({e.code}): {body[:120]}")
    if not d.get("accessToken"):
        raise RuntimeError(f"anon mint rejected: {json.dumps(d)[:120]}")
    return d["accessToken"], d.get("accessTokenExpirationTimestampMs") or 0

TOKEN_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "spotify_get_token.json")
SECRET_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "spotify_get_secret.json")

def _cache_load():
    try:
        d = json.load(open(TOKEN_CACHE))
        tok = d.get("tok")
        if not tok:
            return None
        exp = d.get("exp")
        if exp:
            # keep a minute of slack so a token never dies mid-request
            return tok if exp > time.time() * 1000 + 60_000 else None
        return tok if time.time() - d.get("t", 0) < 3300 else None
    except Exception:
        return None

def _cache_save(tok, exp_ms=0):
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
        json.dump({"t": time.time(), "tok": tok, "exp": exp_ms}, open(TOKEN_CACHE, "w"))
    except Exception:
        pass

def _cache_clear():
    try:
        os.remove(TOKEN_CACHE)
    except OSError:
        pass

# If the anonymous mint keeps failing, remember that for a while instead of
# retrying it on every single call - the client-credentials lane below still
# resolves public tracks/albums/playlists, and a dead pathfinder must not
# abort the whole resolve.
_anon_dead_until = 0.0

def anon_dead():
    """True when the anonymous web-player token lane is known to be dead, so
    pathfinder cannot authenticate. A client-credentials token is not a
    web-player token, so it answers 403 (or a bare KeyError off a partial
    payload) rather than anything meaningful."""
    return time.time() < _anon_dead_until

class TokenProvider:
    def __init__(self, manual=None):
        self.manual = manual
        self._anon = None
        self._cc = None

    def bearer(self):
        if self.manual:
            return self.manual
        if self._anon:
            return self._anon
        cached = _cache_load()
        if cached:
            self._anon = cached
            log("anonymous token from disk cache")
            return self._anon
        global _anon_dead_until
        if time.time() >= _anon_dead_until:
            try:
                tok, exp = get_anon_token()
                self._anon = tok
                _cache_save(tok, exp)
                log("anonymous token minted (pathfinder lane)")
                return self._anon
            except Exception as e:
                log(f"anon mint failed: {e}")
            _anon_dead_until = time.time() + 1800
            log("anon lane dead - using client_credentials for the rest of this session")
        try:
            if not self._cc:
                self._cc = get_token()
                log("fallback: client_credentials token (api.spotify.com lane)")
            return self._cc
        except Exception as e:
            raise RuntimeError(f"no token lane available: {e}")

def pathfinder_query(provider, operation, vhash, variables, tries=4):
    body = json.dumps({"variables": variables, "operationName": operation,
                       "extensions": {"persistedQuery": {"version": 1, "sha256Hash": vhash}}}).encode()
    last = None
    for i in range(tries):
        req = urlreq.Request("https://api-partner.spotify.com/pathfinder/v2/query", data=body,
                             headers={"Authorization": f"Bearer {provider.bearer()}",
                                      "Content-Type": "application/json",
                                      "User-Agent": "Mozilla/5.0"})
        try:
            d = json.loads(urlreq.urlopen(req, timeout=25).read())
            if d.get("errors"):
                msgs = "; ".join(e.get("message", "")[:80] for e in d["errors"])
                last = RuntimeError(f"pathfinder error: {msgs}")
                m = re.search(r"missing variable \$`(\w+)`", msgs) or re.search(r"missing variable \`(\w+)`", msgs)
                if m:
                    variables = dict(variables)
                    variables[m.group(1)] = {"limit": 10, "offset": 0}.get(m.group(1), False)
                    continue
                raise last
            return d
        except urlreq.HTTPError as e:
            last = e
            if e.code == 403:
                # A rejected bearer (client_credentials is not a web-player
                # token) will be rejected on every retry - fail now so the
                # caller can fall back to the api.spotify.com lane instead of
                # sleeping through the retry ladder.
                if provider.manual:
                    raise RuntimeError("bearer token rejected (403): expired or revoked - "
                                       "grab a fresh one from any logged-out player page or rerun --mint-token")
                raise
            if e.code == 401:
                if provider.manual:
                    raise RuntimeError("bearer token rejected (401): expired or revoked - "
                                       "grab a fresh one from any logged-out player page or rerun --mint-token")
                provider._anon = None   # token died - re-mint
                _cache_clear()          # ...and drop the dead one on disk,
                                       # or the re-mint just reads it back
                try:
                    provider.bearer()   # one immediate re-mint attempt
                    continue
                except Exception as me:
                    raise RuntimeError(f"pathfinder token dead, re-mint failed: {me}") from me
            time.sleep(5 + i * 8)
        except Exception as e:
            last = e
            time.sleep(5 + i * 8)
    raise last or RuntimeError("pathfinder failed")

SEARCH_OP = ("findTopResults", "903df2a65d8121e27d73a2be03c01e88ebe6021bb6d4eb82a389e35d87e51d27")
SIMILAR_ALBUMS_OP = ("similarAlbumsBasedOnThisTrack", "1d1f93a737498adca2c892c73af87fc0b052afe4e1a33c989540c32413dfae17")
ALBUM_TRACKS_OP = ("queryAlbumTracks", "11c9cad9cb24c4f9e25ef9456f68621cfd6006a90f679e729c1d2f2fd70dfe16")

def _pf_duration(track):
    d = track.get("trackDuration") or track.get("duration") or {}
    return int(d.get("totalMilliseconds") or d.get("milliseconds") or 0)

_album_uri_of = {}

def _pick_id(cands, pick):
    # spotify candidates don't carry yt ids; the flat ytsearch is done by search_and_pick at download time.
    # for streaming we run the flat search here and return the best id.
    return cands[pick - 1].get("_ytid") or ""

def spotify_search(provider, query, limit=8):
    d = pathfinder_query(provider, *SEARCH_OP,
        {"query": query, "numberOfTopResults": 20, "includePreReleases": True, "includeAlbumPreReleases": True})
    items = d["data"]["searchV2"]["tracksV2"]["items"]
    out = []
    for it in items:
        t = ((it.get("item") or {}).get("data")) or it.get("data") or {}
        if t.get("__typename") == "Track" and t.get("name"):
            alb = t.get("albumOfTrack") or {}
            cover = None
            try:
                cover = (((alb.get("coverArt") or {}).get("sources")) or [{}])[0].get("url")
            except Exception:
                pass
            out.append({"title": t["name"], "uri": t.get("uri"),
                        "artist": ", ".join(a["profile"]["name"] for a in (t.get("artists") or {}).get("items", []) if a.get("profile")),
                        "album": alb.get("name") or "", "uri_album": alb.get("uri"),
                        "cover": cover, "dur": _pf_duration(t) / 1000.0})
        if len(out) >= limit:
            break
    # findTopResults omits durations -> resolve per album (one call per album, cached)
    dur_cache = {}
    albums = sorted({c["uri_album"] for c in out if c["uri_album"] and c["dur"] == 0})
    for alb_uri in albums:
        try:
            d2 = pathfinder_query(provider, *ALBUM_TRACKS_OP, {"uri": alb_uri, "offset": 0, "limit": 50})
        except Exception as e:
            log(f"album track list failed ({alb_uri}): {e}")
            continue
        for it in d2["data"]["albumUnion"]["tracksV2"]["items"]:
            t = it.get("track") or {}
            if t.get("uri"):
                dur_cache[t["uri"]] = _pf_duration(t) / 1000.0
    for c in out:
        if c["dur"] == 0 and c["uri"] in dur_cache:
            c["dur"] = dur_cache[c["uri"]]
        c.pop("uri_album", None)
    return out

def spotify_recommend(provider, track_uri, n):
    d = pathfinder_query(provider, *SIMILAR_ALBUMS_OP, {"uri": track_uri, "limit": 20})
    albums = []
    def walk(o):
        if isinstance(o, dict):
            if o.get("__typename") == "Album" and o.get("name") and o.get("uri"):
                albums.append(o)
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(d.get("data", {}))
    seen, tracks = set(), []
    for alb in albums:
        if len(tracks) >= n:
            break
        try:
            d2 = pathfinder_query(provider, *ALBUM_TRACKS_OP,
                                  {"uri": alb["uri"], "offset": 0, "limit": 50})
        except Exception as e:
            log(f"album tracks failed ({alb.get('name')}): {e}"); continue
        for it in d2["data"]["albumUnion"]["tracksV2"]["items"]:
            t = it.get("track") or {}
            uri = t.get("uri")
            if not t.get("name") or uri in seen:
                continue
            seen.add(uri)
            tracks.append({"title": t["name"], "uri": uri,
                           "artist": ", ".join(a["profile"]["name"] for a in (t.get("artists") or {}).get("items", []) if a.get("profile")),
                           "album": alb.get("name") or "", "dur": _pf_duration(t) / 1000.0,
                           "cover": (((alb.get("coverArt") or {}).get("sources")) or [{}])[0].get("url") if alb.get("coverArt") else None})
    return tracks[:n]

# ---------------- Spotify resolution ----------------

def get_token(tries=8):
    """Client-credentials token. `tries` bounds the retry ladder: the CLI
    default stays patient (360s of backoff), but a served request must fail in
    seconds rather than leaving the page spinning on a silent sleep loop."""
    body = f"grant_type=client_credentials&client_id={SPOTDL_CLIENT_ID}&client_secret={SPOTDL_CLIENT_SECRET}"
    for attempt in range(tries):
        try:
            j = http_post_form("https://accounts.spotify.com/api/token", body)
            if j.get("access_token"):
                return j["access_token"]
        except Exception as e:
            log(f"token attempt {attempt}: {e}")
        if attempt < tries - 1:
            time.sleep(min(10 + attempt * 10, 20))
    raise RuntimeError("could not mint Spotify token (accounts.spotify.com unreachable?)")

def api_get(url, token, tries=12):
    for attempt in range(tries):
        try:
            return http_json(url, headers={"Authorization": f"Bearer {token}"})
        except urlreq.HTTPError as e:
            if e.code in (401, 403, 404):
                raise RuntimeError(f"Spotify says {e.code} for {url.split('?')[0].split('/')[-1]} "
                                   f"(deleted? private? not found?)")
            if e.code != 429 and e.code < 500:
                raise
            wait = min(30 + attempt * 30, 120)
            if attempt >= _api_get_tries - 1:
                raise RuntimeError("Spotify is rate-limiting this network (HTTP 429) - "
                                   "not your link. Try again in a minute, or on "
                                   "wi-fi instead of mobile data.")
            log(f"api throttled ({e.code}), waiting {wait}s: {url.split('?')[0].split('/')[-1]}")
            time.sleep(wait)
    raise RuntimeError(f"api still throttled after retries: {url}")

def _pf_track_obj(t, album_fallback=""):
    artists = []
    if (t.get("artists") or {}).get("items"):
        artists = [a["profile"]["name"] for a in t["artists"]["items"] if a.get("profile")]
    elif t.get("firstArtist"):
        fi = (t["firstArtist"].get("items") or [{}])[0]
        first = ((fi.get("profile") or {}).get("name")) or ""
        others = [((a.get("profile") or {}).get("name")) or ""
                  for a in (t.get("otherArtists") or {}).get("items", [])]
        artists = [first] + others
    alb = t.get("albumOfTrack") or {}
    cover = None
    try:
        cover = (((alb.get("coverArt") or {}).get("sources")) or [{}])[0].get("url")
    except Exception:
        pass
    return {"title": t.get("name") or "", "artist": ", ".join(a for a in artists if a),
            "album": alb.get("name") or album_fallback,
            "dur": _pf_duration(t) / 1000.0, "cover": cover}

def resolve_pathfinder(kind, sid, provider):
    if kind == "track":
        d = pathfinder_query(provider, "getTrack",
            "a8ef9e9f02b836feb0da3003c31dbb30decc6f4b473ef89ca88c882386d668de",
            {"uri": f"spotify:track:{sid}"})
        t = d["data"]["trackUnion"]
        return t.get("name") or "track", [_pf_track_obj(t)]
    if kind == "album":
        # getAlbumNameAndTracks answers with track nodes that carry no name
        # and no duration; getAlbum is the op that fills them in (and brings
        # the album cover art).
        d = pathfinder_query(provider, "getAlbum",
            "0b6ce3511e1b02e4a40fa95440f992acbe85080eb308af9194322d708fc1914f",
            {"uri": f"spotify:album:{sid}", "offset": 0, "limit": 50})
        alb = d["data"]["albumUnion"]
        if "tracksV2" not in alb or not alb.get("name"):
            # Spotify answers an op it does not understand with a stub node
            # holding only __typename. Treating that as an empty album would
            # save a silently wrong library, so fail loudly and let the
            # caller fall through to api.spotify.com.
            raise RuntimeError("pathfinder returned a stub album "
                               "(no albumUnion data)")
        name = alb.get("name") or "album"
        cover = None
        try:
            cover = (((alb.get("coverArt") or {}).get("sources")) or [{}])[0].get("url")
        except Exception:
            pass
        tracks = []
        for it in alb["tracksV2"]["items"]:
            t = it.get("track") or {}
            if t.get("name"):
                o = _pf_track_obj(t, album_fallback=name)
                if not o["cover"]:
                    o["cover"] = cover
                tracks.append(o)
        return name, tracks
    # playlist
    tracks, off, total, pname = [], 0, None, "playlist"
    while True:
        d = pathfinder_query(provider, "fetchPlaylist",
            "8964e8eafb21aa992a7d951d256d83285c04be2105d209262901de70cb97584a",
            {"uri": f"spotify:playlist:{sid}", "offset": off, "limit": 100,
             "enableWatchFeedEntrypoint": False})
        pv = d["data"]["playlistV2"]
        content = pv["content"]
        total = content.get("totalCount", total)
        for it in content["items"]:
            data = (it.get("itemV2") or {}).get("data") or {}
            if data.get("__typename") == "Track" and data.get("name"):
                tracks.append(_pf_track_obj(data))
        off += 100
        if total is None or off >= total or not content["items"]:
            break
    return (pv.get("title") or pv.get("name") or "playlist"), tracks

def playlist_image(url):
    """Spotify's own square image for a playlist link, or None.

    No track carries a playlist's cover art, so a library thumbnail has to
    ask for it separately - the first track's album art stays the fallback.
    This runs after a resolve that already succeeded, so every failure
    answers fast (one shot, no retry ladder) instead of hanging the request
    that worked. Album and track links already carry their cover on the
    first track, so only playlists make the extra call, and a short
    spotify.link URL never matches here - it falls back too.
    """
    m = re.search(r"spotify\.com/(?:intl-[a-z]{2}/)?playlist/([A-Za-z0-9]+)", url or "")
    if not m:
        return None
    try:
        token = _token_override or get_token(tries=1)
        images = http_json(f"https://api.spotify.com/v1/playlists/{m.group(1)}/images",
                           headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except Exception as e:
        log(f"playlist image lookup failed: {e}")
        return None
    if isinstance(images, list) and images and isinstance(images[0], dict):
        return images[0].get("url") or None
    return None

def resolve(url):
    if url.startswith("spotify:"):
        m = re.match(r"spotify:(track|album|playlist):([A-Za-z0-9]+)", url)
        if m:
            url = f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"
    m = re.search(r"spotify\.com/(?:intl-[a-z]{2}/)?(track|album|playlist)/([A-Za-z0-9]+)", url)
    if not m and "spotify.link/" in url or "spotify.com" not in url and "/" in url:
        # short link: follow redirect, then re-match
        try:
            req = urlreq.Request(url if url.startswith("http") else f"https://{url}",
                                 headers={"User-Agent": "Mozilla/5.0"})
            final = urlreq.urlopen(req, timeout=20).geturl()
            m = re.search(r"spotify\.com/(?:intl-[a-z]{2}/)?(track|album|playlist)/([A-Za-z0-9]+)", final)
        except Exception as e:
            raise ValueError(f"could not follow {url}: {e}")
    if not m:
        raise ValueError(f"unrecognized spotify url: {url}")
    if not m:
        raise ValueError(f"unrecognized spotify url: {url}")
    kind, sid = m.group(1), m.group(2)
    # When the anon lane is already known dead, pathfinder can only answer 403
    # (a client-credentials token is not a web-player token), so skip straight
    # to the lane that works instead of paying for a doomed round-trip.
    skip_pathfinder = anon_dead() and not _token_override
    if skip_pathfinder:
        log("skipping pathfinder (anon token lane known dead) - "
            "going straight to api.spotify.com")
    try:
        if skip_pathfinder:
            raise RuntimeError("pathfinder skipped")
        name, tracks = resolve_pathfinder(kind, sid, TokenProvider(_token_override))
        bad = [t for t in tracks if not t["title"] or not t["artist"]]
        if bad:
            raise RuntimeError(f"unresolvable metadata for {len(bad)}/{len(tracks)} entries "
                               f"(deleted/local/episode?) - first: '{bad[0]['title']}' / '{bad[0]['artist']}'")
        return name, tracks
    except Exception as e:
        log(f"pathfinder resolve failed: {e}")
        if _token_override and any(s in str(e) for s in ("401", "403", "re-mint failed", "rejected")):
            raise   # a user-supplied bearer was rejected - nothing else can fix that
        # Without a manual token the api.spotify.com lane below still resolves
        # public tracks/albums/playlists on client_credentials, so a dead
        # pathfinder (expired anon token) must not abort the whole resolve.
        log("trying api.spotify.com lane")
    # Served from the page, so keep the whole ladder short: a couple of token
    # attempts and a single 429 wait. A throttled shared IP is common on phone
    # hotspots, and making the user sit through 90s of backoff just to hear
    # "throttled" is the hang we are fixing - one wait, then a clear answer.
    token = get_token(tries=3)
    global _api_get_tries
    _api_get_tries = 2
    if kind == "track":
        t = api_get(f"https://api.spotify.com/v1/tracks/{sid}", token)
        return t["name"] or "spotify", [track_obj(t)]
    if kind == "album":
        meta = api_get(f"https://api.spotify.com/v1/albums/{sid}", token)
        name = meta["name"]
        items, off = [], 0
        while True:
            page = api_get(f"https://api.spotify.com/v1/albums/{sid}/tracks?limit=50&offset={off}", token)
            for it in page["items"]:
                it["album"] = {"name": meta["name"], "images": meta["images"]}
                items.append(it)
            off += 50
            if off >= page["total"]:
                break
        return name, [track_obj(t) for t in items]
    meta = api_get(f"https://api.spotify.com/v1/playlists/{sid}?fields=name,tracks(total)", token)
    name = meta["name"]
    total = meta["tracks"]["total"]
    items, off = [], 0
    while off < total:
        for attempt in range(6):
            try:
                page = api_get(f"https://api.spotify.com/v1/playlists/{sid}/tracks?limit=100&offset={off}"
                               f"&fields=items(track(name,artists(name),duration_ms,album(images,name))),total", token)
                if "error" not in page:
                    break
                log(f"api 429 at offset {off}, cooling down...")
            except Exception as e:
                log(f"api error at offset {off}: {e}")
            time.sleep(30 + attempt * 30)
        else:
            raise RuntimeError(f"could not fetch playlist page at offset {off}")
        for it in page["items"]:
            if it.get("track"):
                items.append(it)
        off += 100
    if len(items) < total:
        log(f"WARNING: resolved {len(items)}/{total} tracks")
    return name, [track_obj(t) for t in items if t.get("track")]

def track_obj(t):
    album = t.get("album") or {}
    images = album.get("images") or []
    return {
        "title": t["name"],
        "artist": ", ".join(a["name"] for a in t["artists"]),
        "album": album.get("name") or "",
        "dur": (t.get("duration_ms") or 0) / 1000.0,
        "cover": images[0]["url"] if images else None,
    }


# ---------------- adaptive rate governor (global, cross-thread) ----------------

class Governor:
    """Tracks 429/empty-result signals; all workers respect one global cooldown."""
    def __init__(self):
        self._lock = threading.Lock()
        self._cooldown = 0.0
        self._streak = 0

    def ok(self):
        with self._lock:
            self._streak += 1
            if self._streak >= 5 and self._cooldown > 0:
                self._cooldown = max(0.0, self._cooldown - 1.0)
        time.sleep(self._cooldown * 0.25)

    def hit(self):
        with self._lock:
            self._streak = 0
            self._cooldown = min(120.0, max(2.0, self._cooldown * 2.5 if self._cooldown else 8.0))
            wait = self._cooldown
        log(f"rate signal: global cooldown {wait:.0f}s")
        time.sleep(wait)

GOV = Governor()

# ---------------- Matching & downloading ----------------

def search_and_pick(artist, title, dur):
    """Return (video_id, duration) of best-matching YouTube upload, or None."""
    base = norm(f"{artist} {title}")[:80]
    # "audio" suffix helps long titles, hurts recall on short ones
    attempts = ([base, f"{base} song"] if len([w for w in base.split() if len(w) > 2]) < 4
                else [f"{base} audio", base])
    lo, hi = (dur * 0.80, dur * 1.20) if dur else (0, 10**9)
    for q in attempts:
        for attempt in range(2):
            GOV.ok()
            cmd = [YTDLP, "--flat-playlist", "--dump-json", "--no-playlist", "--quiet",
                   "--no-warnings", f"ytsearch12:{q}"]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            except subprocess.TimeoutExpired:
                GOV.hit(); continue
            cands = [json.loads(l) for l in r.stdout.splitlines() if l.strip().startswith("{")]
            if not cands and "sign in" in r.stderr.lower():
                GOV.hit(); continue
            if cands:
                ntitle = norm(title)
                nwords = [w for w in ntitle.split() if len(w) > 2]
                def score(c):
                    ct = norm(c.get("title", ""))
                    s = sum(1 for w in nwords if w in ct) + (0.5 if norm(artist) in ct else 0)
                    cd = c.get("duration")
                    if dur and cd:
                        if cd < lo or cd > hi:      # python-side duration gate
                            return -1e9
                        s += max(0.0, 1.0 - abs(cd - dur) / max(dur, 1))
                    return s
                live = [c for c in cands if score(c) > -1e8]
                if live:
                    live.sort(key=score, reverse=True)
                    return [(c["id"], c.get("duration") or dur) for c in live[:4]]
            GOV.hit()
            time.sleep(4 + attempt * 4)
    # YouTube ladder exhausted -> SoundCloud lane (same fingerprint gate, credential-free)
    base_sc = norm(f"{artist} {title}")[:80]
    for attempt in range(2):
        GOV.ok()
        try:
            r = subprocess.run([YTDLP, "--flat-playlist", "--dump-json", "--no-playlist",
                                "--quiet", "--no-warnings", f"scsearch8:{base_sc}"],
                               capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            GOV.hit(); continue
        cands = [json.loads(l) for l in r.stdout.splitlines() if l.strip().startswith("{")]
        if cands:
            ntitle = norm(title)
            nwords = [w for w in ntitle.split() if len(w) > 2]
            def s2(c):
                ct = norm(c.get("title", ""))
                s = sum(1 for w in nwords if w in ct) + (0.5 if norm(artist) in ct else 0)
                cd = c.get("duration") or 0
                if dur:
                    if cd and (cd < dur * 0.85 or cd > dur * 1.15):
                        return -1e9
                    if cd:
                        s += max(0.0, 1.0 - abs(cd - dur) / max(dur, 1))
                return s
            live = [c for c in cands if s2(c) > -1e8]
            if live:
                live.sort(key=s2, reverse=True)
                c = live[0]
                log(f"soundcloud lane: {c['title'][:40]} ({c.get('duration')}s)")
                return [(c["id"], c.get("duration") or dur)]
        GOV.hit()
        time.sleep(6)
    return None

def download_track(task, outdir, fmt, quality, overwrite):
    artist, title, dur, cover = task["artist"], task["title"], task["dur"], task["cover"]
    safe = re.sub(r'[/\\:*?"<>|]', "", title).strip()
    safe_art = re.sub(r'[/\\:*?"<>|]', "", artist).strip()
    while len((safe_art + safe).encode("utf-8")) > 180:
        safe = safe[:-1]
    out = os.path.join(outdir, f"{safe_art} - {safe}.{fmt}")
    if overwrite != "force" and os.path.exists(out) and os.path.getsize(out) > 100_000:
        return ("have", out)
    if dur and (dur < 15 or dur > 900):
        return ("skip_range", out)
    ladder = ([(task["_ytid"], dur)] if task.get("_ytid")
              else search_and_pick(artist, title, dur))
    if not ladder:
        return ("no_match", out)
    src = None
    vid = None
    fdur = None
    for vid, vdur in ladder:
        tmp = os.path.join(outdir, f".dl_{vid}.%(ext)s")
        produced = []
        for attempt in range(2):
            GOV.ok()
            client = ["--extractor-args", "youtube:player_client=ios"] if attempt else []
            try:
                r = subprocess.run([YTDLP, "-f", "bestaudio[ext=m4a]/bestaudio", "--no-playlist",
                                    "--quiet", "--no-warnings"] + client +
                                   ["-o", tmp, f"https://www.youtube.com/watch?v={vid}"],
                                   capture_output=True, text=True, timeout=300)
            except subprocess.TimeoutExpired:
                GOV.hit(); continue
            produced = [f for f in os.listdir(outdir) if f.startswith(f".dl_{vid}.")]
            if produced:
                break
            GOV.hit()
            time.sleep(8 + attempt * 8)
        if not produced:
            log(f"dl_fail {vid}: {r.stderr[-200:] if r.stderr else 'no stderr'}")
            continue
        cand = os.path.join(outdir, produced[0])
        chk = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=noprint_wrappers=1:nokey=1", cand], capture_output=True, text=True)
        try:
            fdur = float(chk.stdout.strip())
        except ValueError:
            os.remove(cand); continue
        if dur and abs(fdur - dur) / max(dur, 1) > 0.15:
            log(f"reject {vid}: audio={fdur:.1f}s spotify={dur:.1f}s - trying next candidate")
            os.remove(cand); continue
        src = cand
        break
    if not src:
        return ("no_valid_source", out)
    cover_file = None
    if cover:
        cover_file = os.path.join(outdir, f".cover_{vid}.jpg")
        try:
            urlreq.urlretrieve(cover, cover_file)
            if os.path.getsize(cover_file) < 2000: cover_file = None
        except Exception:
            cover_file = None
    if fmt == "m4a":
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src,
               "-c:a", "copy", "-metadata", f"title={title}", "-metadata", f"artist={artist}"]
        if task["album"]: cmd += ["-metadata", f"album={task['album']}"]
        cmd += [out]
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src]
        if cover_file: cmd += ["-i", cover_file]
        cmd += ["-codec:a", "libmp3lame", "-b:a", f"{quality}k",
                "-metadata", f"title={title}", "-metadata", f"artist={artist}"]
        if task["album"]: cmd += ["-metadata", f"album={task['album']}"]
        if cover_file: cmd += ["-map", "0:a", "-map", "1:v", "-c:v", "mjpeg",
                               "-id3v2_version", "3", "-metadata:s:v", "title=Album cover",
                               "-metadata:s:v", "comment=Cover (front)"]
        cmd += [out]
    try:
        c = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        if os.path.exists(out): os.remove(out)
        os.remove(src)
        if cover_file: os.remove(cover_file)
        return ("encode_timeout", out)
    for f in (src, cover_file):
        if f and os.path.exists(f): os.remove(f)
    if c.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 100_000:
        return ("ok", out)
    log(f"encode_fail: rc={c.returncode} stderr={c.stderr[-250:] if c.stderr else 'none'}")
    if os.path.exists(out): os.remove(out)
    return ("encode_fail", out)

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="spotify url, spotify: URI, or a search query")
    ap.add_argument("--pick", type=int, default=1, help="search mode: pick Nth result (1-based)")
    ap.add_argument("--list", action="store_true", help="search mode: list results, download nothing")
    ap.add_argument("--recommend", type=int, default=0, metavar="N",
                    help="also download N Spotify-recommended tracks seeded by the input")
    ap.add_argument("--token", default=None, help="manual bearer token override")
    ap.add_argument("--stream", action="store_true",
                    help="search mode: stream the pick instantly instead of downloading")
    ap.add_argument("--player", default=None, help="player command for --stream (default: ffplay, else mpv)")
    ap.add_argument("--mint-token", action="store_true",
                    help="just fetch a fresh anonymous token (cache -> TOTP mint -> secret scrape) and print it")
    ap.add_argument("--out", default=os.path.expanduser("~/Music"))
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--quality", default="192")
    ap.add_argument("--format", default="mp3", choices=["mp3", "m4a"])
    ap.add_argument("--report", default=None)
    ap.add_argument("--overwrite", default="skip", choices=["skip", "force"])
    ap.add_argument("--truth-file", default=None,
                    help="JSON [{a: artist, t: title, ms: duration}] - skips API resolution (offline mode)")
    ap.add_argument("--name", default=None, help="override folder name (truth-file mode)")
    args = ap.parse_args()

    global _token_override
    _token_override = args.token or _token_override
    provider = TokenProvider(_token_override)
    if args.mint_token:
        cached = _cache_load()
        if cached:
            print(f"cached token (still fresh): {cached[:40]}...")
            print("full:", cached)
            sys.exit(0)
        try:
            tok, exp = get_anon_token()
            _cache_save(tok, exp)
            print("minted + cached:", tok)
            sys.exit(0)
        except Exception as e:
            print(f"mint failed: {e}")
            print("manual fallback: open any spotify track page logged-out, devtools > network,")
            print("copy the Authorization header of a pathfinder/api request -> pass via --token")
            sys.exit(2)
    mode_search = "open.spotify.com" not in args.url and not args.url.startswith("spotify:")
    if args.truth_file:
        raw = json.load(open(args.truth_file))
        playlist_name = args.name or "spotify_dl"
        tracks = [{"title": x["t"], "artist": x["a"], "album": "", "dur": x["ms"] / 1000.0, "cover": None}
                  for x in raw]
    elif mode_search:
        try:
            cands = spotify_search(provider, args.url)
        except Exception as e:
            log(f"Spotify search unavailable ({e}) - DEGRADED mode: name-only YouTube search, no duration anchor")
            ladder = search_and_pick(args.url, args.url, 0)   # unanchored: trust the title
            if not ladder:
                sys.exit(f"no results anywhere for: {args.url}")
            cands = [{"title": args.url, "artist": "", "album": "", "dur": ladder[0][1], "cover": None,
                      "_ytid": ladder[0][0]}]
        if not cands:
            sys.exit(f"no Spotify results for: {args.url}")
        for i, c in enumerate(cands[:8], 1):
            print(f"  {i}. {c['artist']} - {c['title']} [{int(c['dur']) // 60}:{int(c['dur']) % 60:02d}] ({c['album']})")
        if args.list:
            sys.exit(0)
        pick = min(max(args.pick, 1), len(cands))
        chosen = cands[pick - 1]
        log(f"picked #{pick}: {chosen['artist']} - {chosen['title']}")
        if args.stream:
            player = args.player or ("mpv" if os.path.exists("/usr/bin/mpv") else "ffplay")
            # cache hit? play from disk instantly
            stream_out = os.path.join(args.out, "searches")
            os.makedirs(stream_out, exist_ok=True)
            existing = {norm(f.rsplit(".", 1)[0]): f for f in os.listdir(stream_out)}
            key = norm(f"{chosen['artist']} {chosen['title']}")
            if key in existing:
                log(f"cache hit - instant: {existing[key]}")
                os.execvp(player, [player, "-nodisp" if player == "ffplay" else "--no-video",
                                   os.path.join(stream_out, existing[key])])
            t0 = time.time()
            ladder = ([(chosen["_ytid"], chosen["dur"])] if chosen.get("_ytid")
                      else search_and_pick(chosen["artist"], chosen["title"], chosen["dur"]))
            if not ladder:
                sys.exit("no youtube match")
            vid, _ = ladder[0]
            log(f"yt match {vid} at {time.time()-t0:.1f}s")
            r = subprocess.run([YTDLP, "--get-url", "-f", "bestaudio[ext=m4a]/bestaudio",
                                "--no-playlist", "--quiet", "--no-warnings",
                                f"https://www.youtube.com/watch?v={vid}"],
                               capture_output=True, text=True, timeout=60)
            url = (r.stdout or "").strip().splitlines()[0] if r.stdout else ""
            if not url:
                sys.exit("no stream url")
            log(f"stream ready in {time.time()-t0:.1f}s - handing to {player}")
            print(url)
            # background: full fetch for the library cache - done before the song ends
            bg_code = (
                "import subprocess, os, sys\n"
                f"ytdlp = {YTDLP!r}\n"
                f"tmp = os.path.join({stream_out!r}, f'.bg_{vid}.%(ext)s')\n"
                "subprocess.run([ytdlp, '-f', 'bestaudio[ext=m4a]/bestaudio', '--no-playlist',"
                " '--quiet', '--no-warnings', '-o', tmp, 'https://www.youtube.com/watch?v=' + sys.argv[1]], timeout=240)\n"
                f"out = os.path.join({stream_out!r}, sys.argv[2] + '.mp3')\n"
                "for f in os.listdir(os.path.dirname(tmp)):\n"
                "    if f.startswith('.bg_' + sys.argv[1] + '.'):\n"
                f"        src = os.path.join({stream_out!r}, f)\n"
                "        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src, '-codec:a', 'libmp3lame',"
                " '-b:a', '192k', '-metadata', 'title=' + sys.argv[3], '-metadata', 'artist=' + sys.argv[4],"
                " '-metadata', 'album=' + sys.argv[5], out], timeout=120)\n"
                "        os.remove(src)\n"
            )
            bg = subprocess.Popen([sys.executable, "-c", bg_code, vid,
                                   f"{chosen['artist']} - {chosen['title']}",
                                   chosen["title"], chosen["artist"], chosen["album"] or ""],
                                  start_new_session=True,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log("background cache fetch started")
            os.execvp(player, [player, "-nodisp" if player == "ffplay" else "--no-video", url])
        playlist_name = "searches"
        tracks = [{"title": chosen["title"], "artist": chosen["artist"], "album": chosen["album"],
                   "dur": chosen["dur"], "cover": chosen.get("cover")}]
    else:
        playlist_name, tracks = resolve(args.url)
        if args.recommend and tracks and tracks[0]["title"]:
            seed_uri = re.search(r"track/([A-Za-z0-9]+)", args.url)
            if seed_uri:
                log(f"fetching {args.recommend} recommendations seeded by {tracks[0]['title']}...")
                recs = spotify_recommend(provider, f"spotify:track:{seed_uri.group(1)}", args.recommend)
                playlist_name = f"radio - {tracks[0]['title']}"
                tracks = tracks + recs
                log(f"{len(recs)} recommended tracks queued")
    outdir = os.path.join(args.out, re.sub(r'[/\\:*?"<>|]', "", playlist_name).strip() or "spotify_dl")
    os.makedirs(outdir, exist_ok=True)
    log(f"{playlist_name}: {len(tracks)} tracks -> {outdir}")

    results = {}
    todo = []
    existing = {norm(f.rsplit(".", 1)[0]): f for f in os.listdir(outdir)
                if f.lower().endswith("." + args.format)}
    for t in tracks:
        key = f"{t['artist']} - {t['title']}"
        nkey = norm(key)
        title_words = [w for w in norm(t["title"]).split() if len(w) > 2]
        first_artists = [w for w in norm(t["artist"]).split()[:1] if len(w) > 2] or norm(t["artist"]).split()[:1]
        matched = None
        if args.overwrite != "force":
            safe = re.sub(r'[/\\:*?"<>|]', "", t["title"]).strip()
            safe_art = re.sub(r'[/\\:*?"<>|]', "", t["artist"]).strip()
            out = os.path.join(outdir, f"{safe_art} - {safe}.{args.format}")
            if os.path.exists(out) and os.path.getsize(out) > 100_000:
                matched = out
            else:
                for k, f in existing.items():
                    if all(w in k for w in title_words) and all(w in k for w in first_artists):
                        fp = os.path.join(outdir, f)
                        if os.path.getsize(fp) > 100_000:
                            matched = fp
                        break
        if matched:
            results[key] = "have"
        else:
            todo.append(t)
    log(f"todo: {len(todo)} (have: {len(results)})")

    done_ct = 0
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = {ex.submit(download_track, t, outdir, args.format, args.quality, args.overwrite): t for t in todo}
        for fut in as_completed(futs):
            t = futs[fut]
            key = f"{t['artist']} - {t['title']}"
            try:
                status, path = fut.result()
            except Exception as e:
                import traceback
                status, path = f"crash:{type(e).__name__}: {e} @ {' | '.join(traceback.format_exception_only(type(e), e))[-0:] if False else traceback.extract_tb(e.__traceback__)[-1].lineno}", ""
            results[key] = status
            done_ct += 1
            log(f"[{done_ct}/{len(todo)}] {status}: {key}")
            if args.report:
                json.dump({"results": results}, open(args.report, "w"), indent=1)

    ok = sum(1 for s in results.values() if s in ("ok", "have"))
    log(f"DONE: {ok}/{len(results)} ({100.0*ok/len(results):.1f}%)")
    if args.report:
        json.dump({"results": results, "ok": ok, "total": len(results)}, open(args.report, "w"), indent=1)
    fails = [k for k, s in results.items() if s not in ("ok", "have")]
    for f in fails: print(f"FAIL: {f}")

if __name__ == "__main__":
    main()
