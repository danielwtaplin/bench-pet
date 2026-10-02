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
| Calendar (ICS feeds) | Startled/thinking reaction and calendar pop-up 10 min before an event | Separate white calendar card beside the pet: agenda, today timeline or month |
| Weather (Open-Meteo) | Reacts when conditions change; weather gestures mixed into ambient | Temp + conditions |
| Pomodoro | Laptop focus → tired → coffee break → stretch/thumbs-up | Phase + minutes left |
| Coding (input + focused window) | At the laptop while you type in an editor/terminal, with the odd coding gesture; tired after 90 min without a break, exhausted after 150; refreshed when you come back from one | Time without a break (once tired) |
| `bench-pet` CLI / hooks | At the laptop while working; celebrates on done; facepalms on failed, then gets frustrated and melts down if failures keep coming within 10 min | Task status |
| AI usage (Claude) | Low-battery/"I'm done" when a plan window passes 90%; refreshed when it resets | 5h/week progress bars with reset times, today's tokens and API-equivalent cost (off until enabled in the Info panel menu) |
| AI agent replies | "Message from AI" pose + speech bubble with the reply (only if its terminal isn't focused) | — |

- Drag to move (position is remembered), click to pin/unpin the info bubble, hover to peek.
  Moving from the pet onto the bubble or calendar keeps them open.
- Right-click: music play/pause/next/previous, choose info panel sections, calendar, size, pomodoro,
  pause animation, celebrate, **Settings…**, quit.
- Settings: pet size, info panel sections, and the calendar: add calendars (name, private iCal
  address, colour), the card's layout (agenda / today timeline / month), whether it opens with the
  info panel, an optional calendar button below the pet, and reminder timing.
  Google: Settings → your calendar → Integrate calendar → "Secret address in iCal format".
  Outlook: Settings → Calendar → Shared calendars → Publish a calendar → ICS link.
- Config: `~/.config/bench-pet/config.yaml` (defaults are filled in for anything you leave out;
  Settings writes it too). Disable a source with `sources.<name>: false`. Weather needs a location:

```yaml
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

Plan usage (5-hour and weekly limits) is only available to Claude Code's status line, so make
`bench-pet statusline` your status line. It forwards the limits to the pet and prints
`Opus 5.5 · 5h ███▍░░░░ 42% · week █▌░░░░░░ 18%`. To keep a status line of your own, chain it:
`bench-pet statusline -- ~/bin/my-statusline` (it gets the same JSON on stdin).

```json
{
  "statusLine": {"type": "command",
    "command": "~/workspace/bench-pet/.venv/bin/bench-pet statusline"}
}
```

The figures update whenever a Claude Code session's status line refreshes, so the bubble says
"as of N min ago" once they're stale. Today's token totals are read from
`~/.claude/projects` (`usage.claude_logs`) and need no setup; the cost is what the same tokens
would cost on the API, not what a subscription charges. `usage.react_at_percent: null` turns
the reactions off.

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
