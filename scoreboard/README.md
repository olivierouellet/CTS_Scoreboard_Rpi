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
| `theme.py` | normalises `/config` (colours, fonts, labels, strings, `show_*` flags) |
| `cache.py` | remembers the last `/config` so a cold boot starts themed and translated |
| `format.py` | value formatting (deltas); Qt-free so CI can test it |
| `fonts.py` | registers the bundled TTFs, resolves family names, falls back to monospace |

### Theming

Everything comes from **Settings → Display → Theme** on the server — the same
settings that theme the web scoreboard. Nothing is hard-coded but the fallbacks in
`theme.py`, which only apply before the first `/config` on a fresh install.

All 16 board colours are honoured, including the two that are easy to conflate:
`header_label` (the word *EVENT*) and `header_value` (the number after it) are
separate swatches, so the header is built from `HeaderCell` widgets holding two
labels rather than one string.

The three fonts are three distinct settings and land in three places:

| setting | key | used for |
| --- | --- | --- |
| Font | `family` | names, clubs, headers |
| Timing Font | `timing` | lane times and deltas |
| Digit Font | `digits` | the running clock — usually a seven-segment face |

Only the `schedule_*` colours are unused, and correctly so: they belong to the
schedule and next-heats pages, which this display does not render.

`tests/test_scoreboard_startup.py` paints a distinct sentinel colour into every
key and asserts each one reaches a widget. That test exists because two settings
— `header_label` and Digit Font — were silently ignored at first, and a theme key
the display quietly drops is invisible until someone changes it on meet day.

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

### The column reveal

Time, delta and place collapse to nothing when a heat loads and slide open over
500ms when the race starts, matching `.timing-anim`'s `0.5s ease` in the browser.
It is purely cosmetic, and the contrast is the whole point: between heats the
board is a calm start list with the names given the full width, then the race
begins and the timing columns arrive.

| trigger | effect |
| --- | --- |
| `current_event` **or** `current_heat` changes, results on screen | the heat transition below |
| same, but the board is empty | collapse at once — nothing to dissolve |
| first lane starts running | reveal, animated |
| `columns_state {hidden}` from `/operator` | either, animated |
| `reset()` / idle board | expanded |

Either half of the `(event, heat)` pair changing counts as a new race — event 3
heat 1 → event 4 heat 1 is a new start list even though the heat number held. Only
a *change* counts, since the console resends both fields constantly. The board
starts expanded so an idle display looks finished rather than half-drawn.

Driven by `maximumWidth`, not layout stretch: these cells use
`QSizePolicy.Ignored`, which carries the Expand flag, so a stretch of 0 would not
reliably close them.

### The heat transition

Going from one heat's results to the next start list is a five-step dissolve, not
a cut, mirroring `mode_to_intro()` in `scoreboard.html`. 500ms per step:

1. **Podium tints fade** back to the row stripes
2. **Columns close**
3. **The table fades out**
4. **The new heat is painted while it is invisible**
5. **The table fades back in**

Three things make it work:

- **The table pauses.** From step 1 until step 4, incoming frames merge into the
  snapshot but are not painted (`BoardWindow.paused`). Otherwise the next heat's
  names would appear on top of the outgoing results. The header bar keeps updating
  live, as it does in the browser.
- **A race cancels it.** `cancel_heat_transition()` snaps straight to the current
  state if a lane starts running mid-dissolve — a swimmer on the blocks outranks
  an animation.
- **An empty board skips it.** Two seconds of dissolving nothing just looks slow,
  so a heat loaded onto a clear board collapses outright.

The previous heat's `lane_time`/`lane_place`/`lane_delta` keys are dropped from the
snapshot at the moment of the heat change — *except* any that arrived in that same
frame, which belong to the new heat. They are not merely hidden behind the closed
columns: the operator can reopen those at any moment, and `refresh()` repaints
from the snapshot.

