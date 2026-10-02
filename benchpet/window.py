"""The pet's frameless, transparent, always-on-top window."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

from benchpet.bubble import OPT_IN, SECTION_LABELS, Bubble
from benchpet.config import Config
from benchpet.renderer import PetWidget
from benchpet.speech import SpeechBubble
from benchpet.sprites import Activity, SpriteLibrary

SIZES = {"Small": 140, "Medium": 180, "Large": 240}
WALK_RANGE = 80  # max px the pet strolls away from where it was put down
DRAG_THRESHOLD = 4


class PetWindow(QWidget):
    def __init__(self, library: SpriteLibrary, config: Config):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Bench Pet")
        self.config = config

        self.pet = PetWidget(library, config["height"], self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pet)
        self.pet.pose_changed.connect(self._on_pose_changed)

        self.bubble = Bubble()
        self.bubble.set_hidden(Bubble.hidden_from(config["bubble"]))
        self.speech = SpeechBubble()
        self._bubble_pinned = False
        self._press: QPoint | None = None
        self._drag_offset = QPoint()
        self._dragging = False
        self._walk = QPropertyAnimation(self, b"pos", self)
        self._walk.setEasingCurve(QEasingCurve.InOutSine)
        self.on_celebrate = lambda: None
        self.on_pomodoro = lambda action: None
        self.on_media = lambda action: None
        self.music = None  # latest MusicChanged, for the menu
        self.pomodoro_phase: str | None = None
        self._flash_timer = QTimer(self, singleShot=True)
        self._flash_timer.timeout.connect(self._end_flash)

        self.adjustSize()
        self.anchor = self._initial_position()
        self.move(self.anchor)

    def _initial_position(self) -> QPoint:
        if self.config.get("position"):
            pos = QPoint(*self.config["position"])
            if any(s.availableGeometry().contains(pos) for s in QGuiApplication.screens()):
                return pos
        area = QGuiApplication.primaryScreen().availableGeometry()
        return QPoint(area.right() - self.width() - 40, area.bottom() - self.height())

    # --- activity hooks --------------------------------------------------

    def set_activity(self, activity: Activity) -> None:
        self.pet.set_activity(activity)
        if activity.motion == "walk":
            self._start_walk(activity)

    def _start_walk(self, activity: Activity) -> None:
        duration = sum(activity.hold) / 2 * len(activity.poses)
        offset = self.x() - self.anchor.x()
        # Head back towards the anchor if we've wandered, otherwise pick a side.
        direction = -1 if offset > 0 else 1 if offset < 0 else self.pet.rng.choice((-1, 1))
        distance = self.pet.rng.randint(25, WALK_RANGE)
        target_x = max(self.anchor.x() - WALK_RANGE,
                       min(self.anchor.x() + WALK_RANGE, self.x() + direction * distance))
        screen = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        target_x = max(screen.left(), min(screen.right() - self.width(), target_x))
        self._walk.stop()
        self._walk.setDuration(int(duration * 1000))
        self._walk.setStartValue(self.pos())
        self._walk.setEndValue(QPoint(target_x, self.y()))
        self._walk.start()

    def set_paused(self, paused: bool) -> None:
        self.pet.paused = paused

    # --- bubble ----------------------------------------------------------

    def set_bubble_section(self, name: str, lines) -> None:
        self.bubble.set_section(name, lines)
        if self.bubble.isVisible() or self._bubble_pinned:
            self._place_bubble()

    def say(self, header: str, text: str, seconds: float, can_open: bool) -> None:
        self.bubble.hide()  # one bubble at a time
        self.speech.say(header, text, seconds, can_open)
        self._place_speech()
        self.speech.show()

    def _place_speech(self) -> None:
        head = self.mapToGlobal(QPoint(self.width() // 2, self.pet.pose_rect().top() + 6))
        screen = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        self.speech.place(head, screen)

    def _place_bubble(self) -> None:
        if self.speech.isVisible():
            return
        top = self.pet.pose_rect().top()
        self.bubble.show_above(self.mapToGlobal(QPoint(self.width() // 2, top - 4)))

    def flash_bubble(self, seconds: float) -> None:
        """Pop the bubble up for a while without the user hovering."""
        self._place_bubble()
        self._flash_timer.start(int(seconds * 1000))

    def _end_flash(self) -> None:
        if not self._bubble_pinned and not self.underMouse():
            self.bubble.hide()

    def enterEvent(self, _event) -> None:
        if not self._dragging:
            self._place_bubble()

    def leaveEvent(self, _event) -> None:
        if not self._bubble_pinned and not self._flash_timer.isActive():
            self.bubble.hide()

    def moveEvent(self, _event) -> None:
        if self.bubble.isVisible():
            self._place_bubble()
        if self.speech.isVisible():
            self._place_speech()

    def _on_pose_changed(self) -> None:
        self.setMask(self.pet.input_region())
        if self.bubble.isVisible():
            self._place_bubble()
        if self.speech.isVisible():
            self._place_speech()

    # --- dragging / clicking ---------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._drag_offset = self._press - self.pos()

    def mouseMoveEvent(self, event) -> None:
        if self._press is None:
            return
        pos = event.globalPosition().toPoint()
        if not self._dragging and (pos - self._press).manhattanLength() > DRAG_THRESHOLD:
            self._dragging = True
            self._walk.stop()
            self.bubble.hide()
        if self._dragging:
            self.move(pos - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._dragging:
            self.anchor = self.pos()
            self.config["position"] = [self.x(), self.y()]
            self.config.save()
        else:
            self._bubble_pinned = not self._bubble_pinned
            if self._bubble_pinned:
                self._place_bubble()
        self._press = None
        self._dragging = False

    # --- menu ------------------------------------------------------------

    def contextMenuEvent(self, event) -> None:
        self.build_menu().exec(event.globalPos())

    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        music = self.music
        if music and music.player and music.status != "Stopped":
            title = " — ".join(t for t in (music.title, music.artist) if t) or "Music"
            now = menu.addAction(("▶  " if music.playing else "⏸  ") + title[:60])
            now.setEnabled(False)
            menu.addAction("Pause" if music.playing else "Play").triggered.connect(
                lambda: self.on_media("play_pause"))
            menu.addAction("Next track").triggered.connect(lambda: self.on_media("next"))
            menu.addAction("Previous track").triggered.connect(lambda: self.on_media("previous"))
            menu.addSeparator()

        panel = menu.addMenu("Info panel")
        for name, label in SECTION_LABELS.items():
            action = panel.addAction(label)
            action.setCheckable(True)
            action.setChecked(name not in self.bubble.hidden)
            action.toggled.connect(lambda on, n=name: self._set_section_shown(n, on))
        size_menu = menu.addMenu("Size")
        group = QActionGroup(size_menu)
        for label, height in SIZES.items():
            action = QAction(label, size_menu, checkable=True,
                             checked=self.config["height"] == height)
            action.triggered.connect(lambda _=False, h=height: self._set_height(h))
            group.addAction(action)
            size_menu.addAction(action)
        pause = menu.addAction("Pause animation")
        pause.setCheckable(True)
        pause.setChecked(self.pet.paused)
        pause.toggled.connect(self.set_paused)
        pomodoro = menu.addMenu("Pomodoro")
        if self.pomodoro_phase:
            pomodoro.addAction("Skip to next phase").triggered.connect(lambda: self.on_pomodoro("skip"))
            pomodoro.addAction("Stop").triggered.connect(lambda: self.on_pomodoro("stop"))
        else:
            pomodoro.addAction("Start focus session").triggered.connect(
                lambda: self.on_pomodoro("start"))
        menu.addAction("Celebrate!").triggered.connect(lambda: self.on_celebrate())
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(QApplication.quit)
        return menu

    def _set_section_shown(self, name: str, shown: bool) -> None:
        hidden = set(self.bubble.hidden)
        (hidden.discard if shown else hidden.add)(name)
        self.bubble.set_hidden(hidden)
        self.config["bubble"]["hidden"] = sorted(hidden - OPT_IN)
        self.config["bubble"]["shown"] = sorted(OPT_IN - hidden)
        self.config.save()
        if self.bubble.isVisible() or self._bubble_pinned:
            self._place_bubble()

    def _set_height(self, height: int) -> None:
        bottom = self.y() + self.height()
        self.config["height"] = height
        self.pet.set_display_height(height)
        self.adjustSize()
        # Keep the feet where they were.
        self.move(self.x(), bottom - self.height())
        self.anchor = self.pos()
        self.config["position"] = [self.x(), self.y()]
        self.config.save()
        self._on_pose_changed()
