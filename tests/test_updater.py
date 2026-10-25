import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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
        {"name": "Kotassium-2.1.0-arm64.pkg", "size": 10,
         "browser_download_url": "https://example.invalid/a.pkg"},
        {"name": "Kotassium-2.1.0-x86_64.pkg", "size": 10,
         "browser_download_url": "https://example.invalid/b.pkg"},
        {"name": "SHA256SUMS", "size": 10,
         "browser_download_url": "https://example.invalid/sums"},
    ],
}


class AssetTests(unittest.TestCase):
    def test_picks_matching_arch(self):
        package, sums = updater.asset_for(RELEASE, "arm64")
        self.assertEqual(package["name"], "Kotassium-2.1.0-arm64.pkg")
        self.assertEqual(sums["name"], "SHA256SUMS")
        package, _ = updater.asset_for(RELEASE, "x86_64")
        self.assertEqual(package["name"], "Kotassium-2.1.0-x86_64.pkg")

    def test_missing_arch(self):
        rel = {"assets": [{"name": "Kotassium-2.1.0-arm64.pkg"}]}
        self.assertIsNone(updater.asset_for(rel, "x86_64")[0])

    def test_ignores_legacy_dmgs(self):
        rel = {"assets": [{"name": "Kotassium-2.1.0-arm64.dmg"}]}
        self.assertIsNone(updater.asset_for(rel, "arm64")[0])

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

    def test_system_app_install_is_available_to_non_admin_user(self):
        real_supported, real_app_path = updater.SUPPORTED, updater.app_path
        updater.SUPPORTED = True
        updater.app_path = lambda: "/Applications/Kotassium.app"
        try:
            self.assertTrue(updater.can_install())
        finally:
            updater.SUPPORTED, updater.app_path = real_supported, real_app_path

    def test_previous_bundle_is_available_only_for_a_writable_supported_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = tmp + ".old"
            os.makedirs(previous)
            real_supported, real_install, real_app_path = (
                updater.SUPPORTED, updater.can_install, updater.app_path)
            updater.SUPPORTED = True
            updater.can_install = lambda: True
            updater.app_path = lambda: tmp
            try:
                self.assertFalse(updater.rollback_available())
                updater.can_install = lambda: False
                self.assertFalse(updater.rollback_available())
                updater.can_install = lambda: True
                updater.SUPPORTED = False
                self.assertFalse(updater.rollback_available())
            finally:
                updater.SUPPORTED = real_supported
                updater.can_install = real_install
                updater.app_path = real_app_path
            shutil.rmtree(previous)

    def test_check_async_reports_checking_immediately(self):
        # check_async must return without blocking, flipping state to checking
        # so the page can spin while GitHub is queried in the background.
        real_rel = updater.latest_release
        with updater._lock:
            saved = dict(updater._state)
            updater._state.update(state="idle", available=False, error=None)
        started = threading.Event()
        release = threading.Event()

        def slow():
            started.set()
            release.wait(3)
            return json.loads(json.dumps(RELEASE))

        updater.latest_release = slow
        updater.current_version = lambda: "2.0.0"
        try:
            t0 = time.time()
            st = updater.check_async()
            self.assertLess(time.time() - t0, 1.0)  # did not block on the network
            self.assertEqual(st["state"], "checking")
            self.assertTrue(started.wait(2))
            release.set()
            # let the worker thread finish
            end = time.time() + 3
            while updater.status()["state"] == "checking" and time.time() < end:
                time.sleep(0.02)
        finally:
            release.set()
            updater.latest_release = real_rel
            end = time.time() + 3
            while updater.status()["state"] == "checking" and time.time() < end:
                time.sleep(0.02)
            with updater._lock:
                updater._state.clear()
                updater._state.update(saved)
        self.assertEqual(updater.status()["state"], saved["state"])

    def test_check_async_is_single_flight_and_skips_installs(self):
        real_rel, real_ver = updater.latest_release, updater.current_version
        updater.latest_release = lambda: json.loads(json.dumps(RELEASE))
        updater.current_version = lambda: "2.0.0"
        with updater._lock:
            saved = dict(updater._state)
            updater._state.update(state="idle", available=False, error=None)
        try:
            # a check while a download is running must not clobber the install
            with updater._lock:
                updater._state.update(state="downloading", pct=40, error=None)
            st = updater.check_async()
            self.assertEqual(st["state"], "downloading")
            self.assertEqual(st["pct"], 40)

            # an immediate second click must reuse a running check, not start
            # another thread (one click = one GitHub request). The first check
            # blocks on the gate so the state stays "checking" while we poke it.
            with updater._lock:
                updater._state.update(state="idle", available=False, error=None)
            gate = threading.Event()
            calls = []

            def gated():
                calls.append(1)
                gate.wait(3)
                return json.loads(json.dumps(RELEASE))

            updater.latest_release = gated
            st1 = updater.check_async()
            self.assertEqual(st1["state"], "checking")
            st2 = updater.check_async()
            self.assertEqual(st2["state"], "checking")
            self.assertEqual(len(calls), 1)  # second click did not start a query
            gate.set()
            end = time.time() + 3
            while updater.status()["state"] == "checking" and time.time() < end:
                time.sleep(0.02)
            self.assertEqual(len(calls), 1)  # and the first one only queried once
        finally:
            gate.set()
            updater.latest_release, updater.current_version = real_rel, real_ver
            end = time.time() + 3
            while updater.status()["state"] == "checking" and time.time() < end:
                time.sleep(0.02)
            with updater._lock:
                updater._state.clear()
                updater._state.update(saved)

    def test_parse_checksums(self):
        text = ("abc123  Kotassium-2.1.0-arm64.pkg\n"
                "def456  *Kotassium-2.1.0-x86_64.pkg\n")
        self.assertEqual(updater.parse_checksums(text, "Kotassium-2.1.0-arm64.pkg"), "abc123")
        self.assertEqual(updater.parse_checksums(text, "Kotassium-2.1.0-x86_64.pkg"), "def456")
        self.assertIsNone(updater.parse_checksums(text, "other.pkg"))


