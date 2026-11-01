"""Which upload the page plays for a known track.

The candidates below are cut from a real YouTube search for "Toby Fox ASGORE".
The page used to sort them by |duration - expected| and play the closest, so
the official soundtrack upload - the first result YouTube returns - lost to a
concert recording, a "with lyrics" animation or a boss-fight montage that
happened to run nearer the expected length. `rank_videos` weighs title and
channel agreement first and only corroborates with duration, and this file
pins that on the payload that produced the bug report.
"""
import http.client
import json
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serve_web


def vid(vid_id, title, artist, dur):
    return {"source": "youtube", "id": vid_id, "title": title,
            "artist": artist, "dur": dur, "full": True}


# "Toby Fox ASGORE", in the order YouTube returned it.
ASGORE = [
    vid("0fficial", "077. ASGORE (UNDERTALE Soundtrack) - Toby Fox", "Toby Fox", 161),
    vid("bossfight", "Undertale - Asgore Boss Fight", "Fasgort", 469),
    vid("perfected", "Bergentrückung + ASGORE by Toby Fox but I perfected the gap "
                     "between the songs", "Ph0enix", 174),
    vid("onehour", "Asgore Fight Theme - 1 Hour.", "Isaac van Frotatitude", 3748),
    vid("desslyric", "Asgore Runs Over Dess With Lyrics | Deltarune",
        "Bub8les and KennyTheLyr1c1st", 32),
    vid("onehour2", "Undertale Bergentrückung 1Hour", "Chr1s", 3609),
    vid("berg", "Bergentrückung", "Toby Fox", 22),
    vid("intro", "Bergentrückung / Asgore (with Intro Sound Effects)",
        "LonerofGaming Re:Birth", 181),
    vid("reanim", "ASGORE - REANIMATED", "Maxdestrouction Destroyer", 33),
    vid("concert", "Asgore (Undertale Determination Symphony World Tour Los Angeles "
                   "CA Aug 28, 2026)", "AdamSandler", 273),
    vid("orchestra", "Bergentrükung/Asgore - Undertale Orchestra", "Adrian", 214),
    vid("hateless", "Asgore, but toby fox doesn't hate him.", "Composer Dian", 209),
]

# "ASGORE" without the artist in the query: the parody uploads YouTube's own
# order puts near the top, next to the official soundtrack.
ASGORE_PARODIES = [
    vid("official2", "077. ASGORE (UNDERTALE Soundtrack) - Toby Fox", "Toby Fox", 161),
    vid("vs", "ASGORE VS CHAOS KING [UNDERTALE VS DELTARUNE ANIMATION]",
        "Animated Zorox", 275),
    vid("lyrics", "ASGORE WITH LYRICS | Undertale Cover | FT @Wallium",
        "Maelstrom Lyrics and 4 more", 186),
    vid("dess", "Asgore Runs Over Dess (Animated in flipaclip)", "JaydenAnimationz", 32),
]


