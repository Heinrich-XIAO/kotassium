// GET /api/spot/resolve?url=<spotify playlist/album/track link>
// Resolves PUBLIC Spotify content to a track list with NO user login.
// Lanes (first success wins), mirroring spotify_get.py's philosophy:
//   1. anonymous web-player token (credential-free, scraped live, cached)
//   2. spotdl's public app credentials (shared quota; honors Retry-After)
// The user's own app credentials are deliberately NOT used: since Feb 2026
// Spotify gates all Development Mode traffic on the owner's Premium status.
const MAX_TRACKS = 400;
// spotdl's public credentials (same as spotify_get.py; already world-public).
const PUB_CID = "5f573c9620494bae87890c0f08a60293";
const PUB_SEC = "212476d9b0f3472eaa762d90b19b0ba8";

let anonTok = "", anonExp = 0, totpSec = "", totpVer = "";
let appTok = "", appExp = 0;

async function scrapeTotp() {
  if (totpSec) return;
  const UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36";
  const html = await (await fetch("https://open.spotify.com/", { headers: { "User-Agent": UA } })).text();
  const m = html.match(/https:\/\/open\.spotifycdn\.com\/cdn\/build\/web-player\/web-player\.[a-f0-9]+\.js/);
  if (!m) throw new Error("web bundle not found");
  const js = await (await fetch(m[0], { headers: { "User-Agent": UA } })).text();
  const hit = js.match(/\{secret:"([^"]+)",version:(\d+)\}/);
  if (!hit) throw new Error("totp secret not found");
  totpSec = hit[1]; totpVer = hit[2];
}

function totp(ts) {
  const crypto = require("crypto");
  const counter = Math.floor(Math.floor(ts / 1000) / 30);
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(counter));
  const h = crypto.createHmac("sha1", totpSec).update(buf).digest();
  const o = h[h.length - 1] & 15;
  const n = ((h[o] & 127) << 24) | ((h[o + 1] & 255) << 16) | ((h[o + 2] & 255) << 8) | (h[o + 3] & 255);
  return String(n % 1000000).padStart(6, "0");
}

async function tokenAnon() {
  if (anonTok && Date.now() < anonExp - 60000) return anonTok;
  await scrapeTotp();
  const now = Date.now();
  const q = `reason=init&productType=mobile-web-player&totp=${totp(now)}&totpServer=${totp(now)}&totpVer=${totpVer}`;
  const r = await fetch(`https://open.spotify.com/api/token?${q}`, {
    headers: { "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)" },
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.accessToken) throw Object.assign(new Error("anon mint failed"), { code: 502 });
  anonTok = d.accessToken;
  anonExp = Date.now() + 55 * 60 * 1000;
  return anonTok;
}

async function tokenApp() {
  if (appTok && Date.now() < appExp - 60000) return appTok;
  const r = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "client_credentials", client_id: PUB_CID, client_secret: PUB_SEC }).toString(),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || !d.access_token) throw Object.assign(new Error("app mint failed"), { code: 502 });
  appTok = d.access_token;
  appExp = Date.now() + (d.expires_in || 3600) * 1000;
  return appTok;
}

// Try each lane; return {ok, status, data}. 404 is definitive (no lane-hopping).
async function apiLanes(path) {
  const lanes = [tokenAnon, tokenApp];
  let last = null;
  for (const getTok of lanes) {
    let tok;
    try { tok = await getTok(); } catch (e) { last = { status: 502, error: e }; continue; }
    let r;
    try {
      r = await fetch(`https://api.spotify.com/v1${path}`, { headers: { Authorization: `Bearer ${tok}` } });
    } catch (e) { last = { status: 502, error: e }; continue; }
    if (r.status === 404) {
      return { definitive: true, status: 404 };
    }
    if (r.ok) {
      return { ok: true, data: await r.json() };
    }
    if (r.status === 429) {
      const ra = parseInt(r.headers.get("retry-after") || "0", 10);
      last = { status: 429, retryAfter: ra, body: await r.text().catch(() => "") };
      continue;
    }
    // 401/403 on one lane: token may be stale/limited; clear caches and try next lane
    anonTok = ""; appTok = "";
    last = { status: r.status, body: await r.text().catch(() => "") };
  }
  return last || { status: 502 };
}

