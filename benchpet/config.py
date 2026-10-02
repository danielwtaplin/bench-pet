"""User config at ~/.config/bench-pet/config.yaml, created with defaults on first run."""

from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bench-pet" / "config.yaml"

DEFAULTS = {
    "position": None,  # [x, y] of the window's top-left; None → bottom-right of the screen
    "height": 180,  # on-screen height of a standing pose, px
    "ambient_interval": [20, 60],  # seconds between random ambient gestures
    "walk_chance": 0.3,  # fraction of ambient picks that are a little walk instead
    "music_dance_interval": [15, 40],  # seconds between listen ↔ dance switches
    "sources": {"mpris": True, "idle": True, "notifications": True, "countdown": True, "calendar": True, "weather": True, "pomodoro": True,
                "activity": True},
    "countdown": {
        "label": "Weekend",
        "week_end": {"day": "friday", "time": "17:00"},
        "week_start": {"day": "monday", "time": "09:00"},
        "events": [],  # e.g. [{name: "Holiday", at: "2026-12-19 17:00"}]
    },
    "away": {
        "short_minutes": 5,  # no input for this long → coffee break
        "long_minutes": 30,  # → long absence
    },
    "activity": {
        "input_idle_seconds": 90,  # no keyboard/mouse for this long → no longer "typing"
        "focus_grace_seconds": 45,  # brief switches away from the editor don't stop coding
        "tired_minutes": 90,  # coding this long without a break → tired poses
        "exhausted_minutes": 150,  # → exhausted, and the bubble suggests a break
        "ambient_interval": [45, 120],  # seconds between gestures while coding
        # Matched (case-insensitively, as substrings) against the focused window's class.
        "coding_apps": ["konsole", "yakuake", "kitty", "alacritty", "wezterm", "foot", "ghostty",
                        "gnome-terminal", "ptyxis", "code", "codium", "cursor", "jetbrains", "zed",
                        "kate", "emacs", "neovide", "nvim"],
    },
    "calendar": {
        # ICS feeds: Google "Secret address in iCal format", Outlook "Publish calendar" ICS link,
        # or a local .ics path. e.g. [{name: Work, url: "https://outlook.office365.com/...ics"}]
        "feeds": [],
        "refresh_minutes": 15,
        "lookahead_hours": 36,
        "remind_minutes": 10,  # pet reacts and the bubble pops up this long before an event
        "show": 3,  # events listed in the bubble
    },
    "weather": {
        "location": None,  # e.g. "Wellington"; or set latitude/longitude instead
        "latitude": None,
        "longitude": None,
        "refresh_minutes": 30,
        "ambient_chance": 0.25,  # share of random gestures that reflect the weather
    },
    "pomodoro": {
        "focus_minutes": 25,
        "break_minutes": 5,
        "long_break_minutes": 15,
        "rounds_before_long_break": 4,
    },
    "bubble": {"hidden": []},  # info panel sections to leave out, e.g. [weather, countdown]
    "agent": {
        "only_when_unfocused": True,  # stay quiet if the agent's terminal is in front
        "max_chars": 600,  # reply text shown in the speech bubble
        "min_seconds": 12,  # bubble stays up for min + length/reading speed, capped at max
        "max_seconds": 60,
    },
    "notifications": {
        "reading_seconds": 20,  # how long the pet "reads" after an email/message
        "recent": 3,  # notifications listed in the bubble
        # Matched (case-insensitively) against the app name and desktop-entry hint.
        "email_apps": ["thunderbird", "betterbird", "kmail", "newmailnotifier", "evolution", "geary",
                       "mailspring"],
        "message_apps": ["slack", "teams", "signal", "discord", "telegram", "element", "whatsapp"],
        "ignore_apps": [],
        # Desktop/web AI apps: their notifications become speech-bubble replies.
        "ai_apps": {
            "claude": {"apps": ["claude"], "sites": ["claude.ai"]},
            "chatgpt": {"apps": ["chatgpt"], "sites": ["chatgpt.com", "chat.openai.com"]},
        },
    },
}


def merge(defaults: dict, data: dict) -> dict:
    """Overlay user data on defaults, recursing into nested sections."""
    out = copy.deepcopy(defaults)  # never hand out (and later mutate) the defaults themselves
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(defaults.get(key), dict):
            out[key] = merge(defaults[key], value)
        else:
            out[key] = value
    return out


class Config(dict):
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        data = {}
        if path.exists():
            data = yaml.safe_load(path.read_text()) or {}
        super().__init__(merge(DEFAULTS, data))
        if not path.exists():
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(yaml.safe_dump(dict(self), sort_keys=False))
