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

- **Icons: fix the geometry, never the nudge.** Every glyph in `web/app.jsx`'s
  `Icon` shares the `0 0 24 24` grid and carries its position in the path
  coordinates. A glyph may not carry a `transform`: it is in user units, so it
  centres that glyph at exactly one render size and misplaces it at every
  other one. Four "centre the glyph" commits did that - CSS
  `translateX(1px)`, then `translate(0.6 0)`, then `translate(-1.145 0)` - and
  each was checked with `getBoundingClientRect`, which reports the ink *box*
  and is blind to a right-pointing triangle's mass sitting at its base, so the
  glyph measured centred and read left. Measure with `tools/icon_bbox.py`
  (stdlib, no browser, arc bulges included), put the number in the
  coordinates, and let `tests/test_icons.py` pin it: it asserts one grid, zero
  transforms, and every single-path glyph's ink centre. `play` is the one
  deliberate asymmetry - 0.75 right of centre - and `OPTICAL_X` in that test is
  its single knob.
- **A visual problem gets a measurement, not a compensation.** When the user
  says something "looks off", reproduce it as a number first, then fix it
  where that value is defined: the glyph's own coordinates, the layout rule
  itself. Do not layer a CSS transform, a margin or a negative offset on top of
  the cause. Stacked compensations are how the play button ended up with a CSS
  `translateX(1px)` *and* a path `translate(0.6 0)` at once - removing one left
  the other's number wrong, and the glyph crossed to the far side of centre, so
  the complaint survived the fix. Two more rules from the same episode: check
  the thing is rendered at all before tuning it (a `settings` glyph that two
  rounds "centred" was drawn by nothing - the button uses lucide's
  `Settings2`, so `grep -c 'name="settings"'` was 0), and never report a visual
  fix as verified without pixels.
- **You can get pixels. Do not claim otherwise.** This was recorded here as
  "the cloud sandbox has no browser", and that sentence cost four rounds of
  guessing: a browser is a download, not a system package. Nothing is
  installed, but everything needed installs without root, and it takes about
  as long as a test run. `npx --yes playwright@latest install --only-shell
  chromium` puts a `chrome-headless-shell` in `~/.cache/ms-playwright`; it is
  missing a dozen shared libraries and there is no root or font, so fetch them
  unprivileged and unpack them somewhere private:

  ```sh
  apt-get -o Dir::State::lists=$HOME/.apt/lists -o Dir::Cache=$HOME/.apt/cache \
          -o Dir::Etc::sourcelist=$HOME/.apt/sources.list \
          -o Dir::Etc::sourceparts=/dev/null update    # sources.list: noble main universe
  apt-get ... download libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 \
          libatspi2.0-0t64 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
          libasound2t64 libxkbcommon0 libxrender1 libxi6 fonts-liberation
  for f in *.deb; do dpkg -x "$f" ~/sysroot/; done
  export LD_LIBRARY_PATH=$HOME/sysroot/usr/lib/x86_64-linux-gnu   # add libs the
  #   linker then asks for (libXrender, libXi, ...) until `ldd | grep 'not found'`
  #   is empty - they are transitive, so iterate.
  cp ~/sysroot/usr/share/fonts/**/*.ttf ~/.local/share/fonts/      # sans-serif or
  #   every glyph renders as a box; there are no fonts at all in the image.
  ```

  Then `serve_web.py` with a throwaway `KOTASSIUM_LIB` and
  `chrome-headless-shell --no-sandbox --user-data-dir=/tmp/p --window-size=W,H
  --virtual-time-budget=6000 --screenshot=out.png http://127.0.0.1:PORT/`.
  For anything that needs a click, a hover or a computed style, install
  `npm i --no-save --no-package-lock playwright-core` (no browser download) and
  launch the same shell with `chromium.launch({executablePath: SHELL_BIN})`;
  that is how two 1.5px icon offsets were found, which no box model reports
  correctly because the glyph was overflowing its own content box.
  Measure the PNG with Pillow (`venv/bin/pip install pillow`) instead of
  describing it; cross-check against `tools/icon_bbox.py`, which is what the
  rendered glyph should agree with. Proof it works: the 44px card play disc
  measures its ink box centre at 12.750 in glyph units, and the PNG shows the
  box centred on the disc and the ink *mass* 0.4px left of it - the exact
  asymmetry that makes a box-centred triangle read left. Keep screenshots in
  `artifacts/` (gitignored), never in the repo proper.
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
- `.github/workflows/release.yml` builds the macOS PKG and Android APK on a `v*` tag and
  publishes one release; `workflow_dispatch` only uploads artifacts.