// Last-resort lane: the public embed page carries the first ~50 tracks with
// no auth at all. Used when the API lanes are throttled/gated. Marked partial.
async function embedEntity(id, kind) {
  // Spotify's bot protection intermittently refuses embed fetches from
  // datacenter IPs; a fresh attempt usually passes.
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const r = await fetch(`https://open.spotify.com/embed/${kind}/${id}`, {
        headers: { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36" },
      });
      if (!r.ok) continue;
      const h = await r.text();
      const m = h.match(/<script id="__NEXT_DATA__" type="application\/json">(.*?)<\/script>/s);
      if (!m) continue;
      const d = JSON.parse(m[1]);
      const ent = d?.props?.pageProps?.state?.data?.entity || null;
      if (ent && (ent.type === "track" || (Array.isArray(ent.trackList) && ent.trackList.length))) {
        let pageArtist = "";
        const og = h.match(/<meta property="og:description" content="([^"]+)"\s*\/?>/);
        if (og) {
          const parts = og[1].split(" · ");
          if (parts.length >= 3) pageArtist = parts[0];
        }
        return { ent, pageArtist };
      }
    } catch (e) { /* retry */ }
  }
  return null;
}

function embedTrack(e) {
  if (!e || !e.title) return null;
  const artists = (e.artists || []).map((a) => a.name).filter(Boolean).join(", ");
  return { t: e.title, a: e.subtitle || artists, ms: e.duration || 0 };
}

