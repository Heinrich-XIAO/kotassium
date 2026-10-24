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
        return (0, 0, 900, 600)

    def setFrame_display_(self, frame, display):
        self.frame_displayed = (frame, display)

    def setFrame_display_animate_(self, frame, display, animate):
        self.animated_frame = (frame, display, animate)

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
        return SimpleNamespace(visibleFrame=lambda: (-1920, 24, 1920, 1056))

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
        controls = page.index('<div id=macControls>', top)
        home = page.index('<button id=homeBtn', top)
        search = page.index('<div id=searchwrap', top)
        self.assertLess(controls, home)
        self.assertLess(home, search)
        self.assertIn("html.tbmac #top{padding-left:16px}", page)

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
        self.assertIs(native.movable_by_background, True)
        self.assertIsNotNone(native._delegate)
        self.assertEqual(
            native._delegate.windowWillUseStandardFrame_defaultFrame_(
                native, (1, 2, 3, 4)),
            (-1920, 24, 1920, 1056))

    def test_standard_frame_follows_the_window_screen(self):
        secondary = (-1920, 24, 1920, 1056)
        native = FakeNative()
        self.assertEqual(titlebar_macos.standard_frame(native, (0, 0, 800, 600)),
                         secondary)
        native.screen = lambda: None
        self.assertEqual(titlebar_macos.standard_frame(native, (0, 0, 800, 600)),
                         (0, 0, 800, 600))

    def test_toggle_maximized_sets_frame_on_current_secondary_screen(self):
        native = FakeNative()
        self.assertTrue(titlebar_macos.toggle_maximized(native))
        self.assertEqual(native.animated_frame,
                         ((-1920, 24, 1920, 1056), True, True))

    def test_toggle_maximized_restores_using_native_zoom(self):
        native = FakeNative()
        native.zoomed = True
        self.assertTrue(titlebar_macos.toggle_maximized(native))
        self.assertTrue(native.zoomed is False)

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
        self.assertIn("toggle_maximized", src)
        self.assertIn("titlebar_macos.toggle_maximized", src)
        self.assertIn("DRAG_REGION_DIRECT_TARGET_ONLY", src)
        self.assertIn("frameless=IS_MAC", src)
        self.assertIn("easy_drag=False", src)
        self.assertIn("close_window", src)
        self.assertIn("minimize_window", src)
        self.assertIn("windowWillUseStandardFrame_defaultFrame_", read("titlebar_macos.py"))

    def test_page_marks_the_drag_region(self):
        page = read("web/index.html")
        self.assertIn("pywebview-drag-region", page)
        self.assertIn("tb=mac", page)
        # the flag must be read from the URL, before the bar is used
        self.assertIn("documentElement.className", page)
        self.assertIn("addEventListener('dblclick'", page)
        self.assertIn("addEventListener('mousedown'", page)
        self.assertIn("e.detail===2", page)
        self.assertIn("toggle_maximized", page)
        self.assertIn("id=macControls", page)
        self.assertIn("id=macClose", page)
        self.assertIn("id=macMin", page)
        self.assertIn("id=macZoom", page)
        self.assertIn('id=macClose title="Close window" onclick=', page)
        self.assertIn('id=macMin title="Minimize window" onclick=', page)
        self.assertIn('id=macZoom title="Maximize window" onclick=', page)

if __name__ == "__main__":
    unittest.main()
