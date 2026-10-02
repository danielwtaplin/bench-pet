"""Pomodoro timer the pet manages: focus → coffee break, longer break every Nth round."""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QTimer

from benchpet.events import EventBus, PomodoroCommand, PomodoroPhaseEnded, PomodoroUpdated
from benchpet.sources.base import Source


class PomodoroSource(Source):
    name = "pomodoro"

    def __init__(self, bus: EventBus, config: dict, now: Callable[[], float] = time.monotonic):
        super().__init__(bus)
        self.now = now
        self.durations = {
            "focus": config.get("focus_minutes", 25) * 60,
            "break": config.get("break_minutes", 5) * 60,
            "long_break": config.get("long_break_minutes", 15) * 60,
        }
        self.rounds_before_long = config.get("rounds_before_long_break", 4)
        self.phase: str | None = None  # focus | break | long_break | None (stopped)
        self.round = 0
        self._ends = 0.0
        self._timer = QTimer()
        self._timer.timeout.connect(self.tick)
        bus.event.connect(self._on_event)

    def start(self) -> None:
        self._timer.start(10_000)

    def stop(self) -> None:
        self._timer.stop()

    def _on_event(self, event: object) -> None:
        if not isinstance(event, PomodoroCommand):
            return
        if event.action == "start":
            self.round = 1
            self._enter("focus")
        elif event.action == "stop" and self.phase:
            self.phase = None
            self._publish()
        elif event.action == "skip" and self.phase:
            self._finish_phase()

    def remaining(self) -> float:
        return max(self._ends - self.now(), 0.0) if self.phase else 0.0

    def tick(self) -> None:
        if self.phase and self.now() >= self._ends:
            self._finish_phase()
        elif self.phase:
            self._publish()

    def _finish_phase(self) -> None:
        ended = self.phase
        if ended == "focus":
            long = self.round % self.rounds_before_long == 0
            nxt = "long_break" if long else "break"
        else:
            self.round += 1
            nxt = "focus"
        self.bus.publish(PomodoroPhaseEnded(ended, nxt))
        self._enter(nxt)

    def _enter(self, phase: str) -> None:
        self.phase = phase
        self._ends = self.now() + self.durations[phase]
        self._publish()

    def _publish(self) -> None:
        self.bus.publish(PomodoroUpdated(self.phase, self.remaining(), self.round))
