# Bundled fonts

Every face ships **twice**, on purpose:

- **`.woff2`** — for the browser clients, loaded via `@font-face` in the templates.
  Roughly a quarter the size of the TTF, and web-only.
- **`.ttf`** — for the Qt scoreboard (`scoreboard/`). Qt's font database cannot read
  woff2 at all, so the browser files are useless to it.

Do not delete either set.

## Contents

| family (as Qt reports it) | files | copyright | licence |
| --- | --- | --- | --- |
| DSEG7 Classic | `DSEG7Classic-Regular.{ttf,woff2}` | 2017 keshikan — Reserved Font Name "DSEG" | OFL 1.1 |
| DSEG14 Classic | `DSEG14Classic-Regular.{ttf,woff2}` | 2017 keshikan — Reserved Font Name "DSEG" | OFL 1.1 |
| Overpass Mono | `OverpassMono[wght].ttf`, `OverpassMono-Regular.woff2` | 2021 The Overpass Project Authors | OFL 1.1 |
| Orbitron | `Orbitron[wght].ttf`, `Orbitron-Regular.woff2` | 2018 The Orbitron Project Authors — RFN "Orbitron" | OFL 1.1 |
| Roboto Mono | `RobotoMono[wght].ttf`, `RobotoMono-Regular.woff2` | 2015 The Roboto Mono Project Authors | OFL 1.1 |
| Share Tech Mono | `ShareTechMono-Regular.{ttf,woff2}` | 2012 Carrois Type Design, Ralph du Carrois — RFN "Share" | OFL 1.1 |

Full licence texts are in [`licenses/`](licenses/). All six are under the **SIL Open
Font License 1.1**, which permits bundling and redistribution inside this project
(including commercially). The fonts remain under OFL — they are *not* covered by the
repository's MIT licence.

**If you ever modify one of these fonts, you must rename it.** Four carry a Reserved
Font Name, and OFL forbids a modified version keeping the original name. Subsetting or
instancing a variable font to a static one both count as modification. The easiest way
to stay clear of this is what we do now: ship upstream files untouched.

## Sources

| font | upstream |
| --- | --- |
| DSEG7 / DSEG14 Classic | <https://github.com/keshikan/DSEG> (release `v0.46`) |
| Overpass Mono | <https://github.com/google/fonts/tree/main/ofl/overpassmono> |
| Orbitron | <https://github.com/google/fonts/tree/main/ofl/orbitron> |
| Roboto Mono | <https://github.com/google/fonts/tree/main/ofl/robotomono> |
| Share Tech Mono | <https://github.com/google/fonts/tree/main/ofl/sharetechmono> |

Roboto Mono was Apache 2.0 for years and has since been relicensed to OFL — it now
lives under `ofl/`, not `apache/`. Older notes saying Apache are stale.

## Two things that will trip you up

**The `[wght]` files are variable fonts.** Overpass Mono, Orbitron and Roboto Mono ship
from Google Fonts only in this form. PyQt5 (Qt 5.15) registers their named instances as
selectable styles — verified: `Overpass Mono` exposes Light/Regular/Medium/SemiBold/Bold
— and a plain `QFont(family)` resolves to **Regular**. That last part is not automatic:
Overpass Mono's variable default axis value is `wght=300` (Light), and it is only Qt
asking for weight 400 that lands on Regular. Don't assume the default instance is the
one you want.

**A font's CSS name and its real name can differ.** The templates declare
`@font-face { font-family: 'DSEG7Classic' }` — an arbitrary label with no obligation to
match anything in the file. The font itself is called `DSEG7 Classic`, with a space.
The browser is happy either way; Qt reads the real name and would drop to the fallback.
`scoreboard/fonts.py` bridges this by matching family names ignoring spaces and case.
Keep that in mind before "fixing" a name mismatch in either direction.
