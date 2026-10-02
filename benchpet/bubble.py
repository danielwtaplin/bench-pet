"""Info bubble shown above the pet. Sources contribute named sections of lines."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

STYLE = """
QLabel { color: #f2f2f5; font-size: 12px; }
QLabel[role="title"] { font-weight: 600; font-size: 13px; }
QLabel[role="muted"] { color: #b4b4c0; }
"""

# Sections listed here come first, in this order; others follow as they arrive.
SECTION_LABELS = {"task": "Task status", "activity": "Break reminder", "pomodoro": "Pomodoro", "calendar": "Calendar",
                  "countdown": "Countdown", "weather": "Weather", "music": "Music",
                  "notifications": "Notifications"}
SECTION_ORDER = ["task", "activity", "pomodoro", "calendar", "countdown", "weather", "music", "notifications"]


class Bubble(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(STYLE)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 9, 12, 9)
        self._layout.setSpacing(2)
        # section → list of (text, role)
        self._sections: dict[str, list[tuple[str, str]]] = {}
        self.hidden: set[str] = set()  # sections the user turned off

    def set_section(self, name: str, lines: list[tuple[str, str]] | None) -> None:
        if lines:
            self._sections[name] = lines
        else:
            self._sections.pop(name, None)
        self._rebuild()

    def set_hidden(self, hidden: set[str]) -> None:
        self.hidden = set(hidden)
        self._rebuild()

    def _visible(self) -> list[str]:
        names = [n for n in self._sections if n not in self.hidden]
        return sorted(names, key=lambda n: SECTION_ORDER.index(n)
                      if n in SECTION_ORDER else len(SECTION_ORDER))

    def has_content(self) -> bool:
        return bool(self._visible())

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().hide()  # deleteLater only runs on the next loop pass
                item.widget().deleteLater()
        for i, lines in enumerate(self._sections[n] for n in self._visible()):
            if i:
                self._layout.addSpacing(6)
            for text, role in lines:
                label = QLabel(text)
                label.setProperty("role", role)
                self._layout.addWidget(label)
                label.ensurePolished()  # pick up the bubble stylesheet's font before measuring
                # Word-wrapped labels size to a narrow default, so size to the text instead.
                label.setFixedWidth(min(label.fontMetrics().horizontalAdvance(text) + 4, 260))
                label.setWordWrap(True)
        self.adjustSize()

    def show_above(self, anchor: QPoint) -> None:
        """Show with the bubble's bottom-centre at `anchor` (global coords)."""
        if not self.has_content():
            self.hide()
            return
        self.adjustSize()
        self.move(anchor.x() - self.width() // 2, anchor.y() - self.height())
        self.show()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.fillPath(path, QColor(28, 28, 36, 225))
        p.setPen(QColor(255, 255, 255, 40))
        p.drawPath(path)
