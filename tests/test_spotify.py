import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import spotify_get


class TotpKeyTests(unittest.TestCase):
    """The web-player secret is XOR-obfuscated before it becomes the HMAC key.
    Getting this wrong yields a TOTP the server rejects with
    "400 totpVerExpired", which is what made the anonymous lane look dead -
    so pin the derivation here."""

    def test_key_is_decimal_strings_of_xored_codes(self):
        secret = "abc"
        # 'a'=97 ^ 9 = 104, 'b'=98 ^ 10 = 104, 'c'=99 ^ 11 = 104
        self.assertEqual(spotify_get._totp_key(secret), b"104104104")

    def test_key_is_not_the_raw_secret(self):
        secret = "abc"
        self.assertNotEqual(spotify_get._totp_key(secret), secret.encode())

    def test_key_uses_index_mod_33_plus_9(self):
        # index 0 -> 9, index 1 -> 10, index 33 wraps back to 9
        secret = "a" * 34
        codes = [ord("a") ^ (i % 33 + 9) for i in range(34)]
        self.assertEqual(codes[0], ord("a") ^ 9)
        self.assertEqual(codes[33], ord("a") ^ 9)
        self.assertEqual(spotify_get._totp_key(secret),
                         "".join(str(c) for c in codes).encode())

    def test_known_vector_matches_the_live_web_player(self):
        # Ground truth captured from open.spotify.com: the real player sent
        # totp=676798 for this secret/version at 2026-10-22 01:21:21 UTC.
        key = spotify_get._totp_key(',7/*F("rLJ2oxaKL^f+E1xvP@N')
        self.assertEqual(spotify_get._totp(key, 1792632081292), "676798")


class SecretScrapeTests(unittest.TestCase):
    """The bundle lists several {secret, version} pairs, quoted both ways."""

    def test_regex_finds_double_quoted_secret(self):
        js = 'x={secret:"AAA",version:61}'
        m = spotify_get._TOTP_SECRET_RE.search(js)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "AAA")
        self.assertEqual(m.group(3), "61")

    def test_regex_finds_single_quoted_secret(self):
        js = "x={secret:'AAA',version:61}"
        m = spotify_get._TOTP_SECRET_RE.search(js)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), "AAA")

    def test_regex_finds_secret_with_a_double_quote_inside(self):
        js = """x={secret:',7/*F("rLJ2oxaKL^f+E1xvP@N',version:61}"""
        m = spotify_get._TOTP_SECRET_RE.search(js)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), ',7/*F("rLJ2oxaKL^f+E1xvP@N')
        self.assertEqual(m.group(3), "61")

    def test_regex_ignores_other_objects(self):
        js = 'x={secret:"AAA",version:1},y={other:"BBB",version:2}'
        m = spotify_get._TOTP_SECRET_RE.search(js)
        self.assertEqual(m.group(2), "AAA")


class TotpTests(unittest.TestCase):
    def test_totp_is_six_digits(self):
        key = spotify_get._totp_key("secret")
        for ts in (0, 1_700_000_000_000, 1_792_632_081_292):
            code = spotify_get._totp(key, ts)
            self.assertEqual(len(code), 6)
            self.assertTrue(code.isdigit())

    def test_totp_is_stable_within_a_window(self):
        key = spotify_get._totp_key("secret")
        base = 1_700_000_010_000      # aligned to a 30s boundary
        self.assertEqual(spotify_get._totp(key, base), spotify_get._totp(key, base + 29_000))
        self.assertNotEqual(spotify_get._totp(key, base), spotify_get._totp(key, base + 30_000))


class TokenCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(os.path.expanduser("~"), ".cache", "spotify_get_token.json")
        self.orig = self.tmp
        self.backup = self.tmp + ".testbak"
        try:
            os.replace(self.tmp, self.backup)
        except OSError:
            self.backup = None

    def tearDown(self):
        if self.backup:
            try:
                os.replace(self.backup, self.tmp)
            except OSError:
                pass
        for f in (self.tmp, self.backup):
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def test_expired_token_is_not_reused(self):
        spotify_get._cache_save("BQdead", int(__import__("time").time() * 1000) - 1000)
        self.assertIsNone(spotify_get._cache_load())

    def test_fresh_token_is_reused(self):
        spotify_get._cache_save("BQlive", int(__import__("time").time() * 1000) + 600_000)
        self.assertEqual(spotify_get._cache_load(), "BQlive")


if __name__ == "__main__":
    unittest.main()
