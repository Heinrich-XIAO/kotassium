"""updater.py - self-update from GitHub Releases (macOS app bundle only).

The PKG on the release page is the same artifact this installs, so the update
path is: check the releases API, download the PKG for this architecture,
verify it against the published SHA256SUMS, unpack it and swap the app in
behind the scenes - one click on the download button, no further dialogs. A
detached helper waits for the quit, keeps the old bundle as Kotassium.app.old,
moves the new one in and reopens it. macOS Installer stays as the fallback
for locations we cannot replace ourselves, keeping its own confirmation.

Only runs when frozen (inside Kotassium.app). On Linux and when running from a
source checkout it reports `supported: false` and the UI hides the banner.
"""
import hashlib, json, os, plistlib, platform, re, shlex, shutil, subprocess, sys
import threading, time, urllib.request

REPO = "Heinrich-XIAO/kotassium"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
UA = "Kotassium-Updater"
SUPPORTED = sys.platform == "darwin" and bool(getattr(sys, "frozen", False))
CHECK_EVERY = 6 * 3600

_lock = threading.Lock()
_state = {"state": "idle", "pct": 0, "error": None, "available": False,
          "latest": None, "url": None, "notes": None, "checked": 0}
_worker = None
# The release the last check found, kept so the download click has everything
# it needs: the pill is offering exactly that build, and querying GitHub a
# second time when the button is pressed is one more request that can fail and
# leave the click doing nothing.
_release = None

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
    """True if this copy can update through Installer from a normal app path."""
    app = app_path()
    if not app:
        return False
    if "/AppTranslocation/" in app or app.startswith("/Volumes/"):
        return False
    # The signed/elevated macOS Installer owns writes to the system Applications
    # folder; the running user need not have direct write permission there.
    if os.path.abspath(app) == "/Applications/Kotassium.app":
        return True
    return os.access(os.path.dirname(app), os.W_OK)


def previous_app_path(target=None):
    """Path where the installer keeps the last working app bundle."""
    target = target or app_path()
    return target + ".old" if target else None


def rollback_available():
    previous = previous_app_path()
    # The package installer keeps recovery beside the system Applications app.
    # Other install locations do not have a supported package rollback path.
    return bool(SUPPORTED and can_install()
                and os.path.abspath(app_path() or "") == "/Applications/Kotassium.app"
                and previous and os.path.isdir(previous))


def rollback():
    """Explain how to restore the package installer’s retained app copy."""
    if not rollback_available():
        raise RuntimeError("rollback is only available after a Kotassium package upgrade; no previous app bundle is available")
    raise RuntimeError("Quit Kotassium, then in Finder replace /Applications/Kotassium.app with /Applications/Kotassium.app.old and open it")


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
    """The .pkg for this architecture, plus the checksum file if published."""
    machine = machine or arch()
    pkg = None
    for a in release.get("assets") or []:
        name = a.get("name") or ""
        if not name.endswith(".pkg"):
            continue
        if machine in name:
            pkg = a
            break
    sums = None
    for a in release.get("assets") or []:
        if (a.get("name") or "").upper().startswith("SHA256SUMS"):
            sums = a
            break
    return pkg, sums


