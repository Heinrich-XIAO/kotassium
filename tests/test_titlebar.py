"""macOS title-bar integration: pure logic that runs on any platform.

titlebar_macos talks to AppKit only on a Mac, so these tests stub AppKit out
and pin down the parts Linux CI can check: the traffic-light geometry, the
page reserving room for them, and the wiring in desktop.py / web/index.html.
"""
import os
import re
import unittest
from types import SimpleNamespace

import titlebar_macos
from titlebar_macos import light_origins, lights_right_edge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class StubAppKit:
    """The handful of AppKit names titlebar_macos uses, as plain values."""
    NSWindowCloseButton = 0
    NSWindowMiniaturizeButton = 1
    NSWindowZoomButton = 2
    NSWindowStyleMaskFullSizeContentView = 1 << 15
    NSWindowTitleHidden = 1

    @staticmethod
    def NSMakePoint(x, y):
        return (x, y)


class FakeButton:
    def __init__(self, x=7.0, y=6.0, width=14.0):
        self.f = SimpleNamespace(
            origin=SimpleNamespace(x=x, y=y),
            size=SimpleNamespace(width=width, height=16.0))
        self.hidden = None

    def frame(self):
        return self.f

    def setFrameOrigin_(self, point):
        self.f.origin.x, self.f.origin.y = point[0], point[1]

    def setHidden_(self, value):
        self.hidden = value


class FakeNative:
    def __init__(self, buttons=None, mask=1 | 2 | 4):
        self._mask = mask
        self.buttons = buttons or [FakeButton(), FakeButton(x=28.0),
                                   FakeButton(x=49.0)]
        self.transparent = None
        self.title_visibility = None
        self.movable_by_background = None

    def styleMask(self):
        return self._mask

    def setStyleMask_(self, mask):
        self._mask = mask

    def setTitlebarAppearsTransparent_(self, value):
        self.transparent = value

    def setTitleVisibility_(self, value):
        self.title_visibility = value

    def setMovableByWindowBackground_(self, value):
        self.movable_by_background = value

    def standardWindowButton_(self, kind):
        return self.buttons[kind]


class BrokenNative:
    """Every AppKit call fails: integration must swallow it, not crash."""

    def __getattr__(self, name):
        raise RuntimeError("AppKit refused " + name)


class GeometryTests(unittest.TestCase):
    def test_origins_step_clear_of_the_button(self):
        for width in (12.0, 14.0, 16.0):
            xs = light_origins(width)
            self.assertEqual(len(xs), 3)
            self.assertEqual(xs[0], 20.0)
            self.assertTrue(all(b - a >= width + 4
                                for a, b in zip(xs, xs[1:])),
                            "lights must not touch at width %s" % width)

    def test_page_reserves_room_for_the_lights(self):
        page = read("web/index.html")
        pads = dict(re.findall(r"html\.tbmac #(top|dfsTop)\{padding-left:(\d+)px\}",
                               page))
        self.assertEqual(set(pads), {"top", "dfsTop"},
                         "the shell's top bars must pad for the lights")
        for width in (12.0, 14.0, 16.0):
            for bar, pad in pads.items():
                self.assertLessEqual(
                    lights_right_edge(width) + 8, int(pad),
                    "%s padding leaves no gap after lights of width %s"
                    % (bar, width))


class IntegrateTests(unittest.TestCase):
    def setUp(self):
        self._appkit = titlebar_macos.AppKit
        titlebar_macos.AppKit = StubAppKit

    def tearDown(self):
        titlebar_macos.AppKit = self._appkit

    def test_flags_and_light_positions(self):
        native = FakeNative()
        window = SimpleNamespace(native=native)
        self.assertTrue(titlebar_macos.integrate(window))
        self.assertTrue(native._mask & (1 << 15),
                        "full-size content view must be set")
        self.assertIs(native.transparent, True)
        self.assertEqual(native.title_visibility, StubAppKit.NSWindowTitleHidden)
        self.assertIs(native.movable_by_background, True)
        self.assertEqual([b.frame().origin.x for b in native.buttons],
                         [20.0, 40.0, 60.0])
        # y stays where AppKit put it (centred in the native title bar)
        self.assertEqual([b.frame().origin.y for b in native.buttons],
                         [6.0, 6.0, 6.0])
        # a normal window keeps its lights visible: nothing may hide them
        self.assertEqual([b.hidden for b in native.buttons],
                         [None, None, None])

    def test_failures_leave_a_usable_window(self):
        window = SimpleNamespace(native=BrokenNative())
        self.assertTrue(titlebar_macos.integrate(window))
        self.assertTrue(titlebar_macos.integrate(SimpleNamespace(native=None)))


class WiringTests(unittest.TestCase):
    def test_desktop_passes_the_flag_and_hooks_the_event(self):
        src = read("desktop.py")
        self.assertIn('"tb=mac"', src)
        self.assertIn("IS_MAC", src)
        self.assertIn("titlebar_macos", src)
        self.assertIn("before_show", src)
        self.assertNotIn("DRAG_REGION_DIRECT_TARGET_ONLY", src)
        self.assertIn("setMovableByWindowBackground_", read("titlebar_macos.py"))

    def test_page_does_not_use_webview_drag_regions(self):
        page = read("web/index.html")
        self.assertNotIn("pywebview-drag-region", page)
        self.assertIn("tb=mac", page)
        # CSS flag is read before the page is rendered.
        self.assertIn("documentElement.className", page)


if __name__ == "__main__":
    unittest.main()
