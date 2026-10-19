// GET /api/search?q=<query>
// Multi-source search for the cloud UI: Deezer (30s previews, album art)
// + best-effort YouTube (full playback via embed lane).
const YT = require("../lib/yt.js");
const UA = YT.UA;

module.exports = async (req, res) => {
  if (req.method !== "GET") { res.status(405).json({ error: "method_not_allowed" }); return; }
  const q = (typeof req.query?.q === "string" ? req.query.q : "").trim().slice(0, 200);
  if (!q) { res.status(400).json({ error: "invalid_request", error_description: "q required" }); return; }
  let deezer = [], youtube = [], errs = {};
  try {
    const r = await fetch("https://api.deezer.com/search?q=" + encodeURIComponent(q) + "&limit=25", { headers: { "User-Agent": UA } });
    const j = await r.json();
    deezer = (j.data || []).map((t) => ({
      source: "deezer", title: t.title || "", artist: (t.artist && t.artist.name) || "",
      dur: t.duration || 0, id: String(t.id || ""), preview: t.preview || "",
      cover: (t.album && t.album.cover) || "", full: false,
    }));
  } catch (e) { errs.deezer = String(e.message || e).slice(0, 90); }
  try {
    youtube = (await YT.search(q)).slice(0, 15).map((v) => ({
      source: "youtube", title: v.title, artist: v.author || "YouTube",
      dur: v.dur || 0, id: v.id, full: true,
    }));
  } catch (e) { errs.youtube = String(e.message || e).slice(0, 90); }
  res.setHeader("Cache-Control", "no-store");
  res.status(200).json({ results: deezer.concat(youtube), errors: errs });
};
