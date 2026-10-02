"""Away detection via the Wayland ext-idle-notify-v1 protocol.

KDE on Wayland doesn't implement org.freedesktop.ScreenSaver.GetSessionIdleTime,
and XWayland only sees X11 input, so this opens its own Wayland connection
(independent of Qt, which runs on xcb) and asks the compositor to tell us when
the seat has been idle for each threshold. Idle inhibitors (e.g. video
playback) are respected, so watching something doesn't count as away.

A third, short threshold reports whether you're using the keyboard/mouse right
now (InputChanged). That one ignores inhibitors where the compositor supports
it (protocol v2), so a playing video doesn't look like typing.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QSocketNotifier

from benchpet.events import AwayChanged, EventBus, InputChanged
from benchpet.sources.base import Source

log = logging.getLogger(__name__)


class IdleSource(Source):
    name = "idle"

    def __init__(self, bus: EventBus, short_minutes: float, long_minutes: float,
                 input_seconds: float | None = None):
        super().__init__(bus)
        self.thresholds = {"short": short_minutes * 60_000, "long": long_minutes * 60_000}
        self.input_timeout = input_seconds * 1000 if input_seconds else None
        self._display = None
        self._objects: list = []
        self._notifier: QSocketNotifier | None = None
        self._idle: set[str] = set()
        self.level = "present"

    def start(self) -> None:
        if not os.environ.get("WAYLAND_DISPLAY"):
            log.warning("idle: not a Wayland session; away detection disabled")
            return
        from pywayland.client import Display
        from pywayland.protocol.ext_idle_notify_v1 import ExtIdleNotifierV1
        from pywayland.protocol.wayland import WlSeat

        display = Display()
        display.connect()
        found = {}

        def on_global(registry, name, interface, version):
            if interface == "wl_seat" and "seat" not in found:
                found["seat"] = registry.bind(name, WlSeat, 1)
            elif interface == "ext_idle_notifier_v1":
                found["version"] = min(version, 2)
                found["notifier"] = registry.bind(name, ExtIdleNotifierV1, found["version"])

        registry = display.get_registry()
        registry.dispatcher["global"] = on_global
        display.roundtrip()
        if "notifier" not in found or "seat" not in found:
            log.warning("idle: compositor lacks ext_idle_notifier_v1; away detection disabled")
            display.disconnect()
            return

        self._display = display
        self._objects = [registry, found["seat"], found["notifier"]]
        for level, timeout in self.thresholds.items():
            notification = found["notifier"].get_idle_notification(int(timeout), found["seat"])
            notification.dispatcher["idled"] = lambda *_, lv=level: self._on_idled(lv)
            notification.dispatcher["resumed"] = lambda *_, lv=level: self._on_resumed(lv)
            self._objects.append(notification)
        if self.input_timeout:
            notifier = found["notifier"]
            get = (notifier.get_input_idle_notification if found["version"] >= 2
                   else notifier.get_idle_notification)
            notification = get(int(self.input_timeout), found["seat"])
            notification.dispatcher["idled"] = lambda *_: self.bus.publish(InputChanged(False))
            notification.dispatcher["resumed"] = lambda *_: self.bus.publish(InputChanged(True))
            self._objects.append(notification)
            self.bus.publish(InputChanged(True))  # you just started the pet
        display.flush()

        self._notifier = QSocketNotifier(display.get_fd(), QSocketNotifier.Read)
        self._notifier.activated.connect(self._on_readable)

    def stop(self) -> None:
        if self._notifier:
            self._notifier.setEnabled(False)
            self._notifier = None
        if self._display:
            # Tear down explicitly: leaving pywayland objects to the GC at exit segfaults.
            for obj in reversed(self._objects):
                if hasattr(obj, "destroy") and obj.__class__.__name__ != "WlRegistry":
                    obj.destroy()
            self._objects.clear()
            self._display.flush()
            self._display.disconnect()
            self._display = None

    def _on_readable(self) -> None:
        try:
            self._display.dispatch(block=True)  # socket is readable, so this won't block
            self._display.flush()
        except Exception:
            log.exception("idle: lost Wayland connection; away detection disabled")
            self._notifier.setEnabled(False)

    def _on_idled(self, level: str) -> None:
        self._idle.add(level)
        self._publish()

    def _on_resumed(self, level: str) -> None:
        self._idle.discard(level)
        self._publish()

    def _publish(self) -> None:
        level = "long" if "long" in self._idle else "short" if "short" in self._idle else "present"
        if level != self.level:
            self.level = level
            self.bus.publish(AwayChanged(level))
