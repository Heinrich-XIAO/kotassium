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

# Two glyphs carry a deliberate optical offset. The play triangle reads pulled
# towards its base, so its ink sits 0.75 to the right. The tick's stroke bulges
# at the round join where its arms meet, further than the cap on the long arm,
# so the drawn glyph sat 0.50 low and 0.25 right at 13px (measured in pixels,
# in a headless browser); 0.92 and 0.46 glyph units take that out, and because
# the correction lives in the coordinates it holds at 16px too.
OPTICAL_X = {"play": 12.75, "check": 11.54}
OPTICAL_Y = {"check": 11.08}


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
