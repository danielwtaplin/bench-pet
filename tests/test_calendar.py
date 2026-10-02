from datetime import datetime, timedelta, timezone

from benchpet.sources.calendar import CalEvent, describe, due_reminders, upcoming

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:standup
SUMMARY:Standup
DTSTART:20260928T093000
DTEND:20260928T094500
RRULE:FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR
END:VEVENT
BEGIN:VEVENT
UID:review
SUMMARY:Design review
DTSTART:20261002T020000Z
DTEND:20261002T030000Z
END:VEVENT
BEGIN:VEVENT
UID:holiday
SUMMARY:Holiday
DTSTART;VALUE=DATE:20261005
DTEND;VALUE=DATE:20261006
END:VEVENT
BEGIN:VEVENT
UID:cancelled
SUMMARY:Cancelled thing
STATUS:CANCELLED
DTSTART:20261002T150000
DTEND:20261002T160000
END:VEVENT
END:VCALENDAR
"""


def local(*args):
    return datetime(*args).astimezone()


def test_upcoming_expands_recurrence_and_skips_cancelled():
    events = upcoming(ICS, local(2026, 10, 2), local(2026, 10, 6), "Work")
    names = [e.summary for e in events]
    assert "Cancelled thing" not in names
    # Standup on Fri 2nd and Mon 5th (not the weekend), plus the review and holiday.
    standups = [e for e in events if e.summary == "Standup"]
    assert [e.start.date().isoformat() for e in standups] == ["2026-10-02", "2026-10-05"]
    assert all(e.start.tzinfo is not None for e in events)
    holiday = next(e for e in events if e.summary == "Holiday")
    assert holiday.all_day
    review = next(e for e in events if e.summary == "Design review")
    assert review.start == datetime(2026, 10, 2, 2, 0, tzinfo=timezone.utc)
    assert events == sorted(events, key=lambda e: (e.start, e.summary))


def ev(summary, start, minutes=30, all_day=False):
    return CalEvent(summary, start, start + timedelta(minutes=minutes), all_day, "Work", summary)


def test_due_reminders_only_once_and_only_timed():
    now = local(2026, 10, 2, 13, 52)
    events = [ev("Soon", local(2026, 10, 2, 14, 0)), ev("Later", local(2026, 10, 2, 15, 0)),
              ev("Started", local(2026, 10, 2, 13, 50)),
              ev("All day", local(2026, 10, 2), 24 * 60, all_day=True)]
    done = set()
    due = due_reminders(events, now, timedelta(minutes=10), done)
    assert [e.summary for e in due] == ["Soon"]
    done.update(e.key for e in due)
    assert due_reminders(events, now, timedelta(minutes=10), done) == []


def test_describe():
    now = local(2026, 10, 2, 13, 35)
    assert describe(ev("Standup", local(2026, 10, 2, 14, 0)), now) == "14:00 Standup · in 25m"
    assert describe(ev("Sync", local(2026, 10, 2, 13, 30)), now) == "Now: Sync (until 14:00)"
    assert describe(ev("Plan", local(2026, 10, 3, 9, 0)), now) == "Tomorrow 09:00 Plan"
    assert describe(ev("Off", local(2026, 10, 2), 24 * 60, all_day=True), now) == "Today: Off"
