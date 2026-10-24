"""OS notifications without extra dependencies.

Linux uses notify-send (libnotify); macOS uses osascript. Missing tools are a
no-op: notifications must never break playback.
"""
import shutil
import subprocess
import sys


def _run(cmd):
    try:
        subprocess.run(cmd, timeout=5, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _q(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def notify(title, body, icon=None):
    if sys.platform == "darwin":
        try:
            from Foundation import NSUserNotification, NSUserNotificationCenter
            notification = NSUserNotification.alloc().init()
            notification.setTitle_(str(title))
            notification.setInformativeText_(str(body))
            NSUserNotificationCenter.defaultUserNotificationCenter().deliverNotification_(notification)
        except Exception:
            # Keep notifications best-effort if the native API is unavailable.
            _run(["osascript", "-e",
                  'display notification "%s" with title "%s"' % (_q(body), _q(title))])
    elif shutil.which("notify-send"):
        cmd = ["notify-send", "-a", "Kotassium"]
        if icon:
            cmd.extend(["--icon", icon])
        _run(cmd + [title, body])


def default_icon():
    """Return the bundled raster Kotassium icon path for Linux notifications."""
    from pathlib import Path

    candidates = [
        Path(__file__).resolve().parent / "web" / "icons" / "icon-512.png",
        Path(sys.executable).resolve().parent.parent / "Resources" / "web" / "icons" / "icon-512.png",
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


def available():
    if sys.platform == "darwin":
        return shutil.which("osascript") is not None
    return shutil.which("notify-send") is not None
