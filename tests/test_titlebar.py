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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class StubAppKit:
    """The handful of AppKit names titlebar_macos uses, as plain values."""
    screens = []

    class NSScreen:
        @classmethod
        def screens(cls):
            return StubAppKit.screens

    NSWindowCloseButton = 0
    NSWindowMiniaturizeButton = 1
    NSWindowZoomButton = 2
    NSWindowStyleMaskFullSizeContentView = 1 << 15
    NSWindowTitleHidden = 1
    NSWindowTitlebarSeparatorStyleNone = 2

    class NSColor:
        @staticmethod
        def clearColor():
            return "clear"

    @staticmethod
    def NSMakePoint(x, y):
        return (x, y)

    class NSObject:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def respondsToSelector_(self, selector):
            return False

        def forwardingTargetForSelector_(self, selector):
            return None


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
        self.titlebar_separator = None
        self.background_color = None
        self.frame_displayed = None
        self.animated_frame = None
        self.zoomed = False
        self.movable_by_background = None
        self.toolbar = "existing"
        self._delegate = SimpleNamespace(respondsToSelector_=lambda selector: False)

    def styleMask(self):
        return self._mask

    def setStyleMask_(self, mask):
        self._mask = mask

    def setTitlebarAppearsTransparent_(self, value):
        self.transparent = value

    def setToolbar_(self, toolbar):
        self.toolbar = toolbar

    def setTitleVisibility_(self, value):
        self.title_visibility = value

    def setTitlebarSeparatorStyle_(self, value):
        self.titlebar_separator = value

    def setBackgroundColor_(self, value):
        self.background_color = value

    def frame(self):
        return getattr(self, "_frame", (0, 0, 900, 600))

    def setFrame_display_(self, frame, display):
        self.frame_displayed = (frame, display)

    def setFrame_display_animate_(self, frame, display, animate):
        self.animated_frame = (frame, display, animate)
        self._frame = frame

    def isZoomed(self):
        return self.zoomed

    def zoom_(self, sender):
        self.zoomed = not self.zoomed

    def setMovableByWindowBackground_(self, value):
        self.movable_by_background = value

    def delegate(self):
        return self._delegate

    def setDelegate_(self, delegate):
        self._delegate = delegate

    def screen(self):
        return SimpleNamespace(frame=lambda: (-1920, 0, 1920, 1080),
                               visibleFrame=lambda: (-1920, 24, 1920, 1056))

    def standardWindowButton_(self, kind):
        return self.buttons[kind]


class BrokenNative:
    """Every AppKit call fails: integration must swallow it, not crash."""

    def __getattr__(self, name):
        raise RuntimeError("AppKit refused " + name)


class GeometryTests(unittest.TestCase):
    def test_app_controls_precede_home_and_search(self):
        page = read("web/index.html")
        top = page.index('<div id=top>')
        home = page.index('<button id=homeBtn', top)
        search = page.index('<div id=searchwrap', top)
        self.assertLess(home, search)

    def test_custom_titlebar_helpers_are_retired_noops(self):
        native = FakeNative()
        self.assertFalse(titlebar_macos.integrate(SimpleNamespace(native=native)))
        self.assertFalse(titlebar_macos.toggle_maximized(native))
        self.assertEqual(titlebar_macos.standard_frame(native, (1, 2, 3, 4)),
                         (1, 2, 3, 4))
        self.assertIsNone(titlebar_macos.forget_window(native))

    def test_failures_leave_a_usable_window(self):
        window = SimpleNamespace(native=BrokenNative())
        self.assertFalse(titlebar_macos.integrate(window))
        self.assertFalse(titlebar_macos.integrate(SimpleNamespace(native=None)))


class WiringTests(unittest.TestCase):
    def test_desktop_uses_native_resizable_window(self):
        src = read("desktop.py")
        self.assertNotIn('"tb=mac"', src)
        self.assertNotIn("frameless=IS_MAC", src)
        self.assertNotIn("import titlebar_macos", src)
        self.assertNotIn("easy_drag=False", src)

    def test_mac_page_does_not_replace_native_window_controls(self):
        page = read("web/index.html")
        self.assertNotIn("id=macControls", page)
        self.assertNotIn("pywebview-drag-region", page)
        self.assertNotIn("toggle_maximized", page)

if __name__ == "__main__":
    unittest.main()
