"""The calendar card shown beside the pet: an agenda, today's timeline, or a month.

A white card, unlike the dark info bubble, so it reads as its own thing. The
data shaping (which events land on which day, what's next) is plain functions;
the widgets only lay them out.
"""

from __future__ import annotations

import calendar as pycal
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

CARD_WIDTH = 280
INK = "#1f2330"
MUTED = "#6b7080"
ACCENT = "#2f6fec"
NOW_RED = "#e53935"
GRID = "#e6e8ee"
LAYOUTS = {"agenda": "Agenda", "timeline": "Today timeline", "month": "Month"}

STYLE = f"""
QLabel {{ color: {INK}; font-size: 12px; background: transparent; }}
QLabel[role="day"] {{ font-weight: 600; font-size: 12px; color: {INK}; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="extra"] {{ color: {ACCENT}; font-weight: 600; }}
QLabel[role="heading"] {{ font-weight: 700; font-size: 13px; }}
"""


# --- data shaping ----------------------------------------------------------

@dataclass(frozen=True)
class Row:
    colour: str
    time: str  # "2:00pm" | "All day"
    title: str
    extra: str = ""  # "in 25m" | "now"
    state: str = ""  # now | next | past | ""


def start_of(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time()).astimezone()


def on_day(ev, d: date) -> bool:
    """Whether the event overlaps local day `d` (multi-day events land on each day)."""
    day_start = start_of(d)
    day_end = start_of(d + timedelta(days=1))
    if ev.end <= ev.start:  # zero-length: a point in time
        return day_start <= ev.start < day_end
    return ev.start < day_end and ev.end > day_start


def clock(t: datetime) -> str:
    return t.strftime("%-I:%M%p").lower().replace(":00", "")


