# Splouch API contract

**Contract version: `v1`** · Server implementation: this repo (`server/app.py` local, `cloud/cloud_server.py` cloud).

This is the source-of-truth contract that every non-browser client follows — the
Qt/PySide TV display (`Splouch-tv`), the iOS app (`Splouch-ios`), and the
Android app (`Splouch-android`). There is intentionally **no shared client
library**: the platforms are too different. They agree only on this document.

When you change an event's shape or add a field, bump the version and note it in
the changelog at the bottom. Additive fields are backward-compatible; renames and
removals are breaking.

---

## 1. Transport & envelope

All realtime traffic is **plain WebSocket** (no Socket.IO). Each former namespace
is its own path. Every message — both directions — is a single JSON text frame:

```json
{ "event": "<name>", "data": <any> }
```

- `data` is usually an object; a few events carry `{}` or a bare string.
- Frames on one connection are ordered. Unknown events must be ignored.
- Reconnect is the client's responsibility (WebSockets don't auto-reconnect).
  Reconnect with capped backoff; on every (re)connect, a cloud attendee must
  re-send `join_meet` (see §3). The reference browser client is
  [`static/js/ws.js`](../static/js/ws.js).

There are **two servers** with distinct roles:

| Server | Who connects | Base URL | Rooms? |
| --- | --- | --- | --- |
| **Local** (Pi on pool LAN) | Qt TV display, admin browser | `ws://<pi>:5000` | No — one meet per server |
| **Cloud** (public relay) | phones/spectators; the Pi as a *relay producer* | `wss://<host>` | Yes — many meets, joined by `meet_id` |

---

## 2. Local server (Qt TV display → the Pi)

The Qt display connects directly to the Pi. There is exactly one meet, so there is
no join step — the server starts pushing on connect.

### `/ws/scoreboard`
On connect the server sends, in order: `test_mode`, `display_overlay`,
`columns_state`, then an `update_scoreboard` snapshot.

**Server → client**
| event | data | meaning |
| --- | --- | --- |
| `update_scoreboard` | *partial* scoreboard dict (§5.1) | live lane/time/place changes; **only changed fields** are sent |
| `race_finished` | `{}` | results are confirmed after the finish-debounce window |
| `test_mode` | `{ "active": bool }` | a recorded session is playing |
| `display_overlay` | `{ "active": bool }` | fullscreen overlay on/off |
| `columns_state` | `{ "hidden": bool }` | optional columns collapsed/expanded |
| `reload` | `{}` | settings/theme changed — client should re-fetch config and redraw |

**Client → server**
| event | data | effect |
| --- | --- | --- |
| `set_overlay` | `{ "active": bool }` | toggle overlay (rebroadcast as `display_overlay`) |
| `set_columns` | `{ "hidden": bool }` | toggle columns (rebroadcast as `columns_state`) |
| `adjust_splits` | `{ "lane": 1‑12, "delta": int }` | nudge a lane's split count; server replies `update_scoreboard {"lane_splits<n>": v}` |
| `next_heat` | `{}` | advance to the next event/heat (Hytek/manual mode) |

### `/ws/results`
On connect the server sends the last `results_snapshot` (if any) and `next_heats`.
**Server → client:** `results_snapshot` (§5.2), `next_heats` (§5.3), `reload`.
Client sends nothing.

### `/ws/settings` (admin UI only)
**Server → client:** `serial_log {state, msg}`, `test_status {}`, `test_mode {active}`,
`debug_line {hex, text}`. Client sends nothing. Not needed by the TV display.

### `/ws/terminal` (admin UI only)
Bidirectional PTY. Server → client: `output <string>`, `exit {}`.
Client → server: `input <string>`, `resize {rows, cols}`.

---

## 3. Cloud server (phones → public relay)

Spectator apps connect to the cloud, then **join a meet**. `meet_id` comes from the
picker/meet list (§4). `vid` is a random per-device id the client generates once and
stores locally (used only for anonymous attendance counts; send it or omit it).

Join handshake, then listen — identical pattern on all three attendee paths:

