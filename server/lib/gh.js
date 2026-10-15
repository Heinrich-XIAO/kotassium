// Shared GitHub release lookup for the update endpoints.
// The repo is private, so the GitHub token lives only in Vercel env (GITHUB_TOKEN).
const REPO = "Heinrich-XIAO/kotassium";

async function latestRelease() {
  const token = process.env.GITHUB_TOKEN || "";
  if (!token) throw Object.assign(new Error("GITHUB_TOKEN not set on server"), { code: 500 });
  const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "kotassium-auth",
    },
  });
  if (!r.ok) throw Object.assign(new Error(`github ${r.status}`), { code: 502 });
  const rel = await r.json();
  const asset = (rel.assets || []).find((a) => a.name && a.name.endsWith(".apk"));
  if (!asset) throw Object.assign(new Error("no apk asset on latest release"), { code: 404 });
  return { tag: rel.tag_name, version: String(rel.tag_name || "").replace(/^v/, ""), asset };
}

module.exports = { latestRelease, token: () => process.env.GITHUB_TOKEN || "" };
