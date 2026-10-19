# Kotassium

Kotassium is a browser-based music player. One Python server, one HTML page —
nothing else.

- `serve_web.py` — the server: Spotify link resolution, multi-source search,
  permanent MP3 downloads via `yt-dlp`, on-disk library, cover caching.
  Serves `web/index.html`.
- `web/index.html` — the UI (single file, no build step).
- `spotify_get.py` / `harvest_token.py` — Spotify resolution helpers used by
  `serve_web.py`.
- `venv/` — local Python env supplying `yt-dlp` (gitignored).

There is no cloud edition anymore: the `server/` Vercel project (UI copy +
serverless API, including the leftover APK-serving routes) was removed, and
`serve_web.py` no longer falls back to it for Spotify resolution — the local
`spotify_get.resolve` lane handles playlists, albums, and tracks on its own.
Earlier APK releases live on GitHub Releases.

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
