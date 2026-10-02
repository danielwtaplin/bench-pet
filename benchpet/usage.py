"""AI usage: plan limits from Claude Code's status line, tokens and cost from its logs.

Plan limits (the 5-hour and weekly windows) are only exposed to a status line
command, so `bench-pet statusline` is set as Claude Code's statusLine: it
forwards `rate_limits` to the pet and prints a short status line itself.

Token totals come from the session transcripts in ~/.claude/projects, which
record each reply's `usage`. Costs are what the same tokens would cost on the
API; on a subscription that's a yardstick, not a bill.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# $ per million tokens: input, output, cache read. Cache writes are 1.25x input
# (5-minute TTL) or 2x (1-hour TTL); fast mode doubles everything.
# Matched by longest prefix of the model id. Prices as of 2026-09.
PRICING = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-mythos-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4": (3.0, 15.0, 0.30),
    "claude-haiku-4": (1.0, 5.0, 0.10),
}
WINDOW_NAMES = {"five_hour": "5h", "seven_day": "week"}
# `bench-pet statusline` keeps the last payload here, so a restarted pet has figures straight away.
STATUSLINE_DUMP = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "bench-pet-statusline.json"
RESTORE_MAX_AGE = 12 * 3600


@dataclass(frozen=True)
class Window:
    name: str  # 5h | week
    used: float  # percent
    resets_at: float | None  # epoch seconds


def parse_rate_limits(payload: dict) -> list[Window]:
    """Windows from a status line payload; empty for API-key users or before the first reply."""
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return []
    windows = []
    for key, name in WINDOW_NAMES.items():
        w = limits.get(key)
        if isinstance(w, dict) and isinstance(w.get("used_percentage"), (int, float)):
            resets = w.get("resets_at")
            windows.append(Window(name, float(w["used_percentage"]),
                                  float(resets) if isinstance(resets, (int, float)) else None))
    return windows


def last_report(path: Path = STATUSLINE_DUMP, now: float | None = None) -> tuple[list[Window], float] | None:
    """Windows from the last status line payload and when it arrived, if recent enough."""
    try:
        received = path.stat().st_mtime
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if (now or time.time()) - received > RESTORE_MAX_AGE or not isinstance(payload, dict):
        return None
    windows = parse_rate_limits(payload)
    return (windows, received) if windows else None


def current_used(window: Window, now: float) -> float:
    """A window whose reset time has passed is back to zero, even if nobody told us yet."""
    return 0.0 if window.resets_at is not None and now >= window.resets_at else window.used


BLOCKS = " ▏▎▍▌▋▊▉█"


def text_bar(fraction: float, width: int = 8) -> str:
    """Unicode block bar, eighth-cell resolution, padded with light shade."""
    eighths = round(min(max(fraction, 0.0), 1.0) * width * 8)
    full, part = divmod(eighths, 8)
    bar = "█" * full + (BLOCKS[part] if part else "")
    return bar + "░" * (width - len(bar))


def statusline_text(payload: dict, windows: list[Window]) -> str:
    parts = [str((payload.get("model") or {}).get("display_name") or "Claude")]
    parts += [f"{w.name} {text_bar(w.used / 100)} {w.used:.0f}%" for w in windows]
    return " · ".join(parts)


def price(model: str) -> tuple[float, float, float] | None:
    matches = [k for k in PRICING if model.startswith(k)]
    return PRICING[max(matches, key=len)] if matches else None


def message_cost(model: str, usage: dict) -> float | None:
    rates = price(model)
    if rates is None:
        return None
    rate_in, rate_out, rate_read = rates
    creation = usage.get("cache_creation") or {}
    write_1h = creation.get("ephemeral_1h_input_tokens", 0) or 0
    write_5m = creation.get("ephemeral_5m_input_tokens")
    if write_5m is None:  # older logs only have the total
        write_5m = max((usage.get("cache_creation_input_tokens") or 0) - write_1h, 0)
    dollars = ((usage.get("input_tokens") or 0) * rate_in
               + (usage.get("output_tokens") or 0) * rate_out
               + (usage.get("cache_read_input_tokens") or 0) * rate_read
               + write_5m * rate_in * 1.25 + write_1h * rate_in * 2) / 1_000_000
    return dollars * (2 if usage.get("speed") == "fast" else 1)


def message_tokens(usage: dict) -> int:
    return sum(usage.get(k) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                           "cache_creation_input_tokens"))


@dataclass
class DayTotals:
    day: str = ""  # local date, YYYY-MM-DD
    tokens: int = 0
    cost: float = 0.0
    unpriced_tokens: int = 0  # models missing from PRICING
    by_model: dict[str, int] = field(default_factory=dict)


class TranscriptScanner:
    """Today's Claude Code token usage, read incrementally from the session logs.

    Replies are logged more than once while they stream (one line per content
    block, all carrying the same usage), so each message id counts once.
    """

    def __init__(self, root: Path, now=time.time):
        self.root = root
        self.now = now
        self.totals = DayTotals()
        self._offsets: dict[Path, int] = {}
        self._seen: set[str] = set()

    def scan(self) -> DayTotals:
        today = datetime.fromtimestamp(self.now()).date().isoformat()
        if today != self.totals.day:
            self.totals = DayTotals(day=today)
            self._seen.clear()
            self._offsets.clear()  # re-read today's files from the start
        start_of_day = datetime.fromisoformat(today).timestamp()
        for path in self.root.rglob("*.jsonl"):  # includes subagents/
            try:
                if path.stat().st_mtime < start_of_day:
                    continue
                self._read(path, today)
            except OSError:
                continue
        return self.totals

    def _read(self, path: Path, today: str) -> None:
        with path.open("rb") as f:
            f.seek(self._offsets.get(path, 0))
            while True:
                line = f.readline()
                if not line.endswith(b"\n"):
                    break  # partial line still being written; pick it up next time
                self._offsets[path] = f.tell()
                if b'"usage"' in line:
                    self._add(line, today)

    def _add(self, line: bytes, today: str) -> None:
        try:
            entry = json.loads(line)
        except ValueError:
            return
        message = entry.get("message") if isinstance(entry, dict) else None
        if entry.get("type") != "assistant" or not isinstance(message, dict):
            return
        usage, model, msg_id = message.get("usage"), message.get("model", ""), message.get("id")
        if not isinstance(usage, dict) or model == "<synthetic>" or not msg_id or msg_id in self._seen:
            return
        if not self._is_today(entry, today):
            return
        self._seen.add(msg_id)
        tokens = message_tokens(usage)
        self.totals.tokens += tokens
        self.totals.by_model[model] = self.totals.by_model.get(model, 0) + tokens
        cost = message_cost(model, usage)
        if cost is None:
            self.totals.unpriced_tokens += tokens
        else:
            self.totals.cost += cost

    @staticmethod
    def _is_today(entry: dict, today: str) -> bool:
        """Timestamps are UTC ("...Z"); compare in local time."""
        try:
            stamp = datetime.fromisoformat(str(entry["timestamp"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            return False
        return stamp.astimezone().date().isoformat() == today


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1000:.0f}k" if n >= 1000 else str(n)


def format_reset(resets_at: float | None, now: float) -> str:
    if resets_at is None:
        return ""
    when = datetime.fromtimestamp(resets_at)
    if resets_at - now < 24 * 3600:
        return when.strftime("%-I:%M%p").lower()
    return when.strftime("%a")


def usage_lines(windows: list[Window], received_at: float | None, totals: DayTotals | None,
                now: float) -> list[tuple] | None:
    """Bubble lines: a header, one labelled bar per plan window, then today's tokens."""
    lines = []
    if windows:
        header = "✳  Claude plan"
        if received_at is not None and now - received_at > 10 * 60:
            header += f" · as of {int((now - received_at) // 60)} min ago"
        lines.append((header, "title"))
        for w in windows:
            used = current_used(w, now)
            reset = format_reset(w.resets_at, now)
            lines.append((f"{w.name}  {used:.0f}%" + (f" · resets {reset}" if reset else ""), "bar", used / 100))
    if totals and totals.tokens:
        text = f"✳  Today {format_tokens(totals.tokens)} tokens"
        if totals.cost:
            text += f" · ~${totals.cost:.2f} at API rates"
        lines.append((text, "muted"))
    return lines or None