```json
→ { "event": "join_meet", "data": { "meet_id": "<id>", "vid": "<device-uuid>" } }
```

### `/ws/scoreboard`
**Server → client:** `meet_live {live}` (sent first, then whenever the console
connects/disconnects), `update_scoreboard` (§5.1; the cloud strips `running_time`),
`reload`.

### `/ws/results`
**Server → client:** `meet_live {live}`, `results_snapshot` (§5.2), `next_heats` (§5.3), `reload`.

### `/ws/schedule`
**Server → client:** `schedule_update` (no data) — signal to re-fetch the schedule
JSON from `GET /mobile/schedule` or the meet's `schedule_data`.

> **Re-join on reconnect.** After any drop the client must re-send `join_meet`;
> the server replays `meet_live` + the latest cached snapshot so the UI catches up.

### `/ws/relay` (the Pi relay — not a spectator)
Documented for completeness; implemented by [`relay.py`](../relay.py). The Pi is a
*producer*: it registers once, then forwards the same events it broadcasts locally.

**Client (relay) → server:** `register` (metadata §5.4), then `update_scoreboard`,
`results_snapshot`, `next_heats`, `schedule_snapshot` (§5.5), `reload`.
**Server → relay:** `registered {meet_id}`, `rejected {reason}`.

---

## 4. REST endpoints native clients need

JSON/asset endpoints (everything else the servers expose is HTML for the browser UI).

### Local (Pi)
| method · path | returns |
| --- | --- |
| `GET /config` | **display config JSON** — `num_lanes`, `theme_colors`, `theme_fonts`, `show_*` flags, `labels`, `meet_title`, `locale`, `display_strings` (§6). Lets the Qt display theme *and translate* itself without a rendered page |
| `GET /manifest.json` | PWA manifest (app title, icons) |
| `GET /home_icon`, `/home_icon_512` | meet home-screen icon PNG |
| `GET /picker_image` | active picker image PNG |
| `GET /images/{filename}` | splash/carousel images |

### Cloud
| method · path | returns |
| --- | --- |
| `GET /` | picker page (HTML) — meet cards |
| `GET /meet/{meet_id}/config` | **meet config JSON** — `name`, `location`, `sport`, `meet_date`, `live`, and the `settings` block (§5.4). Lets a phone render the board without scraping the HTML page |
| `GET /manifest/{meet_id}` | per-meet PWA manifest |
| `GET /icon/{meet_id}` | meet icon PNG · `GET /picker_image/{meet_id}` picker image PNG |
| `GET /search_suggestions?meet_id=&q=` | `[{type:"swimmer"|"club", name, club?}]` swimmer/club typeahead |
| `GET /mobile/schedule?meet=<id>` | schedule page (HTML embedding `heats_json`) |

---

## 5. Payload shapes

### 5.1 `update_scoreboard` (partial)
A flat dict; **only changed keys are sent** each frame — merge into local state.
Lane keys are 1-indexed (`<i>` = 1…12).

| key | type | notes |
| --- | --- | --- |
| `current_event`, `current_heat` | string | e.g. `"3"`, `"1"` |
| `event_name` | string | display name, already localised/translated |
| `heat_time` | string | scheduled time, may be `""` |
| `running_time` | string | live clock; **present only on the local server** (cloud strips it) |
| `expected_splits` | int | laps expected for the event |
| `lane_name<i>` | string | swimmer/relay display name |
| `lane_club<i>` | string | club |
| `lane_name_alt<i>` | string | relay member names, else `""` |
| `lane_time<i>` | string | finish/split time, e.g. `"0:25.61"` |
| `lane_place<i>` | string | rank, space when none |
| `lane_running<i>` | bool | lane clock active |
| `lane_delta<i>` | string | **HTML** `<span class="delta-better\|delta-worse">±s.hh</span>` vs seed (for the browser) |
| `lane_delta_seconds<i>` | float\|null | **structured** signed delta vs seed in seconds (negative = faster); `null` when no seed/time |
| `lane_delta_better<i>` | bool\|null | `true` when faster than seed; `null` when no delta |
| `lane_splits<i>` | int | reply to `adjust_splits` |

