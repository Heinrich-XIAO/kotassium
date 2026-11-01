"""Every icon glyph is measured, not nudged.

The page's icons are hand-written path data, and "the icon looks off centre"
has been fixed four times by adding a compensating `transform` - a CSS
`translateX(1px)`, then `translate(0.6 0)`, then `translate(-1.145 0)` on the
play path. Each of those is in user units, so it only ever centred the glyph at
the one render size it was tuned for, and each round was checked with
getBoundingClientRect, which reports the ink BOX and is blind to a triangle's
mass sitting at its base. The glyph that came out of it measured centred and
read left.

So these tests assert the thing that was actually wrong: every glyph lives on
one grid, no glyph is positioned by a transform, and the ink box of each
single-path glyph sits on the centre documented in the code.
"""

import importlib.util
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))

# Glyphs whose entry is one <path>: their ink box is the whole icon, so it can
# be measured here. Multi-element glyphs (search, repeat, volume, ...) mix in
# <circle>/<polygon>/<polyline> from the icon set and would need a shape-aware
# measurer; none of them carries a transform, so they cannot drift the way the
# transport glyphs did.
PURE_PATH_GLYPHS = ("library", "home", "browse", "add", "check", "close", "play", "pause", "prev", "next")

# Two glyphs carry a deliberate optical offset, both from the icon set rather
# than from a nudge of ours. The play triangle reads pulled towards its base, so
# its ink sits 0.75 to the right. The tick is lucide's own `check`, which the
# library draws half a unit above the box centre; a tick's ink weight always
# sits below its box centre, so every tick is a trade between the silhouette and
# the mass, and the library's split is the documented one. Re-centring the box
# (which this file used to assert) moved the mass 0.44px low at 14px in #nowsave,
# where it alternates with a perfectly symmetric plus, and that is what read as
# "still slightly off".
OPTICAL_X = {"play": 12.75}
OPTICAL_Y = {"check": 11.5}


def load_measurer():
    path = os.path.join(ROOT, "tools", "icon_bbox.py")
    spec = importlib.util.spec_from_file_location("icon_bbox", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bbox = load_measurer().bbox


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as source:
        return source.read()


def icon_source():
    source = read("web/app.jsx")
    start = source.index("function Icon(")
    return source, source[start:source.index("  };", start)]


def glyph_entries(body):
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r"^\s{4}(\w+):\s(.+)$", body, re.M)
    }


class IconCentringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.body = icon_source()
        cls.glyphs = glyph_entries(cls.body)

    def test_every_glyph_uses_one_grid(self):
        """Two viewBoxes is what made the same nudge mean different pixels."""
        self.assertIn('viewBox="0 0 24 24"', self.source)
        self.assertNotIn("0 0 16 16", self.source)

    def test_no_glyph_is_positioned_by_a_transform(self):
        self.assertEqual(self.body.count("transform="), 0, "a transform only centres one render size")

    def test_each_measured_glyph_has_a_single_path(self):
        for name in PURE_PATH_GLYPHS:
            with self.subTest(glyph=name):
                self.assertIn(name, self.glyphs)
                self.assertEqual(self.glyphs[name].count('d="'), 1)

    def test_single_path_glyph_ink_sits_on_the_centre(self):
        for name in PURE_PATH_GLYPHS:
            with self.subTest(glyph=name):
                data = re.search(r'd="([^"]+)"', self.glyphs[name]).group(1)
                left, top, right, bottom = bbox(data)
                centre_x, centre_y = (left + right) / 2, (top + bottom) / 2
                self.assertAlmostEqual(centre_y, OPTICAL_Y.get(name, 12.0), delta=0.05)
                self.assertAlmostEqual(centre_x, OPTICAL_X.get(name, 12.0), delta=0.05)

    def test_marks_alternating_in_one_button_share_one_icon_set(self):
        """#nowsave and the save rows swap `add` for `check` in the same box, so the
        two must be drawn alike: lucide's path data for both, one stroke weight,
        no fill override that would make one heavier than the other."""
        for name in ("add", "check"):
            with self.subTest(glyph=name):
                entry = self.glyphs[name]
                self.assertNotIn("fill=", entry, "one mark filled and one stroked is two weights")
                self.assertNotIn("stroke=", entry, "the wrapper's stroke is the shared one")
        self.assertIn('d="M12 5v14M5 12h14"', self.glyphs["add"])
        self.assertIn('d="M20 6 9 17l-5-5"', self.glyphs["check"])

    def test_save_menu_mark_icon_lands_on_whole_pixels(self):
        """The 22px ring's 1px border leaves a 20px content box, so a 13px glyph
        sat on a 3.5px inset: half covered on every edge, which rasterised the
        plus and the tick both about half a pixel off the ring's centre. With
        matching parity the inset is whole and both sit on the same grid."""
        css = read("web/index.html")
        source = read("web/app.jsx")
        ring = int(re.search(r"\.save-mark\{width:(\d+)px", css).group(1))
        border = int(re.search(r"\.save-mark\{[^}]*border:(\d+)px", css).group(1))
        icon = int(re.search(r'className="save-mark"><Icon name=\{inIt \? \'check\' : \'add\'\} size=\{(\d+)\}', source).group(1))
        self.assertEqual((ring - 2 * border - icon) % 2, 0, f"{icon}px glyph in a {ring}px ring sits half a pixel off")

    def test_glyphs_fit_inside_the_box(self):
        """A glyph pushed out of its box is the failure mode a nudge causes."""
        for name in PURE_PATH_GLYPHS:
            with self.subTest(glyph=name):
                data = re.search(r'd="([^"]+)"', self.glyphs[name]).group(1)
                left, top, right, bottom = bbox(data)
                self.assertGreaterEqual(left, 0.0)
                self.assertGreaterEqual(top, 0.0)
                self.assertLessEqual(right, 24.0)
                self.assertLessEqual(bottom, 24.0)


if __name__ == "__main__":
    unittest.main()
