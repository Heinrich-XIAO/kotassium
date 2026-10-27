# Kotassium

Kotassium is a music player with one source of truth: a Python server and a
single HTML page. The desktop window and the Android app are thin shells that
load that page — they contain no UI of their own, so a fix in `web/index.html`
lands on every platform at once.

- `serve_web.py` — the server: Spotify link resolution, multi-source search
  (YouTube, Deezer, SoundCloud, and the Newgrounds Audio Portal), permanent
  MP3 downloads via `yt-dlp` as background jobs with progress (Newgrounds
  tracks are plain mp3 fetches and SoundCloud tracks are reassembled from its
  HLS stream, so neither needs the extractor or ffmpeg), on-disk library, cover caching,
  now-playing state, optional password gate. Serves `web/index.html`, the
  PWA manifest and the service worker.
- `web/index.html` — the UI (single file, no build step). The only place UI
  lives.
- `desktop.py` — desktop shell: either runs the same server on `127.0.0.1`
  and shows the page, or (`--remote`) points at a shared server.
- `updater.py` — macOS self-update from GitHub Releases.
- `android/` — APK that either points at a shared URL or runs `serve_web.py`
  inside the app (Chaquopy embeds CPython and `yt-dlp`). No markup, no UI
  logic.
- `mpris_linux.py` — MPRIS v2 service (Linux): media keys, GNOME media widget,
  lock screen.
- `notify.py` — track-change notifications (`notify-send` on Linux,
  `osascript` on macOS).
- `setup.sh` / `install.sh` — venv setup (Linux + macOS) and the Linux app-grid
  launcher. `install-macos.sh` / `build-macos.sh` build `Kotassium.app`.
- `spotify_get.py` — Spotify resolution helper used by `serve_web.py`: mints an
  anonymous web-player token with four plain HTTP requests (no browser), then
  resolves tracks/albums/playlists through Spotify's Pathfinder API.
- `tests/` — `unittest` coverage for request guards, auth, dependency
  resolution, download jobs, now-playing, MPRIS and the "wrappers stay
  wrappers" invariant.
- `tools/ui_check.py` — headless UI integration check (playback, swap, seek,
  pause, next) under Xvfb.
- `tools/demo.py` — records `docs/kotassium-demo.mp4` from the real app.
- `venv/` — local Python env supplying `yt-dlp` (gitignored).
- `desktop-venv/` — `pywebview` for the desktop shell (gitignored).

There is no cloud edition anymore: the `server/` Vercel project (UI copy +
serverless API, including the leftover APK-serving routes) was removed, and
`serve_web.py` no longer falls back to it for Spotify resolution — the local
`spotify_get.resolve` lane handles playlists, albums, and tracks on its own.

## One server, many clients

Run the server on the machine that should hold the library (the "home" box),
put it behind a stable HTTPS hostname, and point every client at that URL:

```sh
KOTASSIUM_PASSWORD='…' venv/bin/python3 serve_web.py --host 127.0.0.1
```

With `KOTASSIUM_PASSWORD` set, everything except `/login`, `/api/health`, the
manifest and the service worker needs a session cookie from `POST /login`
(HMAC-signed, salt stored next to the library state, 5 tries/minute per IP).
Leave it unset for a purely local server.

- **Desktop** — `desktop-venv/bin/python desktop.py --remote https://music.example.com`
  (or set `KOTASSIUM_URL`, or ship `Contents/Resources/default-url.txt` in the
  bundle). `--local` forces the built-in server. In remote mode the window is
  the only thing this process owns; MPRIS/notifications stay local-mode
  features for now.
- **Android** — `Kotassium-<version>.apk` from the releases, or open the URL
  in Chrome and **Add to Home Screen** (the PWA is the same page, no build).
  With no URL baked into the APK, the first launch asks: **This phone** runs
  the server inside the app, **Shared server** opens the home box.
- **Web** — just the URL.

## Android as its own server

