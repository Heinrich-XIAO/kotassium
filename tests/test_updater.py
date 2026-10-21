import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updater.parse_version("v2.1.0"), (2, 1, 0))
        self.assertEqual(updater.parse_version("2.0.0-beta1"), (2, 0, 0))
        self.assertEqual(updater.parse_version(""), (0,))

    def test_newer(self):
        self.assertTrue(updater.newer("v2.1.0", "2.0.0"))
        self.assertTrue(updater.newer("2.0.10", "2.0.9"))
        self.assertFalse(updater.newer("2.0.0", "2.0.0"))
        self.assertFalse(updater.newer("v1.9.9", "2.0.0"))
        self.assertTrue(updater.newer("2.0", "1.9.9"))


RELEASE = {
    "tag_name": "v2.1.0",
    "html_url": "https://github.com/Heinrich-XIAO/kotassium/releases/tag/v2.1.0",
    "body": "notes",
    "assets": [
        {"name": "Kotassium-2.1.0-arm64.dmg", "size": 10,
         "browser_download_url": "https://example.invalid/a.dmg"},
        {"name": "Kotassium-2.1.0-x86_64.dmg", "size": 10,
         "browser_download_url": "https://example.invalid/b.dmg"},
        {"name": "SHA256SUMS", "size": 10,
         "browser_download_url": "https://example.invalid/sums"},
    ],
}


class AssetTests(unittest.TestCase):
    def test_picks_matching_arch(self):
        dmg, sums = updater.asset_for(RELEASE, "arm64")
        self.assertEqual(dmg["name"], "Kotassium-2.1.0-arm64.dmg")
        self.assertEqual(sums["name"], "SHA256SUMS")
        dmg, _ = updater.asset_for(RELEASE, "x86_64")
        self.assertEqual(dmg["name"], "Kotassium-2.1.0-x86_64.dmg")

    def test_missing_arch(self):
        rel = {"assets": [{"name": "Kotassium-2.1.0-arm64.dmg"}]}
        self.assertIsNone(updater.asset_for(rel, "x86_64")[0])

    def test_status_shape(self):
        st = updater.status()
        for k in ("supported", "version", "available", "state", "pct"):
            self.assertIn(k, st)
        self.assertFalse(st["supported"])  # not a frozen macOS bundle in tests

    def test_check_offline_reports_error(self):
        real = updater.latest_release
        updater.latest_release = lambda: (_ for _ in ()).throw(OSError("no network"))
        try:
            st = updater.check()
        finally:
            updater.latest_release = real
        self.assertIn("update check failed", st["error"])
        self.assertFalse(st["available"])

    def test_check_marks_available(self):
        real_rel, real_ver = updater.latest_release, updater.current_version
        updater.latest_release = lambda: json.loads(json.dumps(RELEASE))
        updater.current_version = lambda: "2.0.0"
        try:
            st = updater.check()
        finally:
            updater.latest_release, updater.current_version = real_rel, real_ver
        self.assertTrue(st["available"])
        self.assertEqual(st["latest"], "2.1.0")

    def test_install_refused_when_unsupported(self):
        st = updater.start_install()
        self.assertEqual(st["state"], "idle")

    def test_parse_checksums(self):
        text = ("abc123  Kotassium-2.1.0-arm64.dmg\n"
                "def456  *Kotassium-2.1.0-x86_64.dmg\n")
        self.assertEqual(updater.parse_checksums(text, "Kotassium-2.1.0-arm64.dmg"), "abc123")
        self.assertEqual(updater.parse_checksums(text, "Kotassium-2.1.0-x86_64.dmg"), "def456")
        self.assertIsNone(updater.parse_checksums(text, "other.dmg"))


class SwapScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kot-swap-")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self._stub("ditto", '[ -n "$FAIL" ] && exit 1\nrm -rf "$2"; cp -R "$1" "$2"\n')
        self._stub("xattr", "exit 0\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stub(self, name, body):
        p = os.path.join(self.bin, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(p, 0o755)

    def _run(self, fail=False):
        target = os.path.join(self.tmp, "Kotassium.app")
        new = os.path.join(self.tmp, "New.app")
        for d, ver in ((target, "old"), (new, "new")):
            os.makedirs(os.path.join(d, "Contents"))
            with open(os.path.join(d, "Contents", "v"), "w") as f:
                f.write(ver)
        script = os.path.join(self.tmp, "swap.sh")
        with open(script, "w") as f:
            f.write(updater.SWAP_SCRIPT)
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"])
        if fail:
            env["FAIL"] = "1"
        r = subprocess.run(["/bin/sh", script, target, new, "0", "0"],
                           env=env, capture_output=True)
        return r.returncode, target, new

    def test_swaps_and_cleans_up(self):
        code, target, new = self._run()
        self.assertEqual(code, 0)
        with open(os.path.join(target, "Contents", "v")) as f:
            self.assertEqual(f.read(), "new")
        self.assertFalse(os.path.exists(new))
        self.assertFalse(os.path.exists(target + ".old"))

    def test_failure_restores_old_bundle(self):
        code, target, _ = self._run(fail=True)
        self.assertNotEqual(code, 0)
        with open(os.path.join(target, "Contents", "v")) as f:
            self.assertEqual(f.read(), "old")
        self.assertFalse(os.path.exists(target + ".old"))

    def test_script_restores_on_failure(self):
        s = updater.SWAP_SCRIPT
        self.assertIn('mv "$TARGET" "$TARGET.old"', s)
        self.assertIn('mv "$TARGET.old" "$TARGET"', s)   # rollback path
        self.assertIn("xattr -dr com.apple.quarantine", s)
        self.assertIn('kill -0 "$PID"', s)
        # A failed swap reopens the old bundle instead of leaving no app.
        self.assertIn('[ "$RELAUNCH" = "1" ] && open "$TARGET"\nexit 1', s)

    def test_no_wait_when_pid_is_zero(self):
        self.assertIn('if [ "$PID" != "0" ]; then', updater.SWAP_SCRIPT)


class InstallGuardTests(unittest.TestCase):
    def test_refuses_when_not_writable(self):
        real_s, real_c = updater.SUPPORTED, updater.can_install
        updater.SUPPORTED, updater.can_install = True, lambda: False
        try:
            with self.assertRaises(RuntimeError):
                updater.start_install()
        finally:
            updater.SUPPORTED, updater.can_install = real_s, real_c


if __name__ == "__main__":
    unittest.main()
