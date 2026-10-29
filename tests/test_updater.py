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


class SilentInstallTests(unittest.TestCase):
    """One click downloads, then the app replaces itself without asking."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._real_cache = updater.cache_dir
        updater.cache_dir = lambda: self.tmp
        self.addCleanup(setattr, updater, "cache_dir", self._real_cache)

    def _patch(self, name, value):
        real = getattr(updater, name)
        setattr(updater, name, value)
        self.addCleanup(setattr, updater, name, real)
        return real

    def _snapshot_state(self):
        with updater._lock:
            saved = dict(updater._state)
            updater._state.update(state="idle", pct=0, error=None)
        self.addCleanup(lambda: (updater._lock.acquire(),
                                 updater._state.clear(),
                                 updater._state.update(saved),
                                 updater._lock.release()))

    def test_swap_script_backs_up_replaces_and_reopens(self):
        script = updater.swap_script("/tmp/stage/Kotassium.new.app",
                                     "/Applications/Kotassium.app")
        self.assertIn("NEW=/tmp/stage/Kotassium.new.app", script)
        self.assertIn("TARGET=/Applications/Kotassium.app", script)
        self.assertIn("/usr/bin/pgrep -x Kotassium", script)      # waits out the quit
        self.assertIn('/usr/bin/ditto "$TARGET" "$STAGED"', script)  # keeps .old
        self.assertIn('/bin/mv "$STAGED" "$PREVIOUS"', script)
        self.assertIn('[ ! -x "$NEW/Contents/MacOS/Kotassium" ]', script)
        self.assertIn('/usr/bin/ditto "$NEW" "$TARGET"', script)
        self.assertIn('/usr/bin/open "$TARGET"', script)          # reopens it
        self.assertIn('report "could not install the update"', script)
        self.assertIn(os.path.join(self.tmp, "install-failed.txt"), script)

    def test_swap_script_quotes_paths_with_spaces(self):
        script = updater.swap_script("/Users/Jane Doe/update/Kotassium.new.app",
                                     "/Applications/Kotassium.app")
        self.assertIn("NEW='/Users/Jane Doe/update/Kotassium.new.app'", script)

    def test_stage_app_unpacks_the_bundle_into_the_cache(self):
        seen = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            if "--expand-full" in cmd:
                app = os.path.join(cmd[3], "Kotassium.app", "Contents", "MacOS")
                os.makedirs(app)
                with open(os.path.join(app, "Kotassium"), "w") as f:
                    f.write("#!/bin/sh\n")
            return subprocess.CompletedProcess(cmd, 0)

        real_run = updater.subprocess.run
        updater.subprocess.run = fake_run
        self.addCleanup(setattr, updater.subprocess, "run", real_run)
        dest = os.path.join(self.tmp, "Kotassium.new.app")
        out = updater.stage_app("/tmp/update.pkg", dest)
        self.assertEqual(out, dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, "Contents", "MacOS",
                                                     "Kotassium")))
        self.assertFalse(os.path.exists(dest + ".work"))   # scratch cleaned up
        self.assertIn("--expand-full", seen[0])

    def test_stage_app_unpacks_the_payload_when_expand_full_is_missing(self):
        def fake_run(cmd, **kwargs):
            if "--expand-full" in cmd:       # old pkgutil without the flag
                raise subprocess.CalledProcessError(64, cmd)
            if "--expand" in cmd:
                os.makedirs(cmd[3], exist_ok=True)   # pkgutil creates it
                with open(os.path.join(cmd[3], "Payload"), "wb") as f:
                    f.write(b"\x1f\x8b\x08\x00")
                return subprocess.CompletedProcess(cmd, 0)
            app = os.path.join(cmd[5], "Kotassium.app", "Contents", "MacOS")
            os.makedirs(app)
            with open(os.path.join(app, "Kotassium"), "w") as f:
                f.write("#!/bin/sh\n")
            return subprocess.CompletedProcess(cmd, 0)

        real_run = updater.subprocess.run
        updater.subprocess.run = fake_run
        self.addCleanup(setattr, updater.subprocess, "run", real_run)
        dest = os.path.join(self.tmp, "staged.app")
        out = updater.stage_app("/tmp/update.pkg", dest)
        self.assertEqual(out, dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, "Contents", "MacOS",
                                                     "Kotassium")))

    def test_stage_app_rejects_a_package_without_the_app(self):
        def fake_run(cmd, **kwargs):
            os.makedirs(os.path.join(cmd[3], "empty")) if "--expand-full" in cmd else None
            return subprocess.CompletedProcess(cmd, 0)

        real_run = updater.subprocess.run
        updater.subprocess.run = fake_run
        self.addCleanup(setattr, updater.subprocess, "run", real_run)
        with self.assertRaises(RuntimeError):
            updater.stage_app("/tmp/update.pkg", os.path.join(self.tmp, "x.app"))

    def test_payload_cmd_reads_the_package_compression(self):
        payload = os.path.join(self.tmp, "Payload")
        with open(payload, "wb") as f:
            f.write(b"\x1f\x8b\x08")
        self.assertIn("gzip -dc", updater._payload_cmd(payload, "/tmp/out")[2])
        with open(payload, "wb") as f:
            f.write(b"070707\x00")
        self.assertIn("cpio -idm", updater._payload_cmd(payload, "/tmp/out")[2])
        with open(payload, "wb") as f:
            f.write(b"pbzx")
        with self.assertRaises(RuntimeError):
            updater._payload_cmd(payload, "/tmp/out")

    def test_install_quits_and_hands_the_swap_to_a_detached_helper(self):
        popen, quits, watched = [], [], []
        staged = os.path.join(self.tmp, "Kotassium.new.app")
        os.makedirs(staged)
        self._patch("download", lambda asset, sums, progress=None: "/tmp/update.pkg")
        self._patch("can_swap", lambda: True)
        self._patch("stage_app", lambda package: staged)
        self._patch("quit_running_app", lambda: quits.append(1))
        self._patch("_watch_helper", lambda: watched.append(1))
        real_popen = updater.subprocess.Popen
        updater.subprocess.Popen = lambda args, **kwargs: popen.append((args, kwargs))
        self.addCleanup(setattr, updater.subprocess, "Popen", real_popen)
        self._snapshot_state()
        updater.install(RELEASE["assets"][0], RELEASE["assets"][2])
        self.assertEqual(updater.status()["state"], "installing")
        self.assertEqual(len(popen), 1)                 # one detached helper
        args, kwargs = popen[0]
        self.assertEqual(args, ["/bin/sh", os.path.join(self.tmp, "swap.sh")])
        self.assertTrue(kwargs["start_new_session"])    # survives our exit
        self.assertNotIn("Installer", json.dumps(args))
        self.assertEqual(quits, [1])                    # the app leaves by itself
        self.assertEqual(watched, [1])                  # failures stay reportable
        with open(os.path.join(self.tmp, "swap.sh")) as f:
            body = f.read()
        self.assertIn("NEW=" + staged, body)
        self.assertIn("/Applications/Kotassium.app", body)

    def test_install_falls_back_to_macos_installer_when_it_cannot_swap(self):
        popen, staged = [], []
        self._patch("download", lambda asset, sums, progress=None: "/tmp/update.pkg")
        self._patch("stage_app", lambda package: staged.append(package))
        real_popen = updater.subprocess.Popen
        updater.subprocess.Popen = lambda args, **kwargs: popen.append((args, kwargs))
        self.addCleanup(setattr, updater.subprocess, "Popen", real_popen)
        self._snapshot_state()
        # a location we cannot replace in place: never unpacked, Installer asked
        self._patch("can_swap", lambda: False)
        updater.install(RELEASE["assets"][0], RELEASE["assets"][2])
        self.assertEqual(staged, [])
        self.assertEqual(popen[0][0],
                         ["/usr/bin/open", "-a", "Installer", "/tmp/update.pkg"])
        self.assertEqual(updater.status()["state"], "ready")
        # an unpackable package falls back the same way
        popen.clear()
        updater.can_swap = lambda: True

        def explode(package):
            raise RuntimeError("unsupported package payload")

        updater.stage_app = explode
        updater.install(RELEASE["assets"][0], RELEASE["assets"][2])
        self.assertEqual(popen[0][0],
                         ["/usr/bin/open", "-a", "Installer", "/tmp/update.pkg"])
        self.assertEqual(updater.status()["state"], "ready")

    def test_helper_report_becomes_an_error_message_while_still_running(self):
        with open(os.path.join(self.tmp, "install-failed.txt"), "w") as f:
            f.write("Kotassium did not quit, so the update was not installed\n")
        self._snapshot_state()
        with updater._lock:
            updater._state.update(state="installing", pct=100)
        updater._watch_helper()
        self.assertEqual(updater.status()["state"], "error")
        self.assertIn("did not quit", updater.status()["error"])

    def test_check_async_reports_a_failed_swap_instead_of_checking(self):
        calls = []
        self._patch("latest_release",
                    lambda: calls.append(1) or json.loads(json.dumps(RELEASE)))
        with open(os.path.join(self.tmp, "install-failed.txt"), "w") as f:
            f.write("Kotassium did not quit, so the update was not installed\n")
        self._snapshot_state()
        st = updater.check_async()
        self.assertEqual(st["state"], "error")
        self.assertIn("Kotassium did not quit", st["error"])
        self.assertFalse(st["available"])
        self.assertEqual(calls, [])   # it reports, it does not ask GitHub
        self.assertFalse(os.path.exists(os.path.join(self.tmp,
                                                      "install-failed.txt")))

    def test_check_keeps_the_release_the_download_button_offers(self):
        # The pill is offering a specific build; the click installs that one
        # from what the check already fetched, so a GitHub hiccup between the
        # two cannot leave the button doing nothing.
        self._snapshot_state()
        real_release = updater._release
        updater._release = None
        self.addCleanup(setattr, updater, "_release", real_release)
        self._patch("latest_release", lambda: json.loads(json.dumps(RELEASE)))
        self._patch("current_version", lambda: "2.0.0")
        st = updater.check()
        self.assertTrue(st["available"])
        self._patch("latest_release", lambda: (_ for _ in ()).throw(OSError("offline")))
        self.assertEqual(updater._release_for_install()["tag_name"], "v2.1.0")
        # nothing usable cached (first click of a session): one fresh request
        updater._release = None
        calls = []
        self._patch("latest_release",
                    lambda: calls.append(1) or json.loads(json.dumps(RELEASE)))
        self.assertEqual(updater._release_for_install()["tag_name"], "v2.1.0")
        self.assertEqual(calls, [1])

    def test_start_install_answers_downloading_without_asking_github_again(self):
        # The page starts polling on this response, so it has to say
        # "downloading" right away and must not spend another request getting
        # there - the anonymous quota is 60/hour and a failure here used to
        # swallow the click silently.
        self._snapshot_state()
        seen = []
        real_release, real_worker = updater._release, updater._worker
        updater._release = json.loads(json.dumps(RELEASE))
        updater._worker = None
        self.addCleanup(setattr, updater, "_release", real_release)
        self.addCleanup(setattr, updater, "_worker", real_worker)
        self._patch("SUPPORTED", True)
        self._patch("can_install", lambda: True)
        self._patch("install", lambda package, sums: seen.append((package, sums)))
        self._patch("latest_release", lambda: (_ for _ in ()).throw(
            AssertionError("the download click must not query GitHub again")))
        st = updater.start_install()
        self.assertEqual(st["state"], "downloading")
        updater._worker.join(3)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0][0]["name"].endswith(".pkg"))
        self.assertEqual(updater.status()["state"], "downloading")

    def test_swap_script_finishes_even_if_the_app_refuses_to_quit(self):
        # It waits for the clean quit first...
        script = updater.swap_script("/tmp/stage/Kotassium.new.app",
                                     "/Applications/Kotassium.app")
        self.assertIn('if [ "$n" -ge 30 ]', script)
        # ...then stops the app itself rather than leaving the update parked
        # on somebody's desk, and only reports failure if it cannot be stopped
        self.assertIn("/bin/kill -TERM", script)
        self.assertIn("/bin/kill -KILL", script)
        self.assertIn('report "Kotassium did not quit, so the update was not installed"',
                      script)

    def test_can_swap_only_where_the_bundle_is_replaceable(self):
        real_app, real_access = updater.app_path, updater.os.access
        try:
            updater.app_path = lambda: None
            self.assertFalse(updater.can_swap())
            updater.app_path = lambda: "/Volumes/Kotassium/Kotassium.app"
            self.assertFalse(updater.can_swap())
            updater.app_path = lambda: (
                "/Users/x/Library/AppTranslocation/abc/Kotassium.app")
            self.assertFalse(updater.can_swap())
            updater.app_path = lambda: "/Applications/Kotassium.app"
            updater.os.access = lambda path, mode: path == "/Applications"
            self.assertTrue(updater.can_swap())
            updater.os.access = lambda path, mode: False
            self.assertFalse(updater.can_swap())
        finally:
            updater.app_path, updater.os.access = real_app, real_access


if __name__ == "__main__":
    unittest.main()
