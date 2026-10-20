"""MPRIS integration test.

Needs a session bus, so it skips in a bare shell. Run it with:

    dbus-run-session -- venv/bin/python -m unittest tests.test_mpris

The service runs in a helper process; gdbus (a separate connection) reads
properties and invokes controls, exactly like a desktop shell would.
"""
import os
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "tests", "mpris_helper.py")
BUS = "org.mpris.MediaPlayer2.kotassium"
PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"


def gdbus(*args):
    return subprocess.run(["gdbus", "call", "--session", "--dest", BUS,
                           "--object-path", PATH, "--method"] + list(args),
                          capture_output=True, text=True, timeout=10)


@unittest.skipUnless(os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
                     "needs a session bus (run under dbus-run-session)")
class MprisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen([sys.executable, HELPER], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
        # Wait for "ready" (or "unavailable").
        deadline = time.time() + 15
        while time.time() < deadline:
            line = cls.proc.stdout.readline()
            if not line:
                break
            if line.strip() in ("ready", "unavailable"):
                cls.ready = line.strip() == "ready"
                return
        cls.ready = False

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(5)
        except Exception:
            cls.proc.kill()

    def setUp(self):
        if not self.ready:
            self.skipTest("MPRIS service could not start")

    def test_name_owned_and_metadata(self):
        out = gdbus("org.freedesktop.DBus.Properties.Get", PLAYER, "Metadata")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Song", out.stdout)
        self.assertIn("Artist", out.stdout)

    def test_playback_status(self):
        out = gdbus("org.freedesktop.DBus.Properties.Get", PLAYER, "PlaybackStatus")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("Playing", out.stdout)

    def test_media_key_controls(self):
        for method, expected in (("PlayPause", "playpause"), ("Next", "next"),
                                 ("Previous", "previous")):
            out = gdbus(PLAYER + "." + method)
            self.assertEqual(out.returncode, 0, out.stderr)
            line = self.proc.stdout.readline().strip()
            self.assertEqual(line, "control:" + expected)


if __name__ == "__main__":
    unittest.main()
