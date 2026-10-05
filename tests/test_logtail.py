import os

from benchpet.sources import logtail
from benchpet.sources.logtail import Tail, clean


def write(path, text, mode="a"):
    with open(path, mode) as f:
        f.write(text)


def test_first_poll_shows_the_last_lines_as_old_news(tmp_path):
    log = tmp_path / "app.log"
    write(log, "".join(f"line {i}\n" for i in range(20)))
    tail = Tail(str(log), 5)
    assert tail.poll() == 0
    assert list(tail.lines) == [f"line {i}" for i in range(15, 20)]
    assert tail.poll() is None  # nothing new


def test_appended_lines_count_and_partial_lines_wait_for_their_newline(tmp_path):
    log = tmp_path / "app.log"
    write(log, "one\n")
    tail = Tail(str(log), 5)
    tail.poll()
    write(log, "two\nthr")
    assert tail.poll() == 1
    assert list(tail.lines) == ["one", "two"]
    write(log, "ee\n")
    assert tail.poll() == 1
    assert list(tail.lines)[-1] == "three"


def test_truncation_starts_again_from_the_top(tmp_path):
    log = tmp_path / "app.log"
    write(log, "old 1\nold 2\nold 3\n")
    tail = Tail(str(log), 5)
    tail.poll()
    write(log, "new\n", mode="w")
    assert tail.poll() == 1
    assert list(tail.lines)[-1] == "new"


def test_rotation_follows_the_new_file(tmp_path):
    log = tmp_path / "app.log"
    write(log, "before\n")
    tail = Tail(str(log), 5)
    tail.poll()
    os.rename(log, tmp_path / "app.log.1")
    write(log, "after 1\nafter 2\n")
    assert tail.poll() == 2
    assert list(tail.lines) == ["before", "after 1", "after 2"]


def test_waits_for_a_missing_file_then_reads_all_of_it(tmp_path):
    log = tmp_path / "later.log"
    tail = Tail(str(log), 5)
    assert tail.poll() == 0
    assert tail.error == "Waiting for later.log…"
    assert tail.poll() is None
    write(log, "hello\n")
    assert tail.poll() == 1  # appeared after we started: it's all new
    assert tail.error == "" and list(tail.lines) == ["hello"]


def test_a_deleted_file_says_so_and_keeps_its_lines(tmp_path):
    log = tmp_path / "app.log"
    write(log, "kept\n")
    tail = Tail(str(log), 5)
    tail.poll()
    log.unlink()
    assert tail.poll() == 0
    assert tail.error and list(tail.lines) == ["kept"]


def test_a_folder_is_an_error(tmp_path):
    tail = Tail(str(tmp_path), 5)
    tail.poll()
    assert "folder" in tail.error


def test_a_flood_skips_ahead_without_a_cut_off_line(tmp_path, monkeypatch):
    monkeypatch.setattr(logtail, "MAX_READ", 100)
    monkeypatch.setattr(logtail, "BACKLOG_BYTES", 30)
    log = tmp_path / "app.log"
    write(log, "start\n")
    tail = Tail(str(log), 3)
    tail.poll()
    write(log, "".join(f"line {i:03d}\n" for i in range(50)))  # 450 bytes
    tail.poll()
    assert list(tail.lines) == ["line 047", "line 048", "line 049"]


def test_backlog_from_mid_file_drops_the_cut_off_line(tmp_path, monkeypatch):
    monkeypatch.setattr(logtail, "BACKLOG_BYTES", 15)
    log = tmp_path / "app.log"
    write(log, "aaaaaaaaaa\nbbbb\ncccc\n")
    tail = Tail(str(log), 5)
    tail.poll()
    assert list(tail.lines) == ["bbbb", "cccc"]


def test_clean_strips_colour_codes_and_controls():
    assert clean(b"\x1b[31mERROR\x1b[0m\tboom\r") == "ERROR   boom"
    assert clean("café \x07".encode()) == "café "
    assert clean(b"\xff ok") == "� ok"


def test_home_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write(tmp_path / "x.log", "hi\n")
    tail = Tail("~/x.log", 2)
    tail.poll()
    assert list(tail.lines) == ["hi"]
