# Qt scoreboard (TV display)

The native display for the kiosk Pi. Replaces the Chromium kiosk that rendered
`/live` in a browser.

## Why native

- **Names fit.** CSS can only truncate an overlong swimmer name; Qt measures text
  before drawing, so `FitLabel` shrinks it to fit. This is the reason the
  migration exists.
- **4K without a layout engine.** Chromium spends RAM and CPU on a DOM the
  scoreboard does not need. Qt draws the rows directly.

## Why it lives in this repo

Same language, same `uv`, same Pi, no app store — none of the reasons that
justify a separate repo for the iOS/Android clients apply here. More importantly,
one repo means `install.sh server <version>` and `install.sh kiosk <version>`
resolve to the same git ref, so the display and the server can never disagree
about the WebSocket contract. See
[`notes/native_app_strategy.md`](../notes/native_app_strategy.md).

The convenience is not a licence to cheat: this package **must not import from
`server/`**. It is a remote client of the documented API in
[`docs/api.md`](../docs/api.md), exactly like the phone apps.

## Running

```bash
uv sync --extra scoreboard                       # PyQt5 — kiosk role only
.venv/bin/python -m scoreboard --windowed        # development, against splouch.local
.venv/bin/python -m scoreboard --server http://10.10.10.10:5000 --windowed
```

On the kiosk Pi the desktop session autostarts
[`install/scripts/start-scoreboard.sh`](../install/scripts/start-scoreboard.sh),
which resolves the venv from its own location, reads the server address from
`~/.config/splouch/scoreboard.env`, and restarts the app if it exits.

## Operator keys

The kiosk window has no decorations and no menu, so these keys are the only way
off the board without an SSH session.

| key | effect |
| --- | --- |
| **Ctrl+Q** | quit to the desktop |
| **F11** or **Ctrl+F** | toggle fullscreen |
| **Esc** | leave fullscreen (never quits) |

Ctrl+Q is deliberately two-handed — a stray keypress must not blank the TV
mid-meet — and Esc deliberately does *not* quit, only un-fullscreens.

F11 is the Linux-wide fullscreen convention and the one to document first;
Ctrl+F is a second binding for hands used to it. Ctrl+F normally means Find, but
the board has nothing to search, so nothing is displaced.

**Quit and relaunch are two halves of one design.** `start-scoreboard.sh` relaunches
the app whenever it exits **non-zero** (a crash, a killed process) but not on a
clean exit, which is what Ctrl+Q produces. So quitting really does return you to
the desktop and stay there. Getting back is the **Scoreboard** icon the installer
puts on the desktop; there is also a **Settings** icon that opens the server's
admin page in a browser.

Consequence worth remembering: anything that makes the app exit 0 looks like a
deliberate quit and will *not* relaunch. That is why the lane-count rebuild in
`app.py` builds the new window before closing the old one — closing the only
window emits `lastWindowClosed`, which quits cleanly under Qt's default
`quitOnLastWindowClosed` and would leave the TV black until someone clicked the
icon.

## How it works

| module | role |
| --- | --- |
| `app.py` | entry point; owns the window, the link, and the config-refresh policy |
| `client.py` | `GET /config` + the `/ws/scoreboard` receive loop, in a daemon thread |
| `board.py` | header bar and lane rows; merges partial `update_scoreboard` frames |
| `widgets.py` | `FitLabel` — the shrink-to-fit label |
| `theme.py` | normalises `/config` (colours, fonts, labels, `show_*` flags) |
| `format.py` | value formatting (deltas); Qt-free so CI can test it |
| `fonts.py` | registers bundled faces, falls back to monospace |

Two rules the code depends on:

- **Frames are partial.** `update_scoreboard` carries only changed keys. They are
  merged into `BoardWindow.snapshot`; never replace it.
- **Deltas come from the structured fields.** Use `lane_delta_seconds<i>` and
  `lane_delta_better<i>`, not the HTML `lane_delta<i>` blob meant for the browser
  (`docs/api.md` §5.1). All three carry the same number — finish minus seed — but
  the HTML one bakes in formatting *and* styling via CSS classes that resolve to
  nothing outside the page. `format.fmt_delta` reproduces the server's own
  formatting from the structured value, including the switch to `m:ss.hh` past a
  minute; `tests/test_scoreboard_format.py` cross-checks it against
  `meet_data._delta_html` so the two can't drift.

