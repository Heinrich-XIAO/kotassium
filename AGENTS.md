# Kotassium — agent conventions

One server (`serve_web.py`), one UI page (`web/index.html`), and thin shells
that load it: `desktop.py` (WebKitGTK on Linux, WKWebView on macOS) and
`android/` (WebView). The server and page are the product; the shells must never
grow their own copy of the UI, and platform code stays in small side modules
(`mpris_linux.py`, `notify.py`, `updater.py`).

**UI changes need no release.** `serve_web.py` reads files fresh on every
request, so editing `web/index.html` (or the manifest/service worker) is live
the moment it is saved. Only the shells need a new tag.

**Ship, then report.** When a task changes files, finish by committing and
pushing (to `main`; a push there intentionally publishes a release). Skip the
push only when the user says not to. And end **every** reply with exactly one
of these lines as the message's last line:

- `NO CHANGES` — the reply made no file changes
- `COMMITTED AND PUSHED` — changes were committed and pushed to GitHub
- `UNCOMMITTED` — changes exist locally but were not committed/pushed

- **The page is the only UI.** `tests/test_wrappers.py` fails if `desktop.py`
  or `MainActivity.java` contains markup, styles, or chunks of the page. If
  something is wrong on Android, fix `web/index.html`.
- **One shared server.** A public deployment sets `KOTASSIUM_PASSWORD`;
  without it every route (library, audio, delete) is open. The session cookie
  is an HMAC of the password and `webstate/auth.salt`, so changing the password
  logs everyone out. `/login`, `/api/health`, the manifest and `/sw.js` stay
  public so the PWA is installable before signing in.
- **Android** is a WebView APK (`android/`, no Kotlin, no AndroidX) with two
  modes: a window onto a shared URL, or the same `serve_web.py` running inside
  the app via Chaquopy. `kotassium_boot.py` only sets `KOTASSIUM_BASE` /
  `KOTASSIUM_LIB`, points `serve_web.JOB_HOOK` at the shell's
  `ServeService.setBusy()` and calls `serve_web.serve_local()`.
  `ServeService` is a foreground service (`mediaPlayback` type, notification
  included): the server lives in this process, so without it Android freezes
  the app — music and downloads — the moment the screen turns off. The wake
  and Wi-Fi locks are held *only* while a download runs (the `JOB_HOOK`), never
  while idle; local mode starts the service, remote mode must stop it. The Gradle build copies
  `serve_web.py`, `spotify_get.py`, `updater.py` and `web/` from the repo root
  into the APK, so there is still exactly one copy of the server and the page.
  The URL is baked at build time (`-PkotassiumUrl=`, CI reads the
  `KOTASSIUM_URL` repo variable); with no URL the first launch offers **This
  phone** / **Shared server**. Release signing uses the
  `ANDROID_KEYSTORE_B64` / `ANDROID_KEYSTORE_PASS` / `ANDROID_KEY_ALIAS`
  secrets — losing that keystore means future APKs cannot install over old ones.
- Every Android dialog needs a way out, and `mode=remote` is saved only after
  an address is entered (saving it earlier traps the user in a prompt they
  cannot leave — `tests/test_wrappers.py` enforces both). With a page loaded,
  the launcher shortcut `CHOOSE` (`res/xml/shortcuts.xml`) reopens the choice;
  a failed main-frame load offers Retry / Change address / This phone.
- Android has no ffmpeg and cannot exec a `yt-dlp` binary, so downloads run
  in-process (`KOTASSIUM_YTDLP=inproc`) and keep yt-dlp's container (usually
  `.m4a`). Never assume `.mp3`: use `track_path()` / `AUDIO_EXTS` in
  `serve_web.py`, and keep the `_preview.mp3` → full-track redirect for
  builds without ffmpeg.
- `.github/workflows/release.yml` builds both DMGs and the APK on a `v*` tag and
  publishes one release; `workflow_dispatch` only uploads artifacts.

- UI state (playlists, cached covers) lives outside the repo in
  `~/Music/Kotassium` — never commit from there. `KOTASSIUM_LIB` overrides the
  library root; tests and `tools/demo.py` use a throwaway copy.
- `spotify_get.py` is required by `serve_web.py` (Spotify link resolution);
  keep it if the server keeps working.
- There is no cloud/Vercel edition — `server/` was removed along with the
  fallback in `/api/spot/resolve`. Don't reintroduce a second UI copy or a
  deploy step.
- **Report the auto-release version after pushes.** Each push to `main` triggers
  `.github/workflows/auto-release.yml`, which chooses the next patch version
  by taking the highest plain `vX.Y.Z` tag and incrementing its patch (see
  `.github/next_version.py`). When a change is committed and pushed to `main`,
  calculate that workflow's resulting version from the current remote tags and
  include `vX.Y.Z` as the final line of the reply, noting that it is pending
  the workflows completing. Do not claim the release succeeded until CI
  confirms it. If no push occurred, keep the existing final status lines.
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
  is checked at launch and re-checked on demand from the page's pill, the DMG
  is verified against `SHA256SUMS`, staged, and a detached `swap.sh` replaces
  `/Applications/Kotassium.app` after exit and reopens it. `desktop.py` sets
  `updater.on_installed` so the window closes — never swap while the app is
  alive. `python updater.py --selftest <dmg>` (run in CI) exercises mount +
  swap against a throwaway target. `updater.check_async()` runs a check on a
  background thread and returns immediately with `state: "checking"`; it is
  single-flight (one click = one GitHub request, so it never stacks a second
  thread and never clobbers an install in progress). The page polls
  `GET /api/update` until the state settles. `POST /api/update/check` triggers
  that manual check. The top-right pill is one morphing button — ⟳ check (idle)
  → ⟳ spin (checking) → ⬇ download (update available) → Restart/Retry — and
  only frozen macOS builds report `supported`; the page hides the pill
  everywhere else.
