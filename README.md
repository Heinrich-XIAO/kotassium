# Kotassium

Kotassium is a local music player: one Python server, one HTML page, and an
optional native window.

- `serve_web.py` — the server: Spotify link resolution, multi-source search,
  permanent MP3 downloads via `yt-dlp`, on-disk library, cover caching.
  Serves `web/index.html`.
- `web/index.html` — the UI (single file, no build step).
- `desktop.py` — desktop shell: runs the same server on `127.0.0.1` and shows
  the same page in a WebKitGTK window.
- `install.sh` / `assets/kotassium.svg` — launcher and icon for the app grid.
- `spotify_get.py` / `harvest_token.py` — Spotify resolution helpers used by
  `serve_web.py`.
- `tests/` — `unittest` coverage for the request guards and dependency
  resolution.
- `venv/` — local Python env supplying `yt-dlp` (gitignored).
- `desktop-venv/` — `pywebview` for the desktop shell (gitignored).

There is no cloud edition anymore: the `server/` Vercel project (UI copy +
serverless API, including the leftover APK-serving routes) was removed, and
`serve_web.py` no longer falls back to it for Spotify resolution — the local
`spotify_get.resolve` lane handles playlists, albums, and tracks on its own.
Earlier APK releases live on GitHub Releases.

## Run

Web (LAN / phone):

```sh
venv/bin/python3 serve_web.py --host 0.0.0.0   # 0.0.0.0:8421
```

Open `http://<machine-ip>:8421` from any browser (e.g. the Tailscale IP).

Desktop:

```sh
python3 -m venv --system-site-packages desktop-venv
desktop-venv/bin/pip install pywebview
desktop-venv/bin/python desktop.py
```

`./install.sh` adds Kotassium to the app grid (it rewrites the launcher with
this checkout's absolute path). Closing the window stops the server.

Flags: `--lan` also serves phones, `--port` picks another port, `--dev` opens
the WebKit inspector, `--no-window` runs the server only.

Downloads and state live outside the repo in `~/Music/Kotassium`.

## Security defaults

The desktop app binds `127.0.0.1`. Both modes reject a `Host` header that is not
a loopback name or an IP literal (DNS rebinding) and reject cross-origin
`POST`s (`/api/links/drop` is POST-only). `--host 0.0.0.0` / `--lan` is the only
way to expose the server, and anything that can reach that port can read and
delete playlists. The desktop venv uses `--system-site-packages` because
WebKitGTK and PyGObject come from the distro.

One WebKitGTK quirk is handled in `desktop.py`: programmatic `play()` is
rejected by default (reported as `NotSupportedError`), which breaks the 5-second
preview → full-track swap. The shell disables
`media-playback-requires-user-gesture` on the view.

## Dependencies

Python standard library plus `yt-dlp` (expected at `venv/bin/yt-dlp`; override
with `KOTASSIUM_YTDLP`), and `ffmpeg` on `PATH` for MP3 conversion and preview
clips. The desktop shell adds `pywebview` plus system GTK3/WebKitGTK 4.1
(Fedora: `gtk3 webkit2gtk4.1`).

```sh
python3 -m venv venv && venv/bin/pip install yt-dlp
venv/bin/python -m unittest discover -s tests
```
