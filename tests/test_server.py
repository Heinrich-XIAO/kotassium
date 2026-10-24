import base64
import http.client
import shutil
import tempfile
import json
import os
import sys
import threading
import time
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serve_web


class ServerSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = serve_web.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_health(self):
        code, body = self.req("GET", "/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["app"], "kotassium")

    def test_update_status(self):
        code, body = self.req("GET", "/api/update")
        self.assertEqual(code, 200)
        st = json.loads(body)
        self.assertIn("state", st)
        self.assertIn("version", st)
        self.assertFalse(st["supported"])  # only the frozen macOS app updates

    def test_update_post_is_origin_guarded(self):
        code, _ = self.req("POST", "/api/update",
                           headers={"Origin": "https://evil.example"})
        self.assertEqual(code, 403)

    def test_update_check_is_origin_guarded(self):
        code, _ = self.req("POST", "/api/update/check",
                           headers={"Origin": "https://evil.example"})
        self.assertEqual(code, 403)

    def test_update_check_is_post_only(self):
        code, _ = self.req("GET", "/api/update/check")
        self.assertEqual(code, 404)

    def test_update_check_answers_immediately(self):
        real = serve_web.updater.latest_release
        with serve_web.updater._lock:
            saved = dict(serve_web.updater._state)
            serve_web.updater._state.update(state="idle", available=False, error=None)
        release = threading.Event()

        def slow():
            release.wait(3)
            return {"tag_name": "v9.9.9", "assets": []}

        serve_web.updater.latest_release = slow
        try:
            code, body = self.req("POST", "/api/update/check", body=b"{}",
                                  headers={"Origin": "http://127.0.0.1:%d" % self.port,
                                           "Content-Type": "application/json"})
            self.assertEqual(code, 200)
            st = json.loads(body)
            self.assertIn(st["state"], ("checking", "idle"))
            release.set()
            # the background worker settles back to idle on its own
            for _ in range(200):
                st = json.loads(self.req("GET", "/api/update")[1])
                if st["state"] != "checking":
                    break
                time.sleep(0.02)
            self.assertEqual(st["state"], "idle")
        finally:
            release.set()
            end = time.time() + 3
            while serve_web.updater.status()["state"] == "checking" and time.time() < end:
                time.sleep(0.02)
            with serve_web.updater._lock:
                serve_web.updater._state.clear()
                serve_web.updater._state.update(saved)
            serve_web.updater.latest_release = real

    def test_dns_rebinding_host_rejected(self):
        code, _ = self.req("GET", "/api/health", headers={"Host": "evil.example"})
        self.assertEqual(code, 403)

    def test_ip_literal_host_accepted(self):
        code, _ = self.req("GET", "/api/health", headers={"Host": "10.1.2.3:8421"})
        self.assertEqual(code, 200)

    def test_cross_origin_post_rejected(self):
        code, _ = self.req("POST", "/api/links/drop?url=x",
                           headers={"Origin": "https://evil.example"})
        self.assertEqual(code, 403)

    def test_same_origin_post_accepted(self):
        # Bad payload, but it should get past the origin guard (400, not 403).
        code, _ = self.req("POST", "/api/cover/cache", body=b"{}",
                           headers={"Origin": "http://127.0.0.1:%d" % self.port,
                                    "Content-Type": "application/json"})
        self.assertEqual(code, 400)

    def test_drop_is_post_only(self):
        code, _ = self.req("GET", "/api/links/drop?url=x")
        self.assertEqual(code, 404)

    def test_traversal_blocked(self):
        code, _ = self.req("GET", "/lib/..%2F..%2Flinks.json")
        self.assertEqual(code, 404)
        code, _ = self.req("GET", "/cover/..%2F..%2Flinks.json")
        self.assertEqual(code, 404)


class CoverIndexTests(unittest.TestCase):
    """/api/cover/index hands the page the durable url -> filename map.

    The page keeps that map in memory only, so without this endpoint every
    reload re-learned each thumbnail at its own pace and the same song showed
    a local file in one view and the raw remote URL in another.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="kot-covers-")
        cls._saved = (serve_web.COVER_DIR, serve_web.COVERS_JSON)
        serve_web.COVER_DIR = cls.tmp
        serve_web.COVERS_JSON = os.path.join(cls.tmp, "covers.json")
        cls.srv = serve_web.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        (serve_web.COVER_DIR, serve_web.COVERS_JSON) = cls._saved
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def post_cover(self, url, payload=b"\xff\xd8\xff\xe0fakjpeg"):
        body = json.dumps({"url": url, "data": base64.b64encode(payload).decode()}).encode()
        return self.req("POST", "/api/cover/cache", body=body,
                        headers={"Origin": "http://127.0.0.1:%d" % self.port,
                                 "Content-Type": "application/json"})

    def test_index_lists_cached_covers(self):
        code, body = self.post_cover("https://img.example/a.jpg")
        self.assertEqual(code, 200)
        f = json.loads(body)["file"]
        code, body = self.req("GET", "/api/cover/index")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"https://img.example/a.jpg": f})

    def test_index_is_empty_without_a_map(self):
        if os.path.exists(serve_web.COVERS_JSON):
            os.remove(serve_web.COVERS_JSON)
        code, body = self.req("GET", "/api/cover/index")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {})

    def test_index_is_closed_behind_the_password(self):
        saved = (serve_web.PASSWORD, serve_web.AUTH, serve_web.SESSION)
        serve_web.PASSWORD, serve_web.AUTH = "hunter2", True
        serve_web.SESSION = serve_web._session_token()
        serve_web._fails.clear()
        try:
            code, body = self.req("GET", "/api/cover/index")
            self.assertEqual(code, 401)
            self.assertEqual(json.loads(body)["error"], "auth")
        finally:
            (serve_web.PASSWORD, serve_web.AUTH, serve_web.SESSION) = saved
            serve_web._fails.clear()


class ResolverTests(unittest.TestCase):
    def test_ytdlp_resolves(self):
        self.assertTrue(serve_web.YTDLP, "yt-dlp should resolve to a command")

    def test_host_helpers(self):
        self.assertTrue(serve_web.host_allowed("127.0.0.1:8421"))
        self.assertTrue(serve_web.host_allowed("localhost"))
        self.assertTrue(serve_web.host_allowed("[::1]:8421"))
        self.assertFalse(serve_web.host_allowed("attacker.example"))
        self.assertTrue(serve_web.origin_allowed(None, "127.0.0.1:8421"))
        self.assertTrue(serve_web.origin_allowed("http://127.0.0.1:8421", "127.0.0.1:8421"))
        self.assertFalse(serve_web.origin_allowed("https://attacker.example", "127.0.0.1:8421"))


class AuthTests(unittest.TestCase):
    """The password gate that makes a public URL safe."""

    @classmethod
    def setUpClass(cls):
        cls._saved = (serve_web.PASSWORD, serve_web.AUTH, serve_web.SESSION, serve_web.STATE)
        cls.tmp = tempfile.mkdtemp(prefix="kot-auth-")
        serve_web.STATE = cls.tmp
        serve_web.PASSWORD = "hunter2"
        serve_web.AUTH = True
        serve_web.SESSION = serve_web._session_token()
        serve_web._fails.clear()
        cls.srv = serve_web.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        (serve_web.PASSWORD, serve_web.AUTH, serve_web.SESSION, serve_web.STATE) = cls._saved

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        hdrs = dict(r.getheaders())
        c.close()
        return r.status, hdrs, data

    def test_page_redirects_to_login(self):
        code, hdrs, _ = self.req("GET", "/")
        self.assertEqual(code, 303)
        self.assertTrue(hdrs.get("Location", "").startswith("/login"))

    def test_api_is_closed(self):
        code, _, body = self.req("GET", "/api/library")
        self.assertEqual(code, 401)
        self.assertEqual(json.loads(body)["error"], "auth")

    def test_audio_is_closed(self):
        code, _, _ = self.req("GET", "/lib/whatever.mp3")
        self.assertEqual(code, 401)

    def test_health_and_manifest_stay_public(self):
        self.assertEqual(self.req("GET", "/api/health")[0], 200)
        self.assertEqual(self.req("GET", "/manifest.webmanifest")[0], 200)
        self.assertEqual(self.req("GET", "/login")[0], 200)

    def test_login_rejects_wrong_password(self):
        code, _, body = self.req("POST", "/login", body="password=nope",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(code, 401)
        self.assertIn(b"Wrong password", body)

    def test_login_grants_a_session(self):
        origin = "http://127.0.0.1:%d" % self.port
        code, hdrs, _ = self.req("POST", "/login", body="password=hunter2",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Origin": origin})
        self.assertEqual(code, 303)
        cookie = hdrs.get("Set-Cookie", "")
        self.assertIn("kot_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        tok = cookie.split("kot_session=")[1].split(";")[0]
        code, _, body = self.req("GET", "/", headers={"Cookie": "kot_session=" + tok})
        self.assertEqual(code, 200)
        self.assertIn(b"Kotassium", body)
        code, _, _ = self.req("GET", "/api/library", headers={"Cookie": "kot_session=" + tok})
        self.assertEqual(code, 200)

    def test_login_keeps_the_destination(self):
        # The shells open /?desktop=1; losing that flag after login would start
        # the 2s reload poll and reload the app mid-track on every deploy.
        code, hdrs, _ = self.req("GET", "/?desktop=1")
        self.assertEqual(code, 303)
        loc = hdrs.get("Location", "")
        self.assertTrue(loc.startswith("/login?next="))
        self.assertEqual(urllib.parse.unquote(loc.split("next=")[1]), "/?desktop=1")

        code, hdrs, _ = self.req(
            "POST", "/login", body="password=hunter2&next=%2F%3Fdesktop%3D1",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(code, 303)
        self.assertEqual(hdrs.get("Location"), "/?desktop=1")

    def test_login_does_not_redirect_off_site(self):
        code, hdrs, _ = self.req(
            "POST", "/login", body="password=hunter2&next=%2F%2Fevil.example",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(code, 303)
        self.assertEqual(hdrs.get("Location"), "/")

    def test_tunnel_hostname_is_accepted(self):
        # A reverse proxy forwards Host: <public name>; without the allowlist
        # every tunnel would 403 on the first request.
        saved = serve_web.EXTRA_HOSTS
        serve_web.EXTRA_HOSTS = ("music.example.com",)
        try:
            self.assertTrue(serve_web.host_allowed("music.example.com"))
            self.assertTrue(serve_web.host_allowed("music.example.com:443"))
            self.assertFalse(serve_web.host_allowed("evil.example"))
            code, _, _ = self.req("GET", "/api/health", headers={"Host": "music.example.com"})
            self.assertEqual(code, 200)
        finally:
            serve_web.EXTRA_HOSTS = saved

    def test_forged_cookie_is_rejected(self):
        code, _, _ = self.req("GET", "/", headers={"Cookie": "kot_session=deadbeef"})
        self.assertEqual(code, 303)

    def test_logout_clears_the_cookie(self):
        code, hdrs, _ = self.req("POST", "/logout", body="",
                                 headers={"Cookie": "kot_session=" + serve_web.SESSION,
                                          "Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(code, 303)
        self.assertIn("Max-Age=0", hdrs.get("Set-Cookie", ""))


class LibraryFormatTests(unittest.TestCase):
    """Android has no ffmpeg, so the library must accept whatever container
    yt-dlp produced instead of assuming every track is an mp3."""

    @classmethod
    def setUpClass(cls):
        cls._lib = serve_web.LIB
        cls.tmp = tempfile.mkdtemp(prefix="kot-lib-")
        for name, data in (("abc.m4a", b"\0\1\2\3"), ("def.mp3", b"\0\1")):
            with open(os.path.join(cls.tmp, name), "wb") as f:
                f.write(data)
        serve_web.LIB = cls.tmp
        cls.srv = serve_web.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        serve_web.LIB = cls._lib
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path)
        r = c.getresponse()
        data = r.read()
        hdrs = dict(r.getheaders())
        c.close()
        return r.status, hdrs, data

    def test_m4a_and_mp3_are_listed(self):
        code, _, body = self.req("/api/library")
        self.assertEqual(code, 200)
        names = {e["name"] for e in json.loads(body)["library"]}
        self.assertEqual(names, {"abc", "def"})

    def test_m4a_served_as_mp4(self):
        code, hdrs, body = self.req("/lib/abc.m4a")
        self.assertEqual(code, 200)
        self.assertEqual(hdrs["Content-Type"], "audio/mp4")
        self.assertEqual(body, b"\0\1\2\3")

    def test_track_path_finds_any_container(self):
        self.assertTrue(serve_web.track_path("abc").endswith("abc.m4a"))
        self.assertTrue(serve_web.track_path("def").endswith("def.mp3"))
        self.assertIsNone(serve_web.track_path("missing"))

    def test_preview_redirects_when_ffmpeg_is_missing(self):
        # Without ffmpeg the player must still start: the preview URL is a
        # redirect to the real track, not a 404.
        saved = serve_web.FFMPEG
        serve_web.FFMPEG = None
        try:
            code, hdrs, _ = self.req("/lib/abc_preview.mp3")
            self.assertEqual(code, 302)
            self.assertEqual(hdrs["Location"], "/lib/abc.m4a")
        finally:
            serve_web.FFMPEG = saved

    def test_previews_are_not_tracks(self):
        self.assertIsNone(serve_web.track_name("abc_preview.mp3"))
        self.assertIsNone(serve_web.track_name(".yt_abc.m4a"))
        self.assertIsNone(serve_web.track_name("links.json"))
        self.assertEqual(serve_web.track_name("abc.m4a"), "abc")


class BaseDirTests(unittest.TestCase):
    def test_env_override_wins(self):
        saved = os.environ.get("KOTASSIUM_BASE")
        os.environ["KOTASSIUM_BASE"] = "/tmp/kotassium-android"
        try:
            self.assertEqual(serve_web._base_dir(), "/tmp/kotassium-android")
        finally:
            if saved is None:
                os.environ.pop("KOTASSIUM_BASE", None)
            else:
                os.environ["KOTASSIUM_BASE"] = saved


if __name__ == "__main__":
    unittest.main()
