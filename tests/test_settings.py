import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from benchpet.config import Config  # noqa: E402
from benchpet.settings import SettingsDialog  # noqa: E402

app = QApplication.instance() or QApplication([])


def test_saves_only_what_changed_and_round_trips(tmp_path):
    config = Config(tmp_path / "config.yaml")
    config["calendar"]["feeds"] = [{"name": "Work", "url": "https://example.com/work.ics"}]
    applied = []
    dialog = SettingsDialog(config, applied.append)
    dialog.apply()
    assert applied == [{"calendar"}]  # only the default colour got filled in
    page = next(p for p in dialog.pages if p.title == "Calendar")
    page.layout_box.setCurrentIndex(page.layout_box.findData("timeline"))
    page._add_row({"name": "Blank"})  # no address: dropped on save
    dialog.apply()
    assert applied[-1] == {"calendar_view"}
    assert config["calendar_view"]["layout"] == "timeline"
    assert [f["name"] for f in config["calendar"]["feeds"]] == ["Work"]
    assert Config(tmp_path / "config.yaml")["calendar_view"]["layout"] == "timeline"


def test_info_panel_page_handles_opt_in_sections(tmp_path):
    config = Config(tmp_path / "config.yaml")
    dialog = SettingsDialog(config, lambda changed: None)
    page = next(p for p in dialog.pages if p.title == "Info panel")
    assert not page.boxes["usage"].isChecked() and page.boxes["music"].isChecked()
    page.boxes["usage"].setChecked(True)
    page.boxes["music"].setChecked(False)
    dialog.apply()
    assert config["bubble"] == {"hidden": ["music"], "shown": ["usage"]}


def test_an_address_still_being_edited_is_saved(tmp_path):
    config = Config(tmp_path / "config.yaml")
    dialog = SettingsDialog(config, lambda changed: None)
    dialog.show()
    dialog.show_page("Calendar")
    page = next(p for p in dialog.pages if p.title == "Calendar")
    page._add_row({}, edit=True)  # "Add calendar" opens the address cell for typing
    app.processEvents()
    page.table.findChild(QLineEdit).setText("https://example.com/cal.ics")
    dialog._ok()  # OK pressed with the editor still open
    assert [f["url"] for f in config["calendar"]["feeds"]] == ["https://example.com/cal.ics"]


def test_music_page_toggles_genre_outfits(tmp_path):
    config = Config(tmp_path / "config.yaml")
    applied = []
    dialog = SettingsDialog(config, applied.append)
    page = next(p for p in dialog.pages if p.title == "Music")
    assert page.genre_outfits.isChecked()
    page.genre_outfits.setChecked(False)
    dialog.apply()
    assert applied == [{"music"}]
    assert Config(tmp_path / "config.yaml")["music"]["genre_lookup"] is False


def test_log_tail_page_saves(tmp_path):
    config = Config(tmp_path / "config.yaml")
    applied = []
    dialog = SettingsDialog(config, applied.append)
    page = next(p for p in dialog.pages if p.title == "Log tail")
    page.path.setText("  ~/app/dev.log ")
    page.lines.setValue(20)
    page.side.setCurrentIndex(page.side.findData("left"))
    page.active.setValue(0)
    dialog.apply()
    assert applied == [{"log_tail"}]
    assert config["log_tail"] == {"path": "~/app/dev.log", "lines": 20, "with_info_panel": True,
                                  "side": "left", "active_seconds": 0}
