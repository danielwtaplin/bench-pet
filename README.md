# Bench Pet

A desktop pet for KDE/Linux that idles, gestures, and reacts to what's going on (see `PLAN.md`).

## Setup

```sh
python3 -m venv --system-site-packages .venv   # system site for PyGObject (Gio D-Bus)
.venv/bin/pip install -e '.[dev]'
.venv/bin/python tools/slice_sheets.py          # refs/*.png → assets/sprites/
```

## Run

```sh
.venv/bin/python -m benchpet
```

What it reacts to:

| Source | Pet behaviour | Bubble |
|---|---|---|
| Music (MPRIS) | Headphones; nods along, dances now and then | Track, artist, ▶/⏸ |
| Notifications | Email/chat: laptop reaction, then reads for a while. Other: surprised | Last few, newest previewed |
| Away (Wayland idle) | Coffee break after 5 min, long absence after 30; waves when you're back | — |
| Countdowns | Celebrates when the weekend or a custom event arrives | Time left |
| Calendar (ICS feeds) | Startled/thinking reaction and bubble pop-up 10 min before an event | Next 3 events |
| Weather (Open-Meteo) | Reacts when conditions change; weather gestures mixed into ambient | Temp + conditions |
| Pomodoro | Laptop focus → tired → coffee break → stretch/thumbs-up | Phase + minutes left |
| Coding (input + focused window) | At the laptop while you type in an editor/terminal, with the odd coding gesture; tired after 90 min without a break, exhausted after 150; refreshed when you come back from one | Time without a break (once tired) |
| `bench-pet` CLI / hooks | At the laptop while working; celebrates on done; facepalms on failed, then gets frustrated and melts down if failures keep coming within 10 min | Task status |
| AI agent replies | "Message from AI" pose + speech bubble with the reply (only if its terminal isn't focused) | — |

- Drag to move (position is remembered), click to pin/unpin the info bubble, hover to peek.
- Right-click: music play/pause/next/previous, choose info panel sections, size, pomodoro,
  pause animation, celebrate, quit.
- Config: `~/.config/bench-pet/config.yaml` (defaults are filled in for anything you leave out).
  Disable a source with `sources.<name>: false`. Two need setting up to do anything:

```yaml
calendar:
  feeds:
    # Google: Settings → your calendar → "Secret address in iCal format"
    # Outlook: Settings → Calendar → Shared calendars → Publish → ICS link
    - {name: Work, url: "https://outlook.office365.com/owa/calendar/.../calendar.ics"}
    - {name: Personal, url: "https://calendar.google.com/calendar/ical/.../basic.ics"}
weather:
  location: "Wellington"   # or latitude/longitude
```

  Other keys: `activity.coding_apps` (window classes that count as coding) / `tired_minutes` /
  `exhausted_minutes`, `away.short_minutes` / `long_minutes`, `countdown.week_end` / `week_start` / `events`,
  `notifications.email_apps` / `message_apps` / `ignore_apps`, `pomodoro.focus_minutes` etc.

## Driving the pet from scripts

```sh
bench-pet working "Refactoring auth"   # laptop/typing until done (15 min safety timeout)
bench-pet done "Tests pass"            # celebrate
bench-pet failed "Build broke"         # facepalm
bench-pet celebrate                    # just celebrate
bench-pet clear                        # stop working, no reaction
bench-pet pomodoro start|stop|skip
```

`make && bench-pet done || bench-pet failed` is the basic pattern.

### AI agents

When an agent finishes replying and its terminal isn't the focused window, the pet shows the
"message from AI" pose and a speech bubble with the reply. Click the bubble to jump to that
terminal, right-click to dismiss; it also goes away when you switch to the terminal yourself.
Focus is tracked with a small KWin script the pet loads at startup.

Claude Code: add hooks to `~/.claude/settings.json` (adjust the path to your checkout).
`working Claude` shows the Claude "thinking" poses while it works; `agent claude` reads the
Stop hook payload from stdin and forwards the reply:

```json
{
  "hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command",
      "command": "~/workspace/bench-pet/.venv/bin/bench-pet working Claude >/dev/null 2>&1 || true"}]}],
    "Stop": [{"hooks": [{"type": "command",
      "command": "~/workspace/bench-pet/.venv/bin/bench-pet agent claude >/dev/null 2>&1 || true"}]}]
  }
}
```

Codex: in `~/.codex/config.toml`, `notify = ["/home/you/workspace/bench-pet/.venv/bin/bench-pet", "agent", "codex"]`.

Anything else: `bench-pet agent <name> "reply text"`.

Desktop/web apps (Claude, ChatGPT) have no hooks, but their desktop notifications are picked up
and shown the same way (`notifications.ai_apps` in config; the text is whatever preview the app
puts in the notification). Turn on notifications in those apps for this to work.

The socket is `$XDG_RUNTIME_DIR/bench-pet.sock` (override with `BENCH_PET_SOCKET`); only one pet runs at a time.

Runs under XWayland (`QT_QPA_PLATFORM=xcb`) so the window can position itself.

## Layout

- `tools/slice_sheets.py`: slices and cleans the sheets in `refs/`.
- `assets/sprites.yaml`: poses grouped into activities (timing, motion, fallbacks).
- `benchpet/sources/`: data sources that publish events and know nothing about sprites.
- `benchpet/state.py`: decides the current activity (priorities: reaction > away > agent > reading >
  pomodoro > working > music > coding > idle).
- `benchpet/renderer.py`: holds poses, crossfades between them, adds breathing/bobbing/dancing.

## Tests

```sh
.venv/bin/python -m pytest
```
