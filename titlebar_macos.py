"""Deprecated compatibility shim for the retired custom macOS titlebar.

Kotassium now uses pywebview's native resizable Cocoa window. Keep these
helpers as harmless no-ops for older imports; do not mutate NSWindow delegates
or frames here.
"""


def integrate(window):
    return False


def standard_frame(window, default):
    return default


def maximize_frame(window, default):
    return default


def toggle_maximized(native):
    return False


def forget_window(native):
    return None


def install_zoom_delegate(native):
    return False
