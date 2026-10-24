"""Tests for the Newgrounds Audio Portal lane: card parsing, result ranking,
listen-page resolution, the guard solver, and the API/job wiring around them.

Nothing here touches the network: pages come from fixtures cut from real
Newgrounds responses, and the fetch tests use a local stand-in server.
"""
import base64
import hashlib
import http.client
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serve_web

try:
    from argon2 import Type, low_level
    HAS_ARGON2 = True
except Exception:
    HAS_ARGON2 = False

# Two result cards exactly as the Audio Portal search emits them: the remake
# first (it quotes "Dimrain47" in its title, which is what the portal's
# whole-term matching rewards), the original second.
SEARCH_HTML = """<html><body>
<ul class="itemlist spaced">
<li>
<div class="audio-wrapper" id="audio-wrapperAAA">
<div class="flexbox">
<a href="https://www.newgrounds.com/audio/listen/1099411" class="item-audiosubmission " title="Dimrain47 - The Prototype (Recreation)">
<div class="item-icon"><div><img
src="https://aicon.ngfiles.com/1099/1099411_medium.png?f1640528409"
width="60" height="60" alt="Dimrain47 - The Prototype (Recreation)" /></div></div>
<div class="item-details"><div class="item-details-main"><div>
<div class="detail-title"><h4>Dimrain47 - The Prototype (Recreation)</h4>
<span>by
<strong>X-ManOfficial</strong>
</span></div>
<div class="detail-description">A remake.</div>
</div></div>
<div class="item-details-meta"><dl><dd><strong class="color-audio">Song</strong></dd></dl></div>
</div>
</a>
<div class="absolute "><a class="play-control-medium" title="PLAY"
data-audio-playback="1099411" data-audio-type="3" data-audio-duration="158"
style="display:none">PLAY</a></div>
</div>
</div>
</li>
<li>
<div class="audio-wrapper" id="audio-wrapperBBB">
<div class="flexbox">
<a href="https://www.newgrounds.com/audio/listen/33326" class="item-audiosubmission " title="The Prototype">
<div class="item-icon"><div><img
src="https://aicon.ngfiles.com/3300/33326_medium.png?f1128048309"
width="60" height="60" alt="The Prototype" /></div></div>
<div class="item-details"><div class="item-details-main"><div>
<div class="detail-title"><h4>The Prototype</h4>
<span>by
<strong>Dimrain47</strong>
</span></div>
</div></div>
<div class="item-details-meta"><dl><dd><strong class="color-audio">Song</strong></dd></dl></div>
</div>
</a>
<div class="absolute "><a class="play-control-medium" title="PLAY"
data-audio-playback="33326" data-audio-type="3" data-audio-duration="161"
style="display:none">PLAY</a></div>
</div>
</div>
</li>
</ul>
</body></html>"""

# The part of a listen page that matters: the player payload with its
# backslash-escaped CDN url (slashes are escaped inside the JS string).
LISTEN_HTML = (
    '<!doctype html><html><head><title>The Prototype</title></head><body>'
    "<script>var audio = [{'id': 33326, 'type_id': 3, "
    "'url': \"https:\\/\\/audio.ngfiles.com\\/33000\\/33326_newgrounds_the_pr.mp3?f1128048309\", "
    "'version': 1128048309, 'duration': 161, 'loop': false, "
    "'title': \"The Prototype\", 'author': \"Dimrain47\"}];"
    "</script></body></html>"
)


