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


if __name__ == "__main__":
    unittest.main()
