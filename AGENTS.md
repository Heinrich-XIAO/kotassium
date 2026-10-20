# Kotassium — agent conventions

One server (`serve_web.py`), one UI page (`web/index.html`), and a thin desktop
shell (`desktop.py`) that starts the same server on loopback and shows the same
page in a WebKitGTK window. The server and page are the product; `desktop.py`
must never grow its own copy of the UI.

**No release pipeline.** Changes to `web/index.html` or `serve_web.py` are live
the moment the file is saved — `serve_web.py` reads files fresh on every
request, so no server restart is needed for UI edits. Just commit.

- UI state (playlists, cached covers) lives outside the repo in
  `~/Music/Kotassium` — never commit from there.
- `spotify_get.py` is required by `serve_web.py` (Spotify link resolution);
  keep it if the server keeps working.
- There is no cloud/Vercel edition — `server/` was removed along with the
  fallback in `/api/spot/resolve`. Don't reintroduce a second UI copy or a
  deploy step.
- `venv/` supplies `yt-dlp`; `desktop-venv/` supplies `pywebview` and is built
  with `--system-site-packages` because WebKitGTK/PyGObject are distro
  packages. Both are gitignored.
- `desktop.py` must disable WebKit's `media-playback-requires-user-gesture`.
  Without it programmatic `play()` is rejected (as `NotSupportedError`) and the
  5s preview → full-track swap stops playback.
- Desktop binds `127.0.0.1`. `--lan` / `--host 0.0.0.0` is the only way to
  serve phones; requests are guarded by `Host` (IP literals/loopback only) and
  same-origin checks for POSTs.
- Run tests with `venv/bin/python -m unittest discover -s tests`.
