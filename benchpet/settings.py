"""Settings window: a page per feature, each loading from and saving to the config.

To add settings for something new, write a Page subclass (title, build, save)
and add it to PAGES. Saving writes config.yaml and calls `on_applied` with the
config sections that changed, so the app can apply them without a restart.
"""

from __future__ import annotations

import copy
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QListWidget, QPushButton, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from benchpet.bubble import OPT_IN, SECTION_LABELS
from benchpet.calendar_view import LAYOUTS
from benchpet.sources.calendar import FEED_COLOURS

SIZES = {"Small": 140, "Medium": 180, "Large": 240}
SIDES = {"auto": "Wherever there's room", "right": "Right of the pet", "left": "Left of the pet"}


class Page:
    title = ""
    keys: tuple[str, ...] = ()  # config sections this page edits

    def build(self, config: dict) -> QWidget:
        raise NotImplementedError

    def save(self, config: dict) -> None:
        raise NotImplementedError


def hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.RichText)
    lab.setStyleSheet("color: palette(placeholder-text);")
    return lab


class GeneralPage(Page):
    title = "General"
    keys = ("height",)

    def build(self, config):
        w = QWidget()
        form = QFormLayout(w)
        self.size = QComboBox()
        for label, height in SIZES.items():
            self.size.addItem(label, height)
        index = self.size.findData(config["height"])
        if index < 0:
            self.size.addItem(f"Custom ({config['height']} px)", config["height"])
            index = self.size.count() - 1
        self.size.setCurrentIndex(index)
        form.addRow("Pet size", self.size)
        return w

    def save(self, config):
        config["height"] = self.size.currentData()


class InfoPanelPage(Page):
    title = "Info panel"
    keys = ("bubble",)

    def build(self, config):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(hint("What the dark panel above the pet shows when you hover or click it."))
        hidden = set(config["bubble"].get("hidden", []))
        shown = set(config["bubble"].get("shown", []))
        self.boxes = {}
        for name, label in SECTION_LABELS.items():
            box = QCheckBox(label)
            box.setChecked(name in shown if name in OPT_IN else name not in hidden)
            v.addWidget(box)
            self.boxes[name] = box
        v.addStretch()
        return w

    def save(self, config):
        bubble = config["bubble"]
        keep_hidden = [n for n in bubble.get("hidden", []) if n not in SECTION_LABELS]  # e.g. retired sections
        bubble["hidden"] = sorted(keep_hidden + [n for n, b in self.boxes.items()
                                                 if n not in OPT_IN and not b.isChecked()])
        bubble["shown"] = sorted(n for n, b in self.boxes.items() if n in OPT_IN and b.isChecked())


