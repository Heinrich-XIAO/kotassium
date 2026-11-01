"""The macOS build may reuse the bundle py2app built last time.

py2app packages the interpreter, pyobjc and pywebview, which do not depend on
our sources, so CI caches its output and replaces the files the checkout owns
instead of rebuilding it every push. That makes correctness depend on one
promise: the helper writes *everything* the commit owns - and proves each copy
byte for byte - or refuses so the build falls back to py2app.

py2app compiles the modules it packages, so they cannot be overwritten where
they lie; this build's copies go to ``Contents/Resources/app/``, which
``desktop.py`` puts first on ``sys.path``. That is only a fast path if it is the
path actually taken, which is why ```--selftest`` reports where ``serve_web``
was imported from and CI asserts it. These tests hold the two halves that can be
checked here: the bundle really does end up carrying this checkout's files, and
a bundle this does not understand is refused rather than half-updated.
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

SETUP = """\
APP = ["desktop.py"]
OPTIONS = {
    "packages": ["webview"],
    "includes": ["serve_web", "updater"],
}
"""


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def make_checkout(path, app="desktop", includes=("serve_web", "updater")):
    with open(os.path.join(path, "setup-macos.py"), "w") as f:
        f.write(SETUP)
    modules = ["%s.py" % app] + ["%s.py" % name for name in includes]
    for name in modules:
        with open(os.path.join(path, name), "w") as f:
            f.write("# %s from this commit\n" % name)
    # A Linux-only module the macOS bundle deliberately excludes.
    with open(os.path.join(path, "mpris_linux.py"), "w") as f:
        f.write("# never bundled on macOS\n")
    os.makedirs(os.path.join(path, "web"))
    with open(os.path.join(path, "web", "index.html"), "w") as f:
        f.write("<title>Kotassium</title>\n")
    os.makedirs(os.path.join(path, "assets"))
    with open(os.path.join(path, "assets", "kotassium.svg"), "w") as f:
        f.write("<svg/>\n")
    return modules


def make_bundle(app, script="desktop.py", includes=("serve_web.py", "updater.py")):
    """py2app's shape: the script loose at Resources/, includes compiled in.

    The includes are *not* written as .py files, because a compiled bundle is
    exactly the case that broke the first attempt: there is no file to replace,
    so the overlay has to shadow them.
    """
    resources = os.path.join(app, "Contents", "Resources")
    libdir = os.path.join(resources, "lib", "python3.12")
    os.makedirs(libdir)
    with open(os.path.join(resources, script), "w") as f:
        f.write("# stale copy from an older commit\n")
    for name in includes:
        with open(os.path.join(libdir, name[:-3] + ".pyc"), "wb") as f:
            f.write(b"stale bytecode")
    with open(os.path.join(libdir, "webview.py"), "w") as f:
        f.write("# a dependency, not ours\n")
    with open(os.path.join(app, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump({"CFBundleIdentifier": "app.kotassium.desktop",
                       "CFBundleShortVersionString": "0.0.1",
                       "CFBundleVersion": "0.0.1"}, f, fmt=plistlib.FMT_BINARY)
    return resources, libdir


class BundleReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = os.path.join(self.tmp, "Kotassium.app")
        self.checkout = os.path.join(self.tmp, "checkout")
        os.makedirs(self.checkout)
        self.modules = make_checkout(self.checkout)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_helper(self, *args):
        return subprocess.run([sys.executable, HELPER, "--app", self.app,
                               "--root", self.checkout, *args],
                              capture_output=True, text=True)

    def test_a_bundle_without_our_script_is_refused(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, REFUSE, result.stderr)
        self.assertIn("no Contents/Resources", result.stderr)

    def test_a_bundle_that_cannot_run_our_script_is_refused(self):
        resources, libdir = make_bundle(self.app)
        os.remove(os.path.join(resources, "desktop.py"))
        result = self.run_helper()
        self.assertEqual(result.returncode, REFUSE, result.stderr)
        self.assertIn("no desktop.py for py2app's boot script to run", result.stderr)
        self.assertFalse(os.path.isdir(os.path.join(resources, "app")),
                         "a refused bundle must not be touched at all")

    def test_the_compiled_modules_are_shadowed_by_this_checkout(self):
        resources, libdir = make_bundle(self.app)
        result = self.run_helper("--version", "9.9.9")
        self.assertEqual(result.returncode, 0, result.stderr)

        with open(os.path.join(resources, "desktop.py")) as f:
            self.assertEqual(f.read(), "# desktop.py from this commit\n",
                             "the boot script runs this by path, so it must be replaced")
        for name in self.modules:
            path = os.path.join(resources, "app", name)
            with open(path) as f:
                self.assertEqual(f.read(), "# %s from this commit\n" % name)
        self.assertFalse(os.path.exists(os.path.join(resources, "app", "mpris_linux.py")),
                         "a module setup-macos.py excludes must not be introduced")
        # py2app's own copies and the dependencies are left alone.
        self.assertEqual(open(os.path.join(libdir, "webview.py")).read(),
                         "# a dependency, not ours\n")
        self.assertFalse(os.path.exists(os.path.join(resources, "app", "web")),
                         "the page belongs next to the bundle, not in the overlay")
        self.assertTrue(os.path.isfile(os.path.join(resources, "web", "index.html")))
        self.assertTrue(os.path.isfile(os.path.join(resources, "assets", "kotassium.svg")))

        with open(os.path.join(self.app, "Contents", "Info.plist"), "rb") as f:
            plist = plistlib.load(f)
        self.assertEqual(plist["CFBundleShortVersionString"], "9.9.9")
        self.assertEqual(plist["CFBundleVersion"], "9.9.9")
        self.assertEqual(plist["CFBundleIdentifier"], "app.kotassium.desktop")

    def test_the_overlay_is_replaced_not_merged(self):
        # A module deleted from app/ (a module dropped from the bundle) must not
        # survive, and a file deleted from web/ must not survive either: the
        # commit is the truth about both.
        resources, _ = make_bundle(self.app)
        os.makedirs(os.path.join(resources, "app"))
        with open(os.path.join(resources, "app", "removed.py"), "w") as f:
            f.write("# deleted two commits ago\n")
        os.makedirs(os.path.join(resources, "web"))
        with open(os.path.join(resources, "web", "removed.js"), "w") as f:
            f.write("// deleted two commits ago\n")

        self.assertEqual(self.run_helper().returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(resources, "app", "removed.py")))
        self.assertFalse(os.path.exists(os.path.join(resources, "web", "removed.js")))


class ShadowingTests(unittest.TestCase):
    """The overlay only works because desktop.py puts app/ first on sys.path."""

    def test_desktop_prefers_the_overlay_and_falls_back_to_its_own_dir(self):
        desktop = read("desktop.py")
        self.assertIn('_FRESH = os.path.join(BASE, "app")', desktop)
        self.assertIn('_OUR_PATH = [_FRESH, BASE] if os.path.isdir(_FRESH) else [BASE]', desktop)
        self.assertIn("sys.path[:0] = _OUR_PATH", desktop)

    def test_selftest_reports_where_the_code_was_imported_from(self):
        desktop = read("desktop.py")
        self.assertIn('print("code    %s" % os.path.dirname(os.path.abspath(serve_web.__file__)))', desktop)
        smoke = read(".github/workflows/build.yml").split("- name: Smoke test the bundle", 1)[1]
        smoke = smoke.split("- name:", 1)[0]
        self.assertIn("Resources/app", smoke,
                      "CI must prove the reused bundle runs this build's code")


class BuildWiringTests(unittest.TestCase):
    """The fallback is only real if the script can be told the bundle is there
    and rebuilds when it is not."""

    def test_the_build_reuses_only_a_restored_bundle_and_falls_back(self):
        build = read("build-macos.sh")
        self.assertIn("KOTASSIUM_REUSE_BUNDLE", build)
        self.assertIn("tools/update-macos-bundle.py", build)
        self.assertIn("rebuilding the bundle from scratch", build)
        self.assertEqual(build.count("rm -rf build dist"), 2,
                         "one clean before py2app, one when the overlay is refused")
        self.assertIn('KOTASSIUM_VERSION="$VERSION" desktop-venv/bin/python setup-macos.py py2app', build)

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

    def test_the_publish_scripts_are_executable(self):
        for name in ("next-version.sh", "publish-release.sh", "await-preflight.sh",
                     "update-macos-bundle.py"):
            path = os.path.join(ROOT, "tools", name)
            self.assertTrue(os.stat(path).st_mode & 0o111, name)


if __name__ == "__main__":
    unittest.main()
