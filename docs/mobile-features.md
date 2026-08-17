# Splouch mobile — feature contract

**Contract version: `v1`** · Reference implementation: `cloud/templates/` (see §0.2).

[`api.md`](api.md) is the *data* contract — sockets, events, payload shapes. This
document is the *behaviour* contract: what a spectator can see and do on a phone,
and what drives each of those things. Together they are what an app repo needs.

It exists because the phone clients — `Splouch-ios` (Swift) and `Splouch-android`
(Kotlin) — live in their own repos. The web mobile view is the only complete
statement of the product; without this file, "is the app finished?" has no answer
other than reading Jinja templates.

---

## 0. How to use this file

### 0.1 Who owns what

| | Owns | Lives in |
| --- | --- | --- |
| **This file** | *what* each feature is, what drives it, whether it is required | Splouch (this repo) |
| **App parity ledger** | *whether* it is implemented on that platform, and why not | `Splouch-ios`, `Splouch-android` |

Each app repo keeps a short `parity.md` with one row per ID below and a status of
`done` / `deferred` / `n/a — <reason>`. **Per-platform status does not belong here.**
Putting it here would mean a commit in this repo every time an app ships a screen,
which is exactly the two-repo coordination tax [`notes/native_app_strategy.md`](../notes/native_app_strategy.md)
argues against.

The IDs (`A-03`, `S-07`, …) are stable. They are the join key between the three
repos, so **never renumber**. A retired feature keeps its ID and gains a
`**retired**` note; new features take the next free number in their section.

### 0.2 What the apps are clients of

Phones connect to the **cloud relay**, not the Pi ([`api.md`](api.md) §3). So the
reference implementation for every row below is `cloud/templates/`:

| Surface | Reference template |
| --- | --- |
| meet picker | [`cloud/templates/picker.html`](../cloud/templates/picker.html) |
| app shell / tabs | [`cloud/templates/mobile.html`](../cloud/templates/mobile.html) |
| Scoreboard tab | [`cloud/templates/live.html`](../cloud/templates/live.html) + [`scoreboard_base.html`](../cloud/templates/scoreboard_base.html) |
| Results tab | [`cloud/templates/results.html`](../cloud/templates/results.html) + `scoreboard_base.html` |
| Schedule tab | [`cloud/templates/schedule.html`](../cloud/templates/schedule.html) |
| socket client | [`shared/static/js/ws.js`](../shared/static/js/ws.js) |

`server/templates/` is the **Pi** mobile view — a different, simpler page for
someone on the pool LAN. Do not spec against it.
[`notes/cloud_parity.md`](../notes/cloud_parity.md) records why the cloud
deliberately shows less than the Pi.

Everything a phone needs is reachable as JSON — no screen is HTML-only, and nothing
here requires scraping a page ([`api.md`](api.md) §4). Each browser page renders from
the same helper its JSON endpoint returns (`_public_meet_list`, `_build_heats_json`,
`_picker_branding`), so web and native cannot drift: a field added for one appears in
the other by construction. Keep it that way — extend the helper, never the route.

### 0.3 Requirement levels

| Level | Meaning |
| --- | --- |
| **must** | the app is not at parity without it |
| **should** | expected, but a first release can ship without it |
| **web-only** | an artifact of running in a browser; a native app satisfies it by existing, or not at all |
| **n/a** | present in the Pi/kiosk product, deliberately absent from mobile |

### 0.4 Describe behaviour, not markup

Rows state observable behaviour and its data source. Where the web implementation
is an accident of HTML — iframes, `env(safe-area-inset-*)`, 28px edge strips — that
is called out as such. **Reproducing a workaround is not parity.** Where the
divergence is expected to be visible, the row says what the native equivalent is.

---

## 1. Meet picker (`P`)

