import random

import pytest

from benchpet.events import (
    AgentResponse, AwayChanged, CalendarReminder, ComputerActivity, LogTailUpdated, MusicChanged, MusicGenre, NotificationReceived, PomodoroPhaseEnded,
    PomodoroUpdated, TaskEvent, WeatherUpdated)
from benchpet.sprites import load_library
from benchpet.state import music_style
from benchpet.state import StateManager


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def setup():
    library = load_library()
    clock = Clock()
    changes = []
    state = StateManager(library, changes.append, now=clock, rng=random.Random(1),
                         ambient_interval=(10, 10), walk_chance=0.0,
                         music_dance_interval=(20, 20), coding_ambient_interval=(30, 30))
    state.start()
    return state, clock, changes


def playing(status="Playing"):
    return MusicChanged("org.mpris.MediaPlayer2.test", status, "Song", "Artist")


def test_starts_idle(setup):
    state, _, changes = setup
    assert [a.name for a in changes] == ["idle"]


def test_music_overrides_idle_and_stops_back_to_idle(setup):
    state, _, changes = setup
    state.handle(playing())
    assert state.current.name == "music_listen"
    state.handle(playing("Paused"))
    assert state.current.name == "idle"


def test_music_alternates_listen_and_dance(setup):
    state, clock, _ = setup
    state.handle(playing())
    clock.t = 20
    state.tick()
    assert state.current.name == "music_dance"
    clock.t = 40
    state.tick()
    assert state.current.name == "music_listen"


def test_music_style_from_genres():
    assert music_style(("brutal death metal", "death metal")) == "metal"
    assert music_style(("east coast hip hop",)) == "hiphop"
    assert music_style(("gangsta rap",)) == music_style(("hip-hop",)) == "hiphop"
    assert music_style(("trance", "drum and bass")) is None  # "rap" only as a word
    assert music_style(()) is None


def test_genre_switches_music_to_its_outfit_until_the_track_changes(setup):
    state, clock, _ = setup
    state.handle(playing())
    state.handle(MusicGenre("Song", "Artist", ("death metal",)))
    assert state.current.name == "music_metal_listen"
    clock.t = 20
    state.tick()
    assert state.current.name == "music_metal_dance"
    state.handle(MusicGenre("Old song", "Artist", ("hip hop",)))  # stale lookup: ignored
    assert state.current.name == "music_metal_dance"
    state.handle(playing("Paused"))
    state.handle(playing())  # same track resumed: keeps its style
    assert state.current.name == "music_metal_listen"
    state.handle(MusicChanged("org.mpris.MediaPlayer2.test", "Playing", "Next", "Rapper"))
    assert state.current.name == "music_listen"  # generic until the new genre arrives
    state.handle(MusicGenre("Next", "Rapper", ("hip hop", "rap")))
    assert state.current.name == "music_hiphop_listen"
    state.handle(MusicChanged("org.mpris.MediaPlayer2.test", "Playing", "Ballad", "Singer"))
    state.handle(MusicGenre("Ballad", "Singer", ("pop",)))
    assert state.current.name == "music_listen"


def test_ambient_gesture_fires_when_idle_and_returns_to_idle(setup):
    state, clock, _ = setup
    clock.t = 9
    state.tick()
    assert state.current.name == "idle"
    clock.t = 10
    state.tick()
    gesture = state.current
    assert gesture.ambient
    state.activity_finished(gesture)
    assert state.current.name == "idle"


def test_no_ambient_while_music_plays(setup):
    state, clock, _ = setup
    state.handle(playing())
    clock.t = 15
    state.tick()
    assert state.current.name == "music_listen"


def test_priority_away_over_reading_over_music(setup):
    state, _, _ = setup
    state.handle(playing())
    state.set_channel("reading", "reading")
    assert state.current.name == "reading"
    state.set_channel("away", "away_short")
    assert state.current.name == "away_short"
    state.set_channel("away", None)
    state.set_channel("reading", None)
    assert state.current.name == "music_listen"


def test_reaction_plays_over_channel_then_resumes(setup):
    state, _, _ = setup
    state.handle(playing())
    state.react("celebrate")
    assert state.current.name == "celebrate"
    state.activity_finished(state.current)
    assert state.current.name == "music_listen"


