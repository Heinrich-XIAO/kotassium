import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class WrapperTests(unittest.TestCase):
    """The web page is the only UI. The shells must stay shells, or a bug
    fixed in web/index.html would not be fixed everywhere."""

    WRAPPERS = ("desktop.py", "android/app/src/main/java/app/kotassium/mobile/MainActivity.java")

    def test_wrappers_contain_no_markup(self):
        for rel in self.WRAPPERS:
            src = read(rel).lower()
            for token in ("<html", "<div", "<style", "<button", "css", "stylesheet"):
                self.assertNotIn(token, src, "%s must not embed UI (%r)" % (rel, token))

    def test_wrappers_load_the_web_app(self):
        self.assertIn("http", read("desktop.py"))
        self.assertIn("loadUrl", read(self.WRAPPERS[1]))

    def test_wrappers_do_not_copy_the_page(self):
        page = read("web/index.html")
        for rel in self.WRAPPERS:
            src = read(rel)
            self.assertNotIn("<title>Kotassium</title>", src)
            # no chunk of the real page is pasted into a wrapper
            for chunk in ("id=nowp", "id=side", "function playIdx", "localStorage.getItem('kot_vol')"):
                self.assertNotIn(chunk, src, "%s copied markup from the page" % rel)

    def test_page_is_the_source_of_truth(self):
        page = read("web/index.html")
        self.assertIn("<title>Kotassium</title>", page)
        self.assertIn("serviceWorker", page)

    def test_android_runs_the_real_server(self):
        # The APK embeds CPython, but it must import the repo's server, not a
        # copy: the Gradle build stages these files from the repo root.
        gradle = read("android/app/build.gradle")
        for name in ("serve_web.py", "spotify_get.py", "updater.py"):
            self.assertIn(name, gradle, "android build must stage %s" % name)
        self.assertIn("new File(repoRoot, \"web\")", gradle)
        boot = read("android/app/src/main/python/kotassium_boot.py")
        self.assertIn("serve_web.serve_local", boot)
        self.assertIn("inproc", boot)

    def test_android_dialogs_can_be_dismissed(self):
        # Every dialog is a dead end if it only has one button: the address
        # prompt used to save "remote" before a URL existed, so backing out
        # left the app asking for an address it could never get past.
        src = read(self.WRAPPERS[1])
        dialogs = src.count("new AlertDialog.Builder")
        self.assertGreaterEqual(src.count(".setNegativeButton("), dialogs,
                                "every dialog needs a way back")
        self.assertNotIn("setCancelable(false)", src)
        choose = src.split("private void chooseMode()")[1].split("private void dismissChooser")[0]
        self.assertNotIn("MODE_REMOTE", choose,
                         "the mode must not be saved before an address is entered")

    def test_android_holds_no_copy_of_the_server_or_page(self):
        for dirpath, _, files in os.walk(os.path.join(ROOT, "android")):
            for name in ("serve_web.py", "index.html", "spotify_get.py", "updater.py"):
                self.assertNotIn(name, files, "%s must not be duplicated under android/" % name)


if __name__ == "__main__":
    unittest.main()
