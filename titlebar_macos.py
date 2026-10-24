"""AppKit helpers for Kotassium's frameless macOS window."""
import threading

try:
    import AppKit
except Exception:
    AppKit = None

_WINDOW_DELEGATES = {}
_MAXIMIZED_FRAMES = {}


def _rect_values(rect):
    """Return (x, y, width, height) for an AppKit rect or a tuple test rect."""
    try:
        return (rect.origin.x, rect.origin.y,
                rect.size.width, rect.size.height)
    except AttributeError:
        return tuple(rect)


def screen_for_window(window):
    """Pick one display from the window's center, stable while it straddles."""
    try:
        screens = list(AppKit.NSScreen.screens()) if AppKit else []
        frame = _rect_values(window.frame())
        x, y, width, height = frame
        cx, cy = x + width / 2, y + height / 2
        containing = []
        best, best_area = None, -1
        for screen in screens:
            sx, sy, sw, sh = _rect_values(screen.frame())
            if sx <= cx <= sx + sw and sy <= cy <= sy + sh:
                containing.append(screen)
            overlap = (max(0, min(x + width, sx + sw) - max(x, sx)) *
                       max(0, min(y + height, sy + sh) - max(y, sy)))
            if overlap > best_area:
                best, best_area = screen, overlap
        if containing:
            return containing[0]
        if best:
            return best
    except Exception:
        pass
    try:
        return window.screen()
    except Exception:
        return None


def standard_frame(window, default):
    """Choose the visible frame of the display containing the window center."""
    try:
        screen = screen_for_window(window)
        if not screen:
            return default
        # Preserve the display's screen-space origin; secondary displays can
        # have negative coordinates relative to the primary display.
        return screen.visibleFrame()
    except Exception:
        return default


def maximize_frame(window, default):
    """Frame covering the visible area of the display holding the window."""
    return standard_frame(window, default)


def toggle_maximized(native):
    """Toggle between the saved normal frame and this screen's visible frame.

    Keep our own restore frame: manually setting an NSWindow frame does not
    enter AppKit's zoom state, so isZoomed()/zoom_() cannot reliably toggle it.
    """
    if native is None:
        return False
    key = id(native)
    try:
        current = _rect_values(native.frame())
        saved = _MAXIMIZED_FRAMES.get(key)
        if saved is not None:
            if _frames_match(current, saved[1]) or _frames_match(
                    current, saved[2]):
                _MAXIMIZED_FRAMES.pop(key, None)
                native.setFrame_display_animate_(saved[0], True, True)
            else:
                # A user resize/move after maximizing becomes the new normal
                # frame before maximizing again on the display now containing it.
                _MAXIMIZED_FRAMES.pop(key, None)
                target = _rect_values(maximize_frame(native, current))
                _MAXIMIZED_FRAMES[key] = (current, target, target)
                native.setFrame_display_animate_(target, True, True)
            return True
        target = _rect_values(maximize_frame(native, current))
        if _frames_match(current, target):
            return True
        _MAXIMIZED_FRAMES[key] = (current, target, target)
        native.setFrame_display_animate_(target, True, True)
        return True
    except Exception:
        _MAXIMIZED_FRAMES.pop(key, None)
        return False


def _frames_match(a, b):
    """Compare AppKit frame values with a small float tolerance."""
    return len(a) == len(b) and all(abs(float(x) - float(y)) < 1 for x, y in zip(a, b))


def forget_window(native):
    """Drop per-window maximize state when the window closes."""
    if native is not None:
        _MAXIMIZED_FRAMES.pop(id(native), None)


def install_zoom_delegate(native):
    """Set a usable maximize frame while forwarding the existing pywebview delegate."""
    if AppKit is None:
        return False
    try:
        original = native.delegate()

        class ZoomDelegate(AppKit.NSObject):
            def initWithDelegate_(self, delegate):
                self = AppKit.NSObject.init(self)
                if self is not None:
                    self._delegate = delegate
                return self

            def windowWillUseStandardFrame_defaultFrame_(self, window, default):
                return maximize_frame(window, default)

            def respondsToSelector_(self, selector):
                if self._delegate and self._delegate.respondsToSelector_(selector):
                    return True
                return AppKit.NSObject.respondsToSelector_(self, selector)

            def forwardingTargetForSelector_(self, selector):
                if self._delegate and self._delegate.respondsToSelector_(selector):
                    return self._delegate
                return AppKit.NSObject.forwardingTargetForSelector_(self, selector)

        delegate = ZoomDelegate.alloc().initWithDelegate_(original)
        native.setDelegate_(delegate)
        _WINDOW_DELEGATES[id(native)] = (delegate, original)
        return True
    except Exception as e:
        print("[kotassium] maximize frame: %s" % e, flush=True)
        return False


def integrate(window):
    """Enable drag on the native background for a frameless pywebview window."""
    if AppKit is None:
        return False

    def apply():
        native = getattr(window, "native", None)
        if native is None:
            return
        try:
            if getattr(window, "events", None):
                window.events.closed += lambda: forget_window(native)
            native.setMovableByWindowBackground_(True)
            install_zoom_delegate(native)
        except Exception as e:
            print("[kotassium] title bar flags: %s" % e, flush=True)

    if threading.current_thread() is threading.main_thread():
        apply()
    else:
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(apply)
        except Exception:
            apply()
    return True
