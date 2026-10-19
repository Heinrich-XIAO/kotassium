# Kotassium

Kotassium is a browser-based music player. One Python server, one HTML page — nothing else.

- `serve_web.py` — the whole app: serves `web/index.html`, resolves playlists
  (Spotify via `spotify_get.py` / the `kotassium-auth` Vercel proxy), searches
  sources (Deezer etc.), and downloads audio through `yt-dlp`.
- `web/index.html` — the UI (single file, no build step).
- `server/` — the `kotassium-auth` Vercel function (Spotify token exchange +
  resolve fallback). It holds the Spotify client secret server-side.
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
