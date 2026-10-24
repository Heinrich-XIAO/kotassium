import tempfile
import unittest
from pathlib import Path
from unittest import mock

import notify


class NotificationIconTests(unittest.TestCase):
    def test_default_icon_finds_project_logo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = root / "assets" / "kotassium.svg"
            logo.parent.mkdir()
            logo.touch()
            with mock.patch.object(notify, "__file__", str(root / "notify.py")):
                self.assertEqual(notify.default_icon(), str(logo))

    def test_linux_notification_receives_icon_option(self):
        with mock.patch.object(notify.sys, "platform", "linux"), \
             mock.patch.object(notify.shutil, "which", return_value="/usr/bin/notify-send"), \
             mock.patch.object(notify, "_run") as run:
            notify.notify("Song", "Artist", icon="/app/logo.svg")
        run.assert_called_once_with([
            "notify-send", "-a", "Kotassium", "--icon", "/app/logo.svg", "Song", "Artist"
        ])


if __name__ == "__main__":
    unittest.main()