Qt stylesheets do not animate, so the podium fade interpolates the colour itself
and re-applies it; the browser gets that free from a CSS `background-color`
transition.

### Why every cell is a `FitLabel`

Not just the names. A plain `QLabel` paints straight over its neighbour rather
than clipping, and at six lanes on 1080p the row is tall enough that `1:12.44`
at 52% of row height is wider than the time column — it rendered as `1:12.44).06`,
spilling into the delta. Long translated headers did the same (`COULOIR` in a
lane column six units wide). Every cell now shrinks to fit, and
`tests/test_scoreboard_columns.py` measures each one against its column width.

### The race clock

A lane's time cell has two owners, and which one is in charge is the whole
mechanism:

| `lane_running<i>` | the time cell shows | why |
| --- | --- | --- |
| `true` | the race clock, ticking | the swimmer is mid-length |
| `false` | `lane_time<i>`, frozen | they touched a wall — this is the split |

**A lane pauses at every wall.** The console drops the running flag and sends the
lap in `lane_time<i>`, which has to stay on screen for the few seconds it takes to
read before the flag returns and the lane rejoins the clock. Freezing it is the
entire point: without that, the lap time is overwritten before anyone sees it.

Consequences worth knowing before touching this code:

- **A running lane ignores `lane_time<i>`.** The split stays in the snapshot after
  it lands, so any later frame touching that lane would stamp the stale split back
  over the live clock. `LaneRow.update_from` skips the time cell while running.
- **All running lanes show the same value** — the console's race clock — as in the
  browser. There is no independent per-lane timer; a lane's own elapsed time only
  becomes meaningful at its split.
- **The clock is interpolated locally.** The console sends `running_time` a few
  times a second, which would visibly step. The board re-bases on each frame and
  ticks at 50ms in between, so it never free-runs for long.
- **The header is painted on every frame, not only by the ticker.** The ticker
  stops when no lane is running, and during the seconds when every lane is paused
  at a wall the header would otherwise freeze.
- **`race_finished` calls `stop_clock()`** as a backstop. The console normally
  clears the flags first, but a missed frame would leave the ticker counting up
  over the final times.

### Starting before the server does

The display depends on the server for two separate things, over two separate
connections:

| | what | when |
| --- | --- | --- |
| `GET /config` | plain HTTP request/response — theme, labels, lane count, column flags | at startup, and again on every `reload` |
| `/ws/scoreboard` | WebSocket — the live frames | held open for the whole meet |

Both fail while the server Pi is still booting, and each recovers on its own:
`ConfigLoader` retries on a timer, `ServerLink` runs its own reconnect loop.

The window therefore opens **before either succeeds**. At a meet both Pis power up
together and the kiosk usually wins — it has no service to start — so the board
draws immediately with fallback theming and a waiting message, then adopts the
real config when `/config` answers.

**Neither call may run on the GUI thread.** This is the whole reason `ConfigLoader`
exists rather than a direct `fetch_config()`. A server that is reachable but not
yet answering does not fail fast; it hangs for the full 10s timeout. Called inline
from `ScoreboardApp.__init__` that runs *before the first paint*, so the TV shows
nothing at all — measured at 10.05s to first paint before the fix, 0.05s after.
`tests/test_scoreboard_startup.py` guards this.

### The waiting screen

| headline | when |
| --- | --- |
| *Waiting for the timing server* | never connected yet |
| *Lost connection to the timing server* | the link dropped mid-meet, so the board on screen is stale |

Under it, a dimmer line: `splouch.local · retrying · 47 s`. The elapsed
count ticks every second, and it is there for one reason — it is the only thing on
screen that tells an operator the display is still trying rather than hung. A
static message looks identical to a crash.

**Translated** from the `[display]` section of the locale files, selected by
**Settings → Display → Scoreboard language** — the same setting that translates the
board itself. The server ships the strings in `/config` as `display_strings`
(English-merged, so a partially translated locale falls back per key). Add a
language by adding a `[display]` section to its `.toml`;
`tests/test_scoreboard_i18n.py` fails if a locale is missing a key.