> Native clients should use `lane_delta_seconds<i>` / `lane_delta_better<i>` and
> ignore the HTML `lane_delta<i>`. On a heat change all three reset (`""` / `null`).

### 5.2 `results_snapshot`
```json
{ "event": "3", "heat": "1", "event_name": "…", "sort": "lane"|"place",
  "lanes": [ { "channel": 4, "place": "1", "place_int": 1, "time": "2:20.92",
              "name": "…", "club": "…", "alt": "…",
              "delta": "<span …>", "delta_seconds": -0.46, "delta_better": true } ] }
```
Lanes without a final time are omitted. `sort` tells the client whether to place each
row by lane (blank gaps) or by finishing place. `delta` is browser HTML;
`delta_seconds`/`delta_better` are the structured equivalents (`null` when no seed).

### 5.3 `next_heats`
```json
{ "heats": [ { "event": 3, "heat": 1, "event_name": "…", "time": "10:42",
              "swimmers": [ { "lane": 1, "name": "…", "club": "…", "alt": "…" } ] } ] }
```

### 5.4 relay `register` metadata (Pi → cloud)
```json
{ "key": "<relay key>", "meet_uid": "<stable per LENEX>", "name": "…",
  "location": "…", "sport": "…", "app_window_title": "…", "meet_date": "YYYY-MM-DD",
  "settings": { "num_lanes": 8, "show_name": true, "show_club": true, "show_delta": true,
                "show_position": true, "show_podium": true, "show_*_header": true,
                "theme_colors": { … }, "theme_fonts": { … }, "locale": "fr",
                "labels": { … }, "home_icon_b64": "…?", "picker_image_b64": "…?" } }
```
This `settings` block is the meet's display config — the same values a native
attendee needs to render the board (lane count, visible columns, theme, labels).

### 5.5 relay `schedule_snapshot` (Pi → cloud)
```json
{ "events": [ [3, [1,2]] ], "names": { "3": "…" }, "times": { "3": { "1": "10:42" } },
  "start_list": { "3": { "1": { "1": { "name":"…","club":"…","seed_time":"…","swimmers":[…] } } } } }
```

---

## 6. Config for native clients

The browser clients receive display config through server-rendered templates
(`web._globals()` locally; the meet's `settings` block on the cloud). Native clients
have no template, so config is exposed as JSON — all three additions below are
**additive** (the browser UI is unchanged):

1. **Local `GET /config`** — what `web._globals()` injects (`num_lanes`, `theme_colors`,
   `theme_fonts`, `show_*` flags, `labels`) plus `meet_title`, `locale` and
   `display_strings`. The Qt display fetches this once on startup and again on a
   `reload` event.

   `display_strings` is the `[display]` section of the active locale file —
   status messages the *client* renders rather than the server (`waiting_server`,
   `connection_lost`, `retrying`), selected by the `locale` setting (Settings →
   Display → Scoreboard language) and English-merged so an untranslated key never
   renders blank. A native client needs these because it must say something while
   `/config` itself is still unreachable; the Qt display caches the last config on
   disk for exactly that reason.
2. **Cloud `GET /meet/{meet_id}/config`** — the meet's `settings` block (§5.4) plus
   `name`/`location`/`sport`/`meet_date`/`live`, so a phone can theme and render the
   board without scraping the HTML page.
3. **Structured delta** — `lane_delta_seconds<i>`/`lane_delta_better<i>` in
   `update_scoreboard` and `delta_seconds`/`delta_better` in `results_snapshot`,
   alongside the browser's HTML `lane_delta<i>` (§5.1, §5.2).

A native client's flow: fetch config once → open the WebSocket → merge event frames.
The cloud relay `register` metadata (§5.4) carries the same `settings` shape, so the
two config sources agree.

---

## Changelog
- **v1** — Initial contract after the Flask/Socket.IO → FastAPI/plain-WebSocket
  migration. Envelope `{event, data}`; local paths `/ws/scoreboard|results|settings|terminal`;
  cloud paths `/ws/relay|scoreboard|results|schedule` with `join_meet` rooms.
