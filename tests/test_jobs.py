import http.client
import json
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serve_web


class JobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = serve_web.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

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
        return r.status, json.loads(data or b"{}")

    def wait_job(self, jid, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            _, j = self.req("GET", "/api/job?id=" + jid)
            if j.get("status") in ("done", "error"):
                return j
            time.sleep(0.02)
        self.fail("job %s did not finish" % jid)

    def test_download_job_reports_progress(self):
        seen = []
        orig = serve_web.ytdl

        def fake(vid, progress=None):
            for pct in (0.0, 42.5, 100.0):
                seen.append(pct)
                if progress:
                    progress(pct)
                time.sleep(0.02)
            return vid + ".mp3"

        serve_web.ytdl = fake
        try:
            _, j = self.req("GET", "/api/ytdl?id=abc123")
            self.assertIn("job", j)
            done = self.wait_job(j["job"])
        finally:
            serve_web.ytdl = orig
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["file"], "abc123.mp3")
        self.assertEqual(done["pct"], 100.0)
        self.assertEqual(seen, [0.0, 42.5, 100.0])

    def test_download_job_surfaces_errors(self):
        orig = serve_web.ytdl

        def boom(vid, progress=None):
            raise RuntimeError("nope")

        serve_web.ytdl = boom
        try:
            _, j = self.req("GET", "/api/ytdl?id=zzz")
            done = self.wait_job(j["job"])
        finally:
            serve_web.ytdl = orig
        self.assertEqual(done["status"], "error")
        self.assertIn("nope", done["error"])

    def test_duplicate_downloads_share_a_job(self):
        release = threading.Event()
        orig = serve_web.ytdl

        def slow(vid, progress=None):
            release.wait(3)
            return vid + ".mp3"

        serve_web.ytdl = slow
        try:
            _, a = self.req("GET", "/api/ytdl?id=same")
            _, b = self.req("GET", "/api/ytdl?id=same")
            self.assertEqual(a["job"], b["job"])
            release.set()
            self.wait_job(a["job"])
        finally:
            serve_web.ytdl = orig
            release.set()

    def test_unknown_job(self):
        _, j = self.req("GET", "/api/job?id=999999")
        self.assertEqual(j.get("error"), "not_found")

    def test_nowplaying_roundtrip(self):
        payload = {"t": "Song", "a": "Artist", "ms": 1000, "pos": 250,
                   "state": "playing", "cover": "/cover/x"}
        code, _ = self.req(
            "POST", "/api/nowplaying", body=json.dumps(payload).encode(),
            headers={"Origin": "http://127.0.0.1:%d" % self.port,
                     "Content-Type": "application/json"})
        self.assertEqual(code, 200)
        _, now = self.req("GET", "/api/nowplaying")
        self.assertEqual(now["t"], "Song")
        self.assertEqual(now["a"], "Artist")
        self.assertEqual(now["state"], "playing")
        self.assertEqual(now["pos"], 250)


if __name__ == "__main__":
    unittest.main()
