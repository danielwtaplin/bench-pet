from datetime import datetime, time

from benchpet.events import CountdownReached, CountdownsUpdated
from benchpet.sources.countdown import (
    CountdownSource, format_remaining, in_weekend, next_weekly, parse_weekly)

END = parse_weekly({"day": "friday", "time": "17:00"})
START = parse_weekly({"day": "Monday", "time": "09:00"})
# 2026-10-02 is a Friday.
FRI_NOON = datetime(2026, 10, 2, 12, 0)


def test_next_weekly_same_day_and_rollover():
    assert next_weekly(FRI_NOON, *END) == datetime(2026, 10, 2, 17, 0)
    assert next_weekly(datetime(2026, 10, 2, 17, 0), *END) == datetime(2026, 10, 9, 17, 0)
    assert next_weekly(FRI_NOON, 0, time(9)) == datetime(2026, 10, 5, 9, 0)


def test_in_weekend():
    assert not in_weekend(FRI_NOON, END, START)
    assert in_weekend(datetime(2026, 10, 2, 18, 0), END, START)
    assert in_weekend(datetime(2026, 10, 4, 12, 0), END, START)  # Sunday
    assert not in_weekend(datetime(2026, 10, 5, 9, 30), END, START)


def test_format_remaining():
    assert format_remaining(2 * 86400 + 5 * 3600 + 120) == "2d 5h"
    assert format_remaining(3 * 3600 + 25 * 60) == "3h 25m"
    assert format_remaining(59 * 60) == "59m"
    assert format_remaining(20) == "under a minute"


class Bus:
    def __init__(self):
        self.events = []

    def publish(self, e):
        self.events.append(e)


def make_source(now_ref):
    config = {"week_end": {"day": "friday", "time": "17:00"},
              "week_start": {"day": "monday", "time": "09:00"},
              "events": [{"name": "Demo", "at": "2026-10-02 15:00"}]}
    return CountdownSource(Bus(), config, now=lambda: now_ref[0])


def test_source_items_and_reached_events():
    now = [FRI_NOON]
    source = make_source(now)
    source.update()
    updated = [e for e in source.bus.events if isinstance(e, CountdownsUpdated)][-1]
    assert updated.items == (("Weekend", 5 * 3600), ("Demo", 3 * 3600))

    now[0] = datetime(2026, 10, 2, 15, 0, 10)
    source.update()
    assert CountdownReached("Demo") in source.bus.events

    now[0] = datetime(2026, 10, 2, 17, 0, 5)
    source.update()
    assert CountdownReached("Weekend") in source.bus.events
    assert source.bus.events[-1].items == (("Weekend", None),)


def test_starting_during_weekend_doesnt_celebrate():
    now = [datetime(2026, 10, 3, 12, 0)]
    source = make_source(now)
    source.update()
    assert not any(isinstance(e, CountdownReached) for e in source.bus.events)
