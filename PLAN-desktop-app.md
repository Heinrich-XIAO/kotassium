# Kotassium desktop app — plan

> **Status:** M1 implemented — `desktop.py`, `serve_web.make_server()`, request
> guards, `install.sh`, `tests/`. The Epiphany interim was dropped: it cannot
> disable WebKitGTK's gesture requirement, so the preview → full switch stops at
> 5s. M2 (MPRIS/tray/offline view) and M3 (packaging) are still open.

## Goal

Double-click an icon → a real window with Kotassium, no terminal and no browser
tab. Same UI, same server, same library in `~/Music/Kotassium`. The web edition
keeps working unchanged (including phone-over-Tailscale), because the desktop
app is a *shell* around `serve_web.py`, not a fork.

Non-goals: a second UI copy, a build step for `web/index.html`, cloud/Vercel,
or rewriting the audio pipeline.

## What the codebase gives us

- `serve_web.py` is already a self-contained local server: Spotify resolve,
  YouTube search, `yt-dlp` downloads, MP3 library, covers, HTTP Range streaming.
- `web/index.html` is a single page using `fetch`, `<audio>`, `localStorage`
  and `navigator.mediaSession`.
- History: an Android WebView app and a Go loopback server ("macos/") existed
  and were deleted in `76d8702` for simplicity. Both were shells — no reason
  to repeat the mistakes (the Go one only opened the system browser; the APK
  bundled a second copy of `index.html`).
- This machine (Fedora 43) has: Python 3.14, PyGObject 3.54, WebKitGTK 4.1
  (2.50), GTK 3, GStreamer `mpg123audiodec`, `ffmpeg`, Node, Rust, and
  `venv/bin/yt-dlp` 2026.08.19. `pywebview` 6.2.1 installs from PyPI.
- The venv is isolated (`include-system-site-packages = false`), so it cannot
  currently `import gi` — a one-line fix, see M1.

## Options

| Option | Verdict |
| --- | --- |
| **pywebview** (GTK/WebKitGTK backend) | **Recommended.** ~150 lines of Python, no new language, no build step, reuses the server in-process. Window, geometry, JS bridge built in. |
| Electron | Most reliable codecs + free MPRIS/media keys, but ~150 MB runtime, `node_modules`, and a second language/toolchain for a Python project. Keep as the **fallback** if WebKitGTK fails the M0 spike. |
| Tauri | Small binary, but adds Rust *and* still needs WebKitGTK *and* still needs Python sidecar bundling. Worst of all three for this repo. |
| PWA / system browser in app mode | ~10-minute interim. Firefox has no `--app` and Chromium isn't installed here; Epiphany's `-a` is WebKitGTK but cannot relax the autoplay gate, so it dies at the 5s swap. Not a viable path. |
| Native GUI rewrite | No. |

## Architecture

```
kotassium.desktop  →  desktop.py  ──┬── ThreadingHTTPServer (127.0.0.1:8421)
   (icon, app grid)                 │      └── serve_web.handle()  (unchanged)
                                    ├── pywebview window → http://127.0.0.1:8421/
                                    └── optional MPRIS / tray bridge (D-Bus)
```

- **In-process server, not a child process.** `desktop.py` imports
  `serve_web` and starts the HTTP server in a daemon thread. One process to
  kill, no orphaned port, no venv-python path guessing at launch.
- **Loopback only by default.** Binding `0.0.0.0` (today's behaviour) stays
  available as `--lan` for the phone.
- **Stable origin.** The UI's prefs (`kot_vol`, `kot_shuf`, `kot_repeat`,
  `kot_side_collapsed`) and the YouTube-id cache (`kot_ytcache`) live in
  `localStorage`, which is keyed by origin. The desktop app therefore must
  reuse the same port across launches: default `8421`, and if it is taken,
  probe upward and persist the chosen port in `webstate/desktop.json` so the
  next launch reuses it. (Phase 4 moves prefs server-side and removes the
  coupling.)
- **Keep HTTP for audio.** `file://` URLs break `fetch` and Range requests, so
  the page must stay served over `http://127.0.0.1` even though everything is
  local.

## Security work that rides along (small, worth doing first)

Today the server listens on `0.0.0.0` with no auth: anything on the tailnet can
read/delete playlists and delete library files. In desktop mode:

1. Bind `127.0.0.1` (explicit `--lan` opt-in for LAN/phone).
2. Reject requests whose `Host` header is not `127.0.0.1:<port>` or
   `localhost:<port>` — blocks DNS rebinding.
3. Reject cross-origin `POST /api/*` (`Origin` check) — any web page can
   otherwise POST to localhost.
4. Path handling in `/lib/` and `/cover/` already uses `basename()`; keep it
   that way and add a test.

## Milestones

### M0 — spike (1–2 h, throwaway code)

`pip install pywebview` in a scratch venv built with
`--system-site-packages`, point a 30-line script at the running server, and
verify:

- MP3 playback through WebKitGTK/GStreamer, seeking, Range requests;
- whether `navigator.mediaSession` reaches MPRIS (media keys, GNOME controls);
- DevTools / console access (`webview.start(debug=True)`);
- window chrome, min size, and HiDPI on Wayland.

