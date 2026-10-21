# Kotassium — agent conventions

One server (`serve_web.py`), one UI page (`web/index.html`), and a thin desktop
shell (`desktop.py`) that starts the same server on loopback and shows the same
page in a native window (WebKitGTK on Linux, WKWebView on macOS). The server and
page are the product; `desktop.py` must never grow its own copy of the UI, and
platform code stays in small side modules (`mpris_linux.py`, `notify.py`).

**No release pipeline.** Changes to `web/index.html` or `serve_web.py` are live
the moment the file is saved — `serve_web.py` reads files fresh on every
request, so no server restart is needed for UI edits. Just commit.

- UI state (playlists, cached covers) lives outside the repo in
  `~/Music/Kotassium` — never commit from there. `KOTASSIUM_LIB` overrides the
  library root; tests and `tools/demo.py` use a throwaway copy.
- `spotify_get.py` is required by `serve_web.py` (Spotify link resolution);
  keep it if the server keeps working.
- There is no cloud/Vercel edition — `server/` was removed along with the
  fallback in `/api/spot/resolve`. Don't reintroduce a second UI copy or a
  deploy step.
- `venv/` supplies `yt-dlp`; `desktop-venv/` supplies `pywebview`. `setup.sh`
  builds it with `--system-site-packages` on Linux (WebKitGTK/PyGObject are
  distro packages) and a plain venv on macOS. Both are gitignored.
- `desktop.py` must disable WebKit's `media-playback-requires-user-gesture` on
  Linux. Without it programmatic `play()` is rejected (as `NotSupportedError`)
  and the 5s preview → full-track swap stops playback. macOS must not get that
  call (there is no GTK view) — it is guarded by `IS_LINUX`.
- The window opens `/?desktop=1`; the page skips the 2s `/api/mtime`
  reload-poll in that mode. `--dev` opens the plain URL so hot reload works.
- `webview.start(...)` must not pass `gui="gtk"` — that is what would break
  macOS. `private_mode=False` is required, otherwise `localStorage` is null and
  the YouTube-id cache/volume/shuffle reset every launch.
- MPRIS controls arrive on the GTK main loop. Never call `evaluate_js` there
  (deadlock); `desktop.py` queues them to a worker thread.
- Downloads are jobs: `/api/ytdl` returns `{"job": id}`, `/api/job?id=` is
  polled by the page. `ytdl(vid, progress=...)` streams yt-dlp output and is
  shared by the job runner. Don't turn it back into a blocking request.
- The page reports now-playing to `POST /api/nowplaying`; `desktop.py` polls it
  for MPRIS and notifications. Media keys/MPRIS are Linux-only.
- Desktop binds `127.0.0.1`. `--lan` / `--host 0.0.0.0` is the only way to
  serve phones; requests are guarded by `Host` (IP literals/loopback only) and
  same-origin checks for POSTs.
- macOS packaging (`setup-macos.py`, `build-macos.sh`, `install-macos.sh`) can
  only be tested on a Mac; keep it boring and note it as unverified.
- Tests: `venv/bin/python -m unittest discover -s tests`, plus
  `dbus-run-session -- desktop-venv/bin/python -m unittest tests.test_mpris`
  and `xvfb-run -a desktop-venv/bin/python tools/ui_check.py`.
- Updates are self-replacing (`updater.py`): the public repo's latest release
  is checked at launch, the DMG is verified against `SHA256SUMS`, staged, and
  a detached `swap.sh` replaces `/Applications/Kotassium.app` after exit and
  reopens it. `desktop.py` sets `updater.on_installed` so the window closes —
  never swap while the app is alive. `python updater.py --selftest <dmg>`
  (run in CI) exercises mount + swap against a throwaway target. Only frozen
  macOS builds report `supported`; the page hides the pill everywhere else.
