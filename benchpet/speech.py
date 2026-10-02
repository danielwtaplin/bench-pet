"""Comic-style speech bubble for things the pet "says" (e.g. an AI agent's reply)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

TAIL = 14  # px height of the tail under the bubble
STYLE = """
QLabel { color: #1d1d24; font-size: 12px; }
QLabel[role="header"] { font-weight: 600; font-size: 13px; }
QLabel[role="hint"] { color: #7a7a86; font-size: 10px; }
"""


class SpeechBubble(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10 + TAIL)
        layout.setSpacing(4)
        self.header = QLabel()
        self.header.setProperty("role", "header")
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.PlainText)
        self.body.setFixedWidth(320)
        self.hint = QLabel("click to open the terminal · right-click to dismiss")
        self.hint.setProperty("role", "hint")
        for w in (self.header, self.body, self.hint):
            layout.addWidget(w)
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self.dismiss)
        self._remaining_ms = 0
        self.tail_x = 0.5  # tail position as a fraction of the width
        self.on_click: Callable[[], None] = lambda: None
        self.on_dismiss: Callable[[], None] = lambda: None

    def say(self, header: str, text: str, seconds: float, can_open: bool) -> None:
        self.header.setText(header)
        self.body.setText(text)
        self.hint.setText("click to open the terminal · right-click to dismiss" if can_open
                          else "click to dismiss")
        self.adjustSize()
        self._remaining_ms = int(seconds * 1000)
        self._timer.start(self._remaining_ms)

    def place(self, head: QPoint, screen_rect) -> None:
        """Position so the tail points at `head` (global), kept on screen."""
        x = head.x() - self.width() // 2
        x = max(screen_rect.left() + 4, min(screen_rect.right() - self.width() - 4, x))
        y = max(screen_rect.top() + 4, head.y() - self.height())
        self.tail_x = min(max((head.x() - x) / self.width(), 0.15), 0.85)
        self.move(x, y)
        self.update()

    def dismiss(self) -> None:
        if self.isVisible():
            self._timer.stop()
            self.hide()
            self.on_dismiss()

    # Hovering pauses the auto-dismiss so a long reply can be read.
    def enterEvent(self, _event) -> None:
        if self._timer.isActive():
            self._remaining_ms = self._timer.remainingTime()
            self._timer.stop()

    def leaveEvent(self, _event) -> None:
        if self.isVisible() and not self._timer.isActive():
            self._timer.start(max(self._remaining_ms, 4000))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.on_click()
        self.dismiss()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        body = QRectF(self.rect()).adjusted(1, 1, -1, -1 - TAIL)
        path = QPainterPath()
        path.addRoundedRect(body, 14, 14)
        tip_x = body.left() + body.width() * self.tail_x
        tail = QPainterPath()
        tail.addPolygon(QPolygonF([QPointF(tip_x - 10, body.bottom() - 1),
                                   QPointF(tip_x + 10, body.bottom() - 1),
                                   QPointF(tip_x - 2, body.bottom() + TAIL - 1)]))
        path = path.united(tail)
        p.fillPath(path, QColor(252, 250, 245, 245))
        p.setPen(QPen(QColor(40, 40, 50, 110), 1.2))
        p.drawPath(path)