def check():
    """Fetch the latest release and update the shared state."""
    global _release
    with _lock:
        _state.update(state="checking", error=None)
    try:
        rel = latest_release()
        tag = rel.get("tag_name") or ""
        package, _ = asset_for(rel)
        avail = newer(tag, current_version()) and bool(package)
        with _lock:
            if avail:
                _release = rel
            _state.update(state="idle", latest=tag.lstrip("v"), url=rel.get("html_url"),
                          notes=(rel.get("body") or "")[:2000], available=avail,
                          checked=int(time.time()), error=None if package else
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


def _checksum(sums_asset, package_name):
    if not sums_asset:
        return None
    try:
        text = _get(sums_asset["browser_download_url"]).decode("utf-8", "replace")
    except Exception:
        return None
    return parse_checksums(text, package_name)


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

def failure_path():
    """Where the swap helper writes a reason when something goes wrong."""
    return os.path.join(cache_dir(), "install-failed.txt")


def take_failure():
    """Read and clear a swap failure reported by the helper (None if none)."""
    try:
        with open(failure_path(), "r", encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
        os.unlink(failure_path())
        return text or None
    except OSError:
        return None


def can_swap():
    """True when this app can be replaced in place, without macOS Installer.

    The helper moves bundles as the logged-in user, so the folder holding the
    app has to be writable (/Applications is group-admin writable, which
    covers every copy a PKG install produced). Translocated and
    disk-image copies still need the installer.
    """
    app = app_path()
    if not app:
        return False
    if "/AppTranslocation/" in app or app.startswith("/Volumes/"):
        return False
    return os.access(os.path.dirname(app), os.W_OK)


def _bundle_in(root):
    """The Kotassium.app inside an unpacked package, whatever its layout."""
    for dirpath, _dirs, _files in os.walk(root):
        if (os.path.basename(dirpath).endswith(".app") and
                os.path.isfile(os.path.join(dirpath, "Contents", "MacOS",
                                            "Kotassium"))):
            return dirpath
    return None


def _payload_cmd(payload, dest):
    """Shell pipeline unpacking a package Payload (cpio) into dest."""
    with open(payload, "rb") as f:
        head = f.read(2)
    if head == b"\x1f\x8b":      # gzip, what pkgbuild writes
        return ["/bin/sh", "-c",
                '/usr/bin/gzip -dc "$1" | (cd "$2" && /usr/bin/cpio -idm)',
                "sh", payload, dest]
    if head == b"07":            # already a bare cpio archive
        return ["/bin/sh", "-c", '(cd "$2" && /usr/bin/cpio -idm) < "$1"',
                "sh", payload, dest]
    raise RuntimeError("unsupported package payload for %s"
                       % os.path.basename(payload))


def stage_app(package, dest=None):
    """Unpack Kotassium.app from a verified package into the cache dir.

    No root and no Installer: pkgutil expands the package the way the
    installer would and the bundle is moved out as plain files. Raises when
    the package cannot be unpacked, which sends install() to macOS Installer.
    """
    dest = dest or os.path.join(cache_dir(), "Kotassium.new.app")
    work = dest + ".work"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    try:
        expanded = os.path.join(work, "expanded")
        bundle = None
        try:
            subprocess.run(["/usr/sbin/pkgutil", "--expand-full", package,
                            expanded], check=True, capture_output=True,
                           stdin=subprocess.DEVNULL)
            bundle = _bundle_in(expanded)
        except (OSError, subprocess.CalledProcessError):
            bundle = None
        if bundle is None:
            # Older macOS has no --expand-full: expand the package and unpack
            # its payload ourselves (gzip-compressed cpio, what pkgbuild writes).
            shutil.rmtree(expanded, ignore_errors=True)
            subprocess.run(["/usr/sbin/pkgutil", "--expand", package, expanded],
                           check=True, capture_output=True,
                           stdin=subprocess.DEVNULL)
            for dirpath, _dirs, files in os.walk(expanded):
                if "Payload" in files:
                    payload = os.path.join(dirpath, "Payload")
                    break
            else:
                raise RuntimeError("no payload in %s" % os.path.basename(package))
            payload_dir = os.path.join(work, "payload")
            os.makedirs(payload_dir)
            subprocess.run(_payload_cmd(payload, payload_dir),
                           check=True, capture_output=True,
                           stdin=subprocess.DEVNULL)
            bundle = _bundle_in(payload_dir)
        if bundle is None:
            raise RuntimeError("no Kotassium.app inside %s"
                               % os.path.basename(package))
        shutil.rmtree(dest, ignore_errors=True)
        shutil.move(bundle, dest)
        return dest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def swap_script(new_app, target=None):
    """Shell that finishes the update once this process is gone.

    The helper runs detached: it waits for the quit, keeps the current app as
    Kotassium.app.old (the copy the recovery panel restores), replaces the
    target, reopens it and reports any failure into the cache so the next
    launch can show why the update did not happen. The quit itself is not left
    to chance: an app that has not left within a few seconds is asked to go,
    then made to, so the update never stalls waiting for someone to act.
    """
    target = target or (app_path() or "/Applications/Kotassium.app")
    quote = shlex.quote
    return """#!/bin/sh
# Kotassium silent update - generated by updater.py, runs after the quit.
set -u
NEW=%(new)s
TARGET=%(target)s
PREVIOUS="$TARGET.old"
FAIL=%(fail)s
report() { printf '%%s\\n' "$1" > "$FAIL"; }

# 1. wait for the updater's quit request to take effect (about 15 seconds)
n=0
while /usr/bin/pgrep -x Kotassium >/dev/null 2>&1; do
    n=$((n + 1))
    if [ "$n" -ge 30 ]; then
        break
    fi
    /bin/sleep 0.5
done

# 2. it is still here: ask it to leave, then make it - nothing after the
#    download click is allowed to need a person
if /usr/bin/pgrep -x Kotassium >/dev/null 2>&1; then
    /bin/kill -TERM $(/usr/bin/pgrep -x Kotassium) 2>/dev/null
    m=0
    while /usr/bin/pgrep -x Kotassium >/dev/null 2>&1; do
        m=$((m + 1))
        if [ "$m" -ge 20 ]; then
            /bin/kill -KILL $(/usr/bin/pgrep -x Kotassium) 2>/dev/null
            /bin/sleep 2
            break
        fi
        /bin/sleep 0.5
    done
fi

# 3. give up only if the app genuinely cannot be stopped
if /usr/bin/pgrep -x Kotassium >/dev/null 2>&1; then
    report "Kotassium did not quit, so the update was not installed"
    exit 1
fi

# 4. never put a bundle we cannot open into place
if [ ! -x "$NEW/Contents/MacOS/Kotassium" ]; then
    report "the downloaded update is missing its app bundle"
    exit 1
fi

# 5. keep the current app for "Restore previous version" (as preinstall does)
STAGED="$TARGET.old.next"
if [ -d "$TARGET" ]; then
    /bin/rm -rf "$STAGED"
    if ! /usr/bin/ditto "$TARGET" "$STAGED"; then
        /bin/rm -rf "$STAGED"
        report "could not back up the current app; the update was not installed"
        exit 1
    fi
    /bin/rm -rf "$PREVIOUS"
    /bin/mv "$STAGED" "$PREVIOUS"
fi

# 6. replace it, restoring the old app if anything about the new one is wrong
/bin/rm -rf "$TARGET"
if ! /usr/bin/ditto "$NEW" "$TARGET" || [ ! -x "$TARGET/Contents/MacOS/Kotassium" ]; then
    /bin/rm -rf "$TARGET"
    if [ -d "$PREVIOUS" ]; then
        /usr/bin/ditto "$PREVIOUS" "$TARGET"
    fi
    report "could not install the update"
    exit 1
fi
/bin/rm -rf "$NEW"
/bin/rm -f "$FAIL"

# 7. reopen the new version
/usr/bin/open "$TARGET"
exit 0
""" % {"new": quote(new_app), "target": quote(target),
        "fail": quote(failure_path())}


def quit_running_app():
    """Ask the app to quit; the helper waits for the process to disappear.

    The same Apple event the package preinstall script sends, so the page and
    the server shut down before anything is replaced.
    """
    try:
        subprocess.run(["/usr/bin/osascript", "-e",
                        'tell application id "app.kotassium.desktop" to quit'],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15, check=False)
    except Exception:
        pass


def _watch_helper():
    """Turn a helper report into an error message while we are still alive.

    The helper only fails if the quit never took effect, in which case the
    app is still running and the page gets to say what went wrong instead of
    spinning on "installing update..." forever.
    """
    end = time.time() + 90
    while time.time() < end:
        time.sleep(1)
        text = take_failure()
        if text:
            with _lock:
                if _state.get("state") in ("installing", "ready"):
                    _state.update(state="error", error=text[:300], pct=0)
            return


def _open_installer(package):
    """Fallback: let macOS Installer own the replacement, dialogs and all."""
    subprocess.Popen(["/usr/bin/open", "-a", "Installer", package],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    with _lock:
        _state.update(state="ready", pct=100)


def install(asset, sums_asset=None):
    """Download, verify and install an update in one click.

    The package is unpacked and swapped in behind the scenes: stage the new
    bundle, hand a detached helper the replacement, quit. Only when the app
    cannot be replaced in place (read-only location, unpackable package)
    does macOS Installer take over, asking before quitting the running app.
    """
    with _lock:
        _state.update(state="downloading", pct=0, error=None)
    try:
        package = download(asset, sums_asset,
                           progress=lambda p: _state.update(pct=p))
    except Exception as e:
        with _lock:
            _state.update(state="error", error=str(e)[:300], pct=0)
        return
    with _lock:
        _state.update(state="installing", pct=100)
    staged = None
    if can_swap():
        try:
            staged = stage_app(package)
        except Exception:
            staged = None
    if staged is None:
        _open_installer(package)
        return
    try:
        script = os.path.join(cache_dir(), "swap.sh")
        with open(script, "w", encoding="utf-8") as f:
            f.write(swap_script(staged))
        os.chmod(script, 0o755)
        subprocess.Popen(["/bin/sh", script], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        threading.Thread(target=_watch_helper, daemon=True).start()
        quit_running_app()
    except Exception as e:
        with _lock:
            _state.update(state="error", error=str(e)[:300], pct=0)


def _release_for_install():
    """The release the download click should install.

    Prefers the one the last check found - that is the build the pill is
    offering - and only asks GitHub again when there is nothing usable in
    hand (first click of a session, or the app was updated since).
    """
    with _lock:
        rel = _release
    if rel:
        package, _ = asset_for(rel)
        if package and newer(rel.get("tag_name") or "", current_version()):
            return rel
    return latest_release()


def start_install():
    """Kick off an install in the background (idempotent while running)."""
    global _worker
    if not SUPPORTED:
        return status()
    if not can_install():
        raise RuntimeError("Kotassium can only update from an installed app "
                           "outside a disk image — move it to /Applications")
    with _lock:
        if _worker and _worker.is_alive():
            return dict(_state)
    rel = _release_for_install()
    package, sums = asset_for(rel)
    if not package:
        raise RuntimeError("no build for this Mac in %s" % (rel.get("tag_name") or "release"))
    # Claim the downloading state before the response goes out: the page starts
    # polling on it, and it must not race the worker thread's first statement.
    with _lock:
        _state.update(state="downloading", pct=0, error=None)
    _worker = threading.Thread(target=install, args=(package, sums), daemon=True)
    _worker.start()
    return status()


def check_async():
    """Start a release check in the background, returning the status with
    state="checking" so the page can spin while the answer is on its way.

    Never runs alongside another check (one click = one GitHub request, and
    the anonymous quota is 60/hour) and never disturbs an install in
    progress: while a download is running its own state is more interesting
    than a fresh check. A swap helper that failed after the last quit wrote
    its reason to the cache; that is reported instead of checking, so the
    user learns on the next launch why the app is still the old version.
    """
    pending = take_failure()
    with _lock:
        run = _state.get("state") not in ("checking", "downloading",
                                          "installing", "ready")
        if pending:
            _state.update(state="error", error=pending[:300], available=False)
            run = False
        elif run:
            _state.update(state="checking", error=None)
    if run:
        threading.Thread(target=check, daemon=True).start()
    return status()


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Kotassium updater")
    ap.add_argument("--check", action="store_true", help="print update status")
    a = ap.parse_args(argv)
    print(json.dumps(check() if a.check else status(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