def test_stale_finish_is_ignored(setup):
    state, _, _ = setup
    state.react("wave")
    wave = state.current
    state.react("celebrate")
    state.activity_finished(wave)
    assert state.current.name == "celebrate"


def test_away_long_falls_back_to_coffee(setup):
    state, _, _ = setup
    state.set_channel("away", "away_long")
    assert state.current.poses and state.current.poses[0].key.startswith("coffee/")


def note(kind="email"):
    return NotificationReceived("Thunderbird", "Subject", "Body", kind)


def test_email_reacts_then_reads_until_expiry(setup):
    state, clock, _ = setup
    state.handle(note())
    assert state.current.name == "reading_react"
    state.activity_finished(state.current)
    assert state.current.name == "reading"
    clock.t = 19
    state.tick()
    assert state.current.name == "reading"
    clock.t = 20
    state.tick()
    assert state.current.name == "idle"


def test_other_notification_is_a_brief_surprise(setup):
    state, _, _ = setup
    state.handle(note("other"))
    assert state.current.name == "surprised"
    state.activity_finished(state.current)
    assert state.current.name == "idle"


def test_away_tiers_and_greets_on_return(setup):
    state, _, _ = setup
    state.handle(AwayChanged("short"))
    assert state.current.name == "away_short"
    state.handle(AwayChanged("long"))
    assert state.current.poses[0].key.startswith("coffee/")  # away_long falls back
    state.handle(AwayChanged("present"))
    assert state.current.name == "greet"
    state.activity_finished(state.current)
    assert state.current.name == "idle"


def test_notifications_dont_react_while_away(setup):
    state, _, _ = setup
    state.handle(AwayChanged("short"))
    state.handle(note())
    assert state.current.name == "away_short"
    assert state.channels["reading"] is None


def test_reactions_dont_flash_the_base_state_first(setup):
    state, _, changes = setup
    state.handle(note())
    state.activity_finished(state.current)
    state.handle(AwayChanged("short"))
    state.handle(AwayChanged("present"))
    names = [a.name for a in changes]
    assert names == ["idle", "reading_react", "reading", "away_short", "greet"]


def test_working_then_done_celebrates_and_returns(setup):
    state, _, changes = setup
    state.handle(playing())
    state.handle(TaskEvent("working", "Refactor"))
    assert state.current.name == "working"  # working beats music
    state.handle(TaskEvent("done"))
    assert state.current.name == "coding_celebrate"
    state.activity_finished(state.current)
    assert state.current.name == "music_listen"
    assert "working" not in [a.name for a in changes[-2:]]  # no flash back to working


def test_failed_facepalms_and_working_times_out(setup):
    state, clock, _ = setup
    state.handle(TaskEvent("working"))
    state.handle(TaskEvent("failed"))
    assert state.current.name == "failed"
    state.activity_finished(state.current)
    state.handle(TaskEvent("working"))
    clock.t = 15 * 60
    state.tick()
    assert state.current.name == "idle"


def test_calendar_reminder_reacts_unless_away(setup):
    state, _, _ = setup
    state.handle(CalendarReminder(None))
    assert state.current.name == "reminder"
    state.activity_finished(state.current)
    state.handle(AwayChanged("short"))
    state.handle(CalendarReminder(None))
    assert state.current.name == "away_short"


def test_weather_change_reacts_once_and_joins_ambient(setup):
    state, clock, _ = setup
    state.handle(WeatherUpdated("rain", 12, "Rain"))
    assert state.current.name == "weather_rain"
    state.activity_finished(state.current)
    state.handle(WeatherUpdated("rain", 11, "Rain"))  # same condition: no reaction
    assert state.current.name == "idle"
    state.weather_chance = 1.0
    clock.t = 100
    state.tick()
    assert state.current.name == "weather_rain"


