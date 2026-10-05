"""The log console shown beside the pet: the tail of a file, like `tail -f` in a terminal.

A dark card, so it reads as a terminal next to the white calendar card. Lines don't
wrap: long ones are cut off with an ellipsis, as the newest lines matter most.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPainterPath
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from benchpet.calendar_view import beside
from benchpet.events import LogTailUpdated

CARD_WIDTH = 420
BACKGROUND = "#1b1e24"
INK = "#d4d7dd"
MUTED = "#8a909c"
NEW = "#ffffff"
LEVEL_COLOURS = {"error": "#ff6b6b", "warn": "#f2c14e"}
NEW_SECONDS = 4  # just-arrived lines stay brighter this long
ERROR = re.compile(r"\b(?:error|err|fatal|critical|crit|panic|exception|traceback|failed)\b", re.I)
WARN = re.compile(r"\b(?:warn|warning)\b", re.I)


def level(line: str) -> str:
    """error | warn | "" for colouring a line."""
    if ERROR.search(line):
        return "error"
    if WARN.search(line):
        return "warn"
    return ""


class LogLines(QWidget):
    """The lines themselves, newest at the bottom, in a monospace font."""

    def __init__(self):
        super().__init__()
        self.lines: tuple[str, ...] = ()
        self.fresh = 0  # how many of the last lines just arrived
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPixelSize(11)
        self.setFont(font)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_lines(self, lines: tuple[str, ...], fresh: int) -> None:
        self.lines = lines
        self.fresh = min(fresh, len(lines))
        self.setFixedHeight(max(1, len(lines)) * self.fontMetrics().lineSpacing() + 2)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        metrics = self.fontMetrics()
        step = metrics.lineSpacing()
        if not self.lines:
            p.setPen(QColor(MUTED))
            p.drawText(QRect(0, 0, self.width(), step), Qt.AlignLeft | Qt.AlignVCenter, "(empty)")
            return
        first_fresh = len(self.lines) - self.fresh
        for i, line in enumerate(self.lines):
            colour = LEVEL_COLOURS.get(level(line)) or (NEW if i >= first_fresh else INK)
            p.setPen(QColor(colour))
            text = metrics.elidedText(line, Qt.ElideRight, self.width())
            p.drawText(QRect(0, 1 + i * step, self.width(), step), Qt.AlignLeft | Qt.AlignVCenter, text)


class LogView(QWidget):
    """The dark card: the file's name, any problem following it, then its last lines."""

    hover_changed = Signal(bool)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(CARD_WIDTH)
        self.path = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 10)
        layout.setSpacing(4)
        self.title = QLabel()
        self.title.setStyleSheet(f"color: {INK}; font-weight: 600; font-size: 12px; background: transparent;")
        self.status = QLabel()
        self.status.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent;")
        self.body = LogLines()
        layout.addWidget(self.title)
        layout.addWidget(self.status)
        layout.addWidget(self.body)
        self._fade = QTimer(self, singleShot=True)
        self._fade.timeout.connect(lambda: self.body.set_lines(self.body.lines, 0))

    @property
    def has_file(self) -> bool:
        return bool(self.path)

    def set_tail(self, event: LogTailUpdated) -> None:
        self.path = event.path
        inner = CARD_WIDTH - 24
        name = f"▍ {Path(event.path).name}" if event.path else ""
        self.title.setText(self.title.fontMetrics().elidedText(name, Qt.ElideMiddle, inner))
        self.title.setToolTip(event.path)
        self.status.setText(self.status.fontMetrics().elidedText(event.error, Qt.ElideRight, inner))
        self.status.setVisible(bool(event.error))
        # Brighten what just arrived; a fresh file or a new path is all old news.
        fresh = event.appended + (self.body.fresh if self._fade.isActive() else 0)
        self.body.set_lines(event.lines, fresh)
        self.body.setVisible(bool(event.lines) or not event.error)
        if event.appended:
            self._fade.start(NEW_SECONDS * 1000)
        self.adjustSize()

    def place_beside(self, pose: QRect, screen: QRect, side: str = "auto", avoid: QRect | None = None) -> None:
        self.adjustSize()
        self.move(beside(pose, self.size(), screen, side, avoid))

    def sizeHint(self) -> QSize:
        return QSize(CARD_WIDTH, super().sizeHint().height())

    def enterEvent(self, _event) -> None:
        self.hover_changed.emit(True)

    def leaveEvent(self, _event) -> None:
        self.hover_changed.emit(False)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.fillPath(path, QColor(BACKGROUND))
        p.setPen(QColor(255, 255, 255, 30))
        p.drawPath(path)

