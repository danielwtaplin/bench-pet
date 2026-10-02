from __future__ import annotations

from benchpet.events import EventBus


class Source:
    """A data source: watches something and publishes events onto the bus."""

    name = "source"

    def __init__(self, bus: EventBus):
        self.bus = bus

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        pass
