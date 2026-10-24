"""macOS window chrome: fold the native title bar into the page's top bar.

The Spotify-style window has no OS strip above the app: the page's own top
bar runs to the window's top edge and the traffic lights float inside it.
pywebview exposes the NSWindow as ``window.native``; on the ``before_show``
event (fired synchronously, before the window is ordered front) this module
adds the full-size-content-view mask, makes the title bar transparent and
titleless, and slides the close/minimize/zoom buttons to the right, into the
space the page reserves for them (desktop.py opens the page with ``tb=mac``,
which pads web/index.html's top bar).

Geometry and AppKit flags only -- markup and presentation stay in the page.
Every AppKit call is best-effort: if any of them fails the window keeps a
normal, usable title bar with its buttons in place. Not runnable on Linux
beyond its pure functions, so keep it boring and verify on a Mac.
"""
import threading

try:
    import AppKit
except Exception:  # no pyobjc, or not macOS: leave the window as it is
    AppKit = None

LIGHT_X0 = 20.0    # left edge of the close light, points from the window edge
LIGHT_STEP = 20.0  # centre-to-centre spacing: light width plus a gap


def light_origins(width, x0=LIGHT_X0, step=LIGHT_STEP):
    """Frame origins (x) of the three lights for a button of `width`."""
    spacing = max(step, width + 6)
    return tuple(x0 + i * spacing for i in range(3))


def lights_right_edge(width, x0=LIGHT_X0, step=LIGHT_STEP):
    """Rightmost point the lights occupy; the page must start after this."""
    return light_origins(width, x0, step)[-1] + width


def integrate(window):
    """Put the page's top bar in charge of the window chrome (macOS).

    Returns False when AppKit is unavailable and never raises: a broken
    integration must leave a normal, closable window behind.
    """
    if AppKit is None:
        return False

    def apply():
        native = getattr(window, "native", None)
        if native is None:
            return
        try:
            fullsize = getattr(AppKit, "NSWindowStyleMaskFullSizeContentView", 0) \
                or getattr(AppKit, "NSFullSizeContentViewWindowMask", 0) \
                or (1 << 15)
            native.setStyleMask_(native.styleMask() | fullsize)
            native.setTitlebarAppearsTransparent_(True)
            native.setTitleVisibility_(getattr(AppKit, "NSWindowTitleHidden", 1))
            # Native titlebar hit-testing gives correct window dragging and
            # preserves macOS's configured double-click action (normally zoom).
            # The webview drag-region handler instead computes a stale offset
            # when the content view extends beneath the titlebar.
            native.setMovableByWindowBackground_(True)
        except Exception as e:
            print("[kotassium] title bar flags: %s" % e, flush=True)
        place_lights(native)

    if threading.current_thread() is threading.main_thread():
        apply()
    else:
        # AppKit belongs on the main thread. before_show normally runs there
        # already (pywebview fires it while building the window); this covers
        # any other flow pywebview might use.
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(apply)
        except Exception:
            apply()
    return True


def place_lights(native):
    """Slide close/minimize/zoom right; y stays at AppKit's default.

    The default keeps the lights centred in the native title bar (~14pt from
    the top), which is where Spotify puts them inside its taller app bar.
    """
    try:
        kinds = (AppKit.NSWindowCloseButton,
                 AppKit.NSWindowMiniaturizeButton,
                 AppKit.NSWindowZoomButton)
        buttons = [b for b in (native.standardWindowButton_(k) for k in kinds)
                   if b is not None]
    except Exception as e:
        print("[kotassium] title bar buttons: %s" % e, flush=True)
        return
    if not buttons:
        return
    try:
        width = float(buttons[0].frame().size.width)
    except Exception:
        width = 14.0
    for button, x in zip(buttons, light_origins(width)):
        try:
            origin = button.frame().origin
            button.setFrameOrigin_(AppKit.NSMakePoint(x, origin.y))
        except Exception as e:
            print("[kotassium] title bar position: %s" % e, flush=True)
