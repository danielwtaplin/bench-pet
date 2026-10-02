"""Calendar source: upcoming events from ICS feeds or files.

Google Calendar and Outlook both publish a private "secret address in iCal
format", so one mechanism covers both without OAuth. Feeds are fetched and
expanded (recurrences included) on a worker thread; results come back to the
GUI thread via a Qt signal.
"""

from __future__ import annotations

import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import icalendar
import recurring_ical_events
from PySide6.QtCore import QObject, QTimer, Signal

from benchpet.events import CalendarReminder, CalendarUpdated, EventBus
from benchpet.sources.base import Source

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalEvent:
    summary: str
    start: datetime  # timezone-aware, local
    end: datetime
    all_day: bool
    calendar: str
    uid: str = ""

    @property
    def key(self) -> str:
        return f"{self.calendar}:{self.uid}:{self.start.isoformat()}"


def _as_local(value) -> tuple[datetime, bool]:
    """(local aware datetime, is_all_day). Floating (naive) times are taken as local."""
    if isinstance(value, datetime):
        return value.astimezone(), False
    # A date: all-day event, midnight local time.
    return datetime.combine(value, datetime.min.time()).astimezone(), True


def upcoming(ics: bytes, start: datetime, end: datetime, calendar: str) -> list[CalEvent]:
    """Events overlapping [start, end), recurrences expanded, sorted by start."""
    cal = icalendar.Calendar.from_ical(ics)
    events = []
    for comp in recurring_ical_events.of(cal).between(start, end):
        if str(comp.get("STATUS", "")).upper() == "CANCELLED":
            continue
        dtstart = comp.get("DTSTART")
        if dtstart is None:
            continue
        s, all_day = _as_local(dtstart.dt)
        dtend = comp.get("DTEND")
        if dtend is not None:
            e, _ = _as_local(dtend.dt)
        else:
            e = s + (timedelta(days=1) if all_day else timedelta(0))
        events.append(CalEvent(str(comp.get("SUMMARY", "(no title)")), s, e, all_day,
                               calendar, str(comp.get("UID", ""))))
    return sorted(events, key=lambda ev: (ev.start, ev.summary))


def due_reminders(events, now: datetime, remind: timedelta, done: set[str]) -> list[CalEvent]:
    """Timed events starting within `remind` that haven't been reminded yet."""
    return [ev for ev in events
            if not ev.all_day and ev.key not in done and now < ev.start <= now + remind]


def describe(ev: CalEvent, now: datetime) -> str:
    """Short bubble text, e.g. '14:00 Standup · in 25m'."""
    from benchpet.sources.countdown import format_remaining

    today = now.date()
    if ev.all_day:
        day = "Today" if ev.start.date() <= today else _day_name(ev.start.date(), today)
        return f"{day}: {ev.summary}"
    if ev.start <= now < ev.end:
        return f"Now: {ev.summary} (until {ev.end:%H:%M})"
    when = f"{ev.start:%H:%M}" if ev.start.date() == today else \
        f"{_day_name(ev.start.date(), today)} {ev.start:%H:%M}"
    text = f"{when} {ev.summary}"
    left = (ev.start - now).total_seconds()
    if left < 6 * 3600:
        text += f" · in {format_remaining(left)}"
    return text


def _day_name(d: date, today: date) -> str:
    return "Tomorrow" if d == today + timedelta(days=1) else f"{d:%a}"


def fetch(source: str, timeout: float = 20) -> bytes:
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": "bench-pet"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    if source.startswith("webcal://"):
        return fetch("https://" + source.removeprefix("webcal://"), timeout)
    return Path(source.removeprefix("file://")).expanduser().read_bytes()


class _Relay(QObject):
    loaded = Signal(object)  # list[CalEvent]


class CalendarSource(Source):
    name = "calendar"

    def __init__(self, bus: EventBus, config: dict, now: Callable[[], datetime] = None):
        super().__init__(bus)
        self.feeds = [(f.get("name", "Calendar"), f["url"]) for f in config.get("feeds", [])]
        self.refresh = config.get("refresh_minutes", 15) * 60_000
        self.lookahead = timedelta(hours=config.get("lookahead_hours", 36))
        self.remind = timedelta(minutes=config.get("remind_minutes", 10))
        self.now = now or (lambda: datetime.now().astimezone())
        self.events: list[CalEvent] = []
        self._reminded: set[str] = set()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="calendar")
        self._relay = _Relay()
        self._relay.loaded.connect(self._on_loaded)
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self.reload)
        self._tick_timer = QTimer()
        self._tick_timer.timeout.connect(self.tick)

    def start(self) -> None:
        if not self.feeds:
            log.info("calendar: no feeds configured (calendar.feeds in config.yaml)")
            return
        self.reload()
        self._refresh_timer.start(self.refresh)
        self._tick_timer.start(30_000)

    def stop(self) -> None:
        self._refresh_timer.stop()
        self._tick_timer.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def reload(self) -> None:
        self._pool.submit(self._load)

    def _load(self) -> None:  # worker thread
        now = self.now()
        start = datetime.combine(now.date(), datetime.min.time()).astimezone()
        events = []
        for name, url in self.feeds:
            try:
                events += upcoming(fetch(url), start, now + self.lookahead, name)
            except Exception as e:  # one bad feed shouldn't hide the others
                log.warning("calendar: %s: %s", name, e)
        events.sort(key=lambda ev: (ev.start, ev.summary))
        self._relay.loaded.emit(events)

    def _on_loaded(self, events: list[CalEvent]) -> None:
        self.events = events
        self.tick()

    def tick(self) -> None:
        now = self.now()
        for ev in due_reminders(self.events, now, self.remind, self._reminded):
            self._reminded.add(ev.key)
            self.bus.publish(CalendarReminder(ev))
        current = tuple(ev for ev in self.events if ev.end > now)
        self.bus.publish(CalendarUpdated(current))
