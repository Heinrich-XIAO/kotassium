"""updater.py - self-update from GitHub Releases (macOS app bundle only).

The PKG on the release page is the same artifact this installs, so the update
path is: check the releases API, download the PKG for this architecture,
verify it against the published SHA256SUMS, then open it with macOS Installer.
The package asks before quitting a running Kotassium and owns the app replacement.

Only runs when frozen (inside Kotassium.app). On Linux and when running from a
source checkout it reports `supported: false` and the UI hides the banner.
"""
import hashlib, json, os, plistlib, platform, re, subprocess, sys
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
    with _lock:
        _state.update(state="checking", error=None)
    try:
        rel = latest_release()
        tag = rel.get("tag_name") or ""
        package, _ = asset_for(rel)
        avail = newer(tag, current_version()) and bool(package)
        with _lock:
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

def install(asset, sums_asset=None):
    """Download and verify a package, then open it in macOS Installer."""
    with _lock:
        _state.update(state="downloading", pct=0, error=None)
    try:
        package = download(asset, sums_asset,
                           progress=lambda p: _state.update(pct=p))
        with _lock:
            _state.update(state="installing", pct=100)
        subprocess.Popen(["/usr/bin/open", "-a", "Installer", package],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        with _lock:
            _state.update(state="ready", pct=100)
    except Exception as e:
        with _lock:
            _state.update(state="error", error=str(e)[:300], pct=0)


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
    rel = latest_release()
    package, sums = asset_for(rel)
    if not package:
        raise RuntimeError("no build for this Mac in %s" % (rel.get("tag_name") or "release"))
    _worker = threading.Thread(target=install, args=(package, sums), daemon=True)
    _worker.start()
    return status()


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


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Kotassium updater")
    ap.add_argument("--check", action="store_true", help="print update status")
    a = ap.parse_args(argv)
    print(json.dumps(check() if a.check else status(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