The window opens *before* the server is reachable. At a meet both Pis power up
together, and a display that waits for a successful HTTP call looks broken for
the first thirty seconds; instead it draws with fallback theming plus a status
message and adopts the real config when `/config` answers.

## Font sizing

Nothing is sized in absolute pixels. Every size derives from the window, so the
same code fills a 1080p TV and a 4K one without a second layout.

**The ceiling.** `_FONT_MAIN = 0.52` in `board.py`: on each resize,
`LaneRow.set_row_height` sets the row's text to 52% of the row height and hands
the same number to the name label as its *maximum*. Names therefore never grow
larger than the lane / club / time / place text beside them — a short name simply
matches its row rather than ballooning to fill the column. Relay member names use
`_FONT_ALT = 0.30`; the header bar uses 55% of its own height.

| ceiling | 6 lanes | 8 lanes | 10 lanes |
| --- | --- | --- | --- |
| **1080p** | 83px | 63px | 52px |
| **4K** | 170px | 130px | 105px |

**The floor.** `FitLabel(min_px=10)` in `widgets.py`. Below 10px the search stops
and the text clips instead of shrinking further. In practice it is unreachable —
a 44-character name still resolves to 27px at 1080p, and only a ~90-character
string gets near it.

What a row actually renders at, 8 lanes:

```text
1080p  →  short 63px · typical 44px · long 27px · 90-char 13px
4K     →  short 130px · typical 91px · long 56px · 90-char 27px
```

### Open question: the spread

The ceiling is settled; the *variation between rows* is not. At 1080p a short
name draws at 63px next to a long one at 27px, which reads as ragged in a way the
browser version never did — CSS truncated everything to one uniform size instead.

Three options, in order of preference:

1. **Fit per heat.** Measure the longest name in the current heat, then apply that
   one size to all rows. Keeps every name complete *and* makes the block uniform.
   Costs a second measuring pass on each heat change.
2. **Leave it.** Maximum information, uneven look.
3. **Raise the floor** to ~50% of the ceiling and elide beyond it. Caps the
   raggedness, but reintroduces the truncation this display exists to avoid.

Not worth deciding from a screenshot — judge it with real names on the real TV.

## Testing

`tests/test_scoreboard_config.py` (config normalisation) and
`tests/test_scoreboard_format.py` (delta formatting) are deliberately Qt-free, so
they run in CI without the `scoreboard` extra installed. Keep pure logic out of
`board.py` for that reason — it is the module that drags in PyQt5.

Widget behaviour needs a `QApplication`. Drive it headless with
`QT_QPA_PLATFORM=offscreen`, build a `BoardWindow`, feed it frames, and assert on
label text and font pixel sizes — that is how shrink-to-fit is verified (a long
name must resolve to a smaller pixel size than a short one, with its text
intact).

## Known gaps

This is a working scaffold, not the finished display. Still to do:

- **Fonts.** `shared/static/fonts/` holds **woff2**, which Qt cannot load. The
  kiosk installs `fonts-overpass` from apt for the default family; the DSEG
  seven-segment faces have no apt package, so drop TTF/OTF copies into
  `shared/static/fonts/` and `fonts.py` will register them automatically.
- **Splash / carousel.** `/live` shows sponsor images between heats
  (`carousel_images`, `carousel_interval`) and an intro splash. Not implemented.
- **Per-lane running clocks.** The header shows `running_time`; the browser also
  ticks a local clock per running lane (`lane_running<i>`).
- **Race-end transitions.** The browser fades between board and results on
  `race_finished`; here the board simply keeps the final times on screen.
- **Background image.** `/live` renders `scoreboard_bg.png` behind the table.
- **`columns_state`.** The browser collapses optional columns mid-race to widen
  the name column. The native board ignores it — worth revisiting once real names
  are on a real TV, since shrink-to-fit may have removed the need.
