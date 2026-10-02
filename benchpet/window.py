"""The pet's frameless, transparent, always-on-top window."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

from benchpet.bubble import OPT_IN, SECTION_LABELS, Bubble
from benchpet.calendar_view import CalendarButton, CalendarView
from benchpet.config import Config
from benchpet.renderer import PetWidget
from benchpet.speech import SpeechBubble
from benchpet.sprites import Activity, SpriteLibrary

SIZES = {"Small": 140, "Medium": 180, "Large": 240}
WALK_RANGE = 80  # max px the pet strolls away from where it was put down
DRAG_THRESHOLD = 4
LEAVE_GRACE_MS = 250  # time to move from the pet onto the bubble or calendar without them closing


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
        self.bubble.hover_changed.connect(self._on_popup_hover)
        self.calendar = CalendarView()
        self.calendar.hover_changed.connect(self._on_popup_hover)
        self.calendar_button = CalendarButton()
        self.calendar_button.clicked.connect(self.toggle_calendar)
        self._calendar_open = False  # opened with the button/menu, independent of the info panel
        self._over_popup = False
        self._leave_timer = QTimer(self, singleShot=True, interval=LEAVE_GRACE_MS)
        self._leave_timer.timeout.connect(self._update_info)
        self.on_settings = lambda: None
        self.speech = SpeechBubble()
        self._bubble_pinned = False
        self._hovered = False  # cursor over the pet; its input area then only grows
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
        self.apply_calendar_settings()

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
        if self._hovered:
            return  # walking off would leave the cursor behind and close the bubble
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
        if self.bubble.isVisible() or self._info_open():
            self._place_bubble()

    def say(self, header: str, text: str, seconds: float, can_open: bool) -> None:
        self.speech.say(header, text, seconds, can_open)
        self._place_speech()
        self.speech.show()
        self._update_info()  # one bubble at a time

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
        """Pop the info panel (and calendar) up for a while without the user hovering."""
        self._flash_timer.start(int(seconds * 1000))
        self._update_info()

    def _end_flash(self) -> None:
        self._update_info()

    def _info_open(self) -> bool:
        """Whether the info panel should be showing: hovered, pinned or flashing."""
        if self.speech.isVisible() or self._dragging:
            return False
        return (self._hovered or self._over_popup or self._bubble_pinned
                or self._flash_timer.isActive())

    def _update_info(self) -> None:
        if self._info_open():
            self._place_bubble()
        else:
            self.bubble.hide()
        self._update_calendar()

    def _on_popup_hover(self, inside: bool) -> None:
        self._over_popup = inside
        if inside:
            self._leave_timer.stop()
        else:
            self._leave_timer.start()

    def enterEvent(self, _event) -> None:
        self._hovered = True
        self._leave_timer.stop()
        self._update_info()

    def leaveEvent(self, _event) -> None:
        self._hovered = False
        self.setMask(self.pet.input_region())  # back to the pose's outline
        self._leave_timer.start()

    # --- calendar --------------------------------------------------------

    def apply_calendar_settings(self) -> None:
        conf = self.config["calendar_view"]
        self.calendar.configure(conf["layout"], conf["agenda_days"])
        if not conf["button"]:
            self._calendar_open = False
        self.calendar_button.set_active(self._calendar_open)
        self._update_calendar()

    def toggle_calendar(self) -> None:
        self._calendar_open = not self._calendar_open
        self.calendar_button.set_active(self._calendar_open)
        self._update_calendar()

    def _pose_global(self) -> QRect:
        rect = self.pet.pose_rect()
        return QRect(self.pet.mapToGlobal(rect.topLeft()), rect.size())

    def _update_calendar(self) -> None:
        conf = self.config["calendar_view"]
        with_panel = conf["with_info_panel"] and self.calendar.has_feeds and self._info_open()
        screen = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        if not self._dragging and (self._calendar_open or with_panel) and self.isVisible():
            self.calendar.place_beside(self._pose_global(), screen, conf["side"])
            self.calendar.show()
        else:
            self.calendar.hide()
        if conf["button"] and self.isVisible():
            self.calendar_button.place_below(self._pose_global(), screen)
            self.calendar_button.show()
        else:
            self.calendar_button.hide()

    def showEvent(self, _event) -> None:
        self._update_calendar()

    def moveEvent(self, _event) -> None:
        if self.bubble.isVisible():
            self._place_bubble()
        if self.speech.isVisible():
            self._place_speech()
        if self.calendar.isVisible() or self.calendar_button.isVisible():
            self._update_calendar()

    def _on_pose_changed(self) -> None:
        region = self.pet.input_region()
        if self._hovered:
            # A new pose with a different outline mustn't leave a still cursor outside it
            # (that would count as leaving and close the bubble), so only grow while hovered.
            region = region.united(self.mask())
        self.setMask(region)
        if self.bubble.isVisible():
            self._place_bubble()
        if self.speech.isVisible():
            self._place_speech()
        if self.calendar.isVisible() or self.calendar_button.isVisible():
            self._update_calendar()

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
            self._update_info()
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
        self._press = None
        self._dragging = False
        self._update_info()

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
        calendar = menu.addAction("Calendar")
        calendar.setCheckable(True)
        calendar.setChecked(self._calendar_open)
        calendar.toggled.connect(lambda _on: self.toggle_calendar())
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
        menu.addAction("Settings…").triggered.connect(lambda: self.on_settings())
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

    def apply_settings(self) -> None:
        """Re-read the config after the Settings window saved it."""
        self.bubble.set_hidden(Bubble.hidden_from(self.config["bubble"]))
        if self.pet.display_height != self.config["height"]:
            self._set_height(self.config["height"])
        self.apply_calendar_settings()
        self._update_info()

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
