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


def notify(title, body):
    if sys.platform == "darwin":
        _run(["osascript", "-e",
              'display notification "%s" with title "%s"' % (_q(body), _q(title))])
    elif shutil.which("notify-send"):
        _run(["notify-send", "-a", "Kotassium", title, body])


def available():
    if sys.platform == "darwin":
        return shutil.which("osascript") is not None
    return shutil.which("notify-send") is not None
