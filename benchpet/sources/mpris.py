"""MPRIS now-playing source.

Uses Gio rather than QtDBus: PySide6 can't unmarshal MPRIS's nested a{sv}
metadata, while Gio hands back native Python types. Qt runs on the GLib event
loop on Linux, so Gio signal callbacks are dispatched without extra plumbing.
"""

from __future__ import annotations

from gi.repository import Gio, GLib

from benchpet.events import EventBus, MediaCommand, MusicChanged
from benchpet.sources.base import Source

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
METHODS = {"play_pause": "PlayPause", "next": "Next", "previous": "Previous"}


def parse_props(props: dict) -> tuple[str | None, ...]:
    """(status, title, artist, album, art_url) from a Player property dict; None for absent keys."""
    status = props.get("PlaybackStatus")
    title = artist = album = art_url = None
    metadata = props.get("Metadata")
    if metadata is not None:
        title = metadata.get("xesam:title", "")
        artists = metadata.get("xesam:artist", [])
        artist = ", ".join(artists) if isinstance(artists, list) else str(artists)
        album = metadata.get("xesam:album", "")
        art_url = metadata.get("mpris:artUrl", "")
    return status, title, artist, album, art_url


class MprisSource(Source):
    name = "mpris"

    def __init__(self, bus: EventBus):
        super().__init__(bus)
        self._dbus: Gio.DBusConnection | None = None
        self._subs: list[int] = []
        # bus name → {"status", "title", "artist", "album", "art_url"}; unique name → well-known name
        self._players: dict[str, dict[str, str]] = {}
        self._owners: dict[str, str] = {}
        self._active: str | None = None
        self._last_published: MusicChanged | None = None
        bus.event.connect(self._on_event)

    def start(self) -> None:
        self._dbus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self._subs.append(self._dbus.signal_subscribe(
            "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
            "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE, self._on_owner_changed))
        # PropertiesChanged arrives from the player's unique name, so subscribe
        # to all senders and map back via _owners.
        self._subs.append(self._dbus.signal_subscribe(
            None, PROPS_IFACE, "PropertiesChanged", PATH, PLAYER_IFACE,
            Gio.DBusSignalFlags.NONE, self._on_properties_changed))
        self._dbus.call(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "ListNames", None, None, Gio.DBusCallFlags.NONE, -1, None, self._on_list_names)

    def stop(self) -> None:
        if self._dbus:
            for sub in self._subs:
                self._dbus.signal_unsubscribe(sub)
        self._subs.clear()

    def _on_event(self, event: object) -> None:
        """Media controls act on the player whose track the pet is showing."""
        if not isinstance(event, MediaCommand) or not self._dbus:
            return
        player = self._last_published.player if self._last_published else ""
        method = METHODS.get(event.action)
        if player and method:
            self._dbus.call(player, PATH, PLAYER_IFACE, method, None, None,
                            Gio.DBusCallFlags.NONE, -1, None, None)

    # --- D-Bus callbacks -------------------------------------------------

    def _on_list_names(self, conn, result) -> None:
        names = conn.call_finish(result).unpack()[0]
        for name in names:
            if name.startswith(PREFIX):
                self._add_player(name)

    def _on_owner_changed(self, conn, sender, path, iface, signal, params) -> None:
        name, old, new = params.unpack()
        if not name.startswith(PREFIX):
            return
        if new:
            self._add_player(name)
        else:
            self._remove_player(name)

    def _on_properties_changed(self, conn, sender, path, iface, signal, params) -> None:
        _iface, changed, _invalidated = params.unpack()
        name = self._owners.get(sender)
        if name is None:
            return
        self._update(name, changed)

    # --- player tracking -------------------------------------------------

    def _add_player(self, name: str) -> None:
        self._players.setdefault(name, {"status": "Stopped", "title": "", "artist": "", "album": "", "art_url": ""})
        self._dbus.call(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "GetNameOwner", GLib.Variant("(s)", (name,)), None, Gio.DBusCallFlags.NONE,
            -1, None, self._on_name_owner, name)
        self._dbus.call(
            name, PATH, PROPS_IFACE, "GetAll", GLib.Variant("(s)", (PLAYER_IFACE,)), None,
            Gio.DBusCallFlags.NONE, -1, None, self._on_get_all, name)

    def _on_name_owner(self, conn, result, name: str) -> None:
        try:
            self._owners[conn.call_finish(result).unpack()[0]] = name
        except GLib.Error:
            pass

    def _on_get_all(self, conn, result, name: str) -> None:
        try:
            props = conn.call_finish(result).unpack()[0]
        except GLib.Error:
            return
        self._update(name, props)

    def _remove_player(self, name: str) -> None:
        self._players.pop(name, None)
        self._owners = {u: n for u, n in self._owners.items() if n != name}
        if self._active == name:
            self._active = None
        self._publish()

    def _update(self, name: str, props: dict) -> None:
        if name not in self._players:
            return
        status, title, artist, album, art_url = parse_props(props)
        player = self._players[name]
        if status is not None:
            player["status"] = status
            if status == "Playing":
                self._active = name  # most recently started player wins
        if title is not None:
            player["title"] = title
            player["artist"] = artist or ""
            player["album"] = album or ""
            player["art_url"] = art_url or ""
        self._publish()

    def _publish(self) -> None:
        name = self._active
        if name is None or self._players.get(name, {}).get("status") != "Playing":
            # Prefer any player still playing, then the last active one if merely
            # paused, then any other paused player.
            ranked = sorted(
                (n for n, p in self._players.items() if p["status"] != "Stopped"),
                key=lambda n: (self._players[n]["status"] != "Playing", n != self._active),
            )
            name = ranked[0] if ranked else name
        if name is None or name not in self._players:
            event = MusicChanged(player="", status="Stopped")
        else:
            p = self._players[name]
            event = MusicChanged(name, p["status"], p["title"], p["artist"], p["album"], p["art_url"])
        if event != self._last_published:
            self._last_published = event
            self.bus.publish(event)
