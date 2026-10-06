"""Typed events published by data sources. Sources know nothing about sprites."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class MusicChanged:
    player: str  # MPRIS bus name, e.g. org.mpris.MediaPlayer2.spotify
    status: str  # Playing | Paused | Stopped
    title: str = ""
    artist: str = ""
    album: str = ""
    art_url: str = ""  # mpris:artUrl, file:// or http(s)://; empty when the player has none

    @property
    def playing(self) -> bool:
        return self.status == "Playing"


@dataclass(frozen=True)
class MusicGenre:
    title: str  # the track this is for, matched against the latest MusicChanged
    artist: str
    genres: tuple[str, ...]  # most-voted first; empty when MusicBrainz has none


class EventBus(QObject):
    event = Signal(object)

    def publish(self, event: object) -> None:
        self.event.emit(event)


@dataclass(frozen=True)
class AwayChanged:
    level: str  # present | short | long


@dataclass(frozen=True)
class NotificationReceived:
    app: str
    summary: str
    body: str  # plain text, markup stripped
    kind: str  # email | message | other


@dataclass(frozen=True)
class CountdownsUpdated:
    items: tuple[tuple[str, float | None], ...]  # (name, seconds left); None → happening now


@dataclass(frozen=True)
class CountdownReached:
    name: str


@dataclass(frozen=True)
class TaskEvent:
    kind: str  # working | done | failed | celebrate | clear
    message: str = ""


@dataclass(frozen=True)
class CalendarUpdated:
    events: tuple  # CalEvents from the start of this month to a few weeks ahead, sorted by start


@dataclass(frozen=True)
class CalendarReminder:
    event: object  # CalEvent starting soon


@dataclass(frozen=True)
class WeatherUpdated:
    condition: str  # sunny | clear_night | cloudy | rain | drizzle | windy | windy_rain | storm | snow | hot | cold
    temperature: float  # °C
    description: str


@dataclass(frozen=True)
class PomodoroCommand:
    action: str  # start | stop | skip


@dataclass(frozen=True)
class PomodoroUpdated:
    phase: str | None  # focus | break | long_break | None when stopped
    remaining: float  # seconds
    round: int


@dataclass(frozen=True)
class PomodoroPhaseEnded:
    ended: str
    next: str


@dataclass(frozen=True)
class AgentResponse:
    agent: str  # claude | codex | ...
    text: str
    project: str = ""
    pids: tuple[int, ...] = ()  # the hook's ancestor processes, to find its terminal


@dataclass(frozen=True)
class MediaCommand:
    action: str  # play_pause | next | previous


@dataclass(frozen=True)
class InputChanged:
    active: bool  # keyboard/mouse used within the last activity.input_idle_seconds


@dataclass(frozen=True)
class FocusChanged:
    app: str  # window class of the active window, e.g. org.kde.konsole


@dataclass(frozen=True)
class ComputerActivity:
    mode: str  # idle | coding | browsing
    tier: str  # fresh | tired | exhausted (how long since the last break)
    session_minutes: float


@dataclass(frozen=True)
class PlanUsage:
    agent: str  # claude | codex
    windows: tuple  # usage.Window: name (5h | week), used percent, resets_at
    received_at: float | None = None  # epoch seconds, when restored from an earlier report


@dataclass(frozen=True)
class TokenUsage:
    totals: object  # usage.DayTotals for today


@dataclass(frozen=True)
class LogTailUpdated:
    path: str  # the followed file; "" when none is set
    lines: tuple[str, ...]  # its last log_tail.lines lines
    appended: int  # new lines since the last update (0 for what was already in the file)
    error: str = ""  # e.g. "Waiting for app.log…" while it doesn't exist
