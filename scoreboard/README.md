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

## How it works

| module | role |
| --- | --- |
| `app.py` | entry point; owns the window, the link, and the config-refresh policy |
| `client.py` | `GET /config` + the `/ws/scoreboard` receive loop, in a daemon thread |
| `board.py` | header bar and lane rows; merges partial `update_scoreboard` frames |
| `widgets.py` | `FitLabel` — the shrink-to-fit label |
| `theme.py` | normalises `/config` (colours, fonts, labels, `show_*` flags) |
| `fonts.py` | registers bundled faces, falls back to monospace |

Two rules the code depends on:

- **Frames are partial.** `update_scoreboard` carries only changed keys. They are
  merged into `BoardWindow.snapshot`; never replace it.
- **Deltas come from the structured fields.** Use `lane_delta_seconds<i>` and
  `lane_delta_better<i>`, not the HTML `lane_delta<i>` blob meant for the browser
  (`docs/api.md` §5.1).

The window opens *before* the server is reachable. At a meet both Pis power up
together, and a display that waits for a successful HTTP call looks broken for
the first thirty seconds; instead it draws with fallback theming plus a status
message and adopts the real config when `/config` answers.

## Testing

`tests/test_scoreboard_config.py` covers config normalisation and is deliberately
Qt-free, so it runs in CI without the `scoreboard` extra installed.

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