- **A push puts the PKG up in about half a minute, and the cheap path is
  deliberate.** The macOS build no longer waits for the `version` job: it asks
  `tools/next-version.sh` for the same patch bump and starts immediately. It
  reuses the app bundle py2app produced last time - py2app packages the
  interpreter, pyobjc and pywebview, none of which depend on our sources -
  and `tools/update-macos-bundle.py` brings the bundle up to this commit before
  re-signing: this build's modules (the ones `setup-macos.py` lists) go to
  `Contents/Resources/app/`, which `desktop.py` puts first on `sys.path` because
  py2app compiles the copies it packs instead of leaving them loose; the loose
  `desktop.py` is replaced where it is, `web/`, `assets/`, the icon and the
  version stamp are replaced whole, and every module is byte-compared after
  copying. `--selftest` reports where `serve_web` was imported from and the
  smoke test fails the build unless a reused bundle says `Resources/app`, so
  shadowing that silently did not take effect cannot ship. `build-macos.sh` rebuilds from
  scratch whenever the helper does not recognise the bundle, and the CI cache is
  only saved after the smoke test passed. **Bump the `v1` in that cache key in
  `build.yml` when a dependency is added** - a stale bundle fails the smoke test
  rather than shipping, but bumping is how you fix it. The PKG is then attached
  by the build job itself through `tools/publish-release.sh` (shared with the
  APK and the tag path) once `tools/await-preflight.sh` has seen this run's
  preflight pass: publishing moved, the gate did not. The APK is built after the
  PKG finishes rather than beside it - the PKG is what a push is waiting for -
  but it still builds when the macOS job failed (`!cancelled()`), so one broken
  platform does not silently stop the other.

- UI state (playlists, cached covers) lives outside the repo in
  `~/Music/Kotassium` — never commit from there. `KOTASSIUM_LIB` overrides the
  library root; tests and `tools/demo.py` use a throwaway copy.
- `spotify_get.py` is required by `serve_web.py` (Spotify link resolution);
  keep it if the server keeps working.
- The Newgrounds Audio Portal is a search/download lane inside `serve_web.py`
  (`ng_search` / `ng_resolve` / `ng_fetch`). Its HTML pages sit behind
  "NG Guard": a 403 proof-of-work challenge (argon2id) that `_ng_fetch`
  solves with `argon2-cffi` when importable and otherwise records as a
  per-lane error in `/api/search` - never let that lane take the others down.
  Get the challenge with GET (POST validates action/formNonce and 400s).
  Library ids are namespaced `ng-<audio id>`, so `/api/ytdl` and the page's
  id cache hand them to `ng_fetch` (direct mp3 from audio.ngfiles.com, the
  official `/audio/download/<id>` as fallback) instead of yt-dlp, and ffmpeg
  is never required for them. Keep the `c=3` search URL and the separate t/a
  hints: the portal ANDs whole terms, so artist+title alone matches remakes
  while the bare title finds the original. Android's pip list has no
  argon2-cffi, so the lane degrades there by design.