class RankTests(unittest.TestCase):
    def test_the_official_upload_wins_with_its_real_length(self):
        top = serve_web.rank_videos(ASGORE, "ASGORE", "Toby Fox", 161)[0]
        self.assertEqual(top["id"], "0fficial")

    def test_the_official_upload_wins_even_when_the_length_hint_is_wrong(self):
        # The hint is a tracklist's length, and a tracklist can describe another
        # master. Nearer-duration parodies must not win on that alone.
        for dur in (0, 156, 254, 200):
            top = serve_web.rank_videos(ASGORE, "ASGORE", "Toby Fox", dur)[0]
            self.assertEqual(top["id"], "0fficial", "length hint %s" % dur)

    def test_the_official_upload_wins_with_no_length_hint_at_all(self):
        top = serve_web.rank_videos(ASGORE, "ASGORE", "Toby Fox", 0)[0]
        self.assertEqual(top["id"], "0fficial")

    def test_without_the_artist_hint_the_takes_still_lose(self):
        # A bare title search puts parodies near the top; "- REANIMATED" and
        # "WITH LYRICS" are still takes on the song, not the song.
        top = serve_web.rank_videos(ASGORE, "ASGORE", "", 161)[0]
        self.assertEqual(top["id"], "0fficial")

    def test_parodies_never_outrank_the_original(self):
        ranked = serve_web.rank_videos(ASGORE_PARODIES, "ASGORE", "Toby Fox", 161)
        self.assertEqual(ranked[0]["id"], "official2")
        for i, v in enumerate(ranked):
            if v["id"] in ("vs", "lyrics", "dess"):
                self.assertGreater(i, 0)

    def test_a_parody_with_the_exact_length_loses_to_a_three_second_off_original(self):
        cands = [
            vid("parody", "Megalovania (Parody)", "Somebody Else", 158),
            vid("real", "MEGALOVANIA", "Toby Fox", 155),
        ]
        self.assertEqual(serve_web.rank_videos(cands, "Megalovania", "Toby Fox", 158)[0]["id"], "real")

    def test_the_artists_own_channel_beats_an_untraceable_reupload(self):
        # The deliberate trade: when YouTube hands back a live session from the
        # artist's own channel and a reupload of the studio master from a
        # stranger, "same channel" is the safer read. A cover landing on the
        # exact title and length is the failure that hurt more.
        cands = [
            vid("live", "Radiohead - Weird Fishes / Arpeggi (From the Basement)",
                "Radiohead", 320),
            vid("album", "Radiohead - Weird Fishes / Arpeggi", "noah2413", 318),
        ]
        self.assertEqual(serve_web.rank_videos(cands, "Weird Fishes / Arpeggi",
                                               "Radiohead", 318)[0]["id"], "live")

    def test_length_decides_between_uploads_that_describe_the_track_equally(self):
        # Both are the artist's channel and both name the track, so the length
        # is the only thing left that separates them - YouTube's own order put
        # the 184s upload first, and it is not the album cut.
        cands = [
            vid("long", "Kendrick Lamar - HUMBLE.", "Kendrick Lamar", 184),
            vid("album", "HUMBLE.", "Kendrick Lamar", 177),
        ]
        ranked = serve_web.rank_videos(cands, "HUMBLE.", "Kendrick Lamar", 177)
        self.assertEqual([v["id"] for v in ranked], ["album", "long"])

    def test_length_is_graded_so_a_different_cut_sinks_further(self):
        # A few seconds of slack is cheap, a re-edit is not. The cliff this
        # replaced treated 40% and 41% off the same and 39% as almost right.
        cands = [
            vid("album", "HUMBLE.", "Kendrick Lamar", 177),
            vid("slack", "HUMBLE.", "Kendrick Lamar", 190),
            vid("cut", "HUMBLE.", "Kendrick Lamar", 354),
        ]
        ranked = serve_web.rank_videos(cands[::-1], "HUMBLE.", "Kendrick Lamar", 177)
        self.assertEqual([v["id"] for v in ranked], ["album", "slack", "cut"])

    def test_a_length_that_close_does_not_outvote_a_better_title(self):
        # The opposite error: 2% too long on a stranger's channel is not a
        # reason to leave the artist's own upload behind.
        cands = [
            vid("stranger", "ASGORE", "Fasgort", 159),
            vid("artist", "077. ASGORE (UNDERTALE Soundtrack) - Toby Fox", "Toby Fox", 161),
        ]
        self.assertEqual(serve_web.rank_videos(cands, "ASGORE", "Toby Fox", 156)[0]["id"],
                         "artist")

    def test_the_next_track_on_the_soundtrack_does_not_win(self):
        # "Field of Hopes and Dreams" contains every word of "Hopes and Dreams"
        # and runs closer to the requested length; it is still a different song.
        cands = [
            vid("hopes", "087. Hopes And Dreams (UNDERTALE Soundtrack) - Toby Fox",
                "Toby Fox", 185),
            vid("field", "Field of Hopes and Dreams", "Toby Fox", 212),
            vid("track13", "13. Field of Hopes and Dreams (DELTARUNE Chapter 1 "
                           "Soundtrack) - Toby Fox", "Toby Fox", 166),
        ]
        ranked = serve_web.rank_videos(cands, "Hopes and Dreams", "Toby Fox", 181)
        self.assertEqual(ranked[0]["id"], "hopes")

    def test_an_artist_name_in_front_of_its_own_title_is_not_a_different_song(self):
        cands = [
            vid("rehearsal", "Daft Punk - Get Lucky (Grammys rehearsal)", "Daft Punk", 204),
            vid("want", "Daft Punk - Get Lucky (Official Audio) ft. Pharrell Williams",
                "Daft Punk", 249),
        ]
        self.assertEqual(serve_web.rank_videos(cands, "Get Lucky", "Daft Punk", 204)[0]["id"],
                         "want")

    def test_a_fan_channel_named_after_the_artist_is_not_the_artist(self):
        cands = [
            vid("fan", "HUMBLE - Kendrick Lamar (DAMN)", "Kendrick Lamar Spotlight", 177),
            vid("real", "HUMBLE.", "Kendrick Lamar", 177),
        ]
        self.assertEqual(serve_web.rank_videos(cands, "HUMBLE.", "Kendrick Lamar", 177)[0]["id"],
                         "real")

    def test_the_labels_own_topic_channel_counts_as_the_artist(self):
        cands = [
            vid("fan", "HUMBLE", "Kendrick Lamar Fan Page", 177),
            vid("topic", "HUMBLE", "Kendrick Lamar - Topic", 177),
        ]
        self.assertEqual(serve_web.rank_videos(cands, "HUMBLE.", "Kendrick Lamar", 177)[0]["id"],
                         "topic")

    def test_another_song_by_the_same_artist_does_not_rank_second(self):
        # YouTube fills a channel with its other tracks; playing "That Day"
        # when "ASGORE" was asked for is the same bug in a different shirt.
        cands = ASGORE + [vid("other", "That Day", "Toby Fox", 91)]
        ranked = serve_web.rank_videos(cands, "ASGORE", "Toby Fox", 156)
        ids = [v["id"] for v in ranked]
        self.assertEqual(ids[0], "0fficial")
        # The ladder retries down this list when a download or the length check
        # fails; a different song must not be one of its early attempts.
        self.assertGreater(ids.index("other"), 4)

    def test_an_hour_long_loop_is_not_a_candidate_for_a_three_minute_song(self):
        # YouTube happily returns 1-hour loops of a fight theme; without a
        # length hint they were scoring level with the real track.
        cands = [
            vid("official", "077. ASGORE (UNDERTALE Soundtrack) - Toby Fox", "Toby Fox", 161),
            vid("loop", "Asgore Fight Theme - 1 Hour.", "Isaac van Frotatitude", 3748),
            vid("loop2", "Undertale Bergentrückung 1Hour", "Chr1s", 3609),
        ]
        ranked = serve_web.rank_videos(cands, "ASGORE", "", 0)
        self.assertEqual(ranked[0]["id"], "official")

    def test_results_without_durations_or_hints_do_not_crash(self):
        cands = [{"id": "a", "title": "ASGORE"}, {"id": "b", "title": ""}]
        ranked = serve_web.rank_videos(cands, "ASGORE", "", 0)
        self.assertEqual(ranked[0]["id"], "a")
        self.assertEqual(serve_web.rank_videos([], "x", "y", 10), [])

    def test_youtube_order_is_kept_between_identical_candidates(self):
        cands = [vid("first", "Song", "Artist", 100), vid("second", "Song", "Artist", 100)]
        self.assertEqual([v["id"] for v in serve_web.rank_videos(cands, "Song", "Artist", 100)],
                         ["first", "second"])


