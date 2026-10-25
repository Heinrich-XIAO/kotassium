"""updater.py - self-update from GitHub Releases (macOS app bundle only).

The DMG on the release page is the same artifact this installs, so the update
path is: check the releases API, download the DMG for this architecture,
verify it against the published SHA256SUMS, mount it, copy the new app next to
the old one, then hand a small shell script the job of swapping the bundle
once this process exits and relaunching.

Only runs when frozen (inside Kotassium.app). On Linux and when running from a
source checkout it reports `supported: false` and the UI hides the banner.
"""
import hashlib, json, os, plistlib, platform, re, shutil, subprocess, sys
import tempfile, threading, time, urllib.request

REPO = "Heinrich-XIAO/kotassium"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
UA = "Kotassium-Updater"
SUPPORTED = sys.platform == "darwin" and bool(getattr(sys, "frozen", False))
CHECK_EVERY = 6 * 3600

_lock = threading.Lock()
_state = {"state": "idle", "pct": 0, "error": None, "available": False,
          "latest": None, "url": None, "notes": None, "checked": 0}
_worker = None
_rollback_worker = None

# Set by desktop.py: called once the swap script is running and this process
# should quit. Falls back to a hard exit if the window does not close.
on_installed = None


# ---------------------------------------------------------------- paths

def app_path():
    """The .app bundle containing this process, or None when not frozen."""
    if not getattr(sys, "frozen", False):
        return None
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(sys.executable))))


def current_version():
    app = app_path()
    if app:
        try:
            with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
                return str(plistlib.load(f).get("CFBundleShortVersionString") or "0")
        except Exception:
            pass
    return os.environ.get("KOTASSIUM_VERSION", "0")


def arch():
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def cache_dir():
    d = os.path.expanduser("~/Library/Caches/Kotassium/update")
    os.makedirs(d, exist_ok=True)
    return d


def can_install():
    """True if this copy can replace itself. False from a DMG or a read-only
    install."""
    app = app_path()
    if not app:
        return False
    if "/AppTranslocation/" in app or app.startswith("/Volumes/"):
        return False
    return os.access(os.path.dirname(app), os.W_OK)


def previous_app_path(target=None):
    """Path where a successful self-update keeps the last working app bundle."""
    target = target or app_path()
    return target + ".old" if target else None


def rollback_available():
    previous = previous_app_path()
    return bool(SUPPORTED and can_install() and previous and os.path.isdir(previous))


def _rollback_available_for(target):
    previous = previous_app_path(target)
    return bool(target and os.path.isdir(target) and previous and os.path.isdir(previous))


# ---------------------------------------------------------------- versions

def parse_version(text):
    """'v2.1.0' -> (2, 1, 0). Non-numeric suffixes are ignored."""
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:3]) or (0,)


def newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


# ---------------------------------------------------------------- GitHub

def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_release():
    return json.loads(_get(API).decode("utf-8", "replace"))


def asset_for(release, machine=None):
    """The .dmg for this architecture, plus the checksum file if published."""
    machine = machine or arch()
    dmg = None
    for a in release.get("assets") or []:
        name = a.get("name") or ""
        if not name.endswith(".dmg"):
            continue
        if machine in name:
            dmg = a
            break
    sums = None
    for a in release.get("assets") or []:
        if (a.get("name") or "").upper().startswith("SHA256SUMS"):
            sums = a
            break
    return dmg, sums


def check():
    """Fetch the latest release and update the shared state."""
    with _lock:
        _state.update(state="checking", error=None)
    try:
        rel = latest_release()
        tag = rel.get("tag_name") or ""
        dmg, _ = asset_for(rel)
        avail = newer(tag, current_version()) and bool(dmg)
        with _lock:
            _state.update(state="idle", latest=tag.lstrip("v"), url=rel.get("html_url"),
                          notes=(rel.get("body") or "")[:2000], available=avail,
                          checked=int(time.time()), error=None if dmg else
                          "no build for this Mac in %s" % (tag or "the latest release"))
    except Exception as e:
        with _lock:
            _state.update(state="idle", available=False, latest=None,
                          error="update check failed: %s" % e)
    return status()


def status():
    with _lock:
        s = dict(_state)
    s.update(supported=SUPPORTED, version=current_version(), can_install=can_install(),
             arch=arch())
    return s


# ---------------------------------------------------------------- download

def parse_checksums(text, name):
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    return None


def _checksum(sums_asset, dmg_name):
    if not sums_asset:
        return None
    try:
        text = _get(sums_asset["browser_download_url"]).decode("utf-8", "replace")
    except Exception:
        return None
    return parse_checksums(text, dmg_name)