- SoundCloud is the third search/download lane (`sc_search` / `sc_track` /
  `sc_media` / `sc_fetch`). api-v2 needs the public `client_id` from
  SoundCloud's own script bundles: `_sc_client_id` scrapes it lazily,
  `_sc_json` re-scrapes once on a 401/403, and the lane **raises** on failure
  so `/api/search` records it in `errors` - a silent `{"results": []}` made it
  look like "no results" while the API was refusing us. Library ids are
  namespaced `sc-<track id>`; `ytdl()` and the page's id cache hand them to
  `sc_fetch`, which prefers a progressive mp3 and otherwise reassembles the
  HLS playlist (init segment + fragments) into an `.m4a` - fMP4 concatenates
  cleanly, so neither ffmpeg nor yt-dlp is involved and Android keeps working.
  Never store the resolved media URL: it is signed and must be resolved per
  download. `src=soundcloud` runs that lane alone, like every other selector.
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
- The `title|artist` → track-id map is what keeps a song from being downloaded
  twice, so it lives next to the library (`webstate/trackids.json`,
  `GET`/`POST /api/trackids`) and is only mirrored into the page's
  localStorage. A browser-only map lost its contents on a cleared web view or
  a second device, and the fresh search that followed could pick a different
  video - a second file for the same song. `GET` returns only ids whose file
  is still in `LIB`; the page reports a pairing when an id starts playing and
  forgets one when its candidate turns out to be the wrong track.
