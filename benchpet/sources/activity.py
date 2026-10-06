"""Whether you're coding or browsing, and for how long since your last break.

Combines input activity (IdleSource), the focused window (FocusTracker) and
away periods into a work session. Coding means recent input with an editor or
terminal focused; a quick switch to another window (looking something up)
doesn't end it. Browsing means a browser is focused once that grace has run out.
A session runs until a real break, i.e. the away threshold.
"""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QTimer

from benchpet.events import AwayChanged, ComputerActivity, EventBus, FocusChanged, InputChanged
from benchpet.sources.base import Source


def is_coding_app(app: str, coding_apps: list[str]) -> bool:
    """Case-insensitive substring match of the window class against `coding_apps`."""
    app = app.lower()
    return bool(app) and any(name.lower() in app for name in coding_apps)


is_browser_app = is_coding_app  # same matching, against `browser_apps`


class ActivitySource(Source):
    name = "activity"

    def __init__(self, bus: EventBus, config: dict, now: Callable[[], float] = time.monotonic):
        super().__init__(bus)
        self.now = now
        self.coding_apps = config["coding_apps"]
        self.browser_apps = config["browser_apps"]
        self.focus_grace = config["focus_grace_seconds"]
        self.tired_after = config["tired_minutes"] * 60
        self.exhausted_after = config["exhausted_minutes"] * 60
        self.input_active: bool | None = None  # None: no input info, judge by focus alone
        self.app = ""
        self._coding_focus_at: float | None = None  # last time an editor/terminal had focus
        self._session_start: float | None = None
        self._last: tuple | None = None
        self._timer = QTimer()
        self._timer.timeout.connect(self.tick)
        bus.event.connect(self._on_event)

    def start(self) -> None:
        self._session_start = self.now()  # you just started the pet, so you're here
        self._timer.start(5_000)

    def stop(self) -> None:
        self._timer.stop()

    def _on_event(self, event: object) -> None:
        if isinstance(event, InputChanged):
            self.input_active = event.active
            if event.active and self._session_start is None:
                self._session_start = self.now()
        elif isinstance(event, FocusChanged):
            if self._coding_focused():
                self._coding_focus_at = self.now()  # grace runs from leaving the editor
            self.app = event.app
        elif isinstance(event, AwayChanged):
            if event.level != "present":
                self._session_start = None
            elif self._session_start is None:
                self._session_start = self.now()
        else:
            return
        self.tick()

    def mode(self) -> str:
        if self.input_active is False or self._session_start is None:
            return "idle"
        if self._coding_focused():
            return "coding"
        recent = self._coding_focus_at is not None and self.now() - self._coding_focus_at < self.focus_grace
        if recent:
            return "coding"
        return "browsing" if is_browser_app(self.app, self.browser_apps) else "idle"

    def session_seconds(self) -> float:
        return 0.0 if self._session_start is None else self.now() - self._session_start

    def tier(self) -> str:
        seconds = self.session_seconds()
        if seconds >= self.exhausted_after:
            return "exhausted"
        return "tired" if seconds >= self.tired_after else "fresh"

    def tick(self) -> None:
        if self._coding_focused():
            self._coding_focus_at = self.now()
        minutes = self.session_seconds() / 60
        key = (self.mode(), self.tier(), int(minutes))
        if key != self._last:
            self._last = key
            self.bus.publish(ComputerActivity(key[0], key[1], minutes))

    def _coding_focused(self) -> bool:
        return is_coding_app(self.app, self.coding_apps)
