# Kotassium

Kotassium is a local music player: one Python server, one HTML page, and an
optional native window. The same code runs on Linux (WebKitGTK) and macOS
(WKWebView).

- `serve_web.py` — the server: Spotify link resolution, multi-source search,
  permanent MP3 downloads via `yt-dlp` (as background jobs with progress),
  on-disk library, cover caching, now-playing state. Serves `web/index.html`.
- `web/index.html` — the UI (single file, no build step).
- `desktop.py` — desktop shell: runs the same server on `127.0.0.1` and shows
  the same page in a native window.
- `mpris_linux.py` — MPRIS v2 service (Linux): media keys, GNOME media widget,
  lock screen.
- `notify.py` — track-change notifications (`notify-send` on Linux,
  `osascript` on macOS).
- `setup.sh` / `install.sh` — venv setup (Linux + macOS) and the Linux app-grid
  launcher. `install-macos.sh` / `build-macos.sh` build `Kotassium.app`.
- `spotify_get.py` / `harvest_token.py` — Spotify resolution helpers used by
  `serve_web.py`.
- `tests/` — `unittest` coverage for request guards, dependency resolution,
  download jobs, now-playing, and MPRIS.
- `tools/ui_check.py` — headless UI integration check (playback, swap, seek,
  pause, next) under Xvfb.
- `tools/demo.py` — records `docs/kotassium-demo.mp4` from the real app.
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

Desktop (Linux and macOS):

```sh
./setup.sh                  # creates desktop-venv (pywebview)
desktop-venv/bin/python desktop.py
./install.sh                # Linux: add to the app grid
```

macOS, as a real app bundle (run these on the Mac — they cannot be built here):

```sh
./install-macos.sh          # py2app -> /Applications/Kotassium.app
./install-macos.sh --wrapper   # fallback: tiny AppleScript app
```

`install.sh` rewrites the launcher with this checkout's absolute path. Closing
the window stops the server.

Flags: `--lan` also serves phones, `--port` picks another port, `--dev` opens
the WebKit inspector (and keeps the live-reload poll), `--no-window` runs the
server only, `--no-notify` disables track-change notifications.

Downloads and state live outside the repo in `~/Music/Kotassium`
(`KOTASSIUM_LIB` overrides it, which is what the tests and the demo use).

## Desktop integration

- **Download progress.** `/api/ytdl` starts a job and returns `{"job": id}`;
  `/api/job?id=` reports status/percent/file. The UI polls it and shows a
  progress pill; the same job is reused for prefetches and duplicate requests.
- **Media keys / MPRIS (Linux).** The page POSTs what it is playing to
  `/api/nowplaying`; `desktop.py` polls that and updates an MPRIS v2 service on
  the session bus. Play/Pause/Next/Previous are queued to a worker thread that
  calls `evaluate_js` (calling it on the GTK main loop would deadlock).
- **Notifications.** The same poll fires `notify-send` (Linux) or `osascript`
  (macOS) when the track changes while playing.
- **No dev polling in the app.** The page only polls `/api/mtime` for
  reload-on-change when it is *not* opened with `?desktop=1`.
- **Persistent storage.** The window uses `private_mode=False`, so the
  YouTube-id cache, volume, shuffle and repeat survive restarts (pywebview's
  default private mode makes `localStorage` null).
- **macOS.** Media keys are expected to work through WKWebView's
  `navigator.mediaSession`; there is no MPRIS equivalent. This path is
  implemented but **untested** (no macOS machine here).

## Security defaults

The desktop app binds `127.0.0.1`. Both modes reject a `Host` header that is not
a loopback name or an IP literal (DNS rebinding) and reject cross-origin
`POST`s (`/api/links/drop` is POST-only). `--host 0.0.0.0` / `--lan` is the only
way to expose the server, and anything that can reach that port can read and
delete playlists.

One WebKitGTK quirk is handled in `desktop.py`: programmatic `play()` is
rejected by default (reported as `NotSupportedError`), which breaks the 5-second
preview → full-track swap. The shell disables
`media-playback-requires-user-gesture` on the view (Linux only — WKWebView does
not need it).

## Dependencies

Python standard library plus `yt-dlp` (expected at `venv/bin/yt-dlp`; override
with `KOTASSIUM_YTDLP`), and `ffmpeg` on `PATH` (or in Homebrew's
`/opt/homebrew/bin`, `/usr/local/bin`) for MP3 conversion and preview clips.
The desktop shell adds `pywebview` plus, on Linux, system GTK3/WebKitGTK 4.1
(Fedora: `gtk3 webkit2gtk4.1`). On macOS `setup.sh` installs pywebview and its
pyobjc dependencies from pip.

```sh
python3 -m venv venv && venv/bin/pip install yt-dlp
venv/bin/python -m unittest discover -s tests

# MPRIS needs a session bus; this runs it against a throwaway one:
dbus-run-session -- desktop-venv/bin/python -m unittest tests.test_mpris

# full UI check in a virtual display:
xvfb-run -a desktop-venv/bin/python tools/ui_check.py
```
