"""Today's Claude Code token usage, rescanned from the session logs every minute."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer

from benchpet.events import EventBus, TokenUsage
from benchpet.sources.base import Source
from benchpet.usage import TranscriptScanner

log = logging.getLogger(__name__)


class UsageSource(Source):
    name = "usage"

    def __init__(self, bus: EventBus, config: dict):
        super().__init__(bus)
        self.scanner = TranscriptScanner(Path(config["claude_logs"]).expanduser())
        self._last = None
        self._timer = QTimer()
        self._timer.timeout.connect(self.tick)

    def start(self) -> None:
        self.tick()
        self._timer.start(60_000)

    def stop(self) -> None:
        self._timer.stop()

    def tick(self) -> None:
        try:
            totals = self.scanner.scan()
        except Exception:
            log.exception("usage: couldn't read the Claude Code logs")
            return
        key = (totals.day, totals.tokens)
        if key != self._last:
            self._last = key
            self.bus.publish(TokenUsage(totals))