class CalendarPage(Page):
    title = "Calendar"
    keys = ("calendar", "calendar_view")

    def build(self, config):
        view, cal = config["calendar_view"], config["calendar"]
        w = QWidget()
        v = QVBoxLayout(w)

        card = QGroupBox("Calendar card")
        form = QFormLayout(card)
        self.with_panel = QCheckBox("Open it with the info panel (hover or click the pet)")
        self.with_panel.setChecked(view["with_info_panel"])
        form.addRow(self.with_panel)
        self.button = QCheckBox("Show a calendar button below the pet to open and close it")
        self.button.setChecked(view["button"])
        form.addRow(self.button)
        self.layout_box = QComboBox()
        for key, label in LAYOUTS.items():
            self.layout_box.addItem(label, key)
        self.layout_box.setCurrentIndex(max(0, self.layout_box.findData(view["layout"])))
        form.addRow("Layout", self.layout_box)
        self.days = QSpinBox(minimum=1, maximum=14, suffix=" days")
        self.days.setValue(view["agenda_days"])
        form.addRow("Agenda shows", self.days)
        self.layout_box.currentIndexChanged.connect(
            lambda: self.days.setEnabled(self.layout_box.currentData() == "agenda"))
        self.days.setEnabled(view["layout"] == "agenda")
        self.side = QComboBox()
        for key, label in SIDES.items():
            self.side.addItem(label, key)
        self.side.setCurrentIndex(max(0, self.side.findData(view["side"])))
        form.addRow("Position", self.side)
        v.addWidget(card)

        feeds = QGroupBox("Calendars")
        fv = QVBoxLayout(feeds)
        fv.addWidget(hint(
            "Paste each calendar's private iCal address (it stays on this computer).<br>"
            "<b>Google:</b> Settings → your calendar → Integrate calendar → "
            "<i>Secret address in iCal format</i><br>"
            "<b>Outlook:</b> Settings → Calendar → Shared calendars → Publish a calendar → ICS link<br>"
            "A local <code>.ics</code> file path works too."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Address", "Colour"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(130)
        for feed in cal["feeds"]:
            self._add_row(feed)
        fv.addWidget(self.table)
        buttons = QHBoxLayout()
        add = QPushButton("Add calendar")
        add.clicked.connect(lambda: self._add_row({}, edit=True))
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_rows)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        fv.addLayout(buttons)
        v.addWidget(feeds)

        timing = QGroupBox("Reminders")
        tf = QFormLayout(timing)
        self.remind = QSpinBox(minimum=0, maximum=120, suffix=" min before")
        self.remind.setValue(cal["remind_minutes"])
        self.remind.setSpecialValueText("Off")
        tf.addRow("Pet reacts and the calendar pops up", self.remind)
        self.refresh = QSpinBox(minimum=5, maximum=240, suffix=" min")
        self.refresh.setValue(cal["refresh_minutes"])
        tf.addRow("Check calendars every", self.refresh)
        v.addWidget(timing)
        return w

    def _add_row(self, feed: dict, edit: bool = False) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(feed.get("name", "" if not edit else "Calendar")))
        url = QTableWidgetItem(feed.get("url", ""))
        url.setToolTip("iCal address or .ics path")
        self.table.setItem(row, 1, url)
        swatch = QPushButton()
        swatch.setFixedWidth(48)
        self._set_swatch(swatch, feed.get("colour") or FEED_COLOURS[row % len(FEED_COLOURS)])
        swatch.clicked.connect(lambda _=False, b=swatch: self._pick_colour(b))
        self.table.setCellWidget(row, 2, swatch)
        if edit:
            self.table.setCurrentCell(row, 1)
            self.table.editItem(self.table.item(row, 1))

    @staticmethod
    def _set_swatch(button: QPushButton, colour: str) -> None:
        button.setProperty("colour", colour)
        button.setStyleSheet(f"background: {colour}; border: 1px solid #888; border-radius: 3px;"
                             "min-height: 18px;")

    def _pick_colour(self, button: QPushButton) -> None:
        colour = QColorDialog.getColor(QColor(button.property("colour")), self.table, "Calendar colour")
        if colour.isValid():
            self._set_swatch(button, colour.name())

    def _remove_rows(self) -> None:
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def feeds(self) -> list[dict]:
        out = []
        for row in range(self.table.rowCount()):
            url = (self.table.item(row, 1).text() if self.table.item(row, 1) else "").strip()
            if not url:
                continue
            name = (self.table.item(row, 0).text() if self.table.item(row, 0) else "").strip()
            out.append({"name": name or "Calendar", "url": url,
                        "colour": self.table.cellWidget(row, 2).property("colour")})
        return out

    def save(self, config):
        view, cal = config["calendar_view"], config["calendar"]
        view["with_info_panel"] = self.with_panel.isChecked()
        view["button"] = self.button.isChecked()
        view["layout"] = self.layout_box.currentData()
        view["agenda_days"] = self.days.value()
        view["side"] = self.side.currentData()
        cal["feeds"] = self.feeds()
        cal["remind_minutes"] = self.remind.value()
        cal["refresh_minutes"] = self.refresh.value()


PAGES = [GeneralPage, InfoPanelPage, CalendarPage]


class SettingsDialog(QDialog):
    def __init__(self, config, on_applied: Callable[[set[str]], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bench Pet Settings")
        self.config = config
        self.on_applied = on_applied
        self.pages = [cls() for cls in PAGES]

        self.nav = QListWidget()
        self.nav.setFixedWidth(130)
        self.stack = QStackedWidget()
        for page in self.pages:
            self.nav.addItem(page.title)
            self.stack.addWidget(page.build(config))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply)

        body = QHBoxLayout()
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        outer = QVBoxLayout(self)
        outer.addLayout(body)
        outer.addWidget(buttons)
        self.resize(640, 560)

    def show_page(self, title: str) -> None:
        for i, page in enumerate(self.pages):
            if page.title == title:
                self.nav.setCurrentRow(i)

    def apply(self) -> None:
        before = copy.deepcopy(dict(self.config))
        for page in self.pages:
            page.save(self.config)
        changed = {key for key in self.config if self.config[key] != before.get(key)}
        if changed:
            self.config.save()
            self.on_applied(changed)

    def _ok(self) -> None:
        self.apply()
        self.accept()
