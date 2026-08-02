# Cloud vs Pi — Design Decisions

Intentional differences between the Pi server and the cloud relay, and the reasoning behind them.

---

## Display philosophy

The cloud view is intentionally simpler than the Pi for two reasons:

1. **Resilience** — the cloud serves remote attendees over a relay connection that can drop and reconnect at any time. A stateless display (always showing whatever the latest data says) means any attendee joining mid-meet immediately sees a correct screen without needing to replay a sequence of events. State-dependent transitions can leave the display stuck if an event is missed.

2. **Load** — high-frequency events that only drive cosmetic display features are stripped before forwarding, since each event is multiplied by the number of connected attendees.

---

## Always-on columns, no transitions

On the Pi, the scoreboard transitions between intro, running, and results states with column animations. On the cloud, columns are always visible and the display directly reflects the latest data from the console.

- **`brief_results`** — on the Pi, when a race ends without explicit results the display briefly shows results for 3 seconds then reverts to waiting. This diverges from the console state, which is exactly what the cloud avoids.
- **`columns_state`** — column visibility is controlled by the operator on the Pi. On the cloud, all columns are always shown; the relay does not forward mid-meet column changes.
- **`race_finished` / podium animation** — the podium highlight is triggered locally by the Pi. Not forwarded; adds complexity with little benefit on mobile.

---

## Chronometer

The Pi sends `running_time` as part of `update_scoreboard` at high frequency during a race (every timing tick). On the cloud this field is stripped before forwarding, eliminating a large share of event traffic with no visible loss.

Race progress is instead communicated by the lane number cell pulsing between the row text colour and the timing colour while a swimmer is active. The pulse continues through lap pauses (where `lane_runningN` is briefly false but the lane has a time and no place yet) and stops when `lane_placeN` is set.

---

## Carousel / image overlay

Carousel images are files local to the Pi. Relaying them would require encoding them as base64 and caching on the cloud server — significant complexity for a feature mainly useful on the pool-deck display, not remote phones.

---

## Name overflow: ellipsis vs font shrink

The cloud `results.html` uses `fitNameFontSize()` (same as the Pi) to shrink long swimmer names that overflow their cell. The cloud `live.html` uses CSS `text-overflow: ellipsis` instead — appropriate for a live scoreboard where consistent row heights and font sizes matter more than showing the full name.

---

## Cloud-only features

The following exist on the cloud but not on the Pi:

- **Pull-to-refresh** — swipe down from the top of the mobile view to reload
- **Safe-area insets** — notch and Dynamic Island support on iOS
- **Add-to-Home-Screen hint** — iOS Safari prompt for full-screen PWA install
