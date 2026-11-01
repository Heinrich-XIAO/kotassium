"""The macOS build may reuse the bundle py2app built last time.

py2app packages the interpreter, pyobjc and pywebview, which do not depend on
our sources, so CI caches its output and replaces the files the checkout owns
instead of rebuilding it every push. That makes correctness depend on one
promise: the helper either replaces *everything* the commit owns - and proves
each copy byte for byte - or refuses so the build falls back to py2app. These
tests hold that promise: a bundle it cannot read is a refusal, never a partial
update, and a bundle it can read really does end up with this checkout's
modules, page and version in it.
"""

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER = os.path.join(ROOT, "tools", "update-macos-bundle.py")
REFUSE = 3


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def make_bundle(path, modules=("desktop.py", "serve_web.py")):
    """A directory tree in the shape py2app leaves behind."""
    resources = os.path.join(path, "Contents", "Resources")
    libdir = os.path.join(resources, "lib", "python3.12")
    os.makedirs(libdir)
    os.makedirs(os.path.join(resources, "web"))
    for name in modules:
        with open(os.path.join(libdir, name), "w") as f:
            f.write("# stale copy from an older commit\n")
    with open(os.path.join(path, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump({"CFBundleShortVersionString": "0.0.1",
                       "CFBundleVersion": "0.0.1",
                       "CFBundleIdentifier": "app.kotassium.desktop"}, f, fmt=plistlib.FMT_BINARY)
    return libdir


def make_checkout(path):
    for name in ("desktop.py", "serve_web.py"):
        with open(os.path.join(path, name), "w") as f:
            f.write("# %s from this commit\n" % name)
    os.makedirs(os.path.join(path, "web"))
    with open(os.path.join(path, "web", "index.html"), "w") as f:
        f.write("<title>Kotassium</title>\n")
    os.makedirs(os.path.join(path, "assets"))
    with open(os.path.join(path, "assets", "kotassium.svg"), "w") as f:
        f.write("<svg/>\n")


class BundleReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = os.path.join(self.tmp, "Kotassium.app")
        self.checkout = os.path.join(self.tmp, "checkout")
        os.makedirs(self.checkout)
        make_checkout(self.checkout)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_helper(self, *args):
        return subprocess.run([sys.executable, HELPER, "--app", self.app,
                               "--root", self.checkout, *args],
                              capture_output=True, text=True)

    def test_a_bundle_without_our_modules_is_refused(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, REFUSE, result.stderr)
        self.assertIn("no Contents/Resources", result.stderr)

    def test_a_bundle_that_does_not_hold_our_modules_is_refused(self):
        # py2app could zipped them, or the cache could be someone else's tree:
        # either way the build must not guess which file to replace.
        make_bundle(self.app, modules=("something_else.py",))
        result = self.run_helper()
        self.assertEqual(result.returncode, REFUSE, result.stderr)
        self.assertIn("desktop.py and serve_web.py", result.stderr)

    def test_a_recognised_bundle_gets_this_checkouts_files(self):
        libdir = make_bundle(self.app)
        result = self.run_helper("--version", "9.9.9")
        self.assertEqual(result.returncode, 0, result.stderr)

        for name in ("desktop.py", "serve_web.py"):
            with open(os.path.join(libdir, name)) as f:
                self.assertEqual(f.read(), "# %s from this commit\n" % name)
        self.assertTrue(os.path.isfile(
            os.path.join(self.app, "Contents", "Resources", "web", "index.html")))
        self.assertTrue(os.path.isfile(
            os.path.join(self.app, "Contents", "Resources", "assets", "kotassium.svg")))

        with open(os.path.join(self.app, "Contents", "Info.plist"), "rb") as f:
            plist = plistlib.load(f)
        self.assertEqual(plist["CFBundleShortVersionString"], "9.9.9")
        self.assertEqual(plist["CFBundleVersion"], "9.9.9")
        self.assertEqual(plist["CFBundleIdentifier"], "app.kotassium.desktop")

    def test_the_page_is_replaced_rather_than_merged(self):
        # A file deleted from web/ must not survive in the reused bundle; the
        # page is one directory and the commit is the truth about it.
        make_bundle(self.app)
        gone = os.path.join(self.app, "Contents", "Resources", "web", "removed.js")
        with open(gone, "w") as f:
            f.write("// deleted two commits ago\n")
        self.assertEqual(self.run_helper().returncode, 0)
        self.assertFalse(os.path.exists(gone))


class BuildWiringTests(unittest.TestCase):
    """The fallback is only real if the script can be told the bundle is there
    and rebuilds when it is not."""

    def test_the_build_reuses_only_a_restored_bundle_and_falls_back(self):
        build = read("build-macos.sh")
        self.assertIn('KOTASSIUM_REUSE_BUNDLE', build)
        self.assertIn("tools/update-macos-bundle.py", build)
        self.assertIn("rebuilding the bundle from scratch", build)
        self.assertEqual(build.count("rm -rf build dist"), 2,
                         "one clean before py2app, one when the overlay is refused")
        self.assertIn("KOTASSIUM_VERSION=\"$VERSION\" desktop-venv/bin/python setup-macos.py py2app", build)

    def test_ci_restores_the_bundle_and_publishes_without_a_third_runner(self):
        workflow = read(".github/workflows/build.yml")
        self.assertIn("actions/cache/restore@v4", workflow)
        self.assertIn("key: app-macos-${{ runner.arch }}-py312-v1-", workflow)
        self.assertIn("KOTASSIUM_REUSE_BUNDLE: ${{ steps.bundle.outputs.cache-hit == 'true' && '1' || '' }}", workflow)
        # Publishing from the build job still waits for preflight's verdict.
        step = workflow.split("- name: Publish the PKG", 1)[1].split("      - uses:", 1)[0]
        self.assertLess(step.index("tools/await-preflight.sh"),
                        step.index("tools/publish-release.sh"),
                        "the gate must run before the upload")
        self.assertIn("if: ${{ inputs.publish }}", workflow)

    def test_the_version_is_resolved_in_one_place(self):
        script = read("tools/next-version.sh")
        self.assertIn(".github/next_version.py", script)
        for workflow in (".github/workflows/build.yml", ".github/workflows/auto-release.yml"):
            self.assertIn("tools/next-version.sh", read(workflow), workflow)
        self.assertIn("tools/next-version.sh", read(".github/workflows/build.yml"))

    def test_the_publish_scripts_are_executable(self):
        for name in ("next-version.sh", "publish-release.sh", "await-preflight.sh"):
            path = os.path.join(ROOT, "tools", name)
            self.assertTrue(os.stat(path).st_mode & 0o111, name)


if __name__ == "__main__":
    unittest.main()
