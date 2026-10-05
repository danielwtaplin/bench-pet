from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QLabel

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


def test_bubble_opens_below_when_there_is_no_room_above():
    bubble = Bubble()
    bubble.set_section("task", [("Working", "title")])
    screen = QRect(0, 0, 1920, 1080)
    bubble.show_near(QPoint(500, 400), 700, screen)
    assert bubble.geometry().bottom() < 400  # room above: sits over the head
    bubble.show_near(QPoint(10, 5), 300, screen)  # pet at the top-left corner
    assert bubble.y() == 300 and bubble.x() == 0  # below the feet, kept on screen
    bubble.hide()


def test_music_section_with_art_shows_a_tile_beside_the_text():
    from PySide6.QtGui import QPixmap

    from benchpet.bubble import ART_SIZE

    cover = QPixmap(300, 200)
    cover.fill()
    b = Bubble()
    b.set_section("music", [("", "art", cover), ("▶  Song", "title"), ("Artist", "muted")])
    tiles = [l for l in b.findChildren(QLabel) if l.pixmap() and not l.pixmap().isNull()]
    assert len(tiles) == 1 and tiles[0].pixmap().size().width() == ART_SIZE
    assert {l.text() for l in b.findChildren(QLabel)} >= {"▶  Song", "Artist"}


def test_flatpak_tmp_art_paths_are_found_on_the_host(tmp_path, monkeypatch):
    from benchpet.art import local_path

    sandboxed = tmp_path / ".flatpak" / "com.google.Chrome" / "tmp"
    sandboxed.mkdir(parents=True)
    (sandboxed / ".com.google.Chrome.abc").write_bytes(b"x")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert local_path("file:///tmp/.com.google.Chrome.abc") == str(sandboxed / ".com.google.Chrome.abc")
    assert local_path("file:///tmp/missing") is None