class NgParseTests(unittest.TestCase):
    def test_cards_fields(self):
        cards = serve_web._ng_cards(SEARCH_HTML)
        self.assertEqual([c["id"] for c in cards], ["1099411", "33326"])
        remake, orig = cards
        self.assertEqual(remake["title"], "Dimrain47 - The Prototype (Recreation)")
        self.assertEqual(remake["artist"], "X-ManOfficial")
        self.assertEqual(remake["dur"], 158)
        self.assertIn("aicon.ngfiles.com", remake["cover"])
        self.assertEqual(orig["title"], "The Prototype")
        self.assertEqual(orig["artist"], "Dimrain47")
        self.assertEqual(orig["dur"], 161)

    def test_ignores_non_result_listen_links(self):
        page = ('<a href="https://www.newgrounds.com/audio/listen/999">more audio</a>'
                + SEARCH_HTML)
        cards = serve_web._ng_cards(page)
        self.assertEqual([c["id"] for c in cards], ["1099411", "33326"])

    def _ranked(self, **kw):
        orig = serve_web._ng_search_page
        serve_web._ng_search_page = lambda terms: SEARCH_HTML
        try:
            return serve_web.ng_search(**kw)
        finally:
            serve_web._ng_search_page = orig

    def test_search_ranks_original_first_with_hints(self):
        # artist+title as one query only matches the remake; the bare-title
        # second query is what surfaces the original at all.
        j = self._ranked(q="Dimrain47 The Prototype",
                         t="The Prototype", a="Dimrain47")
        ids = [r["id"] for r in j["results"]]
        self.assertEqual(ids[0], "ng-33326")
        self.assertIn("ng-1099411", ids)
        top = j["results"][0]
        self.assertEqual(top["source"], "newgrounds")
        self.assertEqual(top["title"], "The Prototype")
        self.assertEqual(top["artist"], "Dimrain47")
        self.assertEqual(top["dur"], 161)
        self.assertTrue(top["full"])

    def test_search_without_hints_still_finds_original(self):
        # plain search-box query: no t/a, so ranking falls back to token
        # coverage with the remix markers breaking the tie.
        j = self._ranked(q="Dimrain47 The Prototype")
        ids = [r["id"] for r in j["results"]]
        self.assertEqual(ids[0], "ng-33326")
        self.assertIn("ng-1099411", ids)

    def test_empty_query_returns_nothing(self):
        self.assertEqual(self._ranked(q="", t="", a=""), {"results": []})

    def test_resolve_listen_page(self):
        orig = serve_web._ng_fetch
        serve_web._ng_fetch = lambda url, **kw: (200, LISTEN_HTML.encode("utf-8"))
        try:
            info = serve_web.ng_resolve("33326")
        finally:
            serve_web._ng_fetch = orig
        self.assertEqual(info["id"], "33326")
        self.assertEqual(info["url"],
                         "https://audio.ngfiles.com/33000/33326_newgrounds_the_pr.mp3?f1128048309")
        self.assertEqual(info["title"], "The Prototype")
        self.assertEqual(info["artist"], "Dimrain47")
        self.assertEqual(info["dur"], 161)

    def test_resolve_rejects_garbage(self):
        with self.assertRaises(RuntimeError):
            serve_web.ng_resolve("not-a-number")


class NgPowTests(unittest.TestCase):
    @staticmethod
    def _b64(b):
        return base64.urlsafe_b64encode(b).decode().rstrip("=")

    @staticmethod
    def _unb64(s):
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    def test_sha256_challenge(self):
        payload = self._b64(b"unit-test")
        out = serve_web._ng_pow({"algo": "sha256", "bits": 8,
                                 "payload": payload, "sig": "s"})
        d = hashlib.sha256(self._unb64(payload) + b":" + out["nonce"].encode()).digest()
        self.assertGreaterEqual(serve_web._ng_zero_bits(d), 8)
        self.assertNotIn("params", out)

    def test_unsupported_algo_raises(self):
        with self.assertRaises(RuntimeError):
            serve_web._ng_pow({"algo": "scrypt", "bits": 8,
                               "payload": self._b64(b"x"), "sig": "s"})

    @unittest.skipUnless(HAS_ARGON2, "argon2-cffi not installed")
    def test_argon2id_challenge(self):
        params = {"iterations": 1, "memorySize": 8, "parallelism": 1, "hashLength": 4}
        payload = self._b64(b"unit")
        out = serve_web._ng_pow({"algo": "argon2id", "bits": 8,
                                 "payload": payload, "sig": "s", "params": params})
        d = low_level.hash_secret_raw(
            secret=self._unb64(payload) + b":" + out["nonce"].encode(),
            salt=b"\x00" * 8, time_cost=1, memory_cost=8, parallelism=1,
            hash_len=4, type=Type.ID, version=0x13)
        self.assertGreaterEqual(serve_web._ng_zero_bits(d), 8)
        self.assertEqual(out["params"], params)


