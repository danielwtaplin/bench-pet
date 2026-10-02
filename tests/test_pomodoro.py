from benchpet.control import parse
from benchpet.events import PomodoroCommand, PomodoroPhaseEnded, PomodoroUpdated
from benchpet.sources.pomodoro import PomodoroSource


class Bus:
    """Synchronous stand-in for EventBus."""

    def __init__(self):
        self.events, self.handlers = [], []

    class _Sig:
        def __init__(self, bus):
            self.bus = bus

        def connect(self, fn):
            self.bus.handlers.append(fn)

    @property
    def event(self):
        return Bus._Sig(self)

    def publish(self, e):
        self.events.append(e)
        for h in self.handlers:
            h(e)


def make():
    t = [0.0]
    bus = Bus()
    src = PomodoroSource(bus, {"focus_minutes": 25, "break_minutes": 5, "long_break_minutes": 15,
                               "rounds_before_long_break": 2}, now=lambda: t[0])
    return src, bus, t


def test_cycle_with_long_break():
    src, bus, t = make()
    bus.publish(PomodoroCommand("start"))
    assert (src.phase, src.round) == ("focus", 1)
    t[0] = 25 * 60
    src.tick()
    assert PomodoroPhaseEnded("focus", "break") in bus.events
    assert src.phase == "break"
    t[0] += 5 * 60
    src.tick()
    assert (src.phase, src.round) == ("focus", 2)
    t[0] += 25 * 60
    src.tick()
    assert src.phase == "long_break"  # every 2nd round here


def test_skip_and_stop():
    src, bus, t = make()
    bus.publish(PomodoroCommand("start"))
    bus.publish(PomodoroCommand("skip"))
    assert src.phase == "break"
    bus.publish(PomodoroCommand("stop"))
    assert src.phase is None
    assert bus.events[-1] == PomodoroUpdated(None, 0.0, 1)


def test_control_parses_pomodoro():
    assert parse(b'{"cmd": "pomodoro", "message": "start"}') == PomodoroCommand("start")
    assert parse(b'{"cmd": "pomodoro", "message": "explode"}') is None
