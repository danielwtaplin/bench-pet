"""Info bubble shown above the pet. Sources contribute named sections of lines."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from benchpet.art import rounded_tile

STYLE = """
QLabel { color: #f2f2f5; font-size: 12px; }
QLabel[role="title"] { font-weight: 600; font-size: 13px; }
QLabel[role="muted"] { color: #b4b4c0; }
"""

MAX_WIDTH = 260
ART_SIZE = 40  # album cover tile beside the music section's text
BAR_COLOURS = ((0.9, QColor("#ff6b6b")), (0.7, QColor("#f5c26b")), (0.0, QColor("#7bd88f")))


class Bar(QWidget):
    """Thin rounded progress bar; green, then amber from 70%, red from 90%."""

    def __init__(self, fraction: float):
        super().__init__()
        self.fraction = min(max(fraction, 0.0), 1.0)
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def colour(self) -> QColor:
        return next(c for threshold, c in BAR_COLOURS if self.fraction >= threshold)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        rect = QRectF(self.rect())
        p.setBrush(QColor(255, 255, 255, 38))
        p.drawRoundedRect(rect, 3, 3)
        if self.fraction > 0:
            p.setBrush(self.colour())
            p.drawRoundedRect(QRectF(rect.x(), rect.y(), max(rect.width() * self.fraction, 6), rect.height()),
                              3, 3)


# Sections listed here come first, in this order; others follow as they arrive.
SECTION_LABELS = {"task": "Task status", "activity": "Break reminder", "pomodoro": "Pomodoro",
                  "countdown": "Countdown", "weather": "Weather", "music": "Music",
                  "notifications": "Notifications", "usage": "AI usage"}
OPT_IN = {"usage"}  # hidden unless turned on (config bubble.shown)
SECTION_ORDER = ["task", "activity", "pomodoro", "countdown", "weather", "music", "notifications", "usage"]


class Bubble(QWidget):
    hover_changed = Signal(bool)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(STYLE)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 9, 12, 9)
        self._layout.setSpacing(2)
        # section → list of (text, role), or (text, "bar", fraction) for a labelled progress bar;
        # a leading ("", "art", QPixmap) line shows that image as a tile beside the rest
        self._sections: dict[str, list[tuple]] = {}
        self.hidden: set[str] = set()  # sections the user turned off

    def set_section(self, name: str, lines: list[tuple] | None) -> None:
        if lines:
            self._sections[name] = lines
        else:
            self._sections.pop(name, None)
        self._rebuild()

    @staticmethod
    def hidden_from(config: dict) -> set[str]:
        """Sections to hide: the ones turned off plus opt-in ones not turned on."""
        return set(config.get("hidden", [])) | (OPT_IN - set(config.get("shown", [])))

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
            if lines[0][1] == "art":
                self._add_art_row(lines[0][2], lines[1:])
            else:
                self._add_lines(self._layout, lines, MAX_WIDTH)
        self.adjustSize()

    def _add_art_row(self, pixmap, lines: list[tuple]) -> None:
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(8)
        art = QLabel()
        art.setPixmap(rounded_tile(pixmap, ART_SIZE))
        art.setFixedSize(ART_SIZE, ART_SIZE)
        hbox.addWidget(art, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addStretch()
        self._add_lines(text, lines, MAX_WIDTH - ART_SIZE - 8)
        text.addStretch()
        hbox.addLayout(text)
        self._layout.addWidget(row)

    @staticmethod
    def _add_lines(layout, lines: list[tuple], max_width: int) -> None:
        for text, role, *extra in lines:
            label = QLabel(text)
            label.setProperty("role", "muted" if role == "bar" else role)
            layout.addWidget(label)
            label.ensurePolished()  # pick up the bubble stylesheet's font before measuring
            # Word-wrapped labels size to a narrow default, so size to the text instead.
            width = label.fontMetrics().horizontalAdvance(text) + 4
            if role == "bar":
                width = max(width, 200)  # bars line up, whatever their labels say
                layout.addWidget(Bar(extra[0] if extra else 0.0))
                layout.addSpacing(3)
            label.setFixedWidth(min(width, max_width))
            label.setWordWrap(True)

    def show_near(self, above: QPoint, below_y: int, screen: QRect) -> None:
        """Show with the bubble's bottom-centre at `above` (global coords), or with its top
        at `below_y` when there's no room above. Never pushed back over the pet by the window
        manager, where it would catch the cursor and block dragging."""
        if not self.has_content():
            self.hide()
            return
        self.adjustSize()
        x = max(screen.left(), min(screen.right() - self.width(), above.x() - self.width() // 2))
        y = above.y() - self.height()
        if y < screen.top():
            y = below_y
        self.move(x, y)
        self.show()

    def enterEvent(self, _event) -> None:
        self.hover_changed.emit(True)

    def leaveEvent(self, _event) -> None:
        self.hover_changed.emit(False)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.fillPath(path, QColor(28, 28, 36, 225))
        p.setPen(QColor(255, 255, 255, 40))
        p.drawPath(path)