class NgGuardFetchTests(unittest.TestCase):
    def test_fetch_solves_guard_and_retries(self):
        # Deterministic stand-in for the network: first page hit 403s with the
        # guard, a sha256 challenge keeps this argon2-free, and the retry
        # after /verify succeeds.
        payload = base64.urlsafe_b64encode(b"unit").decode().rstrip("=")
        challenge = json.dumps({"algo": "sha256", "bits": 8, "payload": payload,
                                "sig": "sig"}).encode()
        page_hits = []
        verifies = []
        challenge_calls = []
        def fake_call(url, data=None, **kw):
            if url.endswith("/_guard/api/v1/challenge"):
                challenge_calls.append(data)   # must be a GET: POST 400s
                return 200, challenge
            if url.endswith("/_guard/api/v1/verify"):
                verifies.append(data)
                return 200, b'{"ok":true}'
            page_hits.append(url)
            if len(page_hits) == 1:
                return 403, b"NG Guard challenge page"
            return 200, b"<html>verified</html>"
        saved = serve_web._ng_call
        serve_web._ng_call = fake_call
        try:
            code, body = serve_web._ng_fetch("https://www.newgrounds.com/audio/listen/1",
                                             referer="https://www.newgrounds.com/audio/")
        finally:
            serve_web._ng_call = saved
        self.assertEqual((code, body), (200, b"<html>verified</html>"))
        self.assertEqual(len(page_hits), 2)   # challenged once, retried once
        self.assertEqual(challenge_calls, [None])
        self.assertEqual(len(verifies), 1)
        self.assertEqual(verifies[0]["algo"], "sha256")
        self.assertEqual(verifies[0]["payload"], payload)
        self.assertEqual(verifies[0]["sig"], "sig")
        d = hashlib.sha256(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            + b":" + verifies[0]["nonce"].encode()).digest()
        self.assertGreaterEqual(serve_web._ng_zero_bits(d), 8)


class NgApiTests(unittest.TestCase):
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
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
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

    def wait_job(self, jid, timeout=5.0):
        import time
        end = time.time() + timeout
        while time.time() < end:
            _, j = self.json("/api/job?id=" + jid)
            if j.get("status") in ("done", "error"):
                return j
            time.sleep(0.02)
        self.fail("job %s did not finish" % jid)

    def test_search_lane_is_exclusive(self):
        # src=newgrounds must run the Newgrounds lane and nothing else.
        ran = []
        def boom(q):
            ran.append(q)
            raise AssertionError("another lane should not run")
        saved = (serve_web.yt_search, serve_web.dz_search, serve_web.ng_search)
        serve_web.yt_search = serve_web.dz_search = boom
        serve_web.ng_search = lambda q, t="", a="": {"results": [
            {"source": "newgrounds", "id": "ng-33326", "title": t or q,
             "artist": a, "dur": 161, "cover": "", "full": True}]}
        try:
            code, j = self.json(
                "/api/search?src=newgrounds&q=Dimrain47%20The%20Prototype"
                "&t=The%20Prototype&a=Dimrain47")
        finally:
            serve_web.yt_search, serve_web.dz_search, serve_web.ng_search = saved
        self.assertEqual(code, 200)
        self.assertEqual(ran, [])
        self.assertEqual(j.get("errors"), {})
        self.assertEqual(j["results"][0]["id"], "ng-33326")
        self.assertEqual(j["results"][0]["title"], "The Prototype")
        self.assertEqual(j["results"][0]["artist"], "Dimrain47")

    def test_all_lanes_include_newgrounds(self):
        saved = (serve_web.yt_search, serve_web.dz_search, serve_web.sc_search,
                 serve_web.ia_search, serve_web.ng_search)
        empty = lambda q: {"results": []}
        serve_web.yt_search = serve_web.dz_search = serve_web.sc_search = empty
        serve_web.ia_search = empty
        serve_web.ng_search = lambda q, t="", a="": {"results": [
            {"source": "newgrounds", "id": "ng-1", "title": "T", "artist": "A",
             "dur": 1, "cover": "", "full": True}]}
        try:
            code, j = self.json("/api/search?q=whatever")
        finally:
            (serve_web.yt_search, serve_web.dz_search, serve_web.sc_search,
             serve_web.ia_search, serve_web.ng_search) = saved
        self.assertEqual(code, 200)
        self.assertEqual([r["source"] for r in j["results"]], ["newgrounds"])

    def test_play_redirects_to_cdn(self):
        seen = []
        saved = serve_web.ng_resolve
        serve_web.ng_resolve = lambda mid: (
            seen.append(mid) or
            {"id": mid, "url": "https://audio.ngfiles.com/33000/x.mp3?f1"})
        try:
            code, hdr, _ = self.fetch("/api/play?src=newgrounds&id=ng-33326")
        finally:
            serve_web.ng_resolve = saved
        self.assertEqual(code, 302)
        self.assertEqual(hdr.get("Location"), "https://audio.ngfiles.com/33000/x.mp3?f1")
        self.assertEqual(seen, ["33326"])   # prefix stripped for the page

    def test_play_failure_explains_itself(self):
        saved = serve_web.ng_resolve
        def boom(mid):
            raise RuntimeError("newgrounds needs argon2-cffi")
        serve_web.ng_resolve = boom
        try:
            code, _, data = self.fetch("/api/play?src=newgrounds&id=ng-33326")
        finally:
            serve_web.ng_resolve = saved
        self.assertEqual(code, 502)
        self.assertIn(b"argon2-cffi", data)

    def test_ytdl_job_passes_ng_id_through(self):
        seen = []
        saved = serve_web.ytdl
        def fake(vid, progress=None):
            seen.append(vid)
            return vid + ".mp3"
        serve_web.ytdl = fake
        try:
            _, j = self.json("/api/ytdl?id=ng-33326")
            self.assertIn("job", j)
            done = self.wait_job(j["job"])
        finally:
            serve_web.ytdl = saved
        self.assertEqual(seen, ["ng-33326"])
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["file"], "ng-33326.mp3")