def download(asset, sums_asset=None, progress=None):
    """Download an asset to the cache dir, verify it, return its path."""
    name = asset["name"]
    dest = os.path.join(cache_dir(), name)
    tmp = dest + ".part"
    want = _checksum(sums_asset, name)
    h = hashlib.sha256()
    got = 0
    total = int(asset.get("size") or 0)
    req = urllib.request.Request(asset["browser_download_url"],
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress and total:
                progress(min(99, int(got * 100 / total)))
    if want and h.hexdigest() != want:
        os.unlink(tmp)
        raise RuntimeError("checksum mismatch for %s" % name)
    if total and got != total:
        os.unlink(tmp)
        raise RuntimeError("short download for %s (%d/%d bytes)" % (name, got, total))
    os.replace(tmp, dest)
    if progress:
        progress(100)
    return dest


# ---------------------------------------------------------------- install

SWAP_SCRIPT = """#!/bin/sh
# Written by Kotassium's updater. Waits for the old app to exit, swaps in the
# new bundle, and reopens it. Keep one previous app for manual recovery; restore
# it automatically if the new bundle cannot be installed.
TARGET="$1"; NEW="$2"; PID="$3"; RELAUNCH="$4"; MODE="$5"
PREVIOUS="$TARGET.old"; SAVED="$TARGET.old.next"
if [ "$PID" != "0" ]; then
  i=0
  while kill -0 "$PID" 2>/dev/null; do
    sleep 0.5
    i=$((i + 1))
    [ "$i" -gt 240 ] && exit 1
  done
fi
rm -rf "$SAVED"
if [ -d "$PREVIOUS" ]; then
  if ! mv "$PREVIOUS" "$SAVED"; then
    [ "$RELAUNCH" = "1" ] && open "$TARGET"
    exit 1
  fi
fi
if ! mv "$TARGET" "$PREVIOUS"; then
  [ -d "$SAVED" ] && mv "$SAVED" "$PREVIOUS"
  [ "$RELAUNCH" = "1" ] && open "$TARGET"
  exit 1
fi
if ditto "$NEW" "$TARGET"; then
  if [ "$MODE" = "keep" ]; then
    rm -rf "$SAVED"
  elif [ "$MODE" = "rollback" ] || [ "$MODE" = "discard" ]; then
    rm -rf "$PREVIOUS" "$SAVED"
  elif [ -d "$SAVED" ]; then
    mv "$SAVED" "$PREVIOUS"
  fi
  rm -rf "$NEW"
  xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null
  [ "$RELAUNCH" = "1" ] && open "$TARGET"
  exit 0
fi
rm -rf "$TARGET"
mv "$PREVIOUS" "$TARGET"
[ -d "$SAVED" ] && mv "$SAVED" "$PREVIOUS"
[ "$RELAUNCH" = "1" ] && open "$TARGET"
exit 1
"""


def mount(dmg):
    mnt = tempfile.mkdtemp(prefix="kotassium-update-")
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly",
                    "-mountpoint", mnt, dmg],
                   check=True, capture_output=True)
    return mnt


def stage(dmg):
    """Mount the DMG and copy its app out. Returns (staged_app, cleanup_dir)."""
    mnt = mount(dmg)
    try:
        src = os.path.join(mnt, "Kotassium.app")
        if not os.path.isdir(src):
            raise RuntimeError("Kotassium.app not found in the disk image")
        out = tempfile.mkdtemp(prefix="kotassium-app-")
        dst = os.path.join(out, "Kotassium.app")
        subprocess.run(["ditto", src, dst], check=True, capture_output=True)
    finally:
        subprocess.run(["hdiutil", "detach", mnt], capture_output=True)
    return dst, out


