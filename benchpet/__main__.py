"""Entry point.

    bench-pet                      run the pet
    bench-pet <command> [message]  send a command to the running pet (see control.py)
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from collections import deque

# Run under XWayland: Wayland doesn't let clients position their own windows,
# which the pet needs for dragging and walking. Layer-shell is a later option.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from benchpet.config import Config  # noqa: E402
from benchpet import control  # noqa: E402
from benchpet.sources.weather import ICONS  # noqa: E402
from benchpet.events import (  # noqa: E402
    CalendarReminder, CalendarUpdated, ComputerActivity, CountdownsUpdated, EventBus, FocusChanged, MusicChanged,
    PlanUsage, TokenUsage,
    AgentResponse, MediaCommand, NotificationReceived, PomodoroCommand, PomodoroPhaseEnded, PomodoroUpdated, TaskEvent,
    WeatherUpdated)
from benchpet.sprites import load_library  # noqa: E402
from benchpet.state import StateManager  # noqa: E402
from benchpet.window import PetWindow  # noqa: E402


def music_lines(event: MusicChanged) -> list[tuple[str, str]] | None:
    if event.status == "Stopped" or not event.title:
        return None
    icon = "▶" if event.playing else "⏸"
    lines = [(f"{icon}  {event.title}", "title")]
    if event.artist:
        lines.append((event.artist, "muted"))
    return lines


KIND_ICONS = {"email": "✉", "message": "💬", "other": "🔔"}


def notification_lines(recent: deque) -> list[tuple[str, str]]:
    lines = []
    for i, n in enumerate(reversed(recent)):
        lines.append((f"{KIND_ICONS[n.kind]}  {n.app}: {n.summary}", "title"))
        if i == 0 and n.body:  # preview only the newest, to keep the bubble small
            preview = n.body.replace("\n", " ")
            lines.append((preview[:90] + ("…" if len(preview) > 90 else ""), "muted"))
    return lines


def countdown_lines(event: CountdownsUpdated) -> list[tuple[str, str]]:
    from benchpet.sources.countdown import format_remaining
    return [(f"🎉  {name}!" if left is None else f"⏳  {name} in {format_remaining(left)}", "muted")
            for name, left in event.items]


TASK_LINES = {"working": "🛠  Working", "done": "✅  Done", "failed": "❌  Failed"}
TASK_RESULT_SECONDS = 120  # how long a done/failed line stays in the bubble


def task_lines(event: TaskEvent) -> list[tuple[str, str]] | None:
    if event.kind not in TASK_LINES:
        return None
    text = TASK_LINES[event.kind] + (f": {event.message}" if event.message else "")
    return [(text, "title" if event.kind == "working" else "muted")]


REMINDER_FLASH_SECONDS = 12
AGENT_NAMES = {"claude": "✳  Claude", "codex": "◎  Codex", "chatgpt": "◎  ChatGPT"}
READING_CHARS_PER_SECOND = 20
POMODORO_LABELS = {"focus": "🍅  Focus", "break": "☕  Break", "long_break": "☕  Long break"}


def pomodoro_lines(event: PomodoroUpdated) -> list[tuple[str, str]] | None:
    if event.phase is None:
        return None
    minutes = max(1, round(event.remaining / 60))
    return [(f"{POMODORO_LABELS[event.phase]} · {minutes} min left (round {event.round})", "title")]


def activity_lines(event: ComputerActivity) -> list[tuple[str, str]] | None:
    if event.tier == "fresh":
        return None
    hours, minutes = divmod(int(event.session_minutes), 60)
    text = f"⏱  {hours}h {minutes:02d}m without a break"
    return [(text + (" · time for one?" if event.tier == "exhausted" else ""), "muted")]


def run_agent_command(args: list[str]) -> int:
    """`bench-pet agent <name> [json|text]`: forward an agent's reply to the pet.

    Always exits 0 so a misbehaving pet never breaks the agent's hook.
    """
    import json

    from benchpet.agent import MAX_SEND, claude_response, codex_response, project_name
    from benchpet.focus import ancestor_pids

    name = args[0] if args else "agent"
    raw = " ".join(args[1:]) if len(args) > 1 else ("" if sys.stdin.isatty() else sys.stdin.read())
    try:
        payload = json.loads(raw) if raw.strip().startswith("{") else None
    except ValueError:
        payload = None
    if payload is None:
        text, project = raw.strip(), ""
    elif name == "codex":
        text, project = codex_response(payload), project_name(payload)
    else:
        text, project = claude_response(payload), project_name(payload)
    if text:
        control.send("agent", text[:MAX_SEND], agent=name, project=project,
                     pids=ancestor_pids()[1:])  # skip our own short-lived PID
    return 0


def run_statusline_command(args: list[str]) -> int:
    """`bench-pet statusline [-- command...]`: Claude Code statusLine.

    Forwards the plan usage windows to the pet, then prints a short status line, or
    hands the payload to `command` and prints whatever it prints. Never fails.
    """
    import json
    import subprocess
    from dataclasses import asdict

    from benchpet.usage import STATUSLINE_DUMP, parse_rate_limits, statusline_text

    raw = "" if sys.stdin.isatty() else sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    try:  # last payload, for checking what Claude Code sends
        STATUSLINE_DUMP.write_text(raw)
    except OSError:
        pass
    windows = parse_rate_limits(payload)
    if windows:
        control.send("usage", agent="claude", windows=[asdict(w) for w in windows])
    chained = args[1:] if args[:1] == ["--"] else []
    if chained:
        try:
            result = subprocess.run(chained, input=raw, capture_output=True, text=True, timeout=5)
            sys.stdout.write(result.stdout)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        print(statusline_text(payload, windows))
    return 0


def run_command(args: list[str]) -> int:
    if args[0] == "agent":
        return run_agent_command(args[1:])
    if args[0] == "statusline":
        return run_statusline_command(args[1:])
    cmd, message = args[0], " ".join(args[1:])
    if cmd not in control.COMMANDS or (cmd == "pomodoro" and message not in control.POMODORO_ACTIONS):
        print(f"usage: bench-pet [{'|'.join(control.COMMANDS)}] [message]\n"
              f"       bench-pet pomodoro [{'|'.join(control.POMODORO_ACTIONS)}]", file=sys.stderr)
        return 2
    if not control.send(cmd, message):
        print("bench-pet: the pet isn't running", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        return run_command(sys.argv[1:])
    if control.is_running():
        print("bench-pet: already running", file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("bench-pet")
    app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    config = Config()
    library = load_library()
    bus = EventBus()
    window = PetWindow(library, config)

    state = StateManager(
        library,
        on_change=window.set_activity,
        now=time.monotonic,
        ambient_interval=tuple(config["ambient_interval"]),
        walk_chance=config["walk_chance"],
        music_dance_interval=tuple(config["music_dance_interval"]),
        reading_seconds=config["notifications"]["reading_seconds"],
        weather_chance=config["weather"]["ambient_chance"],
        coding_ambient_interval=tuple(config["activity"]["ambient_interval"]),
        usage_react_percent=config["usage"]["react_at_percent"],
    )
    window.pet.activity_finished.connect(state.activity_finished)
    window.on_celebrate = lambda: state.react("celebrate")
    window.on_pomodoro = lambda action: bus.publish(PomodoroCommand(action))
    window.on_media = lambda action: bus.publish(MediaCommand(action))
    # Agent replies go through on_agent, which decides whether to show them.
    bus.event.connect(lambda e: isinstance(e, AgentResponse) or state.handle(e))

    from benchpet.agent import for_display
    from benchpet.focus import FocusTracker
    focus = FocusTracker()
    agent_conf = config["agent"]
    speaking: list[AgentResponse] = []  # the reply currently in the speech bubble

    def on_agent(e) -> None:
        if not isinstance(e, AgentResponse):
            return
        if agent_conf["only_when_unfocused"] and focus.is_focused(list(e.pids)):
            state.handle(TaskEvent("clear"))  # you're looking at it already
            return
        state.handle(e)
        speaking[:] = [e]
        text = for_display(e.text, agent_conf["max_chars"])
        header = AGENT_NAMES.get(e.agent.lower(), f"🤖  {e.agent.title()}")
        if e.project:
            header += f" · {e.project}"
        seconds = min(agent_conf["min_seconds"] + len(text) / READING_CHARS_PER_SECOND,
                      agent_conf["max_seconds"])
        window.say(header, text, seconds, can_open=bool(e.pids) and focus.available)
    bus.event.connect(on_agent)

    window.speech.on_click = lambda: speaking and focus.activate(list(speaking[0].pids))
    window.speech.on_dismiss = lambda: (speaking.clear(), state.set_channel("agent", None))

    def on_focus_change() -> None:
        bus.publish(FocusChanged(focus.active_class))
        # Switching to the agent's terminal answers the bubble.
        if speaking and window.speech.isVisible() and focus.is_focused(list(speaking[0].pids)):
            window.speech.dismiss()
    focus.on_change = on_focus_change
    def on_music(e) -> None:
        if isinstance(e, MusicChanged):
            window.music = e
            window.set_bubble_section("music", music_lines(e))
    bus.event.connect(on_music)
    recent: deque[NotificationReceived] = deque(maxlen=config["notifications"]["recent"])

    def on_notification(e) -> None:
        if isinstance(e, NotificationReceived):
            recent.append(e)
            window.set_bubble_section("notifications", notification_lines(recent))
    bus.event.connect(on_notification)
    task_clear = QTimer(singleShot=True)
    task_clear.timeout.connect(lambda: window.set_bubble_section("task", None))

    def on_task(e) -> None:
        if not isinstance(e, TaskEvent) or e.kind == "celebrate":
            return
        window.set_bubble_section("task", task_lines(e))
        if e.kind in ("done", "failed"):
            task_clear.start(TASK_RESULT_SECONDS * 1000)
        else:
            task_clear.stop()
    bus.event.connect(on_task)
    def has_feeds() -> bool:
        return bool(config["sources"].get("calendar") and config["calendar"]["feeds"])
    window.calendar.set_events((), has_feeds())
    calendar_events: list = []

    def on_calendar(e) -> None:
        if isinstance(e, CalendarUpdated):
            calendar_events[:] = e.events
            window.calendar.set_events(e.events, has_feeds())
    bus.event.connect(on_calendar)
    bus.event.connect(lambda e: isinstance(e, CalendarReminder)
                      and window.flash_bubble(REMINDER_FLASH_SECONDS))
    def on_pomodoro(e) -> None:
        if isinstance(e, PomodoroUpdated):
            window.pomodoro_phase = e.phase
            window.set_bubble_section("pomodoro", pomodoro_lines(e))
        elif isinstance(e, PomodoroPhaseEnded):
            window.flash_bubble(REMINDER_FLASH_SECONDS)
    bus.event.connect(on_pomodoro)
    bus.event.connect(lambda e: isinstance(e, WeatherUpdated) and window.set_bubble_section(
        "weather", [(f"{ICONS.get(e.condition, '')}  {e.temperature:.0f}°C · {e.description}",
                     "muted")]))
    bus.event.connect(lambda e: isinstance(e, ComputerActivity)
                      and window.set_bubble_section("activity", activity_lines(e)))
    from benchpet.usage import usage_lines
    usage = {"windows": [], "received_at": None, "totals": None}

    def show_usage() -> None:
        window.set_bubble_section("usage", usage_lines(usage["windows"], usage["received_at"],
                                                       usage["totals"], time.time()))

    def on_usage(e) -> None:
        if isinstance(e, PlanUsage):
            usage.update(windows=list(e.windows), received_at=e.received_at or time.time())
        elif isinstance(e, TokenUsage):
            usage["totals"] = e.totals
        else:
            return
        show_usage()
    bus.event.connect(on_usage)
    usage_refresh = QTimer()  # keep "resets"/"as of" current between reports
    usage_refresh.timeout.connect(show_usage)
    usage_refresh.start(60_000)
    bus.event.connect(lambda e: isinstance(e, CountdownsUpdated)
                      and window.set_bubble_section("countdown", countdown_lines(e)))

    ticker = QTimer()
    ticker.timeout.connect(state.tick)
    ticker.start(250)  # also lets Python handle SIGINT promptly

    sources = [control.ControlSource(bus)]
    if config["sources"].get("mpris"):
        from benchpet.sources.mpris import MprisSource
        sources.append(MprisSource(bus))
    if config["sources"].get("idle"):
        from benchpet.sources.idle import IdleSource
        away = config["away"]
        input_seconds = config["activity"]["input_idle_seconds"] if config["sources"].get("activity") else None
        sources.append(IdleSource(bus, away["short_minutes"], away["long_minutes"], input_seconds))
    if config["sources"].get("activity"):
        from benchpet.sources.activity import ActivitySource
        sources.append(ActivitySource(bus, config["activity"]))
    if config["sources"].get("notifications"):
        from benchpet.sources.notifications import NotificationSource
        n = config["notifications"]
        sources.append(NotificationSource(bus, n["email_apps"], n["message_apps"], n["ignore_apps"],
                                          n["ai_apps"]))
    if config["sources"].get("countdown"):
        from benchpet.sources.countdown import CountdownSource
        sources.append(CountdownSource(bus, config["countdown"]))
    if config["sources"].get("pomodoro"):
        from benchpet.sources.pomodoro import PomodoroSource
        sources.append(PomodoroSource(bus, config["pomodoro"]))
    if config["sources"].get("weather"):
        from benchpet.sources.weather import WeatherSource
        sources.append(WeatherSource(bus, config["weather"]))
    if config["sources"].get("calendar"):
        from benchpet.sources.calendar import CalendarSource
        calendar_source = CalendarSource(bus, config["calendar"])
        sources.append(calendar_source)
    else:
        calendar_source = None

    def on_settings_applied(changed: set[str]) -> None:
        window.apply_settings()
        if "calendar" in changed and calendar_source:
            calendar_source.reconfigure(config["calendar"])
        window.calendar.set_events(calendar_events, has_feeds())

    def open_settings() -> None:
        from benchpet.settings import SettingsDialog
        SettingsDialog(config, on_settings_applied).exec()
    window.on_settings = open_settings
    if config["sources"].get("usage"):
        from benchpet.sources.usage import UsageSource
        sources.append(UsageSource(bus, config["usage"]))
    for source in sources:
        source.start()

    focus.start()
    state.start()
    window.show()
    code = app.exec()
    focus.stop()
    for source in sources:
        source.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