The entry screen. On the web it is the site root; in an app it is the launch screen,
and the place the user returns to via `A-02`.

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `P-01` | List of meets as cards: name, date, location, sport | `GET /meets` ([`api.md`](api.md) §5.6) | must |
| `P-02` | Per-meet picker image on the card, when the meet supplies one | `settings.picker_image_b64` → `GET /picker_image/{meet_id}` | should |
| `P-03` | Offline meets stay listed, marked with a dimmed status dot | `offline` = meet is retained but no relay connected | must |
| `P-04` | Empty state when no meets are active | `strings.no_meets` | must |
| `P-05` | Picker branding: title, logo, logo above or below the title | `GET /picker/config` → `title`, `has_logo`, `logo_above`; image at `GET /picker_logo` | should |
| `P-06` | Unofficial-results disclaimer under the list | `GET /picker/config` → `strings.results_disclaimer` | **must** — see note |
| `P-07` | Privacy note, shown whenever attendance counting is on for this server | `strings.privacy_note`, gated on `analytics_enabled` | must |
| `P-08` | Selecting a meet opens the app shell for it | `GET /meet/{id}/config` | must |
| `P-09` | Pull-to-refresh re-fetches the meet list | — | should |
| `P-10` | Add-to-Home-Screen prompt (iOS hint / Android `beforeinstallprompt`) | — | web-only |

> **`P-06` is not decoration.** The disclaimer states these are live, unofficial
> results subject to validation, and points at SplashMe for validated ones. It is
> the only thing standing between a live feed and a spectator treating it as a
> result. It must be visible on the meet list, not buried in an About screen.
>
> Render the server's text rather than a copy compiled into the app: it is served
> from `/picker/config` precisely so wording can be corrected without waiting on a
> store review.

> **Picker language is the device's, not a meet's.** The list spans meets that may
> each run in a different language, so `/picker/config` resolves from `?lang=` or
> `Accept-Language`. Per-meet language starts at `T-06`, once a meet is chosen.

---

## 2. App shell (`A`)

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `A-01` | Three tabs — Scoreboard, Results, Schedule — each with icon and label | `mobile.scoreboard` / `.results` / `.schedule` | must |
| `A-02` | Back affordance to the meet picker | — | must |
| `A-03` | Horizontal swipe moves between adjacent tabs | web: 28px edge strips only, ≥40px travel | must — **see note** |
| `A-04` | The selected tab survives a relaunch | web: `sessionStorage['tab']` | should |
| `A-05` | Pull-to-refresh re-fetches config and rejoins the sockets | web: 80px threshold, rotating indicator | should |
| `A-06` | Content clears notch, Dynamic Island, and home indicator | web: `env(safe-area-inset-*)` | must (free natively) |
| `A-07` | Portrait stacks label under icon; landscape drops labels to save height | CSS media queries | should |
| `A-08` | App/window title is the meet's `app_window_title`, falling back to its name | `settings.app_window_title` | should |
| `A-09` | Add-to-Home-Screen hint | — | web-only |
| `A-10` | Meet goes offline mid-session → return to the picker | `GET /mobile` 303s to `/` when the meet is gone | must |

> **`A-03` — do not port the edge strips.** The web restricts swipe to two 28px
> strips at the screen edges purely because each tab is an `<iframe>`, and a
> full-width listener would swallow touches meant for the schedule list. A native
> pager has no such problem: **use a normal full-width swipe** with the platform's
> standard pager. This is the clearest case in the file where matching the web
> implementation would make the app worse.

> **The iframes themselves are `web-only` throughout.** Anything the templates do
> to work around them — re-dispatching `resize` on tab switch, calling into
> `contentWindow.on_tab_shown()`, the `#edgeT` / `#filter-header` 65px alignment
> contract documented in `mobile.html` — has no native counterpart. Implement the
> *effect* (`R-06`, `L-14`), never the mechanism.

---

## 3. Scoreboard tab (`L`)

Live lane state during a heat. The busiest screen and the one most worth getting right.

### 3.1 Header

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `L-01` | EVENT number, HEAT number, each a small label above a large value | `current_event`, `current_heat` | must |
| `L-02` | Event name | `event_name` — already localised by the server | must |
| `L-03` | Wall clock, `HH:MM`, ticking every second | **device local time**, not the server | must |

