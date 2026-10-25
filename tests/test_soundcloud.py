"""Tests for the SoundCloud lane: client_id scraping, api-v2 result mapping,
transcoding choice, HLS assembly, and the API/job wiring around them.

Nothing here touches the network: payloads are fixtures shaped like real
api-v2 answers, and the fetch tests use a local stand-in server.
"""
import http.client
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error

from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serve_web

# /search/tracks as api-v2 returns it - duration is milliseconds there, while
# every other lane reports seconds.
SEARCH_JSON = {"collection": [
    {"id": 296236692, "title": "Merp Merp",
     "user": {"username": "Schtiffles"}, "duration": 99426,
     "artwork_url": "https://i1.sndcdn.com/artworks-x-large.jpg"},
    {"id": 2035754836, "title": "meep merp",
     "user": {"username": "Doppelgänger"}, "duration": 111641,
     "artwork_url": None},
]}

TRACK_HLS = {"id": 296236692, "title": "Merp Merp", "media": {"transcodings": [
    {"url": "https://api-v2.soundcloud.com/media/hls/a", "preset": "aac_160k",
     "format": {"protocol": "hls", "mime": "audio/mp4"}},
    {"url": "https://api-v2.soundcloud.com/media/hls/b", "preset": "aac_96k",
     "format": {"protocol": "hls", "mime": "audio/mp4"}},
]}}

TRACK_PROGRESSIVE = {"id": 7, "title": "Old Upload",
                     "media": {"transcodings": [
                         {"url": "https://api-v2.soundcloud.com/media/prog",
                          "preset": "mp3_128",
                          "format": {"protocol": "progressive",
                                     "mime": "audio/mpeg"}}]}}


class ScClientIdTests(unittest.TestCase):
    def tearDown(self):
        serve_web._sc["cid"] = ""

    def test_scrapes_the_bundle_and_caches_it(self):
        pages = {
            serve_web._SC_HOME:
                '<script src="https://a-v2.sndcdn.com/assets/11-a.js"></script>'
                '<script src="https://a-v2.sndcdn.com/assets/55-b.js"></script>',
            "https://a-v2.sndcdn.com/assets/11-a.js": "var x=1",
            "https://a-v2.sndcdn.com/assets/55-b.js":
                'n.exports={client_id:"0ebc4b3e9a1f2d3c4b5a697887766554"}',
        }
        seen = []
        def fake(url):
            seen.append(url)
            return pages[url]
        with mock.patch.object(serve_web, "_sc_page", side_effect=fake):
            self.assertEqual(serve_web._sc_client_id(),
                             "0ebc4b3e9a1f2d3c4b5a697887766554")
            # a second call must reuse the cached id, not re-scrape the site
            self.assertEqual(serve_web._sc_client_id(),
                             "0ebc4b3e9a1f2d3c4b5a697887766554")
        self.assertEqual(seen.count(serve_web._SC_HOME), 1)

    def test_missing_id_is_an_error_not_an_empty_answer(self):
        with mock.patch.object(serve_web, "_sc_page",
                               return_value="<html>no bundles here</html>"):
            with self.assertRaisesRegex(RuntimeError, "client_id"):
                serve_web._sc_client_id()

    def test_expired_client_id_is_rescraped_once(self):
        """A 401 means SoundCloud rotated the id: refresh and retry once."""
        urls = []
        def fake_urlopen(req, timeout=None):
            urls.append(req.full_url)
            if "client_id=rotated-away" in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 401, "no", None, None)
            return io.BytesIO(b'{"ok":1}')
        with mock.patch.object(serve_web, "_sc_client_id",
                               side_effect=["rotated-away", "fresh"]), \
             mock.patch.object(serve_web.urllib.request, "urlopen",
                               side_effect=fake_urlopen):
            self.assertEqual(serve_web._sc_json(
                "https://api-v2.soundcloud.com/tracks/1"), {"ok": 1})
        self.assertIn("client_id=rotated-away", urls[0])
        self.assertIn("client_id=fresh", urls[1])


