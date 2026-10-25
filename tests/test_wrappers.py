import os
import re
import shutil
import subprocess
import threading
import unittest
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class WrapperTests(unittest.TestCase):
    """The web page is the only UI. The shells must stay shells, or a bug
    fixed in web/index.html would not be fixed everywhere."""

    WRAPPERS = (
        "desktop.py",
        "android/app/src/main/java/app/kotassium/mobile/MainActivity.java",
        "android/app/src/main/java/app/kotassium/mobile/ServeService.java",
        "titlebar_macos.py",
    )

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

    def test_react_app_is_the_only_ui_and_preserves_shared_state_behaviors(self):
        page = read("web/index.html")
        app = read("web/app.jsx")
        bundle = read("web/app.js")
        self.assertIn('<div id="root"></div>', page)
        self.assertIn('<script src="/app.js" defer></script>', page)
        self.assertNotIn("<script>\nvar AU", page)
        self.assertIn("function App()", app)
        self.assertIn("const prefetchTrackRef = useRef(null)", app)
        self.assertIn("const nextTrack = nextIndex >= 0 && nextIndex !== currentIndex ? queue[nextIndex] : null", app)
        self.assertIn("useEffect(() => { if (nextTrack) prefetchTrack(nextTrack); }, [nextTrack, prefetchTrack])", app)
        self.assertIn("audio.addEventListener('loadedmetadata', onMeta)", app)
        self.assertIn("Math.abs(actual - expected) > Math.max(8, expected * 0.2)", app)
        self.assertIn("/api/nowplaying", app)
        self.assertIn("/api/cover/cache", app)
        self.assertIn("/api/update/check", app)
        self.assertIn("/api/recommend", app)
        self.assertIn("function bootstrap()", app)
        self.assertIn("React", bundle)
        self.assertTrue(bundle.endswith("\n"))

    def test_pre_react_recovery_is_injected_by_server_shell(self):
        server = read("serve_web.py")
        self.assertIn('id="recovery"', server)
        self.assertIn("setTimeout(function(){if(!ready)show()},5000)", server)
        self.assertIn("window.__kotReactReady", server)
        self.assertIn("window.__kotRollbackAvailable", server)
        self.assertIn("/api/update/rollback", server)
        self.assertIn("previous app version if available", server)
        self.assertIn("updater.rollback_available()", server)
        app = read("web/app.jsx")
        self.assertIn("restore the previous app version", app)
        self.assertIn("previous app version if available", app)
        self.assertIn("window.__kotShowRecovery?.()", app)
        self.assertIn("panel.classList.add('visible')", app)
        self.assertIn("window.__kotRollbackAvailable &&", app)
        self.assertIn("class AppBoundary extends React.Component", app)
        self.assertIn("window.__kotReactReady?.()", app)
        self.assertIn("useEffect(() => { window.__kotReactReady?.(); }, [])", app)

    def test_update_step_formatter_is_hoisted_before_render_and_effects(self):
        app = read("web/app.jsx")
        self.assertLess(app.index("function updateStepsText("), app.index("function App()"))
        self.assertIn("updateStepsText(st.version, st.latest)", app)
        self.assertNotIn("[updateState, updateSteps]", app)
        self.assertIn("updateStepsText(updateState.version, updateState.latest)", app)

    def test_http_serves_recovery_outside_the_react_mount(self):
        import serve_web
        old_base = serve_web.BASE
        old_available = serve_web.updater.rollback_available
        serve_web.BASE = ROOT
        serve_web.updater.rollback_available = lambda: False
        server = serve_web.make_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen("http://127.0.0.1:%s/" % server.server_address[1]) as response:
                page = response.read().decode("utf-8")
            self.assertIn('<div id="root"></div>', page)
            self.assertIn('id="recovery"', page)
            self.assertIn("Restore previous version</button>", page)
            self.assertIn(" disabled>", page)
            self.assertIn("setTimeout(function(){if(!ready)show()},5000)", page)
            self.assertIn("window.__kotRollbackAvailable=false", page)
        finally:
            server.shutdown()
            server.server_close()
            serve_web.BASE = old_base
            serve_web.updater.rollback_available = old_available

    def test_serve_web_serves_built_react_bundle(self):
        server = read("serve_web.py")
        self.assertEqual(server.count('if path == "/app.js":'), 1)
        self.assertIn('"web", "app.js"', server)
        package = read("package.json")
        self.assertIn('"react"', package)
        self.assertIn('"build"', package)
        result = subprocess.run(["node", "--check", os.path.join(ROOT, "web/app.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_react_callbacks_are_initialized_before_use_and_search_state_exists(self):
        app = read("web/app.jsx")
        self.assertLess(app.index("const warmCover = useCallback"), app.index("const resolveCover = useCallback"))
        self.assertIn("const [searching, setSearching] = useState(false)", app)

    def test_legacy_web_ui_regressions_are_covered_by_react_state_and_handlers(self):
        app = read("web/app.jsx")
        self.assertIn("localStorage.setItem('kot_side_collapsed'", app)
        self.assertIn("const startSidebarResize = useCallback", app)
        self.assertIn("setPointerCapture(event.pointerId)", app)
        self.assertIn("saveSidebarCollapsed(width < 165)", app)
        self.assertIn("setSideResizePreview(width < 165)", app)
        self.assertIn("sideResizePreview !== null ? sideResizePreview : collapsed", app)
        self.assertIn("setSideResizePreview(null)", app)
        self.assertIn('id="sideResize" role="separator"', app)
        self.assertIn("#mid.resizing #side{transition:none}", read("web/index.html"))
        self.assertIn("#sideResize{display:none}", read("web/index.html"))
        self.assertIn("// Touch + pointer gestures work on Android WebView and desktop browsers", app)
        self.assertIn("window.matchMedia('(max-width:820px)').matches", app)
        self.assertIn("const toggleRadio", app)
        self.assertNotIn('aria-label="Radio"', app)
        self.assertNotIn("collapsedPlayer", app)
        self.assertNotIn("togglePlayerBar", app)
        self.assertNotIn('aria-label="Collapse player"', app)
        self.assertIn("const fetchRadio", app)
        self.assertIn("function QueueRow(", app)
        self.assertIn("Math.abs(actual - expected) > Math.max(8, expected * 0.2)", app)
        self.assertIn("const updateSteps", app)
        self.assertIn("localStorage.getItem('kot_vol')", app)
        self.assertIn("localStorage.getItem('kot_shuf')", app)
        self.assertIn("localStorage.getItem('kot_repeat')", app)

    def test_http_serves_root_and_bundle_from_shared_server_handler(self):
        import serve_web
        old_base = serve_web.BASE
        serve_web.BASE = ROOT
        server = serve_web.make_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = "http://127.0.0.1:%s" % server.server_address[1]
            with urllib.request.urlopen(base + "/") as response:
                page = response.read().decode("utf-8")
                self.assertEqual(response.headers.get_content_type(), "text/html")
            self.assertIn('<script src="/app.js" defer></script>', page)
            with urllib.request.urlopen(base + "/app.js") as response:
                bundle = response.read()
                self.assertEqual(response.headers.get_content_type(), "application/javascript")
                self.assertEqual(response.headers.get("Cache-Control"), "no-cache")
            self.assertEqual(bundle, read("web/app.js").encode())
        finally:
            server.shutdown()
            server.server_close()
            serve_web.BASE = old_base

    def test_macos_release_builds_pkgs_with_running_app_confirmation(self):
        builder = read("make-pkg.sh")
        script = read("macos-pkg-scripts/preinstall")
        self.assertIn("pkgbuild", builder)
        self.assertIn("--scripts macos-pkg-scripts", builder)
        self.assertIn('display dialog "Kotassium is currently running. Quit it now so the update can finish installing?"', script)
        self.assertIn('buttons {"Cancel", "Quit Kotassium"}', script)
        self.assertIn("TARGET=\"/Applications/Kotassium.app\"", script)
        self.assertIn('/usr/bin/ditto "$TARGET" "$STAGED"', script)
        self.assertIn("exit 1", script)
        self.assertIn("/usr/bin/ditto", script)
        self.assertIn('if [ -d "$TARGET" ]; then', script)
        self.assertIn('/bin/mv "$STAGED" "$PREVIOUS"', script)
        updater = read("updater.py")
        self.assertIn('if not name.endswith(".pkg")', updater)
        self.assertIn('["/usr/bin/open", "-a", "Installer", package]', updater)
        self.assertNotIn('if not name.endswith(".dmg")', updater)
        build = read(".github/workflows/build.yml")
        self.assertIn("./make-pkg.sh", build)
        self.assertIn("Kotassium-*.pkg", build)
        self.assertIn("./make-dmg.sh", build)
        self.assertIn("Kotassium-*.dmg", build)
        self.assertIn("legacy-dmg", build)
        auto_release = read(".github/workflows/auto-release.yml")
        tag_release = read(".github/workflows/release.yml")
        for workflow in (auto_release, tag_release):
            self.assertIn("publish-macos-legacy-dmg:", workflow)
            self.assertIn("arm64.dmg", workflow)
        self.assertIn(".pkg", read(".github/release-body.md"))

    def test_platform_builds_ship_the_compiled_page_bundle(self):
        mac_setup = read("setup-macos.py")
        self.assertIn('"web/app.js"', mac_setup)
        self.assertIn("npm ci", read("build-macos.sh"))
        gradle = read("android/app/build.gradle")
        self.assertIn('include "**/*"', gradle)
        self.assertIn('exclude "app.jsx"', gradle)
        self.assertIn('"npm", "run", "build"', gradle)
        build = read(".github/workflows/build.yml")
        self.assertIn("npm ci", build)
        self.assertIn("npm run build", read("build-macos.sh"))
        self.assertIn('include "**/*"', gradle)

    def test_page_really_escapes_what_it_injects(self):
        app = read("web/app.jsx")
        self.assertIn("const escStyle = (url)", app)
        self.assertIn("<b>{track.t}</b>", app)

    def test_platform_icons_use_shared_kotassium_logo(self):
        mac_setup = read("setup-macos.py")
        self.assertIn('"iconfile": ICON', mac_setup)
        self.assertIn('"CFBundleIconFile": "kotassium.icns"', mac_setup)
        icon_builder = read("tools/make-macos-icon.py")
        self.assertIn('web", "icons", "icon-512.png', icon_builder)
        self.assertIn('"iconutil", "-c", "icns"', icon_builder)
        build = read("build-macos.sh")
        self.assertIn("tools/normalize-icons.py", build)
        self.assertIn("tools/make-macos-icon.py", build)
        normalizer = read("tools/normalize-icons.py")
        self.assertIn("Image.Resampling.LANCZOS", normalizer)
        self.assertIn("0.82", normalizer)
        self.assertIn("size / 2 - cx", normalizer)
        for icon in ("web/icons/icon-512.png", "web/icons/icon-192.png",
                     "web/icons/apple-touch-icon.png", "web/icons/icon-maskable-512.png",
                     "android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, icon)), icon)

    def test_android_runs_the_real_server(self):
        normalizer = read("tools/normalize-icons.py")
        self.assertIn('android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png', normalizer)
        gradle = read("android/app/build.gradle")
        for name in ("serve_web.py", "spotify_get.py", "updater.py"):
            self.assertIn(name, gradle, "android build must stage %s" % name)
        self.assertIn("new File(repoRoot, \"web\")", gradle)
        boot = read("android/app/src/main/python/kotassium_boot.py")
        self.assertIn("serve_web.serve_local", boot)
        self.assertIn("inproc", boot)

    def test_page_is_the_source_of_truth(self):
        self.assertIn("<title>Kotassium</title>", read("web/index.html"))
        self.assertIn("serviceWorker", read("web/app.jsx"))

    def test_macos_bundle_uses_pywebview_py2app_compatible_configuration(self):
        requirements = read("requirements-macos-build.txt")
        self.assertIn("pywebview>=5.4", requirements)
        setup = read("setup-macos.py")
        self.assertNotIn('"zipfile": False', setup)
        self.assertIn('"packages": ["webview"]', setup)
        bootstrap = read("setup.sh")
        self.assertIn("pywebview>=5.4", bootstrap)

    def test_release_builds_publish_each_platform_as_soon_as_it_finishes(self):
        auto = read(".github/workflows/auto-release.yml")
        manual = read(".github/workflows/release.yml")
        build = read(".github/workflows/build.yml")
        preflight = read(".github/workflows/preflight.yml")
        publisher = read(".github/workflows/publish-artifact.yml")
        for workflow in (auto, manual):
            self.assertIn("uses: ./.github/workflows/preflight.yml", workflow)
            self.assertIn("needs: version", workflow)
            self.assertIn("needs: [version, preflight, macos]", workflow)
            self.assertIn("needs: [version, preflight, android]", workflow)
            self.assertNotIn("needs: [version, build]", workflow)
            self.assertIn("uses: ./.github/workflows/publish-artifact.yml", workflow)
            self.assertIn("cancel-builds-on-preflight-failure", workflow)
            self.assertIn('needs.preflight.result == \'failure\'', workflow)
            self.assertIn('GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}', workflow)
            self.assertIn('gh run cancel "$GITHUB_RUN_ID"', workflow)
        self.assertIn("inputs.platform == 'macos'", build)
        self.assertIn("inputs.platform == 'android'", build)
        self.assertNotIn("npm ci", preflight)
        self.assertIn("needs: [version, preflight, macos]", auto)
        self.assertIn("needs: [version, preflight, android]", auto)
        self.assertIn("actions: write", auto)
        self.assertIn("actions: write", manual)
        self.assertIn("concurrency:", publisher)
        self.assertIn("gh release upload", publisher)
        self.assertIn("sha256sum", publisher)

    def test_update_button_keeps_manual_recheck_separate_from_install(self):
        app = read("web/app.jsx")
        self.assertIn("Check again", app)
        self.assertIn("Restart & Update", app)
        self.assertIn("match(/\\d+/g)", app)
        self.assertIn("version${count === 1 ? '' : 's'} forward", app)
        self.assertIn("updateState.can_install === false", app)
        self.assertIn("updateCheckManual.current = true", app)
        self.assertIn("st.available) { updateCheckManual.current = false; setUpdateMessage(`Kotassium ${st.latest || 'A Kotassium update'} is available (${updateStepsText(st.version, st.latest)})", app)
        self.assertIn("else if (st.available) setUpdateMessage(`Kotassium ${st.latest || 'A Kotassium update'} is available (${updateStepsText(st.version, st.latest)})", app)

    def test_desktop_queue_scrollbar_is_subtle(self):
        page = read("web/index.html")
        self.assertIn("#dfsQueue #dfsQrows{scrollbar-width:thin;scrollbar-color:#ffffff18 transparent}", page)
        self.assertIn("#dfsQueue #dfsQrows::-webkit-scrollbar{width:6px}", page)
        self.assertIn("#dfsQueue #dfsQrows::-webkit-scrollbar-track{background:transparent}", page)
        self.assertIn("#dfsQueue #dfsQrows::-webkit-scrollbar-thumb{background:#ffffff18;border-radius:6px}", page)

    def test_library_and_main_scrollbars_stay_hidden_on_webkit(self):
        # Safari/WKWebView ignore width:0 on ::-webkit-scrollbar and do not
        # implement scrollbar-width before 18.2, so without display:none the
        # dark lists kept a bright white native bar down their right edge.
        page = read("web/index.html")
        self.assertIn("#main,#sideList{scrollbar-width:none}", page)
        self.assertIn("#main::-webkit-scrollbar,#sideList::-webkit-scrollbar{width:0}", page)
        self.assertIn("#main::-webkit-scrollbar,#sideList::-webkit-scrollbar{display:none}", page)

    def test_up_next_toast_places_white_heading_above_track_details(self):
        app = read("web/app.jsx")
        page = read("web/index.html")
        self.assertIn("grid-template-columns:36px minmax(0,1fr)", page)
        self.assertIn("grid-template-rows:auto auto", page)
        self.assertIn("#upnext .upnext-label{grid-column:1/-1", page)
        self.assertIn("<span className=\"upnext-label\">Up next</span>", app)
        self.assertNotIn("text-transform:uppercase", re.sub(r"\.link-eyebrow\{[^}]*\}", "", page))
        self.assertIn(".dfsQsect{font-size:11px;color:#8a8a8a", page)
        self.assertIn(".settings-label{margin:0 0 8px 2px;font-size:11px;font-weight:700;color:#8f8f8f}", page)
        self.assertIn("#upnext .upnext-art{grid-column:1;grid-row:2", page)
        self.assertIn("#upnext .upnext-copy{grid-column:2;grid-row:2", page)

    def test_custom_tooltips_and_lucide_update_and_settings_controls(self):
        app = read("web/app.jsx")
        page = read("web/index.html")
        package = read("package.json")
        self.assertIn('from \'lucide-react\'', app)
        self.assertIn("<Settings2", app)
        self.assertIn("<RefreshCw", app)
        self.assertIn("<Download", app)
        self.assertIn("Repeat1", app)
        self.assertIn("Repeat size={fullscreen ? 24 : 18}", app)
        self.assertIn("Repeat ${repeat === 0 ? 'off' : repeat === 1 ? 'all' : 'one'}", app)
        self.assertNotIn("toast(`repeat ${", app)
        self.assertNotIn("<button onClick={addLink} disabled={busy}>Add</button>", app)
        self.assertIn("function TooltipLayer()", app)
        self.assertIn("data-tooltip", app)
        self.assertIn("useLayoutEffect(() => {", app)
        self.assertIn("12 + halfWidth", app)
        self.assertIn("window.innerWidth - 12 - halfWidth", app)
        self.assertIn("<div className={`app-tooltip", app)
        self.assertIn(".app-tooltip", page)
        self.assertNotIn("title=", app)
        self.assertIn('"lucide-react"', package)

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

    def test_android_survives_the_screen_turning_off(self):
        # The server runs inside the app process, so without a foreground
        # service Android freezes it the moment the screen turns off: the
        # music stops and downloads stall mid-transfer. The notification is
        # the price Android charges for a process that outlives the screen.
        manifest = read("android/app/src/main/AndroidManifest.xml")
        self.assertIn("android.permission.FOREGROUND_SERVICE", manifest)
        self.assertIn("android:foregroundServiceType=", manifest)
        src = read(self.WRAPPERS[1])
        self.assertIn("startForegroundService", src)
        self.assertIn("stopService", src)
        service = read(self.WRAPPERS[2])
        self.assertIn("startForeground(", service)
        self.assertIn("PARTIAL_WAKE_LOCK", service)
        # The wake lock is held only while a download runs, not forever.
        boot = read("android/app/src/main/python/kotassium_boot.py")
        self.assertIn("JOB_HOOK", boot)

    def test_remote_mode_does_not_keep_the_phone_awake(self):
        # Remote mode serves from another machine: a persistent "serving"
        # notification here would be a lie and a battery cost.
        src = read(self.WRAPPERS[1])
        connecting = src.split("private void askForServer()")[1].split("private void load(")[0]
        self.assertIn("stopServing()", connecting,
                      "connecting to a shared server must stop the local service")
        local = src.split("private void startLocal()")[1].split("private void unpackWebAssets(")[0]
        self.assertNotIn("stopServing", local)
        self.assertIn("startServing", local)

    def test_android_holds_no_copy_of_the_server_or_page(self):
        for dirpath, _, files in os.walk(os.path.join(ROOT, "android")):
            for name in ("serve_web.py", "index.html", "spotify_get.py", "updater.py"):
                self.assertNotIn(name, files, "%s must not be duplicated under android/" % name)


if __name__ == "__main__":
    unittest.main()
