# Kotassium

Kotassium is a browser-based music player. One Python server, one HTML page — nothing else.

- **Cloud URL: https://kotassium-auth.vercel.app** — serverless edition
  (Spotify resolve, Deezer search + previews, YouTube via the IFrame embed
  player; playlists live in the browser's localStorage). Deployed from
  `server/` with `vercel --prod`.
- `serve_web.py` — the full local edition: permanent MP3 downloads via
  `yt-dlp`, on-disk library, cover caching. Serves the same `web/index.html`.
- `web/index.html` — the UI (single file, no build step).
- `server/` — one Vercel project (`kotassium-auth`) that serves BOTH the
  cloud UI (`server/index.html` — a synced copy of `web/index.html`) and the
  API functions: `/api/spot/resolve` (token-exchange + resolve fallback,
  original role), `/api/search`, `/api/ytsearch`, `/api/cover`. Deploy from
  `server/` with `vercel --prod`. If `web/index.html` changes, re-copy it
  to `server/index.html` before deploying.
- `venv/` — local Python env supplying `yt-dlp`.

Everything else (Android APK, macOS wrapper, desktop daemons, PWA server) was
removed; the earlier APK releases live on GitHub Releases.

## Run

```sh
venv/bin/python3 serve_web.py        # 0.0.0.0:8421
```

Open `http://<machine-ip>:8421` from any browser (e.g. the Tailscale IP).

Downloads and state live outside the repo in `~/Music/Kotassium`.

## Dependencies

Only the Python standard library plus `yt-dlp` (expected at `venv/bin/yt-dlp`):

```sh
python3 -m venv venv && venv/bin/pip install yt-dlp
```