def until(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"in {minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"in {hours}h" + (f" {minutes}m" if minutes else "")


def day_label(d: date, today: date) -> str:
    if d == today:
        return f"Today · {d:%a} {d.day} {d:%b}"
    if d == today + timedelta(days=1):
        return f"Tomorrow · {d:%a} {d.day} {d:%b}"
    return f"{d:%a} {d.day} {d:%b}"


def next_event(events, now: datetime):
    return next((ev for ev in events if not ev.all_day and ev.start > now), None)


def day_rows(events, d: date, now: datetime, keep_past: bool = False) -> list[Row]:
    """One day's rows: all-day events first, then timed ones in order."""
    upcoming = next_event(events, now)
    next_start = upcoming.start if upcoming else None  # events starting together are all "next"
    todays = [ev for ev in events if on_day(ev, d)]
    rows = []
    for ev in sorted(todays, key=lambda ev: (not ev.all_day, ev.start, ev.summary)):
        if ev.all_day:
            rows.append(Row(ev.colour, "All day", ev.summary))
            continue
        ended = ev.end <= now if ev.end > ev.start else ev.start <= now
        if ended:
            if keep_past:
                rows.append(Row(ev.colour, clock(ev.start), ev.summary, state="past"))
            continue
        if ev.start <= now < ev.end:
            rows.append(Row(ev.colour, clock(ev.start), ev.summary, "now", "now"))
        elif ev.start == next_start and (ev.start - now).total_seconds() < 12 * 3600:
            rows.append(Row(ev.colour, clock(ev.start), ev.summary,
                            until((ev.start - now).total_seconds()), "next"))
        else:
            rows.append(Row(ev.colour, clock(ev.start), ev.summary))
    return rows


def agenda(events, now: datetime, days: int) -> list[tuple[str, list[Row]]]:
    """(day heading, rows) for each of the next `days` days that has something on."""
    today = now.date()
    out = []
    for i in range(days):
        d = today + timedelta(days=i)
        rows = day_rows(events, d, now)
        if rows:
            out.append((day_label(d, today), rows))
    return out


def lay_out_day(events, d: date) -> list[tuple[object, int, int]]:
    """Timed events of day `d` as (event, column, columns) so overlaps sit side by side."""
    timed = sorted((ev for ev in events if not ev.all_day and on_day(ev, d)), key=lambda ev: ev.start)
    placed, group, group_end = [], [], None
    for ev in timed:
        if group and ev.start >= group_end:
            placed += _columns(group)
            group = []
        group.append(ev)
        group_end = ev.end if group_end is None or len(group) == 1 else max(group_end, ev.end)
    return placed + _columns(group)


def _columns(group: list) -> list[tuple[object, int, int]]:
    ends: list[datetime] = []
    cols = []
    for ev in group:
        col = next((i for i, end in enumerate(ends) if end <= ev.start), None)
        if col is None:
            col = len(ends)
            ends.append(ev.end)
        else:
            ends[col] = ev.end
        cols.append((ev, col))
    return [(ev, col, len(ends)) for ev, col in cols]


def month_days(year: int, month: int) -> list[date | None]:
    """The month's days in Monday-first weeks, padded with None."""
    cells = [None] * pycal.monthrange(year, month)[0]
    cells += [date(year, month, d) for d in range(1, pycal.monthrange(year, month)[1] + 1)]
    return cells + [None] * (-len(cells) % 7)


def beside(pose: QRect, size: QSize, screen: QRect, side: str = "auto", avoid: QRect | None = None) -> QPoint:
    """Top-left for a card next to the pet's pose (global coords), bottom-aligned with its feet.

    `side` is auto | left | right; auto takes the right if there's room. A card already
    beside the pet (`avoid`) pushes this one to the other side, or on top of it when
    that side is off screen. Always kept on screen.
    """
    gap = 10
    right_x = pose.right() + gap
    left_x = pose.left() - gap - size.width()
    fits_right = right_x + size.width() <= screen.right()
    fits_left = left_x >= screen.left()
    if side == "left" or (side == "auto" and not fits_right):
        x = left_x if fits_left or side == "left" else right_x
    else:
        x = right_x
    y = pose.bottom() - size.height()
    if avoid is not None and QRect(QPoint(x, y), size).intersects(avoid):
        other = right_x if x == left_x else left_x
        if side == "auto" and (fits_right if other == right_x else fits_left):
            x = other
        else:
            y = avoid.top() - gap - size.height()
    x = max(screen.left(), min(screen.right() - size.width(), x))
    y = max(screen.top(), min(screen.bottom() - size.height(), y))
    return QPoint(x, y)


# --- widgets ---------------------------------------------------------------

def label(text: str, role: str = "", width: int | None = None) -> QLabel:
    lab = QLabel()
    if role:
        lab.setProperty("role", role)
    lab.setStyleSheet(STYLE)
    lab.ensurePolished()
    if width:
        text = lab.fontMetrics().elidedText(text, Qt.ElideRight, width)
        lab.setFixedWidth(width)
    lab.setText(text)
    return lab


class Dot(QWidget):
    def __init__(self, colour: str, hollow: bool = False):
        super().__init__()
        self.colour = QColor(colour or ACCENT)
        self.hollow = hollow
        self.setFixedSize(10, 10)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.hollow:
            p.setPen(QPen(self.colour, 1.6))
            p.setBrush(Qt.NoBrush)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(self.colour)
        p.drawEllipse(QRectF(1.5, 1.5, 7, 7))


def row_widget(row: Row) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 1, 0, 1)
    h.setSpacing(6)
    h.addWidget(Dot(row.colour, hollow=row.time == "All day"), 0, Qt.AlignVCenter)
    h.addWidget(label(row.time, "muted", 52))
    extra_w = 0
    extra = None
    if row.extra:
        extra = label(row.extra, "extra")
        extra_w = extra.fontMetrics().horizontalAdvance(row.extra) + 6
    title = label(row.title, "muted" if row.state == "past" else "", CARD_WIDTH - 28 - 10 - 52 - 12 - extra_w)
    if row.state == "now":
        f = title.font()
        f.setWeight(QFont.DemiBold)
        title.setFont(f)
    h.addWidget(title, 1)
    if extra:
        h.addWidget(extra)
    return w


