# Kotassium — agent conventions

Web-only project: one server (`serve_web.py`), one UI page (`web/index.html`).
There is no build step and nothing to package.

**No release pipeline.** Changes to `web/index.html` or `serve_web.py` are live
the moment the file is saved — `serve_web.py` reads files fresh on every
request, so no server restart is needed for UI edits. Just commit.

- UI state (playlists, cached covers) lives outside the repo in
  `~/Music/Kotassium` — never commit from there.
- `spotify_get.py` is required by `serve_web.py` (Spotify link resolution);
  keep it if the server keeps working.
- `server/` is the deployed `kotassium-auth` Vercel project (cloud UI +
  API functions; URL https://kotassium-auth.vercel.app). Deploy with
  `cd server && vercel --prod`; sync `web/index.html` → `server/index.html`
  right before deploying.
- `venv/` supplies `yt-dlp`; it is gitignored.
