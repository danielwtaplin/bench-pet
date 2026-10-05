from benchpet.config import DEFAULTS
from benchpet.events import AwayChanged, ComputerActivity, FocusChanged, InputChanged
from benchpet.sources.activity import ActivitySource, is_browser_app, is_coding_app

from tests.test_pomodoro import Bus


def make():
    t = [0.0]
    bus = Bus()
    src = ActivitySource(bus, DEFAULTS["activity"], now=lambda: t[0])
    return src, bus, t


def last(bus) -> ComputerActivity:
    return [e for e in bus.events if isinstance(e, ComputerActivity)][-1]


def test_is_coding_app():
    apps = DEFAULTS["activity"]["coding_apps"]
    for app in ("org.kde.konsole", "code", "jetbrains-pycharm", "Alacritty", "dev.zed.Zed"):
        assert is_coding_app(app, apps), app
    for app in ("firefox", "org.kde.dolphin", "slack", ""):
        assert not is_coding_app(app, apps), app


def test_is_browser_app():
    apps = DEFAULTS["activity"]["browser_apps"]
    for app in ("firefox", "org.mozilla.firefox", "Chromium-browser", "google-chrome", "brave-browser"):
        assert is_browser_app(app, apps), app
    for app in ("code", "org.kde.konsole", "slack", ""):
        assert not is_browser_app(app, apps), app


def test_coding_needs_input_and_an_editor():
    src, bus, t = make()
    bus.publish(InputChanged(True))
    bus.publish(FocusChanged("org.kde.dolphin"))
    assert last(bus).mode == "idle"
    bus.publish(FocusChanged("org.kde.konsole"))
    assert last(bus).mode == "coding"
    bus.publish(InputChanged(False))
    assert last(bus).mode == "idle"


def test_no_input_info_judges_by_focus():
    src, bus, t = make()
    src._session_start = 0.0  # as start() does
    bus.publish(FocusChanged("code"))
    assert last(bus).mode == "coding"


def test_brief_switch_away_keeps_coding():
    src, bus, t = make()
    bus.publish(InputChanged(True))
    bus.publish(FocusChanged("code"))
    t[0] = 100
    bus.publish(FocusChanged("firefox"))  # grace runs from here, not from when code got focus
    t[0] = 140
    src.tick()
    assert last(bus).mode == "coding"
    t[0] = 146
    src.tick()
    assert last(bus).mode == "browsing"  # the lookup turned into browsing
    bus.publish(FocusChanged("org.kde.dolphin"))
    assert last(bus).mode == "idle"


def test_browsing_needs_input_and_a_browser():
    src, bus, t = make()
    bus.publish(InputChanged(True))
    bus.publish(FocusChanged("firefox"))
    assert last(bus).mode == "browsing"
    bus.publish(InputChanged(False))
    assert last(bus).mode == "idle"


def test_session_tiers_and_reset_on_break():
    src, bus, t = make()
    bus.publish(InputChanged(True))
    bus.publish(FocusChanged("code"))
    t[0] = 89 * 60
    src.tick()
    assert last(bus).tier == "fresh"
    t[0] = 90 * 60
    src.tick()
    assert (last(bus).tier, last(bus).session_minutes) == ("tired", 90)
    t[0] = 150 * 60
    src.tick()
    assert last(bus).tier == "exhausted"
    bus.publish(AwayChanged("short"))
    assert (last(bus).mode, last(bus).tier) == ("idle", "fresh")
    t[0] = 160 * 60
    bus.publish(AwayChanged("present"))
    bus.publish(InputChanged(True))
    t[0] = 161 * 60
    src.tick()
    assert (last(bus).mode, last(bus).tier, last(bus).session_minutes) == ("coding", "fresh", 1)


def test_publishes_only_on_change_or_each_minute():
    src, bus, t = make()
    bus.publish(InputChanged(True))
    count = len(bus.events)
    t[0] = 30
    src.tick()
    assert len(bus.events) == count
    t[0] = 60
    src.tick()
    assert len(bus.events) == count + 1
