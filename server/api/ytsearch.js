// GET /api/ytsearch?q=<title artist>
// Resolves a track name to a playable YouTube video id (embed lane).
const YT = require("../lib/yt.js");

module.exports = async (req, res) => {
  if (req.method !== "GET") { res.status(405).json({ error: "method_not_allowed" }); return; }
  const q = (typeof req.query?.q === "string" ? req.query.q : "").trim().slice(0, 200);
  if (!q) { res.status(400).json({ error: "invalid_request", error_description: "q required" }); return; }
  try {
    const results = (await YT.search(q)).slice(0, 5).map((v) => ({
      source: "youtube", id: v.id, title: v.title, artist: v.author || "YouTube", dur: v.dur || 0, full: true,
    }));
    res.setHeader("Cache-Control", "public, max-age=86400");
    res.status(200).json({ results });
  } catch (e) {
    res.status(502).json({ error: "ytsearch_failed", error_description: String(e.message || e).slice(0, 200) });
  }
};