// Track pages (unlike embeds) carry title/artist/duration in meta tags:
// og:title, og:description ("Artist · Title · Song · Year"), music:duration (sec).
async function trackFromPage(id) {
  try {
    const r = await fetch(`https://open.spotify.com/track/${id}`, {
      headers: { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36" },
    });
    if (!r.ok) return null;
    const h = await r.text();
    const meta = (name) => {
      const m = h.match(new RegExp(`<meta (?:property|name)="${name}" content="([^"]+)"\\s*\\/?>`));
      return m ? m[1] : "";
    };
    const title = meta("og:title");
    if (!title) return null;
    let artist = "";
    const desc = meta("og:description").split(" · ");
    if (desc.length >= 3) artist = desc[0];
    return { t: title, a: artist, ms: (parseInt(meta("music:duration"), 10) || 0) * 1000 };
  } catch (e) {
    return null;
  }
}

// Canonical playlist pages carry the true track total in a meta tag,
// independent of any API quota. Used to label partial results honestly.
async function pageTotal(id) {
  try {
    const r = await fetch(`https://open.spotify.com/playlist/${id}`, {
      headers: { "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36" },
    });
    if (!r.ok) return null;
    const h = await r.text();
    const m = h.match(/<meta name="music:song_count" content="(\d+)"\s*\/?>/);
    return m ? parseInt(m[1], 10) : null;
  } catch (e) {
    return null;
  }
}

async function followShortLink(url) {  let u = url;
  for (let i = 0; i < 5; i++) {
    if (/(^|\.)open\.spotify\.com$/i.test(new URL(u).hostname)) return u;
    const r = await fetch(u, { method: "GET", redirect: "manual", headers: { "User-Agent": "Mozilla/5.0" } });
    await r.arrayBuffer().catch(() => {});
    const loc = r.headers.get("location");
    if (r.status >= 300 && r.status < 400 && loc) u = new URL(loc, u).toString();
    else return u;
  }
  return u;
}

function parseSpotifyUrl(u) {
  if (u.startsWith("spotify:")) {
    const p = u.split(":");
    if (p.length === 3 && ["playlist", "album", "track"].includes(p[1]) && p[2]) return { kind: p[1], id: p[2] };
    return null;
  }
  let url;
  try { url = new URL(u); } catch (e) { return null; }
  const m = url.pathname.match(/\/(playlist|album|track)\/([A-Za-z0-9]+)/);
  if (m) return { kind: m[1], id: m[2] };
  return null;
}

function trackOf(entry) {
  const t = entry.track || entry.item || entry;
  if (!t || !t.name) return null;
  const artists = (t.artists || []).map((a) => a.name).filter(Boolean).join(", ");
  return { t: t.name, a: artists, ms: t.duration_ms || 0 };
}

async function pagedTracks(base) {
  const paths = base.includes("{p}") ? [`${base.replace("{p}", "items")}`, `${base.replace("{p}", "tracks")}`] : [base];
  const out = [];
  let truncated = false;
  for (const p of paths) {
    let url = `${p}${p.includes("?") ? "&" : "?"}limit=50`;
    let gotAny = false;
    while (url && out.length < MAX_TRACKS) {
      const r = await apiLanes(url.replace("https://api.spotify.com/v1", ""));
      if (r.definitive) break;
      if (!r.ok) {
        if (!gotAny && p !== paths[paths.length - 1]) break; // try next path shape
        const err = new Error(r.status === 429 ? "spotify throttling public lookups" : `spotify ${r.status}`);
        err.code = r.status === 429 ? 429 : 502;
        if (r.retryAfter) err.retryAfter = r.retryAfter;
        throw err;
      }
      gotAny = true;
      const d = r.data;
      for (const e of d.items || []) {
        const t = trackOf(e);
        if (t) out.push(t);
        if (out.length >= MAX_TRACKS) { truncated = true; break; }
      }
      url = d.next && out.length < MAX_TRACKS ? d.next : null;
    }
    if (gotAny) break;
  }
  return { out, truncated };
}

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.status(405).json({ error: "method_not_allowed" });
    return;
  }
  try {
    const raw = typeof req.query?.url === "string" ? req.query.url.trim() : "";
    if (!raw || !/^https?:\/\//i.test(raw) || raw.length > 2000) {
      res.status(400).json({ error: "invalid_request", error_description: "url required" });
      return;
    }
    const finalUrl = await followShortLink(raw);
    const parsed = parseSpotifyUrl(finalUrl);
    if (!parsed) {
      res.status(400).json({ error: "not_spotify_link", error_description: "need a Spotify playlist, album or track link" });
      return;
    }
    const fail = (r, what) => {
      if (r.definitive) {
        res.status(404).json({ error: "resolve_failed", error_description: `${what} not found or private - public links only` });
      } else if (r.status === 429) {
        const hrs = r.retryAfter ? Math.ceil(r.retryAfter / 3600) : null;
        res.status(429).json({ error: "throttled", error_description: `spotify is throttling public lookups${hrs ? ` - try again in ~${hrs}h` : " - try again later"}` });
      } else {
        res.status(502).json({ error: "resolve_failed", error_description: `spotify ${r.status || "unreachable"}` });
      }
    };
    if (parsed.kind === "track") {
      const r = await apiLanes(`/tracks/${parsed.id}`);
      if (r.ok) {
        const t = trackOf(r.data);
        if (t) {
          res.status(200).json({ type: "track", name: `${t.a} - ${t.t}`, tracks: [t], count: 1, truncated: false, partial: false });
          return;
        }
      }
      if (!r.definitive) {
        const page = await embedEntity(parsed.id, "track");
        let t = page && embedTrack(page.ent && page.ent.type === "track" ? page.ent : null);
        if (!t || !t.a) t = (await trackFromPage(parsed.id)) || t;
        if (t) {
          res.status(200).json({ type: "track", name: `${t.a} - ${t.t}`, tracks: [t], count: 1, truncated: false, partial: false });
          return;
        }
      }
      return fail(r, "track");
    }
    if (parsed.kind === "album") {
      const r = await apiLanes(`/albums/${parsed.id}`);
      if (r.ok) {
        const artist = (r.data.artists || []).map((x) => x.name).filter(Boolean).join(", ");
        const { out, truncated } = await pagedTracks(`/albums/${parsed.id}/tracks`);
        res.status(200).json({ type: "album", name: r.data.name || "Album", artist, tracks: out, count: out.length, truncated, partial: false });
        return;
      }
      if (!r.definitive) {
        const page = await embedEntity(parsed.id, "album");
        const ent = page && page.ent;
        const list = ent && Array.isArray(ent.trackList) ? ent.trackList.map(embedTrack).filter(Boolean) : [];
        if (list.length) {
          res.status(200).json({ type: "album", name: ent.title || ent.name || "Album", artist: ent.subtitle || "", tracks: list, count: list.length, truncated: true, partial: true });
          return;
        }
      }
      return fail(r, "album");
    }
    const meta = await apiLanes(`/playlists/${parsed.id}?fields=name`);
    if (meta.ok) {
      const { out, truncated } = await pagedTracks(`/playlists/${parsed.id}/{p}`);
      const total = await pageTotal(parsed.id);
      res.setHeader("Cache-Control", "no-store");
      res.status(200).json({ type: "playlist", name: meta.data.name || "Playlist", tracks: out, count: out.length, total: total || out.length, truncated, partial: false });
      return;
    }
    if (!meta.definitive) {
      const page = await embedEntity(parsed.id, "playlist");
      const ent = page && page.ent;
      const list = ent && Array.isArray(ent.trackList) ? ent.trackList.map(embedTrack).filter(Boolean) : [];
      if (list.length) {
        const total = await pageTotal(parsed.id);
        res.setHeader("Cache-Control", "no-store");
        res.status(200).json({ type: "playlist", name: ent.title || ent.name || "Playlist", tracks: list, count: list.length, total: total || null, truncated: true, partial: true });
        return;
      }
    }
    return fail(meta, "playlist");
  } catch (e) {
    if (e.code === 429 || /throttl/i.test(e.message)) {
      res.status(429).json({ error: "throttled", error_description: e.message });
    } else {
      res.status(500).json({ error: "resolve_failed", error_description: e.message });
    }
  }
};