class NgFetchTests(unittest.TestCase):
    """ng_fetch end to end against a local stand-in for the CDN."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kot_ng_")
        self.saved = (serve_web.LIB, serve_web.ng_resolve, serve_web.FFMPEG)
        serve_web.LIB = self.tmp
        serve_web.FFMPEG = ""   # no preview clip for fake audio

    def tearDown(self):
        serve_web.LIB, serve_web.ng_resolve, serve_web.FFMPEG = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_streams_into_library(self):
        payload = b"ID3" + os.urandom(8192)

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self_):
                self_.send_response(200)
                self_.send_header("Content-Type", "audio/mpeg")
                self_.send_header("Content-Length", str(len(payload)))
                self_.end_headers()
                self_.wfile.write(payload)

            def log_message(self_, *args):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        serve_web.ng_resolve = lambda mid: {
            "id": mid, "url": "http://127.0.0.1:%d/t.mp3" % srv.server_address[1]}
        seen = []
        try:
            name = serve_web.ng_fetch("ng-33326", lambda p: seen.append(p))
            with open(os.path.join(self.tmp, name), "rb") as f:
                data = f.read()
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(name, "ng-33326.mp3")
        self.assertEqual(data, payload)
        self.assertTrue(seen, "progress was never reported")
        self.assertEqual(seen[-1], 100.0)

    def test_falls_back_to_official_download_route(self):
        payload = b"ID3" + b"\x00" * 64
        def bad_resolve(mid):
            raise RuntimeError("no mp3 url in newgrounds page")
        serve_web.ng_resolve = bad_resolve
        saved_fetch = serve_web._ng_fetch
        seen_urls = []
        def fake_fetch(url, **kw):
            seen_urls.append(url)
            return 200, payload
        serve_web._ng_fetch = fake_fetch
        try:
            name = serve_web.ng_fetch("ng-33326")
            with open(os.path.join(self.tmp, name), "rb") as f:
                data = f.read()
        finally:
            serve_web._ng_fetch = saved_fetch
        self.assertEqual(name, "ng-33326.mp3")
        self.assertEqual(data, payload)
        self.assertIn("https://www.newgrounds.com/audio/download/33326", seen_urls)

    def test_reports_the_real_error_when_everything_fails(self):
        def bad_resolve(mid):
            raise RuntimeError("no mp3 url in newgrounds page")
        serve_web.ng_resolve = bad_resolve
        saved_fetch = serve_web._ng_fetch
        serve_web._ng_fetch = lambda url, **kw: (403, b"blocked")
        try:
            with self.assertRaisesRegex(RuntimeError, "no mp3 url"):
                serve_web.ng_fetch("ng-33326")
        finally:
            serve_web._ng_fetch = saved_fetch
        # the partial download must not linger in the library
        self.assertEqual(os.listdir(self.tmp), [])


if __name__ == "__main__":
    unittest.main()