def test_pomodoro_focus_break_reactions_without_flashes(setup):
    state, _, changes = setup
    state.handle(PomodoroUpdated("focus", 1500, 1))
    assert state.current.name == "focus"
    state.handle(PomodoroPhaseEnded("focus", "break"))
    state.handle(PomodoroUpdated("break", 300, 1))
    assert state.current.name == "tired"
    state.activity_finished(state.current)
    assert state.current.name == "pomodoro_break"
    state.handle(PomodoroUpdated(None, 0, 1))
    assert state.current.name == "idle"
    assert [a.name for a in changes] == ["idle", "focus", "tired", "pomodoro_break", "idle"]


def test_agent_reply_reacts_then_shows_agent_poses(setup):
    state, _, changes = setup
    state.handle(TaskEvent("working", "Claude"))
    assert state.current.name == "agent_claude_working"
    state.handle(AgentResponse("claude", "All done"))
    assert state.current.name == "ai_message"
    state.activity_finished(state.current)
    assert state.current.name == "agent_claude"
    assert state.channels["working"] is None
    state.set_channel("agent", None)  # speech bubble dismissed
    assert state.current.name == "idle"
    state.handle(AgentResponse("gemini", "Hi"))
    state.activity_finished(state.current)
    assert state.current.name == "agent_generic"


def coding(tier="fresh", minutes=0.0):
    return ComputerActivity("coding", tier, minutes)


def test_coding_is_lowest_priority(setup):
    state, _, _ = setup
    state.handle(coding())
    assert state.current.name == "coding"
    state.handle(playing())
    assert state.current.name == "music_listen"
    state.handle(TaskEvent("working"))
    assert state.current.name == "working"
    state.handle(TaskEvent("clear"))
    state.handle(playing("Paused"))
    assert state.current.name == "coding"
    state.handle(ComputerActivity("idle", "fresh", 0))
    assert state.current.name == "idle"


def test_coding_gestures_come_from_the_coding_group_less_often(setup):
    state, clock, _ = setup
    state.handle(coding())
    clock.t = 29
    state.tick()
    assert state.current.name == "coding"
    clock.t = 30
    state.tick()
    gesture = state.current
    assert gesture.ambient == "coding"
    state.activity_finished(gesture)
    assert state.current.name == "coding"
    clock.t = 59
    state.tick()
    assert state.current.name == "coding"  # rescheduled from when it settled back


def browsing(tier="fresh", minutes=0.0):
    return ComputerActivity("browsing", tier, minutes)


def test_browsing_has_its_own_poses_gestures_and_tiers(setup):
    state, clock, _ = setup
    state.handle(browsing())
    assert state.current.name == "browsing"
    clock.t = 30
    state.tick()
    assert state.current.ambient == "browsing"
    state.activity_finished(state.current)
    state.handle(TaskEvent("celebrate"))
    assert state.current.name == "browsing_celebrate"
    state.activity_finished(state.current)
    state.handle(browsing("tired", 90))
    assert state.current.name == "browsing_tired"
    state.handle(coding("tired", 91))
    assert state.current.name == "coding_tired"
    state.handle(browsing("exhausted", 150))
    assert state.current.name == "browsing_exhausted"


def test_long_sessions_get_tired_then_refreshed_after_a_break(setup):
    state, _, _ = setup
    state.handle(coding("tired", 90))
    assert state.current.name == "coding_tired"
    state.handle(coding("exhausted", 150))
    assert state.current.name == "coding_exhausted"
    state.handle(AwayChanged("short"))
    state.handle(ComputerActivity("idle", "fresh", 0))  # the session resets while away
    state.handle(AwayChanged("present"))
    assert state.current.name == "refreshed"
    state.activity_finished(state.current)
    state.handle(AwayChanged("short"))
    state.handle(AwayChanged("present"))
    assert state.current.name == "greet"  # a fresh session gets the normal welcome


def test_repeated_failures_escalate_and_done_resets(setup):
    state, clock, _ = setup
    reactions = []
    for _ in range(4):
        state.handle(TaskEvent("failed"))
        reactions.append(state.current.name)
        state.activity_finished(state.current)
    assert reactions == ["failed", "frustrated", "meltdown", "meltdown"]
    state.handle(TaskEvent("done"))
    state.activity_finished(state.current)
    state.handle(TaskEvent("failed"))
    assert state.current.name == "failed"
    state.activity_finished(state.current)
    clock.t = 11 * 60  # an old failure doesn't count
    state.handle(TaskEvent("failed"))
    assert state.current.name == "failed"