### The config cache

Those strings create a chicken-and-egg problem: the waiting screen exists to be
shown *before* `/config` arrives, but `/config` is what carries the language,
theme and lane count.

`cache.py` resolves it by writing the last config to
`~/.cache/splouch/scoreboard-config.json` and loading it at startup. Only the very
first boot after installation looks generic; after that the kiosk comes up in the
right language and colours even if the server never answers at all.

Two details that matter on a Pi someone switches off at the wall: the write is
atomic (temp file + `os.replace`), so a power cut cannot leave a truncated cache
that poisons every later boot; and an unchanged config is not rewritten, since
`/config` is re-fetched on every reconnect and that would be pure SD-card wear.
Any unreadable cache reads as absent and falls back to the built-in English.

> A WebSocket is only HTTP for its handshake: the client opens with a normal
> `GET /ws/scoreboard` carrying `Upgrade: websocket`, the server replies `101
> Switching Protocols`, and from then on the connection carries frames, not
> HTTP messages. Same host and port as `/config` either way — it is all one
> uvicorn process.

### Fonts

The theme faces ship with the repo as TTF in
[`shared/static/fonts/`](../shared/static/fonts/) — alongside the woff2 the browser
uses, since Qt cannot read woff2 — and `fonts.py` registers them at startup. No
system font packages are required.

One trap is worth knowing before you touch font names. The browser declares its
own family label in CSS (`@font-face { font-family: 'DSEG7Classic' }`), which need
not match anything inside the file; the font itself is called `DSEG7 Classic`,
with a space. Qt reads the real name, so an exact-match lookup drops both DSEG
faces to the fallback. `resolve_family()` therefore matches ignoring spaces and
case. See that directory's [README](../shared/static/fonts/README.md) for
provenance, licences, and the variable-font caveat.

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

`tests/test_scoreboard_config.py` (config normalisation),
`tests/test_scoreboard_format.py` (delta formatting) and
`tests/test_scoreboard_fonts.py` (family-name matching, bundled-font inventory)
are deliberately Qt-free, so they run in CI without the `scoreboard` extra
installed. Keep pure logic out of `board.py` for that reason — it is the module
that drags in PyQt5.

`tests/test_scoreboard_startup.py`, `tests/test_scoreboard_clock.py` and
`tests/test_scoreboard_columns.py` need Qt and `importorskip` without it. Run them where PyQt5 is available:

```bash
uv run --extra scoreboard pytest tests/
```

They share the session-scoped `qt_app` fixture in `tests/conftest.py`, which also
points `XDG_CACHE_HOME` at a temp dir. **Do not** give a QApplication a narrower
fixture scope: whichever fixture yields it holds the only Python reference, so
PyQt destroys the C++ object at teardown — and Qt discards every font registered
with `addApplicationFont` along with it. The next module then runs against a
font-less application while `fonts._APP_FONTS_LOADED` still reports them loaded,
and every family silently falls back to monospace.

Widget behaviour needs a `QApplication`. Drive it headless with
`QT_QPA_PLATFORM=offscreen`, build a `BoardWindow`, feed it frames, and assert on
label text and font pixel sizes — that is how shrink-to-fit is verified (a long
name must resolve to a smaller pixel size than a short one, with its text
intact).

## Known gaps

This is a working scaffold, not the finished display. Still to do:

- **Splash / carousel.** `/live` shows sponsor images between heats
  (`carousel_images`, `carousel_interval`) and an intro splash. Not implemented,
  so there is no idle mode: the board holds the last start list indefinitely
  rather than timing out to a splash the way `INTRO_TIMEOUT` does in the browser.
- **Background image.** `/live` renders `scoreboard_bg.png` behind the table.
- **Results hold.** The browser pauses on results for `RESULTS_TIMEOUT` and
  distinguishes a brief result from a full one; here results simply stay until
  the next heat arrives.
