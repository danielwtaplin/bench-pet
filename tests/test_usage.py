import json
from datetime import datetime

import pytest

from benchpet.bubble import Bubble
from benchpet.control import parse
from benchpet.events import PlanUsage
from benchpet.usage import (
    TranscriptScanner, Window, current_used, message_cost, parse_rate_limits, statusline_text, usage_lines)

PAYLOAD = {
    "model": {"display_name": "Opus 5.5"},
    "rate_limits": {
        "five_hour": {"used_percentage": 42.4, "resets_at": 2_000_000_000},
        "seven_day": {"used_percentage": 18, "resets_at": 2_000_500_000},
    },
}


def test_parse_rate_limits_and_statusline():
    windows = parse_rate_limits(PAYLOAD)
    assert windows == [Window("5h", 42.4, 2e9), Window("week", 18.0, 2.0005e9)]
    assert statusline_text(PAYLOAD, windows) == "Opus 5.5 · 5h ███▍░░░░ 42% · week █▌░░░░░░ 18%"


def test_missing_rate_limits():
    assert parse_rate_limits({"model": {"display_name": "Opus"}}) == []
    assert parse_rate_limits({"rate_limits": {"five_hour": {"used_percentage": None}}}) == []
    assert statusline_text({}, []) == "Claude"


def test_control_parses_usage_and_rejects_junk():
    line = json.dumps({"cmd": "usage", "agent": "claude",
                       "windows": [{"name": "5h", "used": 91, "resets_at": 5}]}).encode()
    assert parse(line) == PlanUsage("claude", (Window("5h", 91.0, 5.0),))
    assert parse(b'{"cmd": "usage", "windows": [{"name": "5h"}]}') is None
    assert parse(b'{"cmd": "usage", "windows": []}') is None
    assert parse(b'{"cmd": "statusline"}') is None  # a CLI command, not a socket message


def test_window_past_its_reset_reads_zero():
    assert current_used(Window("5h", 80, 100), now=99) == 80
    assert current_used(Window("5h", 80, 100), now=100) == 0


def test_message_cost():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000,
             "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 1_000_000}}
    # Opus 5.5: 4 in + 20 out + 0.20 read + 4*1.25 + 4*2
    assert message_cost("claude-opus-5-5", usage) == pytest.approx(37.2)
    assert message_cost("claude-opus-5-5", {**usage, "speed": "fast"}) == pytest.approx(74.4)
    assert message_cost("claude-opus-4-8", {"output_tokens": 1_000_000}) == pytest.approx(25)
    assert message_cost("claude-sonnet-5", {"input_tokens": 1_000_000}) == pytest.approx(2)
    assert message_cost("gpt-9", usage) is None
    # Older logs: only the total cache write, treated as 5-minute writes.
    assert message_cost("claude-haiku-4-5", {"cache_creation_input_tokens": 1_000_000}) == pytest.approx(1.25)


def entry(msg_id, model="claude-opus-5-5", out=1000, stamp="2026-10-02T01:00:00Z", kind="assistant"):
    return json.dumps({"type": kind, "timestamp": stamp,
                       "message": {"id": msg_id, "model": model, "usage": {"output_tokens": out}}}) + "\n"


@pytest.fixture
def logs(tmp_path):
    now = [datetime(2026, 10, 2, 15, 0).timestamp()]
    return tmp_path, TranscriptScanner(tmp_path, now=lambda: now[0]), now


def local_stamp(hour):
    return datetime(2026, 10, 2, hour).astimezone().isoformat()


def test_scanner_counts_each_message_once_and_reads_incrementally(logs):
    root, scanner, _ = logs
    (root / "proj").mkdir()
    log = root / "proj" / "session.jsonl"
    log.write_text(entry("a", stamp=local_stamp(9)) * 3  # streamed reply logged three times
                   + entry("u", kind="user", stamp=local_stamp(9))
                   + entry("s", model="<synthetic>", stamp=local_stamp(9)))
    totals = scanner.scan()
    assert (totals.tokens, totals.by_model) == (1000, {"claude-opus-5-5": 1000})
    assert totals.cost == pytest.approx(0.02)
    with log.open("a") as f:
        f.write(entry("b", model="mystery-model", stamp=local_stamp(10)))
        f.write(entry("c", stamp=local_stamp(11))[:-10])  # still being written
    totals = scanner.scan()
    assert (totals.tokens, totals.unpriced_tokens) == (2000, 1000)
    with log.open("a") as f:
        f.write(entry("c", stamp=local_stamp(11))[-10:])
    assert scanner.scan().tokens == 3000


def test_scanner_skips_other_days_and_resets_at_midnight(logs):
    root, scanner, now = logs
    sub = root / "proj" / "session" / "subagents"
    sub.mkdir(parents=True)
    yesterday = datetime(2026, 10, 1, 23).astimezone().isoformat()
    (sub / "agent.jsonl").write_text(entry("old", stamp=yesterday) + entry("new", stamp=local_stamp(8)))
    assert scanner.scan().tokens == 1000
    now[0] = datetime(2026, 10, 3, 0, 5).timestamp()
    totals = scanner.scan()
    assert (totals.day, totals.tokens) == ("2026-10-03", 0)


def test_usage_lines():
    now = 1_000_000.0
    windows = [Window("5h", 42, now + 3600), Window("week", 18, None)]
    lines = usage_lines(windows, received_at=now - 15 * 60, totals=None, now=now)
    assert lines[0] == ("✳  Claude plan · as of 15 min ago", "title")
    text, role, fraction = lines[1]
    assert text.startswith("5h  42% · resets ") and (role, fraction) == ("bar", 0.42)
    assert lines[2] == ("week  18%", "bar", 0.18)
    assert usage_lines([], None, None, now) is None


def test_text_bar():
    from benchpet.usage import text_bar
    assert text_bar(0) == "░" * 8
    assert text_bar(1) == "█" * 8
    assert text_bar(0.5) == "████░░░░"
    assert text_bar(1.7) == "█" * 8
    assert len(text_bar(0.33)) == 8


def test_usage_section_is_opt_in():
    assert Bubble.hidden_from({"hidden": ["weather"]}) == {"weather", "usage"}
    assert Bubble.hidden_from({"hidden": [], "shown": ["usage"]}) == set()


def test_bubble_renders_bars():
    from PySide6.QtWidgets import QApplication
    from benchpet.bubble import Bar
    app = QApplication.instance() or QApplication([])
    b = Bubble()
    b.set_section("usage", [("✳  Claude plan", "title"), ("5h  95%", "bar", 0.95), ("week  10%", "bar", 0.1)])
    bars = b.findChildren(Bar)
    assert [bar.fraction for bar in bars] == [0.95, 0.1]
    assert bars[0].colour().name() == "#ff6b6b" and bars[1].colour().name() == "#7bd88f"
