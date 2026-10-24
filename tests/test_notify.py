import tempfile
import unittest
from pathlib import Path
from unittest import mock

import notify


class NotificationIconTests(unittest.TestCase):
    def test_default_icon_finds_project_logo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = root / "web" / "icons" / "icon-512.png"
            logo.parent.mkdir(parents=True)
            logo.touch()
            with mock.patch.object(notify, "__file__", str(root / "notify.py")):
                self.assertEqual(notify.default_icon(), str(logo))

    def test_bundle_resource_icon_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = root / "Resources" / "web" / "icons" / "icon-512.png"
            logo.parent.mkdir(parents=True)
            logo.touch()
            with mock.patch.object(notify, "__file__", str(root / "lib" / "notify.py")), \
                 mock.patch.object(notify.sys, "executable", str(root / "MacOS" / "Kotassium")):
                self.assertEqual(notify.default_icon(), str(logo))

    def test_linux_notification_receives_icon_option(self):
        with mock.patch.object(notify.sys, "platform", "linux"), \
             mock.patch.object(notify.shutil, "which", return_value="/usr/bin/notify-send"), \
             mock.patch.object(notify, "_run") as run:
            notify.notify("Song", "Artist", icon="/app/logo.png")
        run.assert_called_once_with([
            "notify-send", "-a", "Kotassium", "--icon", "/app/logo.png", "Song", "Artist"
        ])

    def test_macos_notification_uses_native_notification_center(self):
        import types

        delivered = []

        class Notification:
            @classmethod
            def alloc(cls):
                return cls()

            def init(self):
                return self

            def setTitle_(self, value):
                self.title = value

            def setInformativeText_(self, value):
                self.body = value

        class Center:
            @classmethod
            def defaultUserNotificationCenter(cls):
                return cls()

            def deliverNotification_(self, notification):
                delivered.append(notification)

        foundation = types.SimpleNamespace(NSUserNotification=Notification,
                                           NSUserNotificationCenter=Center)
        with mock.patch.object(notify.sys, "platform", "darwin"), \
             mock.patch.dict("sys.modules", {"Foundation": foundation}), \
             mock.patch.object(notify, "_run") as run:
            notify.notify("Song", "Artist")
        self.assertEqual((delivered[0].title, delivered[0].body), ("Song", "Artist"))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