def swap(staged_app, target=None, relaunch=True, pid=None, mode="normal"):
    """Spawn a detached swap; mode can retain or discard the previous bundle."""
    target = target or app_path()
    if not target:
        raise RuntimeError("not running from an app bundle")
    script = os.path.join(cache_dir(), "swap.sh")
    with open(script, "w") as f:
        f.write(SWAP_SCRIPT)
    os.chmod(script, 0o755)
    log = os.path.join(cache_dir(), "update.log")
    with open(log, "ab") as lf:
        subprocess.Popen(["/bin/sh", script, target, staged_app,
                          str(pid if pid is not None else os.getpid()),
                          "1" if relaunch else "0",
                          str(mode)],
                         stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    return script


def install(asset, sums_asset=None):
    """Download, verify, stage and swap. Raises on failure."""
    with _lock:
        _state.update(state="downloading", pct=0, error=None)
    try:
        dmg = download(asset, sums_asset,
                       progress=lambda p: _state.update(pct=p))
        with _lock:
            _state.update(state="installing", pct=100)
        staged, _tmp = stage(dmg)
        swap(staged, mode="keep")
        with _lock:
            _state.update(state="ready", pct=100)
        if on_installed:
            try:
                on_installed()
            except Exception:
                pass
        # The window close should end the process; make sure it does.
        time.sleep(6)
        os._exit(0)
    except Exception as e:
        with _lock:
            _state.update(state="error", error=str(e)[:300], pct=0)


def start_install():
    """Kick off an install in the background (idempotent while running)."""
    global _worker
    if not SUPPORTED:
        return status()
    if not can_install():
        raise RuntimeError("Kotassium can only update itself from a writable "
                           "copy — move it to /Applications")
    with _lock:
        if _worker and _worker.is_alive():
            return dict(_state)
    rel = latest_release()
    dmg, sums = asset_for(rel)
    if not dmg:
        raise RuntimeError("no build for this Mac in %s" % (rel.get("tag_name") or "release"))
    _worker = threading.Thread(target=install, args=(dmg, sums), daemon=True)
    _worker.start()
    return status()


def rollback():
    """Restore the retained previous bundle without needing the React UI."""
    global _rollback_worker
    if not SUPPORTED or not can_install():
        raise RuntimeError("rollback is only available from a writable app bundle")
    if not rollback_available():
        raise RuntimeError("no previous Kotassium version is available")
    if _rollback_worker and _rollback_worker.is_alive():
        return status()
    target = app_path()
    previous = previous_app_path(target)
    staged_dir = tempfile.mkdtemp(prefix="kotassium-rollback-")
    staged = os.path.join(staged_dir, "Kotassium.app")
    try:
        subprocess.run(["ditto", previous, staged], check=True, capture_output=True)
        swap(staged, target=target, mode="rollback")
    except Exception:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise
    _rollback_worker = threading.Thread(target=_exit_for_rollback, daemon=True)
    _rollback_worker.start()
    return dict(status(), state="installing", rollback_started=True)


def _exit_for_rollback():
    if on_installed:
        try:
            on_installed()
        except Exception:
            pass
    time.sleep(6)
    os._exit(0)


def check_async():
    """Start a release check in the background, returning the status with
    state="checking" so the page can spin while the answer is on its way.

    Never runs alongside another check (one click = one GitHub request, and
    the anonymous quota is 60/hour) and never disturbs an install in
    progress: while a download is running its own state is more interesting
    than a fresh check.
    """
    with _lock:
        run = _state.get("state") not in ("checking", "downloading",
                                          "installing", "ready")
        if run:
            _state.update(state="checking", error=None)
    if run:
        threading.Thread(target=check, daemon=True).start()
    return status()


# ---------------------------------------------------------------- selftest

def selftest(dmg):
    """Exercise mount/stage/swap against a throwaway target. Used by CI.

    Proves the risky parts work without needing a real newer release or a GUI.
    """
    ok = True
    print("dmg     %s" % dmg)
    staged, tmp = stage(dmg)
    print("staged  %s" % staged)
    target = os.path.join(tmp, "Target.app")
    subprocess.run(["ditto", staged, target], check=True, capture_output=True)
    script = swap(staged, target=target, relaunch=False, pid=0, mode="discard")
    print("script  %s" % script)
    deadline = time.time() + 60
    while time.time() < deadline and os.path.exists(staged):
        time.sleep(0.5)
    ok = ok and not os.path.exists(staged)
    print("%-7s swap completed" % ("ok" if not os.path.exists(staged) else "TIMEOUT"))
    for rel in ("Contents/Resources/web/index.html",
                "Contents/Resources/bin/yt-dlp",
                "Contents/MacOS/Kotassium"):
        p = os.path.join(target, rel)
        good = os.path.exists(p)
        ok = ok and good
        print("%-7s %s" % ("ok" if good else "MISSING", rel))
    v = subprocess.run(["codesign", "--verify", "--deep", "--strict", target],
                       capture_output=True)
    ok = ok and v.returncode == 0
    print("%-7s codesign" % ("ok" if v.returncode == 0 else "FAILED"))
    shutil.rmtree(tmp, ignore_errors=True)
    print("RESULT  %s" % ("ok" if ok else "failed"))
    return 0 if ok else 1


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Kotassium updater")
    ap.add_argument("--check", action="store_true", help="print update status")
    ap.add_argument("--selftest", metavar="DMG", help="test mount/swap with a DMG")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a.selftest)
    print(json.dumps(check() if a.check else status(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
