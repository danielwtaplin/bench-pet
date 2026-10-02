"""AI agent responses: pull the reply out of agent hooks and tidy it for the speech bubble.

    Claude Code (Stop hook, payload on stdin):   bench-pet agent claude
    Codex (notify = [...] in config.toml, JSON as the last argument):
                                                 bench-pet agent codex '<json>'
"""

from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path

MAX_SEND = 4000  # chars sent over the socket; the bubble shows less
TRANSCRIPT_TAIL = 400  # JSONL lines read from the end of a Claude transcript


def claude_response(payload: dict) -> str:
    """The final assistant text for a Claude Code Stop hook payload."""
    text = payload.get("last_assistant_message")
    if isinstance(text, str) and text.strip():
        return text.strip()
    path = payload.get("transcript_path")
    if not path:
        return ""
    try:
        with open(Path(path).expanduser(), encoding="utf-8") as f:
            lines = deque(f, maxlen=TRANSCRIPT_TAIL)
    except OSError:
        return ""
    return last_assistant_text(lines)


def last_assistant_text(lines) -> str:
    """Text the assistant wrote after its last tool call in the latest turn."""
    texts: list[str] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("isSidechain"):
            continue  # subagent traffic
        kind = entry.get("type")
        content = (entry.get("message") or {}).get("content")
        if kind == "user":
            texts = []  # a new prompt or a tool result: what came before isn't the reply
            continue
        if kind != "assistant" or not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                texts = []
            elif block.get("type") == "text" and block.get("text", "").strip():
                texts.append(block["text"].strip())
    return "\n\n".join(texts)


def codex_response(payload: dict) -> str:
    if payload.get("type") not in (None, "agent-turn-complete"):
        return ""
    return str(payload.get("last-assistant-message") or "").strip()


def project_name(payload: dict) -> str:
    cwd = payload.get("cwd") or ""
    return Path(cwd).name if cwd else ""


def for_display(text: str, limit: int) -> str:
    """Markdown → compact plain text, truncated at a word boundary."""
    text = re.sub(r"```.*?(```|$)", "[code]", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]*", "", text, flags=re.M)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"^[ \t]*[-*+][ \t]+", "• ", text, flags=re.M)
    text = re.sub(r"^[ \t]*\|.*\|[ \t]*$", "", text, flags=re.M)  # tables don't fit a bubble
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "…"