The APK embeds CPython through [Chaquopy](https://chaquo.com/chaquopy/), so
"this phone" mode runs the same `serve_web.py` and the same `web/index.html`
as every other platform — not a port, not a copy. `kotassium_boot.py` only
sets two paths and starts the loopback server.

What differs from desktop, and why:

- **No ffmpeg.** yt-dlp cannot convert to mp3, so a download keeps yt-dlp's
  own container (usually `.m4a`). The library, `/lib/` and the player all work
  off the file extension instead of assuming mp3, and a `_preview.mp3` request
  redirects to the full track when there is no clip to generate.
- **No subprocesses.** Android cannot exec a `yt-dlp` binary, so the download
  runs in-process (`KOTASSIUM_YTDLP=inproc`) with yt-dlp's progress hooks.
- **Loopback only.** The local server binds `127.0.0.1`: the phone serves
  itself, with no password and nothing exposed to the network it happens to be
  on. Sharing the phone's library to other devices needs a password and a bind
  address, which is a deliberate follow-up rather than a default.
- **Survives the screen turning off.** Local mode runs the server under a
  foreground service (with a notification — Android's price for a process
  that outlives the screen), and a wake lock is held only while a download
  runs, so downloads finish with the phone asleep.
- **Library location.** `Android/data/app.kotassium.mobile/files/Music` — the
  app's own external directory. Syncthing cannot reach it on Android 11+, so
  tracks downloaded on the phone stay on the phone.
- **Size.** The CPython runtime makes the APK ~44 MB instead of tens of
  kilobytes (arm64 and x86_64, plus yt-dlp).

## Updating the Android app

The APK has no updater, and Android never updates an app that was installed
from a file — that is a Play Store behaviour, and this app is not in a store.
The page is a different story: in **Shared server** mode it comes from the
server and updates on the next load, with no release. Only the shell needs a
new APK, and now that **This phone** mode ships the page *inside* the APK, so
does the page.

Point [Obtainium](https://github.com/ImranR98/Obtainium) at this repo and it
watches the releases for you:

[**Add Kotassium to Obtainium**](https://apps.obtainium.imranr.dev/redirect?r=obtainium://add/https://github.com/Heinrich-XIAO/kotassium)

or, inside Obtainium: **Add App** → paste
`https://github.com/Heinrich-XIAO/kotassium` → **Add**.

- It reads the release tag as the version and picks the `.apk` asset, so each
  tagged release is offered as an update.
- The signing key never changes, so the update installs over your existing
  copy rather than asking you to uninstall first.
- Android still shows the installer: silent replacement is impossible outside
  a store. Obtainium adds the file and the notification; you tap **Update**.
- Set **Auto check for updates** (default on) to be told on its own schedule.

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

macOS: download and open the PKG from [GitHub Releases](https://github.com/Heinrich-XIAO/kotassium/releases)
(`Kotassium-*-arm64.pkg` for Apple Silicon, `Kotassium-*-x86_64.pkg` for
Intel). It installs Kotassium into **Applications** and asks before quitting an
already running copy; Cancel leaves the current app untouched. The app is
unsigned, so right-click → **Open** the first time. Downloads
still need `ffmpeg`:
`brew install ffmpeg` — `yt-dlp` is bundled inside the app.

Building the app yourself (on the Mac — it cannot be cross-compiled here):

```sh
./install-macos.sh          # py2app -> /Applications/Kotassium.app
./build-macos.sh            # just build dist/Kotassium.app
./make-pkg.sh               # package it as Kotassium-<version>.pkg
./install-macos.sh --wrapper   # fallback: tiny AppleScript app
```

CI builds the Apple Silicon PKG on every `v*` tag
(`.github/workflows/build.yml`); a manual run of the release workflow only
uploads artifacts, so it is the safe way to test packaging changes.

`install.sh` rewrites the launcher with this checkout's absolute path. Closing
the window stops the server.

Flags: `--lan` also serves phones, `--port` picks another port, `--dev` uses
the plain URL with live-reload polling, `--no-window` runs the server only,
`--no-notify` disables track-change notifications. Right-click → Inspect
Element opens the WebKit inspector in any session.

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
- **Self-update (macOS).** At launch the app asks the public repo for the
  latest release. The top-right pill is a single morphing button, like T3
  Code's updater: a circular **⟳ check** icon when it has not found an update
  (tap it to re-check GitHub on demand), a spinning arrow while the check is
  in flight, and a **⬇ download** icon when a newer PKG exists. One click on
  it downloads the build for its architecture, checks it against the
  release's `SHA256SUMS`, unpacks the package, waits for the app to quit,
  saves the prior bundle as `/Applications/Kotassium.app.old` for recovery
  when installed in `/Applications`, replaces the app and reopens it — no
  further dialogs. (An app sitting where it cannot replace itself falls back
  to macOS Installer, which asks before quitting as usual.) If recovery is
  needed, its recovery panel provides instructions to
  restore the saved bundle. Only frozen macOS app builds report
  `supported: true`; the web and Linux builds hide the pill.
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
with `KOTASSIUM_YTDLP`), `argon2-cffi` (the Newgrounds source answers that
site's proof-of-work guard with it; without it that lane reports a miss in
`/api/search`'s `errors` and every other source keeps working), and `ffmpeg`
for MP3 conversion and preview clips. The SoundCloud source needs neither: it
takes its `client_id` from SoundCloud's own script bundles and re-scrapes it
when the API answers 401.
on `PATH` (or in Homebrew's `/opt/homebrew/bin`, `/usr/local/bin`) for MP3
conversion and preview clips.
The desktop shell adds `pywebview` plus, on Linux, system GTK3/WebKitGTK 4.1
(Fedora: `gtk3 webkit2gtk4.1`). On macOS `setup.sh` installs pywebview and its
pyobjc dependencies from pip.

```sh
python3 -m venv venv && venv/bin/pip install yt-dlp argon2-cffi
venv/bin/python -m unittest discover -s tests

# MPRIS needs a session bus; this runs it against a throwaway one:
dbus-run-session -- desktop-venv/bin/python -m unittest tests.test_mpris

# full UI check in a virtual display:
xvfb-run -a desktop-venv/bin/python tools/ui_check.py
```
