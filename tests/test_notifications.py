from benchpet.config import merge
from benchpet.sources.notifications import classify, strip_markup

EMAIL = ["thunderbird", "kmail"]
MESSAGE = ["slack", "signal"]


def test_classify_by_category_hint_first():
    assert classify("Whatever", "", "email.arrived", EMAIL, MESSAGE) == "email"
    assert classify("Whatever", "", "im.received", EMAIL, MESSAGE) == "message"


def test_classify_by_app_name_or_desktop_entry():
    assert classify("Thunderbird", "", "", EMAIL, MESSAGE) == "email"
    assert classify("", "com.slack.Slack", "", EMAIL, MESSAGE) == "message"
    assert classify("Discover", "org.kde.discover", "", EMAIL, MESSAGE) == "other"


def test_strip_markup():
    assert strip_markup("Hello <b>there</b> &amp; <a href='x'>you</a>") == "Hello there & you"
    assert strip_markup("line one<br/>line two") == "line one\nline two"


def test_config_merge_is_recursive():
    defaults = {"a": 1, "nested": {"x": 1, "y": 2}}
    assert merge(defaults, {"nested": {"y": 3}}) == {"a": 1, "nested": {"x": 1, "y": 3}}


def test_config_merge_does_not_share_default_objects():
    defaults = {"bubble": {"hidden": []}}
    merged = merge(defaults, {})
    merged["bubble"]["hidden"].append("weather")
    assert defaults["bubble"]["hidden"] == []


AI = {"claude": {"apps": ["claude"], "sites": ["claude.ai"]},
      "chatgpt": {"apps": ["chatgpt"], "sites": ["chatgpt.com"]}}


def test_ai_agent_from_desktop_app_and_browser_site():
    from benchpet.sources.notifications import ai_agent
    assert ai_agent("Claude", "", "Claude", "Here's the fix", AI) == "claude"
    assert ai_agent("ChatGPT", "", "", "Done", AI) == "chatgpt"
    assert ai_agent("Google Chrome", "", "New message", "chatgpt.com\nYour answer", AI) == "chatgpt"
    assert ai_agent("Chromium", "", "claude.ai", "Response ready", AI) == "claude"


def test_ai_agent_ignores_mentions_outside_browsers():
    from benchpet.sources.notifications import ai_agent
    assert ai_agent("Thunderbird", "", "Re: claude.ai pricing", "…", AI) is None
    assert ai_agent("Slack", "", "Bob", "have you tried Claude?", AI) is None


def test_ai_notification_becomes_agent_response_without_site_line():
    from benchpet.events import AgentResponse
    from benchpet.sources.notifications import NotificationSource

    class Bus:
        def __init__(self):
            self.events = []

        def publish(self, e):
            self.events.append(e)

    bus = Bus()
    src = NotificationSource(bus, [], [], [], AI)
    src._handle(("Google Chrome", 0, "", "ChatGPT", "chatgpt.com<br/>Here you go", [], {}, -1))
    assert bus.events == [AgentResponse("chatgpt", "Here you go")]