- **Picking the upload is `rank_videos`, not the nearest length.** The page
  asked for a YouTube search and played whichever result ran closest to the
  track's expected duration; searching ASGORE played a concert recording or a
  "VS CHAOS KING" animation over the official soundtrack, because length is
  the one thing a parody, a lyrics video, a 1-hour loop and a different song
  on the same soundtrack all get right. The page now sends its title/artist/
  length hints with `pick=1` and `serve_web.rank_videos` weighs them the right
  way round: title coverage and the artist's own channel (exact, or `- Topic`;
  a channel that merely contains the artist's name is a fan page) identify the
  recording, words added before or beyond the title mark a take on it or the
  next track on the album, and the markers in `_YT_TAKE` cover the usual
  "parody / lyrics / 1 hour / live / (Rhythm Ver.)" cases. The length is
  graded evidence on top of that, not a threshold and not the only thing: it
  separates candidates that describe the track equally well (the album cut at
  the tracklist's 177s over a 184s upload on the same channel) and sinks a
  different cut, but it saturates at 2.2 - just below the 2.5 for the artist's
  channel - so a tracklist that times another master cannot throw the
  artist's own upload out. Strip bracket metadata from the *raw* title: `_ng_norm`
  already turns "(" into a space, so stripping afterwards matches nothing and
  every soundtrack upload paid for "(DELTARUNE Chapter 2 Soundtrack)" as five
  extra words. `pick=1` is
  only for resolving one known track: without it `/api/search` returns
  YouTube's own order for the visible result list. `tests/test_search_rank.py`
  pins this on the ASGORE payload that produced the report; tune the weights
  against it and the probe songs, never by nudging a single case.
- The page reports now-playing to `POST /api/nowplaying`; `desktop.py` polls it
  for MPRIS and notifications. Media keys/MPRIS are Linux-only.
- Desktop binds `127.0.0.1`. `--lan` / `--host 0.0.0.0` is the only way to
  serve phones; requests are guarded by `Host` (IP literals/loopback only) and
  same-origin checks for POSTs.
- macOS packaging (`setup-macos.py`, `build-macos.sh`, `install-macos.sh`) can
  only be tested on a Mac; keep it boring and note it as unverified.
- **Drive the page, don't guess.** `venv/bin/python tools/ui.py tools/ui_views.json`
  runs every view at phone and desktop width, audits icon centring (`{"icons": "all"}`)
  and writes one contact sheet, `artifacts/ui/review.png`. It takes JSON steps
  (`goto`, `click`, `hover`, `press`, `eval`, `shot`, `sheet`). The scores and
  categories are in `tools/ui_rubric.md`. Play triangles carry the documented
  optical offset, so the audit lists them and that is expected.
- **Before shipping, run `tools/agent-preflight.sh`.** It executes the portable
  unittest suite, Python compilation checks and (when Node is installed) the
  page's JavaScript syntax check. It requires `yt-dlp` available to the chosen
  Python (`PYTHON=/path/to/python tools/agent-preflight.sh`); MPRIS tests skip
  without a session bus. The suite includes `tests/test_icons.py`, so an icon
  nudge or a second viewBox fails the gate instead of shipping. The shared
  release build workflow runs this same gate, and no artifact is published
  until it has passed: the tag path waits on the preflight job, and the macOS
  build that publishes its own PKG polls it (`tools/await-preflight.sh`). A
  failing preflight still blocks publishing.
- Tests: `venv/bin/python -m unittest discover -s tests`, plus
  `dbus-run-session -- desktop-venv/bin/python -m unittest tests.test_mpris`
  and `xvfb-run -a desktop-venv/bin/python tools/ui_check.py`.
- Updates are installer-package based (`updater.py`), and one click on the
  download button finishes them: the public repo's latest release is checked
  at launch and on demand from the page's pill, the PKG is verified against
  `SHA256SUMS`, then `stage_app()` unpacks it with `pkgutil` (no root) and a
  detached helper waits for the quit, moves the previous bundle aside as
  `/Applications/Kotassium.app.old` for recovery when installed in
  `/Applications`, renames the staged bundle into its place and reopens it.
  The swap is two renames, never a delete-and-copy: a PKG install leaves the
  installed bundle root-owned, which the logged-in user can neither delete in
  place nor copy over — that is what made every update die with "could not
  install the update". A rename needs only the write bit on the folder holding
  the app, which is exactly what `can_swap()` asks for, and an unremovable
  `.old` is parked as `.old.stale.<pid>` instead of blocking the update. The
  helper deletes those parked copies it can (the root-owned ones go in the
  root-run preinstall) and the PKG itself once the swap succeeds, and
  `download()` prunes older packages first, so the cache never holds more
  than one installer. The
  helper waits
  about fifteen seconds for the clean quit and then stops the app itself
  (TERM, then KILL), so nothing after the download click is left waiting on a
  person; it only writes a failure when the process cannot be stopped at all.
  Every step of the helper is appended to
  `~/Library/Caches/Kotassium/update/install.log`, a failure carries the
  failing command's own message into the report (never a bare "could not
  install the update"), and the executable bit that package expansion can
  drop is restored instead of refusing the bundle. When the folder holding
  the app is not writable — or the swap fails anyway — the helper hands the
  verified PKG to macOS Installer, which runs as root, so an update finishes
  instead of dead-ending. `start_install()` installs the release the last
  check already found — no
  second GitHub request at click time — and claims `state: "downloading"`
  before the response goes out, so the page starts polling immediately, and a
  refusal to start comes back with `error` for the pill to show. macOS Installer
  is only the fallback when the bundle cannot be replaced in place
  (read-only location, unpackable package): its preinstall script then asks
  before quitting a running Kotassium; the recovery endpoint displays Finder
  restore instructions rather than modifying the root-owned app from the user
  process. A helper failure is written next to the cache and reported on the
  next launch. `updater.check_async()` runs a check on a
  background thread and returns immediately with `state: "checking"` — unless
  such a failure is pending, which it reports instead — and it is
  single-flight (one click = one GitHub request, so it never stacks a second
  thread and never clobbers an install in progress). The page polls
  `GET /api/update` until the state settles. `POST /api/update/check` triggers
  that manual check. The top-right  pill is one morphing button — ⟳ check (idle)
  → ⟳ spin (checking) → ⬇ download (update available) → Restart/Retry — and
  the Settings dialog's About row shows the current version (from
  `/api/update`, or "development build" for a source checkout), refreshing
  the status whenever the dialog opens. The About row is on every platform;
  only frozen macOS builds report `supported`, and the page hides the pill
  everywhere else.