### 3.2 Lane table

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `L-04` | One row per lane, `num_lanes` rows always present | `settings.num_lanes` | must |
| `L-05` | Columns: lane · name (+ alt sub-line) · club · time · delta · place | `lane_*<i>` | must |
| `L-06` | Relay member names on a dimmed second line under the name | `lane_name_alt<i>` | must |
| `L-07` | Column visibility follows config: `show_name`, `show_club`, `show_delta`, `show_position` | meet `settings` | must |
| `L-08` | Column *headers* hide independently of the columns: `show_*_header` | meet `settings` | should |
| `L-09` | Empty lanes render blank in place — rows never collapse or shift | — | must |
| `L-10` | Frames are partial: merge changed keys into local state, never replace | `update_scoreboard` (§5.1) | must |
| `L-11` | A running lane's time is styled distinctly; on stop it plays a one-shot "locked" transition | `lane_running<i>` false-edge | should |
| `L-12` | Lane **number pulses** between row text colour and timing colour while that lane runs | `lane_running<i>` **and** `meet_live` | **must** |
| `L-13` | Event or heat change blanks all times, deltas, and places | `current_event` / `current_heat` change | must |
| `L-14` | Returning to the tab re-runs layout and refreshes the clock | web: parent re-dispatches `resize` | must (native: on-appear) |

> **`L-12` is the chronometer's replacement.** The cloud strips `running_time`
> before forwarding — one field at timing-tick frequency multiplied by every
> connected phone ([`notes/cloud_parity.md`](../notes/cloud_parity.md)). The pulse
> is therefore the *only* signal that a race is under way. An app that skips it
> shows a board that looks frozen for the length of every heat.
>
> It is gated on `meet_live` as well as `lane_running<i>`: with no console feeding
> the meet, nothing pulses, so stale lane state cannot masquerade as a live race.

### 3.3 Layout

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `L-15` | Portrait: two-line compact row — lane number spanning left, name on line 1 with club right-aligned, time and delta and place on line 2; place prefixed `#` | — | must |
| `L-16` | Landscape: full table with a header row, row font scaled to lane count | — | should |
| `L-17` | Long names are clipped rather than shrunk on this tab | — | must — see note |

> **`L-17` — clip here, shrink on Results (`R-08`).** A live board wants uniform
> row heights and one font size across lanes more than it wants the full name;
> Results is static long enough to be read carefully.
>
> **Note that the cloud web clips on *both* tabs today** — only the Pi's results
> page shrinks ([`notes/cloud_parity.md`](../notes/cloud_parity.md)). So `R-08` is
> the one row in this file that asks an app to beat its reference implementation
> rather than match it, and it is deliberate.
>
> **This is the single problem the native rewrite exists to solve.** Per
> [`notes/native_app_strategy.md`](../notes/native_app_strategy.md), CSS can only
> truncate, while `UILabel.adjustsFontSizeToFitWidth` and Android's
> `autoSizeTextType` shrink to fit. **Shrink-to-fit within the row's own height is
> a legitimate improvement over the web on both tabs** — it is one of the reasons
> to build the apps at all. Only the fallback differs: clip at the floor here,
> wrap or shrink further on Results.

### 3.4 Not on this tab

| ID | Feature | Level |
| --- | --- | --- |
| `L-18` | Carousel / fullscreen image overlay | n/a — images are local to the Pi and are never relayed |
| `L-19` | Podium highlight animation | n/a — Pi-local, `race_finished` is not forwarded |
| `L-20` | Animated column show/hide, operator-driven | n/a — cloud columns are always visible |
| `L-21` | `brief_results` (3s results flash on an unconfirmed finish) | n/a — the cloud stays stateless, see `cloud_parity.md` |
| `L-22` | Live running clock per lane | n/a — `running_time` is stripped; see `L-12` |

---

## 4. Results tab (`R`)

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `R-01` | "Waiting for results…" until the first snapshot arrives | `mobile.waiting_results` | must |
| `R-02` | The waiting state returns on disconnect and when `meet_live` goes false | `disconnect`, `meet_live` | must |
| `R-03` | Header shows the snapshot's own event, heat, and event name | `results_snapshot` | must |
| `R-04` | Same six columns and visibility flags as the Scoreboard tab | shared config | must |
| `R-05` | **Lane sort**: row index = `channel`; a lane with no final time leaves its row blank | `sort == "lane"`, and when `sort` is absent | must |
| `R-06` | **Place sort**: rows fill top-down as a ranking | `sort == "place"` | must |
| `R-07` | Missing time or place renders as `—`, not blank | — | should |
| `R-08` | Long names shrink to fit rather than clipping | — | should — **exceeds the web**, see `L-17` |
| `R-09` | Final times carry the "locked" styling | `r.time` non-empty | should |
| `R-10` | Returning to the tab re-joins the meet, reconnecting first if needed | web: `on_tab_shown` | must |