class ScSearchTests(unittest.TestCase):
    def test_maps_results_into_the_lane_shape(self):
        with mock.patch.object(serve_web, "_sc_json", return_value=SEARCH_JSON):
            out = serve_web.sc_search("schtiffles merp merp")
        first = out["results"][0]
        self.assertEqual(first["source"], "soundcloud")
        self.assertEqual(first["id"], "sc-296236692")
        self.assertEqual(first["title"], "Merp Merp")
        self.assertEqual(first["artist"], "Schtiffles")
        self.assertEqual(first["dur"], 99)      # seconds, like every lane
        self.assertTrue(first["full"])
        self.assertEqual(first["cover"],
                         "https://i1.sndcdn.com/artworks-x-large.jpg")
        self.assertEqual(out["results"][1]["cover"], "")

    def test_a_broken_api_surfaces_instead_of_reporting_no_results(self):
        """Silence here is what made the lane look empty when it was failing."""
        with mock.patch.object(serve_web, "_sc_json",
                               side_effect=RuntimeError("soundcloud HTTP 401")):
            with self.assertRaisesRegex(RuntimeError, "401"):
                serve_web.sc_search("merp merp")


class ScMediaTests(unittest.TestCase):
    def test_hls_is_used_when_there_is_no_progressive_stream(self):
        with mock.patch.object(serve_web, "sc_track", return_value=TRACK_HLS), \
             mock.patch.object(serve_web, "_sc_json",
                               return_value={"url": "http://x/pl.m3u8"}):
            url, proto = serve_web.sc_media("sc-296236692")
        self.assertEqual((url, proto), ("http://x/pl.m3u8", "hls"))

    def test_progressive_mp3_wins_when_the_track_offers_one(self):
        with mock.patch.object(serve_web, "sc_track",
                               return_value=TRACK_PROGRESSIVE), \
             mock.patch.object(serve_web, "_sc_json",
                               return_value={"url": "http://x/t.mp3"}):
            url, proto = serve_web.sc_media("sc-7")
        self.assertEqual((url, proto), ("http://x/t.mp3", "progressive"))

    def test_a_track_with_no_stream_is_an_error(self):
        bare = {"id": 1, "media": {"transcodings": []}}
        with mock.patch.object(serve_web, "sc_track", return_value=bare):
            with self.assertRaisesRegex(RuntimeError, "no downloadable stream"):
                serve_web.sc_media("sc-1")


