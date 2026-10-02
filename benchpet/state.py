"""Decides what the pet should be doing. Pure logic: no Qt, clock is injected.

Persistent states live in channels, ordered by priority (away > agent > reading >
pomodoro > working > music > coding). A transient reaction (a oneshot activity)
plays over whatever is active. With nothing active the pet idles and occasionally
performs a random ambient gesture or a short walk; while coding it still makes the
odd coding-themed gesture, less often.
"""

from __future__ import annotations

import random
from typing import Callable

from benchpet.events import (
    AgentResponse, AwayChanged, CalendarReminder, ComputerActivity, CountdownReached, MusicChanged,
    NotificationReceived, TaskEvent, PomodoroPhaseEnded, PomodoroUpdated, WeatherUpdated)
from benchpet.sprites import Activity, SpriteLibrary

CHANNELS = ("away", "agent", "reading", "pomodoro", "working", "music", "coding")  # highest first
WORKING_TIMEOUT = 15 * 60  # forget a `working` that never got its `done`
FAILURE_WINDOW = 10 * 60  # failures this close together escalate: failed → frustrated → meltdown
CODING_ACTIVITIES = {"fresh": "coding", "tired": "coding_tired", "exhausted": "coding_exhausted"}


class StateManager:
    def __init__(
        self,
        library: SpriteLibrary,
        on_change: Callable[[Activity], None],
        now: Callable[[], float],
        rng: random.Random | None = None,
        ambient_interval: tuple[float, float] = (20, 60),
        walk_chance: float = 0.3,
        music_dance_interval: tuple[float, float] = (15, 40),
        reading_seconds: float = 20,
        weather_chance: float = 0.25,
        coding_ambient_interval: tuple[float, float] = (45, 120),
    ):
        self.library = library
        self.on_change = on_change
        self.now = now
        self.rng = rng or random.Random()
        self.ambient_interval = ambient_interval
        self.walk_chance = walk_chance
        self.music_dance_interval = music_dance_interval
        self.reading_seconds = reading_seconds
        self.weather_chance = weather_chance
        self.coding_ambient_interval = coding_ambient_interval
        self._failures: list[float] = []  # times of recent `failed` tasks
        self._tired_since_break = False
        self.weather: str | None = None  # current weather activity name

        self.channels: dict[str, str | None] = dict.fromkeys(CHANNELS)
        self._channel_until: dict[str, float] = {}  # expiry for timed channels
        self.reaction: str | None = None
        self.current: Activity | None = None
        self.music: MusicChanged | None = None
        self._next_ambient = self._schedule(self.ambient_interval)
        self._next_music_switch = 0.0

    def start(self) -> None:
        self._apply()

    # --- inputs ----------------------------------------------------------

    def handle(self, event: object) -> None:
        if isinstance(event, MusicChanged):
            self.music = event
            if event.playing:
                if self.channels["music"] is None:
                    self.channels["music"] = "music_listen"
                    self._next_music_switch = self._schedule(self.music_dance_interval)
            else:
                self.channels["music"] = None
            self._apply()
        elif isinstance(event, AwayChanged):
            was_away = self.channels["away"] is not None
            activity = {"short": "away_short", "long": "away_long"}.get(event.level)
            returning = was_away and event.level == "present"
            # Update silently before a reaction so the base state doesn't flash first.
            self.set_channel("away", activity, apply=not returning)
            if returning:
                self.react("refreshed" if self._tired_since_break else "greet")
                self._tired_since_break = False
        elif isinstance(event, NotificationReceived):
            if self.channels["away"]:
                return  # nobody's watching; the bubble still lists it
            if event.kind in ("email", "message"):
                self.set_channel("reading", "reading", duration=self.reading_seconds, apply=False)
                self.react("reading_react")
            else:
                self.react("surprised")
        elif isinstance(event, TaskEvent):
            if event.kind == "working":
                agent = f"agent_{event.message.strip().lower()}_working"
                activity = agent if agent in self.library.activities else "working"
                self.set_channel("working", activity, duration=WORKING_TIMEOUT)
                return
            reaction = {"done": "celebrate", "celebrate": "celebrate", "failed": "failed"}.get(event.kind)
            at_keyboard = self.channels["working"] or self.channels["coding"]
            if reaction == "celebrate" and at_keyboard:
                reaction = "coding_celebrate"
            if event.kind == "failed":
                reaction = self._failure_reaction()
            elif event.kind == "done":
                self._failures.clear()
            if event.kind != "celebrate":
                self.set_channel("working", None, apply=reaction is None)
            if reaction:
                self.react(reaction)
        elif isinstance(event, ComputerActivity):
            if event.tier != "fresh":
                self._tired_since_break = True
            activity = CODING_ACTIVITIES[event.tier] if event.mode == "coding" else None
            if activity != self.channels["coding"]:
                self.set_channel("coding", activity)
        elif isinstance(event, AgentResponse):
            # Only delivered when the reply should be shown (terminal not focused).
            agent = f"agent_{event.agent.lower()}"
            activity = agent if agent in self.library.activities else "agent_generic"
            self.set_channel("working", None, apply=False)
            self.set_channel("agent", activity, apply=False)
            self.react("ai_message")
        elif isinstance(event, CalendarReminder):
            if not self.channels["away"]:
                self.react("reminder")
        elif isinstance(event, PomodoroUpdated):
            activity = {"focus": "focus", "break": "pomodoro_break",
                        "long_break": "pomodoro_break"}.get(event.phase)
            if activity != self.channels["pomodoro"]:
                self.set_channel("pomodoro", activity)
        elif isinstance(event, PomodoroPhaseEnded):
            # Published just before the next phase's update, so the reaction plays first.
            self.react("tired" if event.ended == "focus" else "refreshed")
        elif isinstance(event, WeatherUpdated):
            activity = f"weather_{event.condition}"
            if activity not in self.library.activities:
                return
            changed = activity != self.weather
            self.weather = activity
            if changed and self._is_idle():
                self.react(activity)
        elif isinstance(event, CountdownReached):
            if not self.channels["away"]:
                self.react("celebrate")

    def set_channel(self, channel: str, activity: str | None, duration: float | None = None,
                    apply: bool = True) -> None:
        self.channels[channel] = activity
        if activity and duration:
            self._channel_until[channel] = self.now() + duration
        else:
            self._channel_until.pop(channel, None)
        if apply:
            self._apply()

    def react(self, activity: str) -> None:
        """Play a oneshot activity over the current state."""
        self.reaction = activity
        self._apply()

    def activity_finished(self, activity: Activity) -> None:
        """Called by the renderer when a oneshot activity has played through."""
        if self.reaction is not None and self.current is activity:
            self.reaction = None
            self._apply()

    def tick(self) -> None:
        now = self.now()
        for channel, until in list(self._channel_until.items()):
            if now >= until:
                self.set_channel(channel, None)
        if self.channels["music"] and now >= self._next_music_switch:
            self.channels["music"] = (
                "music_dance" if self.channels["music"] == "music_listen" else "music_listen"
            )
            self._next_music_switch = self._schedule(self.music_dance_interval)
            self._apply()
        if self._can_gesture() and now >= self._next_ambient:
            self.react(self._pick_ambient())

    # --- internals -------------------------------------------------------

    def target(self) -> str:
        if self.reaction:
            return self.reaction
        for channel in CHANNELS:
            if self.channels[channel]:
                return self.channels[channel]
        return "idle"

    def _is_idle(self) -> bool:
        return self.reaction is None and not any(self.channels.values())

    def _can_gesture(self) -> bool:
        """Idle, or coding with nothing more important going on."""
        return self.reaction is None and not any(
            activity for channel, activity in self.channels.items() if channel != "coding")

    def _failure_reaction(self) -> str:
        now = self.now()
        self._failures = [t for t in self._failures if now - t < FAILURE_WINDOW] + [now]
        return ("failed", "frustrated", "meltdown")[min(len(self._failures), 3) - 1]

    def _pick_ambient(self) -> str:
        if self.channels["coding"]:
            return self.rng.choice(self.library.ambient("coding")).name
        roll = self.rng.random()
        if roll < self.walk_chance:
            return "walk"
        if self.weather and roll < self.walk_chance + self.weather_chance:
            return self.weather
        return self.rng.choice(self.library.ambient()).name

    def _schedule(self, interval: tuple[float, float]) -> float:
        return self.now() + self.rng.uniform(*interval)

    def _apply(self) -> None:
        activity = self.library.get(self.target())
        if activity is not self.current:
            if self.reaction is None and self._can_gesture():
                # Settle into idle/coding for a while before the next ambient gesture.
                interval = self.coding_ambient_interval if self.channels["coding"] else self.ambient_interval
                self._next_ambient = self._schedule(interval)
            self.current = activity
            self.on_change(activity)