> **`R-05` / `R-06` is one field with two very different layouts.** Getting it
> backwards silently renumbers every swimmer. A relay predating the field omits
> `sort` entirely — **absent must be read as `lane`**, never as a default of
> `place`.

---

## 5. Schedule tab (`S`)

The richest screen, and the only one with real client-side state. A spectator uses
it to find *their* swimmer among several hundred.

### 5.1 The list

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `S-01` | Every heat as a card: scheduled time, "Event N — Heat M", event name | `GET /meet/{id}/schedule` ([`api.md`](api.md) §5.8) | must |
| `S-02` | Each card lists its lanes: lane number, name, club, seed time | `lanes[]` | must |
| `S-03` | Relay entries show member first names joined by `·` | `lane.swimmers[].first`, falling back to `.name` | should |
| `S-04` | Alternating card backgrounds, computed over *visible* cards so filtering keeps the stripe | — | should |
| `S-05` | The current heat is highlighted | `results_snapshot` **and** `update_scoreboard` — both update it | must |
| `S-06` | The list auto-scrolls to the current heat once per appearance | re-armed on returning to the foreground | must |
| `S-07` | Empty state when no meet file is loaded | `mobile.no_schedule` / `mobile.no_meet` | must |

> **`S-05` listens to two sockets on purpose.** `update_scoreboard` moves first as
> the operator advances; `results_snapshot` corrects it at the end of a heat.
> Subscribing to only one leaves the highlight lagging or stuck.

### 5.2 Filtering

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `S-08` | Full-screen filter sheet, opened from a button in the top bar | — | must |
| `S-09` | Typeahead search over swimmers and clubs, debounced ~220ms | `GET /search_suggestions?meet_id=&q=` | must |
| `S-10` | Suggestions show type (swimmer/club), name, and club; already-added ones are marked and inert | — | should |
| `S-11` | Active filters appear as chips; tapping a chip's × removes it | — | must |
| `S-12` | A count badge on the filter button shows how many filters are active | — | should |
| `S-13` | Filters are OR-ed: a lane matches if it hits *any* club or swimmer filter | `laneMatches()` | must |
| `S-14` | A swimmer filter matches relay members, not just the lane's display name | `lane.swimmers[]` | must |
| `S-15` | With filters on, non-matching lanes are hidden and heats with no match disappear | — | must |
| `S-16` | **All heats** toggle: keep every heat visible, still filtering the lanes inside | — | should |
| `S-17` | **Upcoming** toggle: hide heats before the current one | needs `S-05`'s current event/heat | should |
| `S-18` | Reset clears filters and both toggles, behind a confirmation | `mobile.reset_confirm` | should |
| `S-19` | Distinct empty states for "no swimmers match these filters" and "no search results" | — | should |
| `S-20` | Filters live only for the session — not persisted | — | should |

> **`S-16` exists to answer "when does my kid swim next?"** With filters on and
> All-heats off, the list collapses to only the heats they are in — the common
> case. Toggled on, the full running order returns with their lanes still
> highlighted, so the spectator can see how many heats away it is.

### 5.3 Refresh

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `S-21` | A new schedule from the Pi refreshes the list | `schedule_update` on `/ws/schedule` → re-fetch `GET /meet/{id}/schedule` | must |

> `schedule_update` carries no payload — it is a signal to re-fetch
> `GET /meet/{id}/schedule`. Preserve the user's active filters across it where the
> filtered names still exist; silently dropping them mid-meet is worse than a stale
> list. An empty `heats` means "loaded, no schedule yet" — show `S-07`, do not treat
> it as an error.

---

## 6. Connection and session (`C`)

