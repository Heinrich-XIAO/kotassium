// GET /api/update/apk?tag=vX.Y.Z -> the release APK, fetched with the server-side token.
const { latestRelease, token } = require("../../lib/gh");

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.status(405).json({ error: "method_not_allowed" });
    return;
  }
  try {
    const rel = await latestRelease();
    const wanted = typeof req.query?.tag === "string" ? req.query.tag : rel.tag;
    if (wanted !== rel.tag) {
      // only ever serve the current latest release (no arbitrary tags)
      res.status(404).json({ error: "not_latest", error_description: "request the latest tag" });
      return;
    }
    // GitHub asset download: API URL + octet-stream accept + token; it redirects to storage.
    const r = await fetch(rel.asset.url, {
      headers: {
        Authorization: `Bearer ${token()}`,
        Accept: "application/octet-stream",
        "User-Agent": "kotassium-auth",
      },
    });
    if (!r.ok) {
      res.status(502).json({ error: "asset_fetch_failed", error_description: `github ${r.status}` });
      return;
    }
    const buf = Buffer.from(await r.arrayBuffer());
    res.setHeader("Content-Type", "application/vnd.android.package-archive");
    res.setHeader("Content-Disposition", `attachment; filename="${rel.asset.name}"`);
    res.setHeader("Cache-Control", "no-store");
    res.status(200).send(buf);
  } catch (e) {
    res.status(e.code || 500).json({ error: "apk_failed", error_description: e.message });
  }
};
