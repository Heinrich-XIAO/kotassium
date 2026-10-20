"""Helper process for tests/test_mpris.py: run the MPRIS service and log controls.

Kept separate so the test can talk to it with gdbus from another process while
the service's main loop stays free to dispatch method calls.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gi  # noqa: E402

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from mpris_linux import MprisLinux  # noqa: E402


def ctl(name):
    print("control:" + name, flush=True)


svc = MprisLinux("http://127.0.0.1:8421",
                 {"playpause": lambda: ctl("playpause"),
                  "next": lambda: ctl("next"),
                  "previous": lambda: ctl("previous")})
if not svc.conn:
    print("unavailable", flush=True)
    sys.exit(1)

svc.update({"t": "Song", "a": "Artist", "ms": 1000, "pos": 250,
            "state": "playing", "cover": "/cover/x"})

ctx = GLib.MainContext.default()
while ctx.pending():
    ctx.iteration(False)
print("ready", flush=True)
GLib.MainLoop().run()