class RollbackGuardTests(unittest.TestCase):
    def test_rollback_explains_manual_package_recovery(self):
        real_supported, real_can_install, real_app_path, real_isdir = (
            updater.SUPPORTED, updater.can_install, updater.app_path, updater.os.path.isdir)
        updater.SUPPORTED = True
        updater.can_install = lambda: True
        updater.app_path = lambda: "/Applications/Kotassium.app"
        updater.os.path.isdir = lambda path: path == "/Applications/Kotassium.app.old"
        try:
            self.assertTrue(updater.rollback_available())
            with self.assertRaisesRegex(RuntimeError, "replace /Applications/Kotassium.app"):
                updater.rollback()
        finally:
            updater.SUPPORTED = real_supported
            updater.can_install = real_can_install
            updater.app_path = real_app_path
            updater.os.path.isdir = real_isdir

    def test_system_install_does_not_offer_the_old_bundle_as_recovery(self):
        real_supported, real_can_install, real_app_path, real_isdir = (
            updater.SUPPORTED, updater.can_install, updater.app_path, updater.os.path.isdir)
        updater.SUPPORTED = True
        updater.can_install = lambda: True
        updater.app_path = lambda: "/Applications/Kotassium.app"
        updater.os.path.isdir = lambda path: False
        try:
            self.assertFalse(updater.rollback_available())
        finally:
            updater.SUPPORTED = real_supported
            updater.can_install = real_can_install
            updater.app_path = real_app_path
            updater.os.path.isdir = real_isdir


class InstallerLaunchTests(unittest.TestCase):
    def test_install_opens_verified_pkg_in_macos_installer_without_quitting_app(self):
        real_download, real_popen = updater.download, updater.subprocess.Popen
        launched = []
        updater.download = lambda asset, sums, progress: "/tmp/update.pkg"
        updater.subprocess.Popen = lambda args, **kwargs: launched.append((args, kwargs))
        with updater._lock:
            saved_state = dict(updater._state)
            updater._state.update(state="idle", pct=0, error=None)
        try:
            updater.install(RELEASE["assets"][0], RELEASE["assets"][2])
            self.assertEqual(launched[0][0], ["/usr/bin/open", "-a", "Installer", "/tmp/update.pkg"])
            self.assertTrue(launched[0][1]["start_new_session"])
            self.assertEqual(updater.status()["state"], "ready")
        finally:
            updater.download, updater.subprocess.Popen = real_download, real_popen
            with updater._lock:
                updater._state.clear()
                updater._state.update(saved_state)


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
