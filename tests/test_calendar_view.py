import os
from datetime import date, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from benchpet.calendar_view import (  # noqa: E402
    CalendarView, agenda, beside, clock, day_rows, lay_out_day, month_days, on_day, until)
from benchpet.sources.calendar import CalEvent  # noqa: E402

app = QApplication.instance() or QApplication([])
NOW = datetime(2026, 10, 2, 13, 35).astimezone()


def at(days, hour, minute=0):
    return NOW.replace(hour=0, minute=0) + timedelta(days=days, hours=hour, minutes=minute)


def ev(title, start, end, all_day=False, colour="#4c8bf5"):
    return CalEvent(title, start, end, all_day, "Work", title, colour)


EVENTS = sorted([
    ev("Coffee", at(0, 9), at(0, 9, 30)),
    ev("Standup", at(0, 14), at(0, 14, 15)),
    ev("Review", at(0, 14), at(0, 15)),
    ev("Lunch", at(0, 13), at(0, 14)),
    ev("Market", at(1, 0), at(3, 0), all_day=True),
    ev("Planning", at(3, 9), at(3, 10)),
], key=lambda e: e.start)


def test_formatting():
    assert clock(at(0, 14)) == "2pm" and clock(at(0, 16, 30)) == "4:30pm"
    assert until(25 * 60) == "in 25m" and until(90 * 60) == "in 1h 30m" and until(3600) == "in 1h"


def test_day_rows_mark_now_next_and_drop_past():
    rows = day_rows(EVENTS, NOW.date(), NOW)
    assert [(r.title, r.extra) for r in rows] == [("Lunch", "now"), ("Review", "in 25m"), ("Standup", "in 25m")]
    with_past = day_rows(EVENTS, NOW.date(), NOW, keep_past=True)
    assert with_past[0].title == "Coffee" and with_past[0].state == "past"


def test_agenda_groups_days_and_spans_multi_day_events():
    days = agenda(EVENTS, NOW, 4)
    assert [heading for heading, _ in days] == ["Today · Fri 2 Oct", "Tomorrow · Sat 3 Oct",
                                                 "Sun 4 Oct", "Mon 5 Oct"]
    assert days[1][1][0].time == "All day" and days[2][1][0].title == "Market"
    assert len(agenda(EVENTS, NOW, 1)) == 1


def test_on_day_end_is_exclusive():
    market = next(e for e in EVENTS if e.summary == "Market")
    assert on_day(market, date(2026, 10, 4)) and not on_day(market, date(2026, 10, 5))


def test_overlapping_events_share_the_lane():
    placed = {e.summary: (col, cols) for e, col, cols in lay_out_day(EVENTS, NOW.date())}
    assert placed["Coffee"] == (0, 1)
    assert placed["Standup"][1] == placed["Review"][1] == 2
    assert {placed["Standup"][0], placed["Review"][0]} == {0, 1}


def test_month_days_are_monday_first_weeks():
    cells = month_days(2026, 10)
    assert len(cells) % 7 == 0
    assert cells[:3] == [None, None, None] and cells[3] == date(2026, 10, 1)  # 1 Oct 2026 is a Thursday


def test_view_states_and_placement():
    view = CalendarView(now=lambda: NOW)
    for layout in ("agenda", "timeline", "month"):
        view.configure(layout, 3)
        view.set_events(EVENTS, has_feeds=True)
        assert view.sizeHint().height() > 40
    screen = QRect(0, 0, 1920, 1080)
    view.place_beside(QRect(1000, 600, 120, 240), screen)
    # QRect.right()/bottom() are the last pixel: right of the pet with a 10px gap, level with its feet.
    assert view.x() == 1129 and view.y() + view.height() == 839
    view.place_beside(QRect(1800, 600, 100, 240), screen)
    assert view.x() + view.width() <= 1800  # no room on the right: goes left
    view.place_beside(QRect(1000, 600, 120, 240), screen, side="left")
    assert view.x() + view.width() == 990


def test_a_second_card_goes_the_other_side_or_on_top():
    screen = QRect(0, 0, 1920, 1080)
    pose, size = QRect(1000, 600, 120, 240), QSize(280, 200)
    calendar = QRect(beside(pose, size, screen), size)
    assert calendar.x() == 1129
    log = beside(pose, QSize(420, 150), screen, avoid=calendar)
    assert log.x() + 420 == 990  # left of the pet
    cramped = QRect(0, 0, 1540, 1080)  # no room for the log on the right; calendar went left
    calendar = QRect(beside(pose, size, cramped, "left"), size)
    log = beside(pose, QSize(420, 150), QRect(400, 0, 1140, 1080), avoid=calendar)
    assert log.y() + 150 + 10 == calendar.y()  # neither side free: stacked on top