class PickApiTests(unittest.TestCase):
    """`pick=1` is how the page asks for the original of a known track."""

    @classmethod
    def setUpClass(cls):
        cls.srv = serve_web.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def search(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, json.loads(data or b"{}")

    def stub(self, fn):
        saved = (serve_web.yt_search, serve_web.dz_search, serve_web.ia_search,
                 serve_web.ng_search, serve_web.sc_search)
        serve_web.yt_search = fn
        serve_web.dz_search = lambda q: {"results": []}
        serve_web.ia_search = lambda q: {"results": []}
        serve_web.ng_search = lambda q, t="", a="": {"results": []}
        serve_web.sc_search = lambda q: {"results": []}
        return saved

    def restore(self, saved):
        (serve_web.yt_search, serve_web.dz_search, serve_web.ia_search,
         serve_web.ng_search, serve_web.sc_search) = saved

    def test_pick_ranks_the_youtube_lane_on_the_hints(self):
        saved = self.stub(lambda q: {"results": ASGORE})
        try:
            code, j = self.search("/api/search?src=youtube&pick=1&q=Toby%20Fox%20ASGORE"
                                  "&t=ASGORE&a=Toby%20Fox&d=156")
        finally:
            self.restore(saved)
        self.assertEqual(code, 200)
        self.assertEqual(j["results"][0]["id"], "0fficial")

    def test_without_pick_the_upstream_order_is_untouched(self):
        # The visible search list shows YouTube's own ranking; the page only
        # asks for a reorder when it is resolving one known track.
        saved = self.stub(lambda q: {"results": ASGORE})
        try:
            code, j = self.search("/api/search?src=youtube&q=Toby%20Fox%20ASGORE")
        finally:
            self.restore(saved)
        self.assertEqual(code, 200)
        self.assertEqual([r["id"] for r in j["results"]], [r["id"] for r in ASGORE])

    def test_pick_without_a_title_hint_leaves_the_order_alone(self):
        saved = self.stub(lambda q: {"results": ASGORE})
        try:
            code, j = self.search("/api/search?src=youtube&pick=1&q=ASGORE&d=161")
        finally:
            self.restore(saved)
        self.assertEqual(code, 200)
        self.assertEqual(j["results"][0]["id"], "0fficial")

    def test_a_bad_length_hint_is_ignored(self):
        saved = self.stub(lambda q: {"results": ASGORE})
        try:
            code, j = self.search("/api/search?src=youtube&pick=1&q=ASGORE&t=ASGORE"
                                  "&a=Toby%20Fox&d=abc")
        finally:
            self.restore(saved)
        self.assertEqual(code, 200)
        self.assertEqual(j["results"][0]["id"], "0fficial")

    def test_the_official_upload_wins_on_the_title_alone(self):
        # No artist and no length hint: album numbering and the game name in
        # brackets are what the official upload looks like, and "Undertale -
        # Asgore Boss Fight" prefixing its own words must not beat it.
        ranked = serve_web.rank_videos(ASGORE, "ASGORE", "", 0)
        self.assertEqual(ranked[0]["id"], "0fficial")


class PageWiringTests(unittest.TestCase):
    def test_the_page_asks_the_server_to_pick_instead_of_sorting_by_length(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "web", "app.jsx")) as fh:
            jsx = fh.read()
        self.assertIn("pick=1", jsx)
        self.assertIn("&t=${encodeURIComponent(track.t || '')}", jsx)
        self.assertNotIn("_delta", jsx, "the duration-only sort must not come back")


if __name__ == "__main__":
    unittest.main()