The rules in [`ws.js`](../shared/static/js/ws.js). These are the difference between an
app that works on a pool deck and one that shows a frozen board after a screen lock.

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `C-01` | Three independent sockets: `/ws/scoreboard`, `/ws/results`, `/ws/schedule` | §2–3 of `api.md` | must |
| `C-02` | `join_meet {meet_id, vid}` on **every** connect, including every reconnect | — | must |
| `C-03` | Automatic reconnect, capped exponential backoff (web: 500ms → 5s) | — | must |
| `C-04` | Heartbeat `ping` every 15s; no inbound frame for 35s means dead — close and reconnect | server replies `pong` | must |
| `C-05` | On foreground or network-restored: probe with a `ping`; no `pong` within ~4s means dead | — | **must** |
| `C-06` | Frames sent while disconnected are queued and flushed on connect | — | should |
| `C-07` | Unknown events are ignored, not treated as errors | — | must |
| `C-08` | `reload` → re-fetch config and redraw (web: full page reload) | — | must |
| `C-09` | `meet_live` gates live affordances; a `disconnect` implies `meet_live = false` | — | must |
| `C-10` | Anonymous per-install id (`vid`) sent with `join_meet` | random UUID, stored once | must — see note |

> **`C-05` is the one that bites phones.** iOS and Android freeze background
> sockets without ever firing a close: the connection is dead but looks open, so
> backoff never starts and the board sits frozen after every screen lock. The
> foreground probe is what makes the reconnect prompt. Do not rely on `C-03` alone.

> **`C-10` — privacy constraints are binding.** `vid` is a random UUID generated
> once and stored locally, used server-side only for `COUNT(DISTINCT)` to estimate
> attendance. It must **not** be `identifierForVendor`, an advertising id, a device
> id, or anything derived from one, and it must not be correlated with a name or an
> IP address. It is also what `P-07`'s privacy note describes to the user — that
> notice and this field ship together or not at all. Both stores require the
> disclosure to match the behaviour.

---

## 7. Theme and language (`T`)

Every meet themes itself. The app renders the operator's choices; it does not have
a look of its own.

| ID | Feature | Driven by | Level |
| --- | --- | --- | --- |
| `T-01` | Palette from the meet's config: `bg`, `header_bg`, `header_border`, `header_label`, `header_value`, `th_text`, `th_bg`, `row_odd`, `row_even`, `row_text`, `time`, `delta_better`, `delta_worse` | `settings.theme_colors` | must |
| `T-02` | Schedule-specific colours `schedule_event`, `schedule_time`, `schedule_name`, `schedule_club`, each with a built-in default | `settings.theme_colors` | should |
| `T-03` | Three font roles — `family` (text), `digits` (clock), `timing` (times and deltas) | `settings.theme_fonts` | must |
| `T-04` | Column headers and header labels come from the server, already translated | `settings.labels` | must |
| `T-05` | The app's own chrome strings — tab names, empty states, filter UI | the `[mobile]` locale section, en/fr/es | must |
| `T-06` | Language follows the **meet's** locale, not the phone's | `settings.locale` | must |
| `T-07` | Missing theme keys fall back to the documented defaults rather than rendering unstyled | — | must |

> **`T-04` + `T-06`: never translate a label the server sent.** `labels` and
> `event_name` arrive already localised in the meet's language. Re-translating
> them, or localising the chrome to the device language while the board stays in
> the meet's, produces a screen in two languages at once. The app ships the
> `[mobile]` strings for all three locales and picks by `settings.locale`.

> **`T-03`**: the bundled faces are in [`shared/static/fonts/`](../shared/static/fonts/)
> — Overpass Mono, DSEG7 Classic, DSEG14 Classic, Share Tech Mono, Orbitron, Roboto
> Mono. Apps embed them rather than downloading, and fall back to a system monospace
> for an unknown name.

---

## 8. Out of scope

Not on any phone client, now or planned:

| Feature | Where it lives |
| --- | --- |
| Operator controls — start, heat advance, column toggles | admin web UI on the Pi |
| Settings panel | browser page, laptop on the LAN ([`notes/native_app_strategy.md`](../notes/native_app_strategy.md)) |
| Cloud admin — meet retention, relay keys, attendance stats | `cloud/templates/admin.html`, password-gated |
| Console/terminal views, `/ws/settings`, `/ws/terminal` | admin only ([`api.md`](api.md) §2) |
| Full-screen kiosk board | the Qt display, [`notes/scoreboard_parity.md`](../notes/scoreboard_parity.md) |

---

## Changelog

- **v1** — First statement of the mobile feature contract, taken from the cloud
  templates as of the FastAPI/plain-WebSocket server. Tracks `api.md` v1.
