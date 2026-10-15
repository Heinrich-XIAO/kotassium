// GET /api/update/latest -> { version, apk_url }
// Public: reveals only the latest released version number and the proxy URL.
const { latestRelease } = require("../../lib/gh");

module.exports = async (req, res) => {
  if (req.method !== "GET") {
    res.status(405).json({ error: "method_not_allowed" });
    return;
  }
  try {
    const rel = await latestRelease();
    const host = req.headers.host || "kotassium-auth.vercel.app";
    res.setHeader("Cache-Control", "no-store");
    res.status(200).json({
      version: rel.version,
      apk_url: `https://${host}/api/update/apk?tag=${encodeURIComponent(rel.tag)}`,
    });
  } catch (e) {
    res.status(e.code || 500).json({ error: "update_check_failed", error_description: e.message });
  }
};
