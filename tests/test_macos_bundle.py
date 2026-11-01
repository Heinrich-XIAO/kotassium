"""The macOS build may reuse the bundle py2app built last time.

py2app packages the interpreter, pyobjc and pywebview, which do not depend on
our sources, so CI caches its output and replaces the files the checkout owns
instead of rebuilding it every push. That makes correctness depend on one
promise: the helper replaces *everything* the commit owns - and proves each
copy byte for byte - or refuses so the build falls back to py2app. These tests
hold that promise: a bundle it cannot read is a refusal, never a partial
update, and a bundle it can read really does end up with this checkout's
modules, page and version in it.

The set of modules comes from ``setup-macos.py``, and py2app scatters them: the
app script lands at ``Contents/Resources/``, the includes under
``lib/python3.x/``, and older versions keep them in a zip. All of those shapes
are covered here, because the shape that was *not* covered is the one that made
the first fast-path run rebuild in 26s instead.
"""

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

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


def make_checkout(path, app="desktop.py", includes=("serve_web", "updater")):
    with open(os.path.join(path, "setup-macos.py"), "w") as f:
        f.write(SETUP)
    modules = [app] + ["%s.py" % name for name in includes]
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


def plist(app, keys=("CFBundleShortVersionString", "CFBundleVersion")):
    path = os.path.join(app, "Contents", "Info.plist")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            plistlib.dump({"CFBundleIdentifier": "app.kotassium.desktop"}, f,
                          fmt=plistlib.FMT_BINARY)
    with open(path, "rb") as f:
        return plistlib.load(f)


def set_plist(app):
    with open(os.path.join(app, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump({"CFBundleIdentifier": "app.kotassium.desktop",
                       "CFBundleShortVersionString": "0.0.1",
                       "CFBundleVersion": "0.0.1"}, f, fmt=plistlib.FMT_BINARY)


def make_split_bundle(app, modules):
    """py2app 0.28's real shape: script at Resources/, includes in lib/python3.12/."""
    resources = os.path.join(app, "Contents", "Resources")
    libdir = os.path.join(resources, "lib", "python3.12")
    os.makedirs(libdir)
    with open(os.path.join(resources, "desktop.py"), "w") as f:
        f.write("# stale copy from an older commit\n")
    for name in modules[1:]:
        with open(os.path.join(libdir, name), "w") as f:
            f.write("# stale copy from an older commit\n")
    with open(os.path.join(libdir, "webview.py"), "w") as f:
        f.write("# a dependency, not ours\n")
    set_plist(app)
    return resources, libdir


def make_zipped_bundle(app, modules):
    """The other shape py2app produces: the app's modules in site-packages.zip."""
    resources = os.path.join(app, "Contents", "Resources")
    libdir = os.path.join(resources, "lib", "python3.12")
    os.makedirs(libdir)
    archive = os.path.join(libdir, "site-packages.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name in modules:
            z.writestr(name, "# stale copy from an older commit\n")
        z.writestr("desktop.pyc", "stale bytecode")
        z.writestr("webview/__init__.py", "# a dependency, not ours\n")
    set_plist(app)
    return archive


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

    def test_a_bundle_without_our_modules_is_refused(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, REFUSE, result.stderr)
        self.assertIn("no Contents/Resources", result.stderr)

    def test_a_bundle_missing_a_module_is_refused(self):
        # A module the manifest lists but the cache predates: replacing the
        # rest would ship an app whose imports fail, so nothing is replaced.
        resources, libdir = make_split_bundle(self.app, self.modules)
        os.remove(os.path.join(libdir, "serve_web.py"))
        result = self.run_helper()
        self.assertEqual(result.returncode, REFUSE, result.stderr)
        self.assertIn("the bundle has no serve_web.py", result.stderr)
        with open(os.path.join(resources, "desktop.py")) as f:
            self.assertEqual(f.read(), "# stale copy from an older commit\n",
                             "a refused bundle must not be half-updated")

    def test_the_split_layout_py2app_actually_writes_is_updated(self):
        resources, libdir = make_split_bundle(self.app, self.modules)
        result = self.run_helper("--version", "9.9.9")
        self.assertEqual(result.returncode, 0, result.stderr)

        with open(os.path.join(resources, "desktop.py")) as f:
            self.assertEqual(f.read(), "# desktop.py from this commit\n")
        for name in self.modules[1:]:
            with open(os.path.join(libdir, name)) as f:
                self.assertEqual(f.read(), "# %s from this commit\n" % name)
        with open(os.path.join(libdir, "webview.py")) as f:
            self.assertEqual(f.read(), "# a dependency, not ours\n")
        self.assertFalse(os.path.exists(os.path.join(libdir, "mpris_linux.py")),
                         "a module setup-macos.py excludes must not be added")
        self.assertTrue(os.path.isfile(os.path.join(resources, "web", "index.html")))
        self.assertTrue(os.path.isfile(os.path.join(resources, "assets", "kotassium.svg")))
        self.assertEqual(plist(self.app)["CFBundleShortVersionString"], "9.9.9")
        self.assertEqual(plist(self.app)["CFBundleVersion"], "9.9.9")

    def test_a_zipped_bundle_is_updated_in_place(self):
        archive = make_zipped_bundle(self.app, self.modules)
        result = self.run_helper("--version", "9.9.9")
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(archive) as z:
            for name in self.modules:
                self.assertEqual(z.read(name), ("# %s from this commit\n" % name).encode())
            self.assertNotIn("desktop.pyc", z.namelist(),
                             "stale bytecode would win over the new source")
            self.assertEqual(z.read("webview/__init__.py"), b"# a dependency, not ours\n")

    def test_the_page_is_replaced_rather_than_merged(self):
        # A file deleted from web/ must not survive in the reused bundle; the
        # page is one directory and the commit is the truth about it.
        resources, _ = make_split_bundle(self.app, self.modules)
        os.makedirs(os.path.join(resources, "web"))
        gone = os.path.join(resources, "web", "removed.js")
        with open(gone, "w") as f:
            f.write("// deleted two commits ago\n")
        self.assertEqual(self.run_helper().returncode, 0)
        self.assertFalse(os.path.exists(gone))


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
