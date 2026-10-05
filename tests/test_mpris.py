from benchpet.sources.mpris import parse_props


def test_parse_props_full():
    props = {
        "PlaybackStatus": "Playing",
        "Metadata": {"xesam:title": "Song", "xesam:artist": ["A", "B"],
                     "xesam:album": "LP", "mpris:artUrl": "file:///tmp/cover.png"},
    }
    assert parse_props(props) == ("Playing", "Song", "A, B", "LP", "file:///tmp/cover.png")


def test_parse_props_partial_update():
    assert parse_props({"PlaybackStatus": "Paused"}) == ("Paused", None, None, None, None)
    assert parse_props({"Metadata": {}}) == (None, "", "", "", "")


def test_media_command_targets_the_shown_player():
    from benchpet.events import EventBus, MediaCommand, MusicChanged
    from benchpet.sources.mpris import MprisSource

    calls = []

    class FakeDBus:
        def call(self, name, path, iface, method, *rest):
            calls.append((name, iface, method))

    bus = EventBus()
    src = MprisSource(bus)
    src._dbus = FakeDBus()
    src._last_published = MusicChanged("org.mpris.MediaPlayer2.test", "Playing", "Song")
    bus.publish(MediaCommand("next"))
    bus.publish(MediaCommand("play_pause"))
    bus.publish(MediaCommand("bogus"))
    assert calls == [("org.mpris.MediaPlayer2.test", "org.mpris.MediaPlayer2.Player", "Next"),
                     ("org.mpris.MediaPlayer2.test", "org.mpris.MediaPlayer2.Player", "PlayPause")]
