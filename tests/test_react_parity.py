import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as source:
        return source.read()


def git_show(path):
    return subprocess.run(["git", "show", path], cwd=ROOT, check=True, capture_output=True, text=True).stdout


class ReactParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = read("web/app.jsx")
        cls.original = git_show("8ae5e3e^:web/index.html")

    def test_previous_and_repeat_one_match_legacy_controls(self):
        self.assertIn("function pv(){if(QI>0)playIdx(QI-1)}", self.original)
        previous = self.app.split("const previous = useCallback", 1)[1].split("  const setVolumePercent", 1)[0]
        self.assertIn("if (currentIndex > 0) playIndex(currentIndex - 1)", previous)
        self.assertNotIn("currentTime", previous)
        self.assertIn("if(REPEAT===2){playIdx(QI);return}", self.original)
        self.assertIn("if (repeat === 2) { playIndex(currentIndex); return; }", self.app)
        self.assertIn("if (repeat === 2) { audio.currentTime = 0; audio.play(); return; }", self.app)

    def test_mute_and_volume_match_legacy_threshold_and_storage(self):
        self.assertIn("function muteVol(){AU.muted=!AU.muted", self.original)
        self.assertIn("const toggleVolume = useCallback", self.app)
        self.assertIn("audioRef.current.volume = volume; audioRef.current.muted = muted", self.app)
        self.assertIn("volume <= 0.01", self.app)
        self.assertIn("volume < 0.5", self.app)
        self.assertIn("localStorage.setItem('kot_vol', String(value))", self.app)
        self.assertIn("id={full ? 'volIcon2' : 'volIcon'}", self.app)

    def test_next_radio_shuffle_and_repeat_match_legacy(self):
        self.assertIn("if(n>=0){if(SHUF)SHUFFLE_POS++;playIdx(n)}", self.original)
        self.assertIn("else if(RADIO){radioNext()}", self.original)
        self.assertIn("const n = chooseNext()", self.app)
        self.assertIn("playIndex(order[0], queue, playingPlaylist, false, order)", self.app)
        self.assertIn("else if (radio) fetchRadio()", self.app)
        self.assertIn("if (repeat === 2) return index", self.app)
        self.assertIn("if (shuf && q.length > 1) return pos < order.length ? order[pos] : -1", self.app)

    def test_radio_recommendations_are_appended_and_played(self):
        body = self.app.split("const fetchRadio = useCallback", 1)[1].split("  const next = useCallback", 1)[0]
        self.assertIn("setQueue(extendedQueue); setCurrentIndex(first)", body)
        self.assertIn("playTrack(fresh[0])", body)
        self.assertIn("/api/recommend", body)

    def test_queue_view_uses_only_unplayed_shuffle_entries(self):
        body = self.app.split("const upcoming = useMemo", 1)[1].split("  const trackRows", 1)[0]
        self.assertIn("if (repeat === 2) return out", body)
        self.assertIn("for (let pos = shufflePos; pos < shuffleOrder.length; pos++) add(shuffleOrder[pos])", body)
        self.assertNotIn("for (let index = 0; index < queue.length; index++) add(index)", body)
        self.assertIn("if (repeat === 1 && currentIndex === queue.length - 1)", body)
        self.assertIn('className="dfsQsect">Now Playing</div>', self.app)
        self.assertIn('className="dfsQsect">Next Up</div>', self.app)

    def test_playlist_and_search_preserve_counts_and_empty_state(self):
        self.assertIn("{playlist.length} song{playlist.length === 1 ? '' : 's'}", self.app)
        self.assertIn("Results for “{view.query}”", self.app)
        self.assertIn("No results from any source.", self.app)
        self.assertIn('track.full === false ? <span className="stream-only">stream only</span>', self.app)

    def test_bottom_player_has_no_collapse_feature(self):
        self.assertNotIn("collapsedPlayer", self.app)
        self.assertNotIn("togglePlayerBar", self.app)
        self.assertNotIn("collbtn", self.app)
        self.assertNotIn("#bar.collapsed", read("web/index.html"))
        self.assertNotIn("#thumbstrip", read("web/index.html"))

    def test_add_link_opens_a_modal_from_both_sidebar_states(self):
        self.assertIn("const addLibraryLink = useCallback(() => {\n    setLinkValue('');\n    setLinkOpen(true);", self.app)
        self.assertNotIn("if (collapsed) { setCollapsed(false)", self.app)
        self.assertIn('className="link-backdrop"', self.app)
        self.assertIn('className="link-dialog" role="dialog" aria-modal="true"', self.app)
        self.assertIn('id="plink" type="url"', self.app)
        self.assertIn('className="link-submit" type="submit"', self.app)
        self.assertIn("onSubmit={(event) => { event.preventDefault(); if (!busy) addLink(); }}", self.app)
        self.assertNotIn('id="addBox"', self.app)
        self.assertNotIn('onKeyDown={(e) => e.key === \'Enter\' && !busy && addLink()}', self.app)
        self.assertIn("if (!linkOpen) return;", self.app)
        self.assertIn("event.key === 'Escape' && !busy", self.app)

    def test_fullscreen_tracks_live_playback_and_reference_ids_exist(self):
        self.assertIn("background: currentTrack ? coverBackground(currentTrack.cover, currentTrack.t)", self.app)
        self.assertIn('<b id="dfsTitle">{currentTrack?.t || \'Choose a playlist to listen\'}</b>', self.app)
        self.assertIn('<span id="dfsTopTitle">{playingPlaylist || \'Now playing\'}</span>', self.app)
        self.assertIn("if (!desktopPlayer && (window.innerWidth <= 820 || !currentTrack)) return", self.app)
        original_body = re.sub(r"<script>.*?</script>|<style>.*?</style>", "", self.original, flags=re.S)
        original_ids = set(re.findall(r'''\bid=["']?([A-Za-z][\w-]*)''', original_body))
        app_ids = set(re.findall(r'''\bid=["']([A-Za-z][\w-]*)["']''', self.app))
        dynamic_ids = set(re.findall(r"\bid=\{[^}]*?['\"]([A-Za-z][\w-]*)['\"]", self.app))
        dynamic_control_ids = {"btns", "shufb", "prevb", "playb", "nextb", "repeatb", "prow", "curt", "prog", "progf", "tott", "volIcon", "vol", "volf", "thumbstrip", "fsBtns", "fsShuf", "fsprev", "fsPlay", "fsPlayIcon", "fsnext", "fsRepeat", "fsSeek", "fsCur", "fsProg", "fsProgf", "fsTot", "fsVol", "volIcon2", "fsVolBar", "fsVolFill"}
        intentional_replacements = {"pbIcon", "fsPlayIcon", "repeatIcon", "fsTitle", "fsArtist", "au", "addBox", "qBrowse", "qDiv"}
        self.assertEqual(set(), original_ids - app_ids - dynamic_ids - dynamic_control_ids - intentional_replacements)

    def test_swiping_up_next_dismisses_until_track_or_notice_changes(self):
        self.assertIn("if (node.id === 'upnext') { upNextGone.current = true; setUpNext(false); }", self.app)
        self.assertIn("upNextGone.current = false", self.app)
        self.assertIn("const displayNextTrack = nextTrack || (radio && currentIndex >= 0 ? queue[currentIndex] : null)", self.app)

    def test_replayed_tracks_reuse_the_cached_source_without_searching(self):
        # Source discovery is the only network cost left when replaying a track
        # that is already in the library, so a remembered id has to short-
        # circuit it - both when playing and when prefetching the next track.
        self.assertIn("else if (cached && !track.source)", self.app)
        self.assertIn("candidates = [{ source: 'youtube', id: cached, dur: 0 }]", self.app)
        self.assertIn("const cachedId = !track.source && cacheRef.current[key]", self.app)
        self.assertIn("knownId ? [track] : cachedId ?", self.app)

    def test_background_download_is_opt_in_and_yields_to_playback(self):
        # The whole-playlist download is a per-add choice: an unchecked box
        # in the add-link dialog, reset every time the dialog reopens, and it
        # only ever fires after a resolve that actually saved.
        self.assertIn('className="link-opt" htmlFor="bgdl"', self.app)
        self.assertIn('type="checkbox" checked={bgDownload}', self.app)
        self.assertIn("setLinkOpen(true);\n    setBgDownload(false);", self.app)
        self.assertIn("if (bgDownload) startBackgroundDownload(j.tracks || [], j.name || '');", self.app)
        # Priority: playback and prefetch mark every search/download they
        # start, and the background lane only starts an item when nothing is
        # in flight - so prefetch (and anything you press play on) wins.
        self.assertIn("while (interactiveRef.current > 0)", self.app)
        self.assertIn("asInteractive(() => findCandidates(track))", self.app)
        self.assertIn("asInteractive(() => downloadId(candidate.id, track.t, false))", self.app)
        self.assertIn("const pending = asInteractive((async () => {", self.app)
        # Pacing: strictly one background item at a time with seconds of air
        # between items, so this lane can never burst the search/download
        # queues into rate-limit territory.
        self.assertIn("4000 + Math.random() * 6000", self.app)
        self.assertIn("bgQueueRef.current.shift()", self.app)
        self.assertNotIn("bgQueueRef.current.map", self.app)
        self.assertIn(".link-opt", read("web/index.html"))

    def test_bottom_volume_icon_is_close_to_a_longer_slider(self):
        css = read("web/index.html")
        self.assertIn("#rside .volume-row{width:auto;gap:4px}", css)
        self.assertIn("#rside .volume-row .aicon{width:24px;height:24px;padding:0}", css)
        self.assertIn("#rside #vol{width:112px;", css)

    def test_bottom_play_button_uses_a_smaller_optically_centered_triangle(self):
        self.assertIn("fullscreen ? 26 : 16", self.app)
        css = read("web/index.html")
        # the glyph is centred in its own viewBox; no CSS nudge may push it off-centre
        self.assertNotIn('#playb svg[viewBox="0 0 16 16"]{transform', css)

    def test_cover_frames_have_even_borders_and_clip_square_artwork(self):
        css = read("web/index.html")
        self.assertIn(".pcover,.ccover,#plx,#nowc,.track-cover,#dfsArt,#fsArt{border:1px solid #ffffff18;overflow:hidden;background-clip:padding-box}", css)

    def test_sidebar_and_main_float_as_islands_on_black(self):
        css = read("web/index.html")
        self.assertIn("#mid{flex:1;display:flex;min-height:0;background:#000;padding:8px;gap:8px}", css)
        self.assertIn("#side{flex:0 0 262px;background:#121212;border-radius:8px;", css)
        self.assertIn("#main{flex:1;background:#121212;border-radius:8px;", css)
        self.assertNotIn("#sideResize:after", css)

    def test_reference_css_is_preserved_in_index_shell(self):
        migrated_shell = git_show("8ae5e3e:web/index.html")
        current = read("web/index.html")
        reference_css = re.search(r"<style>(.*?)</style>", migrated_shell, re.S).group(1)
        current_css = re.search(r"<style>(.*?)</style>", current, re.S).group(1)
        reference_update_start = reference_css.index("#upd{")
        reference_update_end = reference_css.index("#empty{", reference_update_start)
        reference_css = reference_css[:reference_update_start] + reference_css[reference_update_end:]
        update_start = current_css.index("#upd{")
        update_end = current_css.index("#empty{", update_start)
        current_css = current_css[:update_start] + current_css[update_end:]
        reference_css = "\n".join(line for line in reference_css.splitlines() if "#upnext" not in line) + "\n"
        current_css = "\n".join(line for line in current_css.splitlines() if "#upnext" not in line) + "\n"
        collapsed_player_css = ("#bar.collapsed", "#bar .collbtn", "#thumbstrip", ".thumb")
        reference_css = "\n".join(line for line in reference_css.splitlines() if not any(selector in line for selector in collapsed_player_css + ("#side.collapsed #addBox", "#addBox"))) + "\n"
        current_css = "\n".join(line for line in current_css.splitlines() if not any(selector in line for selector in ("#mid.resizing #side", "#sideResize", "#side.collapsed #addBox", "#addBox"))) + "\n"
        settings_start = current_css.index("/* settings */")
        current_css = current_css[:settings_start]
        current_css = current_css.replace("#root{flex:1;min-height:0;display:flex;flex-direction:column}\n", "", 1)
        reference_css = reference_css.replace("#qBrowse{width:32px;height:32px;border-radius:6px;color:#b3b3b3;display:grid;place-items:center;flex:none}\n#qBrowse:hover{color:#fff;background:#ffffff14}\n", "", 1)
        reference_css = reference_css.replace("#qDiv{width:1px;height:24px;background:#ffffff26;flex:none;margin:0 4px 0 6px}\n", "", 1)
        current_css = current_css.replace(':root{--font-ui:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;--font-size-body:14px;--font-size-title:22px;--font-size-section:12px;--font-weight-regular:400;--font-weight-medium:500;--font-weight-semibold:600;--font-weight-bold:700;--font-weight-heavy:800}\nh1,h2,h3{font-family:var(--font-ui);font-weight:var(--font-weight-bold);letter-spacing:-.02em}\nh2{font-size:var(--font-size-title)}\nh3{font-size:16px}\n', "", 1)
        reference_css = reference_css.replace("#qDiv{width:1px;height:24px;background:#ffffff26;flex:none;margin:0 4px 0 6px}\\n", "", 1)
        reference_css = reference_css.replace("#qDiv,#qBrowse{display:none}", "", 1)
        current_css = current_css.replace('body{background:#000;color:#fff;font-family:var(--font-ui);font-size:var(--font-size-body);font-weight:var(--font-weight-regular);', 'body{background:#000;color:#fff;font-family:system-ui,sans-serif;', 1)
        current_css = current_css.replace('#homeView h2{margin:0 0 16px}', '#homeView h2{font-size:22px;margin:0 0 16px}', 1)
        current_css = current_css.replace('#mid{flex:1;display:flex;min-height:0;background:#000;padding:8px;gap:8px}', '#mid{flex:1;display:flex;min-height:0;background:#121212;padding:8px;gap:8px}', 1)
        current_css = current_css.replace("/* Spotify-style islands: black shell, rounded panels, and the gutter between\n   them is the drag affordance instead of a painted handle bar. */\n", "", 1)
        current_css = current_css.replace('.settings-head h2,.link-dialog-copy h2{font-size:var(--font-size-title);font-weight:var(--font-weight-bold);letter-spacing:-.02em}', '.settings-head h2{font-size:28px;font-weight:820;letter-spacing:-.035em}.link-dialog-copy h2{font-size:27px;font-weight:790;letter-spacing:-.045em}', 1)
        current_css = current_css.replace('#empty h3{font-size:16px;font-weight:var(--font-weight-bold)}\n.card b,.pmeta b,#nowt b,.rtxt b{font-weight:var(--font-weight-semibold)}\n', '', 1)
        current_css = current_css.replace('.settings-label{margin:0 0 8px 2px;font-size:var(--font-size-section);font-weight:var(--font-weight-bold);', '.settings-label{margin:0 0 8px 2px;font-size:11px;font-weight:700;', 1)
        current_css = current_css.replace('.dfsQsect{font-size:var(--font-size-section);color:#8a8a8a;font-weight:var(--font-weight-bold);', '.dfsQsect{font-size:11px;color:#8a8a8a;font-weight:700;', 2)
        current_css = current_css.replace('#dfsInfo b,#fsTxt b{font-size:22px;font-weight:var(--font-weight-bold);letter-spacing:-.02em}\n', '', 1)
        current_css = current_css.replace('.plinfo h1{font-size:clamp(40px,6vw,84px);margin:4px 0 8px;line-height:1}', '.plinfo h1{font-size:clamp(40px,6vw,84px);margin:4px 0 8px;line-height:1;letter-spacing:-.04em;font-weight:900}', 1)
        current_css = current_css.replace('#dfsInfo b{display:block;white-space:nowrap;', '#dfsInfo b{display:block;font-size:30px;font-weight:800;white-space:nowrap;', 1)
        current_css = current_css.replace('#fsTxt b{display:block;white-space:nowrap;', '#fsTxt b{display:block;font-size:22px;font-weight:800;white-space:nowrap;', 1)
        for weight, value in (("heavy", "800"), ("bold", "700"), ("semibold", "600"), ("medium", "500"), ("regular", "400")):
            current_css = current_css.replace(f"var(--font-weight-{weight})", value)
        current_css = current_css.replace("#rside .volume-row{width:auto;gap:4px}\n#rside .volume-row .aicon{width:24px;height:24px;padding:0}\n", "", 1)
        current_css = current_css.replace("#rside #vol{width:112px;", "#vol{width:90px;")
        reference_css = reference_css.replace('#btns button[aria-label="Radio"],#btns button[aria-label="Collapse player"]{display:none}', '#btns button[aria-label="Radio"]{display:none}')
        reference_css = reference_css.replace('.dfsQsect{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#8a8a8a;font-weight:700;padding:16px 20px 6px}', '.dfsQsect{font-size:11px;color:#8a8a8a;font-weight:700;padding:16px 20px 6px}')
        reference_css = reference_css.replace('.settings-label{margin:0 0 8px 2px;font-size:11px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;color:#8f8f8f}', '.settings-label{margin:0 0 8px 2px;font-size:11px;font-weight:700;color:#8f8f8f}')
        reference_css = re.sub(r"\n{2,}", "\n", reference_css)
        current_css = re.sub(r"\n{2,}", "\n", current_css)
        self.assertEqual(reference_css, current_css)
        self.assertIn('<div id="root"></div>', current)
        self.assertIn('<script src="/app.js" defer></script>', current)

    def test_reference_gestures_and_submit_interactions_remain(self):
        self.assertIn("node.setPointerCapture(event.pointerId)", self.app)
        self.assertIn("node.style.transform = 'translateX(150%)'", self.app)
        self.assertIn("onTouchStart={(e) => gestureStart(e, 'bar')}", self.app)
        self.assertIn("onTouchStart={(e) => gestureStart(e, 'fs')}", self.app)
        self.assertIn("onTouchStart={(e) => gestureStart(e, 'side')}", self.app)
        self.assertIn("onKeyDown={(e) => e.key === 'Enter' && search()}", self.app)
        self.assertIn("onClick={toggleDesktop}", self.app)


if __name__ == "__main__":
    unittest.main()
