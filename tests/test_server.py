import http.client
import json
import os
import sys
import threading
import unittest

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


if __name__ == "__main__":
    unittest.main()
