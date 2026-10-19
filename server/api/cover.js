// GET /api/cover?url=<image url>
// Proxies album art so the browser avoids hotlink/CORS referrer issues.
// Allowlisted to cover/CDN image hosts only - not a general open proxy.
const UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36";
const OK_HOSTS = /(^|\.)(spotifycdn\.com|scdn\.co|dzcdn\.net|ytimg\.com|archive\.org|deezer\.com)$/i;

async function fetchImageUrl(urlStr) {
  // Resolves a page/alias URL to a direct image URL (JSON wrappers only).
  const r = await fetch(urlStr, { headers: { "User-Agent": UA } });
  if (!r.ok) throw Object.assign(new Error("fetch " + r.status), { status: r.status === 404 ? 404 : 502 });
  const ct = (r.headers.get("content-type") || "").split(";")[0].trim();
  if (/^image\//.test(ct)) return { type: ct, buf: Buffer.from(await r.arrayBuffer()) };
  if (/json/.test(ct)) {
    const j = await r.json().catch(() => { throw new Error("bad json"); });
    const real =
      (j.data && j.data[0] && (j.data[0].cover || j.data[0].cover_medium || j.data[0].cover_small)) ||
      (j.cover_medium || j.cover_big || j.cover) || "";
    if (!real) throw Object.assign(new Error("no_cover"), { status: 404 });
    return { next: real };
  }
  throw new Error("not an image");
}

module.exports = async (req, res) => {
  if (req.method !== "GET") { res.status(405).json({ error: "method_not_allowed" }); return; }
  const raw = (typeof req.query?.url === "string" ? req.query.url : "").slice(0, 2000);
  let u;
  try { u = new URL(raw); } catch (e) { res.status(400).json({ error: "invalid_url" }); return; }
  if (!/^https?:$/.test(u.protocol) || !OK_HOSTS.test(u.hostname)) {
    res.status(400).json({ error: "host_not_allowed" });
    return;
  }
  try {
    let r = await fetchImageUrl(u.toString());
    if (r.next) {
      const nu = new URL(r.next);
      if (!OK_HOSTS.test(nu.hostname)) { res.status(400).json({ error: "host_not_allowed" }); return; }
      r = await fetchImageUrl(r.next);
    }
    if (!r.buf) { res.status(404).json({ error: "no_cover" }); return; }
    if (r.buf.length > 3 * 1024 * 1024) { res.status(502).json({ error: "too_large" }); return; }
    res.setHeader("Content-Type", r.type);
    res.setHeader("Cache-Control", "public, max-age=604800");
    res.status(200).send(r.buf);
  } catch (e) {
    const code = e.status || 502;
    res.status(code).json({ error: "fetch_failed", error_description: String(e.message || e).slice(0, 200) });
  }
};