**Decision gate:** if WebKitGTK plays audio and the window is sane → continue
with pywebview. If audio or media keys are broken in a way that needs native
code → switch to the Electron fallback (`electron/main.js` spawns
`venv/bin/python -m serve_web --no-window`, `BrowserWindow` loads loopback).

### M1 — shell (half a day)

- Recreate `venv` with `--system-site-packages` (and document it), so
  `import gi` works alongside `yt-dlp`; or add `python3-gobject` to the venv
  via a supported path if one exists.
- Refactor `serve_web.py` minimally: `make_server(host, port)` + `main(argv)`;
  `import serve_web` must not block. Keep `venv/bin/python3 serve_web.py`
  behaviour identical.
- New `desktop.py`:
  - args: `--lan`, `--port`, `--dev`, `--no-window`;
  - single instance: `fcntl.flock` on `webstate/desktop.lock`; second launch
    focuses/pings the running window and exits;
  - preflight: locate `yt-dlp` (venv → `PATH` → `python -m yt_dlp`) and
    `ffmpeg`; show a native dialog with the install hint if either is missing
    instead of failing silently on the first play;
  - window: 1200×800 default, min 900×600, remembered geometry, dark bg;
  - clean shutdown: stop the server, terminate any `yt-dlp` child, release
    the lock.
- `kotassium.desktop` + SVG/PNG icon + `install.sh` that copies both into
  `~/.local/share/applications` and `~/.local/share/icons`.

**Acceptance:** icon in the GNOME app grid; double-click → window; play a
playlist end-to-end; close → no `kotassium`/`yt-dlp` processes left; phone still
works when started with `--lan`.

### M2 — the reasons to have a desktop app (1–2 days)

- **MPRIS bridge** (if M0 shows mediaSession isn't enough): the page POSTs
  `{state, title, artist, cover, position}` to `/api/nowplaying`; Python owns
  an `org.mpris.MediaPlayer2.kotassium` player over D-Bus (`dbus-next`), so
  media keys, GNOME's media widget and lock screen work, and the app can be
  controlled without focus. Reverse channel calls `play/pause/next/prev` in the
  page through `webview.evaluate_js`.
- **Tray** (optional, GNOME needs the AppIndicator extension): show/hide,
  play/pause, next, quit, plus "close hides to tray" preference.
- **Download progress:** `/api/ytdl` is synchronous and the UI only says
  "fetching new…". Add a job id + `GET /api/job?id=` poll so the desktop window
  can show a progress row; same endpoint benefits the web UI.
- **Native notifications** on track change (optional, off by default).
- **Kill the dev reloader in packaged mode:** the 2 s `/api/mtime` poll should
  only run in `--dev`.

### M3 — packaging (half a day to a day)

- PyInstaller one-dir build: bundle `desktop.py`, `serve_web.py`,
  `spotify_get.py`, `web/index.html`, and `yt_dlp` via `--collect-all yt_dlp`
  (then `ytdl()` prefers `python -m yt_dlp` when frozen). Keep `venv/` out of
  the bundle.
- `ffmpeg` stays a system dependency (bundling it drags in GPL and ~80 MB):
  detect, explain, degrade to "no preview clip / no mp3 conversion" rather than
  crash.
- Deliver `.tar.gz` + `.desktop` + install script to GitHub Releases
  (`kotassium-linux-x86_64`). AppImage/RPM only if you actually want
  one-click installs.
- Test on a clean Fedora container/VM with no venv and no `ffmpeg` to prove the
  error paths, then on this machine.

### M4 — optional polish

Server-side prefs (`webstate/settings.json`) so web and desktop share
shuffle/repeat/volume; offline "Downloaded" library view; auto-update check
against GitHub Releases; macOS/Windows builds from the same `desktop.py`
(pywebview Cocoa/WebView2, per-OS PyInstaller).

## Risks and gotchas

1. **GStreamer codecs.** MP3 playback in WebKitGTK depends on
   `mpg123audiodec` (gst-plugins-good) and libav. Present here; not guaranteed
   on minimal installs. Detect at startup and explain.
2. **MediaSession → MPRIS** may not exist in WebKitGTK; that is why the MPRIS
   bridge is scoped, and why Electron is the fallback.
3. **`gi` in the venv** — the current venv cannot see PyGObject; recreating it
   with `--system-site-packages` is the cheap fix, but it makes the app depend
   on distro GTK/WebKit packages (fine on Fedora, painful on other distros —
   note it in the README).
4. **`yt-dlp` needs a JS runtime** for YouTube signature solving; Node is
   present here. Bundled builds must keep it or document the requirement.
5. **Python 3.14** is very new: pin `pywebview`/`yt-dlp` versions that
   actually work rather than floating.
6. **Long downloads are synchronous**; closing the window mid-download must
   terminate children, not orphan them.
7. **Wayland + WebKitGTK** HiDPI and window placement can be quirky; verify
   before promising geometry persistence.

## Suggested first commit

`docs`-free, minimal: `desktop.py` + `serve_web.make_server()` refactor +
`--lan` flag + `kotassium.desktop` + README section. Everything else follows
M2/M3. (The `chromium --app` shortcut was a dead end here — see Status.)
