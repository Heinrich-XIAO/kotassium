"""Minimal MPRIS v2 service (Linux).

Exposes Kotassium to media keys, GNOME's media widget and lock screen. The page
reports state to the server; desktop.py polls it and calls update(). Controls
arrive as D-Bus method calls and are queued by desktop.py, never executed on
the GTK main loop (evaluate_js would deadlock there).
"""
import threading

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

PATH = "/org/mpris/MediaPlayer2"
ROOT = "org.mpris.MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
BUS_NAME = "org.mpris.MediaPlayer2.kotassium"

XML = """<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="Identity" type="s" access="read"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="PlayPause"/>
    <method name="Play"/>
    <method name="Pause"/>
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Stop"/>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Position" type="x" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
  </interface>
</node>"""


class MprisLinux:
    def __init__(self, base_url, controls):
        self.base_url = base_url.rstrip("/")
        self.controls = controls
        self.conn = None
        self._lock = threading.Lock()
        self.title = ""
        self.artist = ""
        self.playing = False
        self.art = ""
        self.length_ms = 0
        self.position_ms = 0
        self.track = 0
        try:
            self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(XML)
            self.conn.register_object(PATH, node.lookup_interface(ROOT),
                                      self._root_call, self._root_get, None)
            self.conn.register_object(PATH, node.lookup_interface(PLAYER),
                                      self._player_call, self._player_get, None)
            Gio.bus_own_name_on_connection(self.conn, BUS_NAME,
                                           Gio.BusNameOwnerFlags.NONE, None, None)
        except Exception:
            self.conn = None

    # --- incoming method calls (GTK main loop thread) ---
    def _root_call(self, conn, sender, path, iface, method, params, invocation):
        if method == "Quit":
            self.controls.get("quit", lambda: None)()
        invocation.return_value(None)

    def _player_call(self, conn, sender, path, iface, method, params, invocation):
        fn = self.controls.get(method.lower())
        if fn:
            fn()
        invocation.return_value(None)

    # --- property reads (GTK main loop thread) ---
    def _root_get(self, conn, sender, path, iface, prop):
        return {
            "Identity": GLib.Variant("s", "Kotassium"),
            "CanQuit": GLib.Variant("b", True),
            "CanRaise": GLib.Variant("b", False),
            "HasTrackList": GLib.Variant("b", False),
        }.get(prop, GLib.Variant("s", ""))

    def _player_get(self, conn, sender, path, iface, prop):
        with self._lock:
            if prop == "PlaybackStatus":
                return GLib.Variant("s", "Playing" if self.playing else "Paused")
            if prop == "Metadata":
                return self._metadata()
            if prop == "Position":
                return GLib.Variant("x", int(self.position_ms * 1000))
            if prop in ("CanPlay", "CanPause", "CanGoNext", "CanGoPrevious",
                        "CanControl", "CanSeek"):
                return GLib.Variant("b", prop != "CanSeek")
        return GLib.Variant("b", False)

    def _metadata(self):
        art = self.art
        if art.startswith("/"):
            art = self.base_url + art
        d = {
            "mpris:trackid": GLib.Variant("o", "/org/kotassium/track/%d" % self.track),
            "mpris:length": GLib.Variant("x", int(self.length_ms * 1000)),
        }
        if self.title:
            d["xesam:title"] = GLib.Variant("s", self.title)
        if self.artist:
            d["xesam:artist"] = GLib.Variant("as", [self.artist])
        if art:
            d["mpris:artUrl"] = GLib.Variant("s", art)
        return GLib.Variant("a{sv}", d)

    def update(self, now):
        """Apply a /api/nowplaying payload. Safe from any thread."""
        title = now.get("t") or ""
        artist = now.get("a") or ""
        playing = now.get("state") == "playing"
        art = now.get("cover") or ""
        length = int(now.get("ms") or 0)
        pos = int(now.get("pos") or 0)
        with self._lock:
            new_track = title != self.title
            self.title, self.artist, self.playing = title, artist, playing
            self.art, self.length_ms, self.position_ms = art, length, pos
            if new_track:
                self.track += 1
            conn = self.conn
            if not conn:
                return
            status = GLib.Variant("s", "Playing" if playing else "Paused")
            meta = self._metadata()
        try:
            conn.emit_signal(None, PATH, "org.freedesktop.DBus.Properties",
                             "PropertiesChanged",
                             GLib.Variant("(sa{sv}as)",
                                          (PLAYER, {"PlaybackStatus": status,
                                                    "Metadata": meta}, [])))
        except Exception:
            pass
