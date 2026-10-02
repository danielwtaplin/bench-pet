from benchpet.control import parse
from benchpet.events import TaskEvent


def test_parse_valid_and_invalid():
    assert parse(b'{"cmd": "done", "message": "ok"}\n') == TaskEvent("done", "ok")
    assert parse(b'{"cmd": "rm -rf"}') is None
    assert parse(b"not json") is None
    assert parse(b"[1, 2]") is None


def test_parse_agent():
    from benchpet.events import AgentResponse
    line = b'{"cmd": "agent", "message": "Hi", "agent": "claude", "project": "p", "pids": [3, "x", 2]}'
    assert parse(line) == AgentResponse("claude", "Hi", "p", (3, 2))
    assert parse(b'{"cmd": "agent", "message": "  "}') is None
