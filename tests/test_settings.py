import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

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