def plan(used, window="5h", resets_at=None):
    from benchpet.events import PlanUsage
    from benchpet.usage import Window
    return PlanUsage("claude", (Window(window, used, resets_at),))


def test_plan_usage_reacts_when_crossing_the_threshold_and_on_reset(setup):
    state, _, _ = setup
    state.handle(plan(95))  # first report: no crossing to react to, but already stressed
    assert state.current.name == "usage_stressed"
    state.handle(plan(20))
    assert state.current.name == "refreshed"
    state.activity_finished(state.current)
    state.handle(plan(60))
    assert state.current.name == "idle"
    state.handle(plan(91))
    assert state.current.name == "usage_low"
    state.activity_finished(state.current)
    assert state.current.name == "usage_stressed"
    state.handle(plan(93))  # still over: no repeat
    assert state.current.name == "usage_stressed"
    state.handle(AwayChanged("short"))
    state.handle(plan(5))
    assert state.current.name == "away_short"  # nobody's watching
    state.handle(AwayChanged("present"))
    state.activity_finished(state.current)
    assert state.current.name == "idle"  # the reset cleared the stress while away


def test_over_the_usage_threshold_stress_replaces_idle_and_coding(setup):
    state, clock, _ = setup
    state.handle(plan(95))  # already over at startup: stressed, but no crossing reaction
    assert state.current.name == "usage_stressed"
    state.handle(coding())
    assert state.current.name == "usage_stressed"  # stress outranks coding
    clock.t = 1000
    state.tick()
    assert state.current.name == "usage_stressed"  # no ambient gestures while stressed
    state.handle(PomodoroUpdated("break", 300, 1))
    assert state.current.name == "pomodoro_break"  # breaks still show
    state.handle(PomodoroUpdated(None, 0, 1))
    assert state.current.name == "usage_stressed"
    state.handle(plan(40))
    assert state.current.name == "refreshed"
    state.activity_finished(state.current)
    assert state.current.name == "coding"


def test_stress_ends_when_the_window_resets_without_a_new_report(setup):
    state, _, _ = setup
    wall = [1000.0]
    state.wall_clock = lambda: wall[0]
    state.handle(plan(97, resets_at=2000.0))
    assert state.current.name == "usage_stressed"
    wall[0] = 2001.0
    state.tick()
    assert state.current.name == "idle"


def test_usage_stress_is_off_without_a_threshold(setup):
    state, _, _ = setup
    state.usage_react_percent = None
    state.handle(plan(99))
    assert state.current.name == "idle"


def log_lines(appended, path="/var/log/app.log"):
    return LogTailUpdated(path, ("a", "b"), appended)


def test_new_log_lines_take_notes_for_a_while(setup):
    state, clock, _ = setup
    state.handle(log_lines(0))  # what was in the file already
    assert state.current.name == "idle"
    state.handle(log_lines(2))
    assert state.current.name == "logging"
    clock.t += 20
    state.handle(log_lines(1))  # keeps going while lines keep coming
    clock.t += 20
    state.tick()
    assert state.current.name == "logging"
    clock.t += 15
    state.tick()
    assert state.current.name == "idle"


def test_logging_wears_headphones_over_music(setup):
    state, _, _ = setup
    state.handle(playing())
    state.handle(log_lines(1))
    assert state.current.name == "logging_music"
    state.handle(playing("Paused"))
    assert state.current.name == "logging"


def test_logging_quiet_while_away_off_at_zero_and_stops_with_the_file(setup):
    state, _, _ = setup
    state.handle(AwayChanged("short"))
    state.handle(log_lines(3))
    assert state.channels["logging"] is None
    state.handle(AwayChanged("present"))
    state.logging_seconds = 0
    state.handle(log_lines(3))
    assert state.channels["logging"] is None
    state.logging_seconds = 30
    state.handle(log_lines(3))
    state.handle(LogTailUpdated("", (), 0))  # path cleared in Settings
    assert state.channels["logging"] is None