class ScFetchTests(unittest.TestCase):
    """sc_fetch end to end against a local stand-in for the CDN."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kot_sc_")
        self.saved = (serve_web.LIB, serve_web.FFMPEG, serve_web.sc_media)
        serve_web.LIB = self.tmp
        serve_web.FFMPEG = ""      # no ffmpeg, exactly like Android

    def tearDown(self):
        serve_web.LIB, serve_web.FFMPEG, serve_web.sc_media = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def serve(self, files):
        """A local HTTP server for the given path -> bytes map."""
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self_):
                body = files.get(self_.path)
                if body is None:
                    self_.send_response(404)
                    self_.end_headers()
                    return
                self_.send_response(200)
                self_.send_header("Content-Length", str(len(body)))
                self_.end_headers()
                self_.wfile.write(body)

            def log_message(self_, *args):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return "http://127.0.0.1:%d" % srv.server_address[1]

    def test_hls_playlist_is_assembled_into_one_file(self):
        # The playlist points at an init segment and two fragments, both by
        # relative path - which is how SoundCloud writes them.
        base = self.serve({
            "/pl.m3u8": (b"#EXTM3U\n#EXT-X-VERSION:7\n"
                         b'#EXT-X-MAP:URI="init"\n'
                         b"#EXTINF:5.0,\nseg0\n#EXTINF:4.0,\nseg1\n"),
            "/init": b"INITBYTES",
            "/seg0": b"AAAA",
            "/seg1": b"BBBB",
        })
        serve_web.sc_media = lambda tid: (base + "/pl.m3u8", "hls")
        seen = []
        name = serve_web.sc_fetch("sc-296236692", lambda p: seen.append(p))
        with open(os.path.join(self.tmp, name), "rb") as fh:
            data = fh.read()
        self.assertEqual(name, "sc-296236692.m4a")
        self.assertEqual(data, b"INITBYTES" + b"AAAA" + b"BBBB")
        self.assertTrue(seen, "progress was never reported")
        self.assertEqual(seen[-1], 100.0)

    def test_progressive_stream_keeps_its_mp3_extension(self):
        base = self.serve({"/t.mp3": b"ID3" + b"\x00" * 32})
        serve_web.sc_media = lambda tid: (base + "/t.mp3", "progressive")
        name = serve_web.sc_fetch("sc-7")
        self.assertEqual(name, "sc-7.mp3")
        with open(os.path.join(self.tmp, name), "rb") as fh:
            self.assertEqual(fh.read(3), b"ID3")

    def test_a_failed_segment_leaves_no_half_file_behind(self):
        base = self.serve({
            "/pl.m3u8": (b"#EXTM3U\n#EXT-X-MAP:URI=\"INIT\"\n"
                         b"#EXTINF:5.0,\nseg0\n#EXTINF:5.0,\nmissing\n"),
            "/init": b"I",
            "/seg0": b"A",
        })
        serve_web.sc_media = lambda tid: (base + "/pl.m3u8", "hls")
        with self.assertRaises(Exception):
            serve_web.sc_fetch("sc-296236692")
        self.assertEqual(os.listdir(self.tmp), [])

    def test_another_prefix_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "bad soundcloud id"):
            serve_web.sc_fetch("ng-33326")


class ScApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = serve_web.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def fetch(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path)
        r = c.getresponse()
        data = r.read()
        hdr = dict(r.getheaders())
        code = r.status
        c.close()
        return code, hdr, data

    def json(self, path):
        code, _, data = self.fetch(path)
        return code, json.loads(data or b"{}")

    def wait_job(self, jid, timeout=10.0):
        import time
        end = time.time() + timeout
        while time.time() < end:
            _, j = self.json("/api/job?id=" + jid)
            if j.get("status") in ("done", "error"):
                return j
            time.sleep(0.02)
        self.fail("job %s did not finish" % jid)

    def stub_lanes(self, sc):
        """Silence every other lane so only SoundCloud can answer."""
        def boom(q):
            raise AssertionError("another lane should not run")
        saved = (serve_web.yt_search, serve_web.dz_search, serve_web.ia_search,
                 serve_web.ng_search, serve_web.sc_search)
        serve_web.yt_search = serve_web.dz_search = boom
        serve_web.ia_search = boom
        serve_web.ng_search = lambda q, t="", a="": boom(q)
        serve_web.sc_search = sc
        return saved

    def test_search_lane_is_exclusive(self):
        saved = self.stub_lanes(lambda q: {"results": [
            {"source": "soundcloud", "id": "sc-296236692", "title": "Merp Merp",
             "artist": "Schtiffles", "dur": 99, "cover": "", "full": True}]})
        try:
            code, j = self.json("/api/search?src=soundcloud&q=merp%20merp")
        finally:
            (serve_web.yt_search, serve_web.dz_search, serve_web.ia_search,
             serve_web.ng_search, serve_web.sc_search) = saved
        self.assertEqual(code, 200)
        self.assertEqual(j.get("errors"), {})
        self.assertEqual([r["id"] for r in j["results"]], ["sc-296236692"])

    def test_a_broken_lane_is_reported_in_errors(self):
        def broken(q):
            raise RuntimeError("soundcloud HTTP 401")
        saved = self.stub_lanes(broken)
        try:
            code, j = self.json("/api/search?q=whatever")
        finally:
            (serve_web.yt_search, serve_web.dz_search, serve_web.ia_search,
             serve_web.ng_search, serve_web.sc_search) = saved
        self.assertEqual(code, 200)
        self.assertEqual(j["results"], [])
        self.assertIn("soundcloud", j["errors"])
        self.assertIn("401", j["errors"]["soundcloud"])

    def test_ytdl_job_accepts_an_sc_id(self):
        seen = []
        saved = serve_web.sc_fetch
        def fake(vid, progress=None):
            seen.append(vid)
            return vid + ".m4a"
        serve_web.sc_fetch = fake
        try:
            _, j = self.json("/api/ytdl?id=sc-296236692")
            self.assertIn("job", j)
            done = self.wait_job(j["job"])
        finally:
            serve_web.sc_fetch = saved
        self.assertEqual(seen, ["sc-296236692"])
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["file"], "sc-296236692.m4a")

    def test_play_redirects_to_the_library_copy(self):
        seen = []
        saved = serve_web.sc_fetch
        serve_web.sc_fetch = lambda vid, progress=None: seen.append(vid) or "sc-9.m4a"
        try:
            code, hdr, _ = self.fetch("/api/play?src=soundcloud&id=sc-9")
        finally:
            serve_web.sc_fetch = saved
        self.assertEqual(seen, ["sc-9"])
        self.assertEqual(code, 302)
        self.assertEqual(hdr.get("Location"), "/lib/sc-9.m4a")

    def test_play_failure_explains_itself(self):
        saved = serve_web.sc_fetch
        def boom(vid, progress=None):
            raise RuntimeError("soundcloud has no downloadable stream")
        serve_web.sc_fetch = boom
        try:
            code, _, data = self.fetch("/api/play?src=soundcloud&id=sc-9")
        finally:
            serve_web.sc_fetch = saved
        self.assertEqual(code, 502)
        self.assertIn(b"no downloadable stream", data)


if __name__ == "__main__":
    unittest.main()
