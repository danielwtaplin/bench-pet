import json

from benchpet.agent import claude_response, codex_response, for_display, last_assistant_text


def line(**entry):
    return json.dumps(entry)


def assistant(*blocks, **extra):
    return line(type="assistant", message={"role": "assistant", "content": list(blocks)}, **extra)


TRANSCRIPT = [
    line(type="user", message={"role": "user", "content": "do the thing"}),
    assistant({"type": "text", "text": "Looking into it."},
              {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}),
    line(type="user", message={"role": "user", "content": [{"type": "tool_result"}]}),
    assistant({"type": "text", "text": "Subagent chatter"}, isSidechain=True),
    assistant({"type": "text", "text": "Done: all **tests** pass."}),
    assistant({"type": "text", "text": "Anything else?"}),
    line(type="last-prompt", lastPrompt="x"),
]


def test_last_assistant_text_takes_text_after_last_tool_call():
    assert last_assistant_text(TRANSCRIPT) == "Done: all **tests** pass.\n\nAnything else?"


def test_claude_response_prefers_payload_field(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(TRANSCRIPT) + "\n")
    assert claude_response({"last_assistant_message": "  Hi  ", "transcript_path": str(path)}) == "Hi"
    assert claude_response({"transcript_path": str(path)}).startswith("Done:")
    assert claude_response({"transcript_path": str(tmp_path / "missing")}) == ""


def test_codex_response():
    assert codex_response({"type": "agent-turn-complete", "last-assistant-message": "Ok"}) == "Ok"
    assert codex_response({"type": "something-else", "last-assistant-message": "Ok"}) == ""


def test_for_display_strips_markdown_and_truncates():
    md = "## Summary\n\n- **Fixed** the `parser`\n- See [docs](http://x)\n\n```py\nx = 1\n```\n"
    assert for_display(md, 500) == "Summary\n\n• Fixed the parser\n• See docs\n\n[code]"
    long = "word " * 100
    out = for_display(long, 30)
    assert len(out) <= 31 and out.endswith("…")
