// Shared best-effort YouTube search (scrapes public results page, no keys).
// Returns [{id,title,author,dur}] - used by /api/search and /api/ytsearch.
const UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36";

function durSec(text) {
  const m = /\d/.test(text) ? text.match(/^(?:(\d+):)?(\d{1,2}):(\d{2})$/) : null;
  if (!m) return 0;
  const a = m.slice(1).map((x) => parseInt(x || "0", 10));
  return (a[0] * 3600) + (a[1] * 60) + a[2];
}

async function search(q) {
  const url = "https://www.youtube.com/results?search_query=" + encodeURIComponent(q) + "&hl=en&gl=US";
  const r = await fetch(url, { headers: { "User-Agent": UA, "Accept-Language": "en" } });
  if (!r.ok) throw new Error("youtube " + r.status);
  const html = await r.text();
  const out = [];
  let d = null;
  const m = html.match(/var ytInitialData = (\{[\s\S]*?\});<\/script>/);
  if (m) { try { d = JSON.parse(m[1]); } catch (e) { /* fall through to regex */ } }
  if (d) {
    const sections = d?.contents?.twoColumnSearchResultsRenderer?.primaryContents?.sectionListRenderer?.contents || [];
    for (const s of sections) {
      for (const c of (s?.itemSectionRenderer?.contents || [])) {
        const v = c?.videoRenderer;
        if (!v || !v.videoId) continue;
        const title = v.title?.runs?.[0]?.text || v.title?.simpleText || "";
        if (!title) continue;
        out.push({
          id: v.videoId,
          title,
          author: v.ownerText?.runs?.[0]?.text || v.shortBylineText?.runs?.[0]?.text || "YouTube",
          dur: durSec(v.lengthText?.simpleText || "") || 0,
        });
        if (out.length >= 12) break;
      }
      if (out.length >= 12) break;
    }
  }
  if (!out.length) {
    // Crude fallback when ytInitialData isn't parseable
    const re = /"videoRenderer":\{"videoId":"([\w-]{11})"[\s\S]{0,600}?"accessibilityData":"playlist[^"\\]*"[\s\S]{0,600}?\}\},"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"/g;
    let hit;
    while ((hit = re.exec(html)) && out.length < 12) {
      out.push({ id: hit[1], title: JSON.parse('"' + hit[2] + '"'), author: "YouTube", dur: 0 });
    }
  }
  return out;
}

module.exports = { search, UA };
