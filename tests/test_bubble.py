from PySide6.QtWidgets import QApplication

from benchpet.bubble import Bubble

app = QApplication.instance() or QApplication([])


def test_hidden_sections_are_left_out_and_order_is_fixed():
    b = Bubble()
    b.set_section("music", [("Song", "title")])
    b.set_section("countdown", [("Weekend in 2h", "muted")])
    assert b._visible() == ["countdown", "music"]
    b.set_hidden({"countdown"})
    assert b._visible() == ["music"]
    b.set_hidden({"countdown", "music"})
    assert not b.has_content()
