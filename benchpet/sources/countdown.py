"""Countdowns: to the end of the working week, plus custom one-off events."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Callable

from PySide6.QtCore import QTimer

from benchpet.events import CountdownReached, CountdownsUpdated, EventBus
from benchpet.sources.base import Source

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_weekly(spec: dict) -> tuple[int, time]:
    return DAYS.index(spec["day"].lower()), time.fromisoformat(spec["time"])


def next_weekly(now: datetime, weekday: int, at: time) -> datetime:
    """The next occurrence of weekday/at strictly after `now`."""
    candidate = datetime.combine(now.date() + timedelta(days=(weekday - now.weekday()) % 7), at)
    return candidate if candidate > now else candidate + timedelta(days=7)


def in_weekend(now: datetime, week_end: tuple[int, time], week_start: tuple[int, time]) -> bool:
    """True between the end of one working week and the start of the next."""
    return next_weekly(now, *week_start) < next_weekly(now, *week_end)


def format_remaining(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m" if minutes else "under a minute"


class CountdownSource(Source):
    name = "countdown"

    def __init__(self, bus: EventBus, config: dict, now: Callable[[], datetime] = datetime.now):
        super().__init__(bus)
        self.now = now
        self.week_end = parse_weekly(config["week_end"])
        self.week_start = parse_weekly(config["week_start"])
        self.label = config.get("label", "Weekend")
        self.events = [(e["name"], datetime.fromisoformat(str(e["at"]))) for e in config.get("events", [])]
        self._timer = QTimer()
        self._timer.timeout.connect(self.update)
        self._was_weekend: bool | None = None
        self._last = self.now()

    def start(self) -> None:
        self.update()
        self._timer.start(15_000)

    def stop(self) -> None:
        self._timer.stop()

    def items(self, now: datetime) -> list[tuple[str, float | None]]:
        """(name, seconds remaining) for each countdown; over the weekend, time until the week starts."""
        items: list[tuple[str, float | None]] = []
        if in_weekend(now, self.week_end, self.week_start):
            items.append(("Back to work", (next_weekly(now, *self.week_start) - now).total_seconds()))
        else:
            items.append((self.label, (next_weekly(now, *self.week_end) - now).total_seconds()))
        for name, at in self.events:
            if at > now:
                items.append((name, (at - now).total_seconds()))
        return items

    def update(self) -> None:
        now = self.now()
        weekend = in_weekend(now, self.week_end, self.week_start)
        if self._was_weekend is False and weekend:
            self.bus.publish(CountdownReached(self.label))
        self._was_weekend = weekend
        for name, at in self.events:
            if self._last < at <= now:
                self.bus.publish(CountdownReached(name))
        self._last = now
        self.bus.publish(CountdownsUpdated(tuple(self.items(now))))
