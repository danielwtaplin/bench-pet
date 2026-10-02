import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from benchpet.config import Config  # noqa: E402
from benchpet.sprites import load_library  # noqa: E402
from benchpet.window import PetWindow  # noqa: E402

app = QApplication.instance() or QApplication([])


def make(tmp_path):
    library = load_library()
    window = PetWindow(library, Config(tmp_path / "config.yaml"))
    return window, library


def test_pose_change_while_hovered_keeps_the_cursor_inside(tmp_path):
    window, library = make(tmp_path)
    window.set_activity(library.get("crouch"))  # wide, low pose
    window.pet.prev_pose = None
    window._on_pose_changed()
    crouch_area = window.mask()
    window.enterEvent(None)
    window.set_activity(library.get("idle"))  # narrow standing pose: a different outline
    window.pet.prev_pose = None  # crossfade over
    window._on_pose_changed()
    assert window.mask().contains(crouch_area.boundingRect().center())
    assert crouch_area.subtracted(window.mask()).isEmpty()


def test_leaving_restores_the_pose_outline(tmp_path):
    window, library = make(tmp_path)
    window.enterEvent(None)
    window.set_activity(library.get("crouch"))
    window.pet.prev_pose = None
    window._on_pose_changed()
    window.set_activity(library.get("idle"))
    window.pet.prev_pose = None
    window._on_pose_changed()
    window.leaveEvent(None)
    assert window.mask() == window.pet.input_region()


def test_no_walking_off_while_hovered(tmp_path):
    window, library = make(tmp_path)
    window.enterEvent(None)
    window.set_activity(library.get("walk"))
    assert window._walk.state() != window._walk.State.Running
    window.leaveEvent(None)
    window.set_activity(library.get("walk"))
    assert window._walk.state() == window._walk.State.Running


def test_calendar_follows_the_info_panel_and_the_button(tmp_path):
    window, _ = make(tmp_path)
    window.show()
    window.calendar.set_events((), has_feeds=True)
    window.enterEvent(None)
    assert window.calendar.isVisible()
    window.leaveEvent(None)
    window._leave_timer.timeout.emit()
    assert not window.calendar.isVisible()
    window.config["calendar_view"].update(with_info_panel=False, button=True)
    window.apply_calendar_settings()
    assert window.calendar_button.isVisible() and not window.calendar.isVisible()
    window.enterEvent(None)
    assert not window.calendar.isVisible()  # no longer tied to the info panel
    window.calendar_button.clicked.emit()
    assert window.calendar.isVisible()
    window.calendar_button.clicked.emit()
    assert not window.calendar.isVisible()


def test_moving_onto_the_calendar_keeps_it_open(tmp_path):
    window, _ = make(tmp_path)
    window.show()
    window.calendar.set_events((), has_feeds=True)
    window.enterEvent(None)
    window.leaveEvent(None)  # heading for the card...
    window.calendar.hover_changed.emit(True)  # ...and there before the grace period ends
    window._leave_timer.timeout.emit()
    assert window.calendar.isVisible()
    window.calendar.hover_changed.emit(False)
    window._leave_timer.timeout.emit()
    assert not window.calendar.isVisible()


def test_no_calendar_card_on_hover_without_feeds(tmp_path):
    window, _ = make(tmp_path)
    window.show()
    window.enterEvent(None)
    assert not window.calendar.isVisible()