class Timeline(QWidget):
    """Today's hours with event blocks and a line at the current time."""

    HOUR_PX = 26
    GUTTER = 38

    def __init__(self, events, now: datetime):
        super().__init__()
        self.now = now
        self.placed = lay_out_day(events, now.date())
        starts = [ev.start.hour for ev, _, _ in self.placed if ev.start.date() == now.date()]
        ends = [ev.end.hour + (ev.end.minute > 0) for ev, _, _ in self.placed if ev.end.date() == now.date()]
        self.first = max(0, min([8, now.hour] + starts))
        self.last = min(24, max([18, now.hour + 1] + ends))
        self.setFixedHeight((self.last - self.first) * self.HOUR_PX + 8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def y_of(self, t: datetime) -> float:
        day = start_of(self.now.date())
        hours = (t - day).total_seconds() / 3600
        return 4 + (min(max(hours, self.first), self.last) - self.first) * self.HOUR_PX

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        small = QFont(self.font())
        small.setPixelSize(10)
        p.setFont(small)
        width = self.width()
        for hour in range(self.first, self.last + 1):
            y = 4 + (hour - self.first) * self.HOUR_PX
            p.setPen(QColor(GRID))
            p.drawLine(self.GUTTER, y, width, y)
            if hour < self.last:
                p.setPen(QColor(MUTED))
                text = datetime(2000, 1, 1, hour % 24).strftime("%-I%p").lower()
                p.drawText(QRect(0, y - 6, self.GUTTER - 6, 12), Qt.AlignRight | Qt.AlignVCenter, text)
        body = QFont(self.font())
        body.setPixelSize(11)
        p.setFont(body)
        lane = width - self.GUTTER - 2
        for ev, col, cols in self.placed:
            top, bottom = self.y_of(ev.start), self.y_of(ev.end)
            rect = QRectF(self.GUTTER + 2 + col * lane / cols, top + 1,
                          lane / cols - 3, max(bottom - top - 2, 14))
            colour = QColor(ev.colour or ACCENT)
            fill = QColor(colour)
            fill.setAlpha(46 if ev.end > self.now else 22)
            path = QPainterPath()
            path.addRoundedRect(rect, 4, 4)
            p.fillPath(path, fill)
            p.fillRect(QRectF(rect.x(), rect.y(), 3, rect.height()), colour)
            p.setPen(QColor(INK if ev.end > self.now else MUTED))
            text = p.fontMetrics().elidedText(ev.summary, Qt.ElideRight, int(rect.width()) - 9)
            p.drawText(rect.adjusted(6, 1, -3, 0), Qt.AlignLeft | Qt.AlignTop, text)
        if self.first <= self.now.hour < self.last:
            y = self.y_of(self.now)
            red = QColor(NOW_RED)
            p.setPen(QPen(red, 1.5))
            p.drawLine(self.GUTTER, y, width, y)
            p.setPen(Qt.NoPen)
            p.setBrush(red)
            p.drawEllipse(QRectF(self.GUTTER - 4, y - 4, 8, 8))


class MonthGrid(QWidget):
    """A month of days; dots mark days with events. Click a day to list it below."""

    CELL_H = 30
    day_clicked = Signal(object)

    def __init__(self, events, now: datetime, selected: date):
        super().__init__()
        self.today = now.date()
        self.selected = selected
        self.days = month_days(self.today.year, self.today.month)
        self.colours: dict[date, list[str]] = {}
        for d in self.days:
            if d:
                found = [ev.colour or ACCENT for ev in events if on_day(ev, d)]
                self.colours[d] = list(dict.fromkeys(found))[:3]
        self.setFixedHeight(18 + self.CELL_H * (len(self.days) // 7))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _cell(self, i: int) -> QRectF:
        w = self.width() / 7
        return QRectF((i % 7) * w, 18 + (i // 7) * self.CELL_H, w, self.CELL_H)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        small = QFont(self.font())
        small.setPixelSize(10)
        p.setFont(small)
        p.setPen(QColor(MUTED))
        w = self.width() / 7
        for i, name in enumerate("MTWTFSS"):
            p.drawText(QRectF(i * w, 0, w, 16), Qt.AlignCenter, name)
        body = QFont(self.font())
        body.setPixelSize(12)
        p.setFont(body)
        for i, d in enumerate(self.days):
            if d is None:
                continue
            cell = self._cell(i)
            circle = QRectF(cell.center().x() - 11, cell.y() + 2, 22, 20)
            if d == self.selected:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(ACCENT))
                p.drawRoundedRect(circle, 10, 10)
                p.setPen(QColor("white"))
            elif d == self.today:
                p.setPen(QPen(QColor(ACCENT), 1.4))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(circle, 10, 10)
                p.setPen(QColor(ACCENT))
            else:
                p.setPen(QColor(MUTED if d < self.today else INK))
            p.drawText(circle, Qt.AlignCenter, str(d.day))
            dots = self.colours.get(d, [])
            x = cell.center().x() - (len(dots) * 5 - 1) / 2
            p.setPen(Qt.NoPen)
            for colour in dots:
                p.setBrush(QColor(colour))
                p.drawEllipse(QRectF(x, cell.y() + 24, 4, 4))
                x += 5

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        for i, d in enumerate(self.days):
            if d and self._cell(i).contains(pos):
                self.day_clicked.emit(d)
                return


class CalendarView(QWidget):
    """The white card. Rebuilds its contents when events, layout or the minute change."""

    hover_changed = Signal(bool)

    def __init__(self, now: Callable[[], datetime] = None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.now = now or (lambda: datetime.now().astimezone())
        self.events: tuple = ()
        self.layout_name = "agenda"
        self.agenda_days = 4
        self.has_feeds = False
        self.selected: date | None = None  # month view's chosen day
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(3)
        self.setFixedWidth(CARD_WIDTH)
        self._minute = QTimer(self)
        self._minute.timeout.connect(self._on_minute)
        self._minute.start(60_000)
        self.rebuild()

    def configure(self, layout: str, agenda_days: int) -> None:
        self.layout_name = layout if layout in LAYOUTS else "agenda"
        self.agenda_days = max(1, int(agenda_days))
        self.rebuild()

    def set_events(self, events, has_feeds: bool) -> None:
        self.events = tuple(events)
        self.has_feeds = has_feeds
        self.rebuild()

    def _on_minute(self) -> None:
        if self.isVisible():
            self.rebuild()

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def rebuild(self) -> None:
        self._clear()
        now = self.now()
        if not self.has_feeds:
            self._layout.addWidget(label("📅  No calendars yet", "heading"))
            self._layout.addWidget(label("Add one in Settings → Calendar.", "muted"))
        elif self.layout_name == "timeline":
            self._build_timeline(now)
        elif self.layout_name == "month":
            self._build_month(now)
        else:
            self._build_agenda(now)
        self.adjustSize()

    def _build_agenda(self, now: datetime) -> None:
        days = agenda(self.events, now, self.agenda_days)
        if not days:
            self._layout.addWidget(label("Nothing on", "heading"))
            span = "today" if self.agenda_days == 1 else f"the next {self.agenda_days} days"
            self._layout.addWidget(label(f"Your calendar is clear for {span}.", "muted"))
        for i, (heading, rows) in enumerate(days):
            if i:
                self._layout.addSpacing(6)
            self._layout.addWidget(label(heading, "day"))
            for row in rows:
                self._layout.addWidget(row_widget(row))

    def _build_timeline(self, now: datetime) -> None:
        today = now.date()
        self._layout.addWidget(label(day_label(today, today), "day"))
        for ev in self.events:
            if ev.all_day and on_day(ev, today):
                self._layout.addWidget(row_widget(Row(ev.colour, "All day", ev.summary)))
        self._layout.addSpacing(2)
        self._layout.addWidget(Timeline(self.events, now))
        later = next((ev for ev in self.events if not ev.all_day and ev.start >= start_of(today + timedelta(days=1))),
                     None)
        if later:
            self._layout.addSpacing(4)
            when = f"{day_label(later.start.date(), today).split(' · ')[0]} {clock(later.start)}"
            self._layout.addWidget(label(f"Next: {when}  {later.summary}", "muted", CARD_WIDTH - 28))

    def _build_month(self, now: datetime) -> None:
        today = now.date()
        if self.selected is None or (self.selected.year, self.selected.month) != (today.year, today.month):
            self.selected = today
        self._layout.addWidget(label(f"{today:%B %Y}", "heading"))
        grid = MonthGrid(self.events, now, self.selected)
        grid.day_clicked.connect(self._select_day)
        self._layout.addWidget(grid)
        self._layout.addSpacing(4)
        self._layout.addWidget(label(day_label(self.selected, today), "day"))
        rows = day_rows(self.events, self.selected, now, keep_past=True)
        for row in rows or [Row("", "", "Nothing on", state="past")]:
            self._layout.addWidget(row_widget(row) if row.time else label(row.title, "muted"))

    def _select_day(self, d: date) -> None:
        self.selected = d
        self.rebuild()

    def place_beside(self, pose: QRect, screen: QRect, side: str = "auto") -> None:
        self.adjustSize()
        self.move(beside(pose, self.size(), screen, side))

    def enterEvent(self, _event) -> None:
        self.hover_changed.emit(True)

    def leaveEvent(self, _event) -> None:
        self.hover_changed.emit(False)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.fillPath(path, QColor("white"))
        p.setPen(QColor(0, 0, 0, 40))
        p.drawPath(path)


class CalendarButton(QWidget):
    """Small round calendar badge below the pet; click to open or close the card."""

    clicked = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Calendar")
        self.active = False

    def set_active(self, active: bool) -> None:
        self.active = active
        self.update()

    def place_below(self, pose: QRect, screen: QRect) -> None:
        x = pose.center().x() - self.width() // 2
        y = pose.bottom() + 6
        if y + self.height() > screen.bottom():  # no room under the feet: sit beside them
            x = pose.right() + 6
            y = pose.bottom() - self.height()
        self.move(QPoint(max(screen.left(), min(screen.right() - self.width(), x)),
                         max(screen.top(), min(screen.bottom() - self.height(), y))))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(0, 0, 0, 50), 1))
        p.setBrush(QColor(ACCENT) if self.active else QColor("white"))
        p.drawEllipse(rect)
        # A little calendar page: header band, rings, a dot for "today".
        ink = QColor("white") if self.active else QColor(INK)
        page = QRectF(9, 10, 14, 12)
        p.setPen(QPen(ink, 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(page, 2, 2)
        p.drawLine(int(page.left()), 14, int(page.right()), 14)
        p.drawLine(12, 8, 12, 11)
        p.drawLine(20, 8, 20, 11)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(NOW_RED) if not self.active else QColor("white"))
        p.drawEllipse(QRectF(17, 16.5, 3.5, 3.5))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
