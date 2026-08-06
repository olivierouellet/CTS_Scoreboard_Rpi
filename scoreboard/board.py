"""The scoreboard window — header bar plus one row per lane.

Layout mirrors ``server/templates/live.html`` — the page the Chromium kiosk
actually rendered, since ``/`` redirects there. ``scoreboard.html`` is a different,
diverged template; do not use it as the reference without checking, as its column
widths and heat transition both differ.

Three things depart from the browser, deliberately:

* Names shrink to fit instead of being ellipsised (see :mod:`scoreboard.widgets`).
* Deltas come from the structured ``lane_delta_seconds<i>`` / ``lane_delta_better<i>``
  fields rather than the HTML ``lane_delta<i>`` blob, as ``docs/api.md`` §5.1
  instructs native clients to do.
* Heats dissolve into one another instead of cutting. ``/live`` collapses the
  columns instantly; this follows ``scoreboard.html``'s softer sequence because it
  reads better on a TV. See the README.
"""
import re
import time

from PyQt5.QtCore import (QEasingCurve, QPropertyAnimation, Qt, QTimer,
                          QVariantAnimation)
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (QWIDGETSIZE_MAX, QApplication, QFrame,
                             QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                             QSizePolicy, QVBoxLayout, QWidget)

from .format import fmt_clock, fmt_delta, parse_clock
from .theme import Config
from .widgets import FitLabel

# Clock repaint cadence. 50ms matches the browser: fast enough that hundredths
# look continuous, slow enough to stay cheap on a Pi.
_CLOCK_TICK_MS = 50

# Column stretch weights = the vw widths of `/live`, the page the Chromium kiosk
# actually rendered: `.lane-column` 5vw and `.club-column` 8vw from
# timing_display.css, 6/17/15vw for place/time/delta from live.html's expand_cols().
# Name takes the remainder, as it does in CSS. They sum to 100, so the weights are
# the percentages directly.
#
# Note these are NOT scoreboard.html's numbers — that page gives delta 9vw. `/live`
# is the reference for this display; see the README.
_W_LANE, _W_NAME, _W_CLUB, _W_TIME, _W_DELTA, _W_PLACE = 5, 49, 8, 17, 15, 6

# The three columns that slide in when a race starts, and how long that takes.
# 500ms matches `.timing-anim { transition: … 0.5s ease }` in timing_display.css.
_COL_ANIM_MS = 500

# Heat transition, mirroring mode_to_intro() in scoreboard.html: the podium tints
# fade, then the columns close, then the table fades out, is swapped while
# invisible, and fades back in. Each step is 500ms in the browser.
_PODIUM_FADE_MS  = 500
_CONTENT_FADE_MS = 500
_COL_TOTAL_WEIGHT = _W_LANE + _W_NAME + _W_CLUB + _W_TIME + _W_DELTA + _W_PLACE

_LANE_SUFFIX = re.compile(r'(\d+)$')

# Fractions of a row's height used as the font ceiling for each kind of cell.
_FONT_MAIN = 0.52
_FONT_ALT  = 0.30   # relay member names, rendered under the team name


class LaneRow(QFrame):
    """One lane. Column widths come from the shared stretch weights, so every
    row (and the header) lines up without a grid."""

    def __init__(self, lane: int, cfg: Config, parent=None):
        super().__init__(parent)
        self.lane = lane
        self.cfg  = cfg
        # While True the time cell belongs to the board's clock ticker, not to
        # `lane_time<i>` — see BoardWindow._tick_clock.
        self.running = False
        self.setAutoFillBackground(True)
        self.setFrameShape(QFrame.NoFrame)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(10)

        self.lane_label = FitLabel(str(lane))
        self.lane_label.setAlignment(Qt.AlignCenter)

        # Name and relay members share one cell, stacked — matching the browser's
        # `.lane-name-cell` with its `.name-sub` second line.
        name_box = QVBoxLayout()
        name_box.setContentsMargins(0, 0, 0, 0)
        name_box.setSpacing(0)
        self.name_label = FitLabel()
        self.name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.alt_label = FitLabel()
        self.alt_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.alt_label.hide()
        name_box.addWidget(self.name_label)
        name_box.addWidget(self.alt_label)
        self.name_cell = QWidget()
        self.name_cell.setLayout(name_box)

        self.club_label = FitLabel()
        self.club_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # All shrink-to-fit. Qt clips a label to its own rect, so an oversized
        # value is not lost into the neighbour — it is cut through a glyph, which
        # is worse: `1:12.44` beside a clipped delta read as `1:12.44).06`.
        self.time_label = FitLabel()
        self.time_label.setAlignment(Qt.AlignCenter)

        self.delta_label = FitLabel()
        self.delta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.place_label = FitLabel()
        self.place_label.setAlignment(Qt.AlignCenter)

        # Size policy Ignored in BOTH directions. Cell fonts are derived from the
        # row height, so a font-driven minimum height would feed straight back into
        # the layout and inflate the window — a 1080p board came out 1460px tall,
        # which on a fullscreen TV means the bottom lane is cut off. Rows are sized
        # purely by their stretch weights.
        for widget, weight in ((self.lane_label,  _W_LANE),
                               (self.name_cell,   _W_NAME),
                               (self.club_label,  _W_CLUB),
                               (self.time_label,  _W_TIME),
                               (self.delta_label, _W_DELTA),
                               (self.place_label, _W_PLACE)):
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            widget.setMinimumSize(0, 0)
            row.addWidget(widget, weight)
        for label in (self.name_label, self.alt_label):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            label.setMinimumSize(0, 0)
        self.setMinimumSize(0, 0)

        self.apply_theme()
        self.clear()

    # ── Appearance ─────────────────────────────────────────────────────────────

    def apply_theme(self):
        cfg  = self.cfg
        base = cfg.color('row_odd' if self.lane % 2 else 'row_even')
        self._base_bg = base
        self.setStyleSheet(f'background-color: {base};')

        text_color = cfg.color('row_text')
        for label in (self.lane_label, self.name_label, self.alt_label,
                      self.club_label, self.place_label):
            label.setStyleSheet(f'color: {text_color}; background: transparent;')
            label.setFont(QFont(cfg.family))
        self.time_label.setStyleSheet(
            f"color: {cfg.color('time')}; background: transparent;")
        self.time_label.setFont(QFont(cfg.timing_family))
        self.delta_label.setFont(QFont(cfg.timing_family))
        self._style_delta(None)

        self.name_cell.setVisible(cfg.show_name)
        self.club_label.setVisible(cfg.show_club)
        self.delta_label.setVisible(cfg.show_delta)
        self.place_label.setVisible(cfg.show_position)

    def animated_cells(self):
        """(widget, weight) for the columns that slide in at race start."""
        return ((self.time_label,  _W_TIME),
                (self.delta_label, _W_DELTA),
                (self.place_label, _W_PLACE))

    def resizeEvent(self, event):     # noqa: N802 — Qt naming
        super().resizeEvent(event)
        self.set_row_height(self.height())

    def set_row_height(self, height: int):
        """Rescale fonts to the row height.

        Driven by this row's own resizeEvent, not the window's. Reading a child's
        height from the parent's resizeEvent gets you the geometry from *before*
        the layout ran — that returned 480 for a row that ended up 161px tall, so
        every cell was sized about three times too large.
        """
        main = max(8, int(height * _FONT_MAIN))
        alt  = max(8, int(height * _FONT_ALT))
        for label in (self.lane_label, self.club_label, self.time_label,
                      self.delta_label, self.place_label, self.name_label):
            label.set_max_px(main)
        self.alt_label.set_max_px(alt)

    def _style_delta(self, better):
        color = self.cfg.color('delta_better' if better else 'delta_worse')
        self.delta_label.setStyleSheet(f'color: {color}; background: transparent;')

    def _podium_bg(self, place: str):
        """Tint the top three rows when `show_podium` is on, as the browser does."""
        self._stop_podium_fade()
        key = {'1': 'podium_gold', '2': 'podium_silver', '3': 'podium_bronze'}.get(
            (place or '').strip())
        bg = self.cfg.color(key) if (key and self.cfg.show_podium) else self._base_bg
        self._current_bg = bg
        self.setStyleSheet(f'background-color: {bg};')

    def _stop_podium_fade(self):
        anim = getattr(self, '_podium_anim', None)
        if anim is not None:
            anim.stop()
            self._podium_anim = None

    def fade_podium_out(self, duration_ms: int):
        """Ease the podium tint back to the row's own stripe.

        Step 1 of the heat transition. The browser gets this free from a CSS
        `background-color` transition; Qt stylesheets do not animate, so the colour
        is interpolated and re-applied.
        """
        start = QColor(getattr(self, '_current_bg', self._base_bg))
        end   = QColor(self._base_bg)
        if start == end:
            return
        self._stop_podium_fade()
        anim = QVariantAnimation(self)
        anim.setDuration(duration_ms)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.InOutQuad)

        def paint(colour):
            self._current_bg = colour.name()
            self.setStyleSheet(f'background-color: {colour.name()};')

        anim.valueChanged.connect(paint)
        anim.finished.connect(self._stop_podium_fade)
        self._podium_anim = anim
        anim.start()

    # ── Data ───────────────────────────────────────────────────────────────────

    def clear(self):
        self.name_label.setText('')
        self.alt_label.setText('')
        self.alt_label.hide()
        self.club_label.setText('')
        self.time_label.setText('')
        self.delta_label.setText('')
        self.place_label.setText('')
        self._podium_bg('')

    def update_from(self, snapshot: dict):
        """Re-render from the merged scoreboard state (only this lane's keys)."""
        i = self.lane
        self.name_label.setText(snapshot.get(f'lane_name{i}', ''))

        alt = snapshot.get(f'lane_name_alt{i}', '')
        self.alt_label.setText(alt)
        self.alt_label.setVisible(bool(alt))

        self.club_label.setText(snapshot.get(f'lane_club{i}', ''))
        # A running lane's time is driven by the ticker; writing `lane_time<i>`
        # here would stamp the last split back over the live clock on every frame.
        if not self.running:
            self.time_label.setText(snapshot.get(f'lane_time{i}', ''))

        self.delta_label.setText(fmt_delta(snapshot.get(f'lane_delta_seconds{i}')))
        self._style_delta(snapshot.get(f'lane_delta_better{i}'))

        place = snapshot.get(f'lane_place{i}', '')
        self.place_label.setText((place or '').strip())
        self._podium_bg(place)


class HeaderBar(QFrame):
    """The top bar. Scales its own children for the same reason the rows do."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scale_children = None      # set by BoardWindow once its cells exist

    def resizeEvent(self, event):     # noqa: N802 — Qt naming
        super().resizeEvent(event)
        if self.scale_children is not None:
            self.scale_children(self.height())


class HeaderCell(QWidget):
    """A header pair like ``EVENT 3`` — word and value in *different* colours.

    The browser renders these as two spans (``header_label`` / ``header_value``),
    which is why the theme has a colour for each. Drawing them as one string would
    silently ignore the Label swatch in Settings → Display → Theme.
    """

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.label = FitLabel()
        self.value = FitLabel()
        row.addWidget(self.label)
        row.addWidget(self.value)
        row.addStretch(1)
        self.apply_theme()

    def apply_theme(self):
        self.label.setStyleSheet(
            f"color: {self.cfg.color('header_label')}; background: transparent; border: none;")
        self.value.setStyleSheet(
            f"color: {self.cfg.color('header_value')}; background: transparent; border: none;")
        for part in (self.label, self.value):
            part.setFont(QFont(self.cfg.family))

    def set_pixel_size(self, px: int):
        for part in (self.label, self.value):
            part.set_max_px(max(10, px))

    def set_text(self, label: str, value: str):
        self.label.setText(label)
        self.value.setText(value)


class HeaderRow(QFrame):
    """Column titles. Each title is independently hideable (``show_*_header``)."""

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setAutoFillBackground(True)
        self.setFrameShape(QFrame.NoFrame)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(10)

        self.cells = {}
        spec = (('lane',  _W_LANE,  Qt.AlignCenter),
                ('name',  _W_NAME,  Qt.AlignLeft | Qt.AlignVCenter),
                ('club',  _W_CLUB,  Qt.AlignLeft | Qt.AlignVCenter),
                ('time',  _W_TIME,  Qt.AlignCenter),
                ('delta', _W_DELTA, Qt.AlignRight | Qt.AlignVCenter),
                ('place', _W_PLACE, Qt.AlignCenter))
        for key, weight, align in spec:
            label = FitLabel()
            label.setAlignment(align)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            label.setMinimumSize(0, 0)
            row.addWidget(label, weight)
            self.cells[key] = label
        self.setMinimumSize(0, 0)

        self.apply_theme()

    def apply_theme(self):
        cfg = self.cfg
        self.setStyleSheet(f"background-color: {cfg.color('th_bg')};")
        for key, label in self.cells.items():
            label.setStyleSheet(f"color: {cfg.color('th_text')}; background: transparent;")
            label.setFont(QFont(cfg.family))
            label.setText(cfg.labels.get(key, key.upper()))

        # A column can be visible while its header is not — mirror the browser's
        # separate hide-<col> / hide-<col>-header classes.
        self.cells['lane'].setVisible(cfg.show_lane_header)
        self.cells['name'].setVisible(cfg.show_name and cfg.show_name_header)
        self.cells['club'].setVisible(cfg.show_club and cfg.show_club_header)
        self.cells['time'].setVisible(cfg.show_time_header)
        self.cells['delta'].setVisible(cfg.show_delta and cfg.show_delta_header)
        self.cells['place'].setVisible(cfg.show_position and cfg.show_position_header)

    def animated_cells(self):
        """(widget, weight) for the columns that slide in at race start."""
        return ((self.cells['time'],  _W_TIME),
                (self.cells['delta'], _W_DELTA),
                (self.cells['place'], _W_PLACE))

    def resizeEvent(self, event):     # noqa: N802 — Qt naming
        super().resizeEvent(event)
        self.set_row_height(self.height())

    def set_row_height(self, height: int):
        for label in self.cells.values():
            label.set_max_px(max(8, int(height * _FONT_MAIN)))


class BoardWindow(QWidget):
    """Top-level display: title/event/heat/chrono bar above the lane rows.

    Holds the merged scoreboard state. ``update_scoreboard`` frames are *partial*
    (only changed keys), so they are merged into ``self.snapshot`` and the
    affected rows redrawn — never replace the dict wholesale.
    """

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg      = cfg
        self.snapshot = {}
        self._windowed_size = None    # size to restore when leaving fullscreen

        # ── Live clock ─────────────────────────────────────────────────────────
        # The console streams `running_time` a few times a second. Rendering only
        # those frames would make the clock visibly step, so we re-base on each
        # one and interpolate locally in between.
        self._clock_base = None       # hundredths at the last console update
        self._clock_at   = None       # monotonic() when that update arrived
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(_CLOCK_TICK_MS)
        self._clock_timer.timeout.connect(self._tick_clock)

        # ── Column reveal ──────────────────────────────────────────────────────
        # Time / delta / place slide open when a race starts. Purely cosmetic, and
        # the reason it reads well is the contrast: between heats the board is a
        # calm start list, then the race begins and the timing columns arrive.
        # Starts expanded so an idle board looks finished rather than half-drawn.
        self._col_fraction = 1.0
        self._heat_key = None        # (event, heat) — a change starts the transition
        # While True, frames merge into the snapshot but are not painted: the
        # outgoing heat stays on screen until the fade hides it.
        self.paused = False
        self._transition_token = 0
        self._col_anim = QVariantAnimation(self)
        self._col_anim.setDuration(_COL_ANIM_MS)
        self._col_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._col_anim.valueChanged.connect(self._apply_col_fraction)
        self.setWindowTitle(cfg.meet_title or 'Splouch')

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ─────────────────────────────────────────────────────────
        self.header = HeaderBar()
        self.header.setAutoFillBackground(True)
        bar = QHBoxLayout(self.header)
        bar.setContentsMargins(16, 6, 16, 6)
        bar.setSpacing(24)

        self.title_label = FitLabel(cfg.meet_title)
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.event_cell = HeaderCell(cfg)
        self.heat_cell  = HeaderCell(cfg)
        self.name_label = FitLabel()
        self.name_label.setAlignment(Qt.AlignCenter)
        self.chrono_label = FitLabel()
        self.chrono_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        bar.addWidget(self.title_label, 30)
        bar.addWidget(self.event_cell, 10)
        bar.addWidget(self.heat_cell, 10)
        bar.addWidget(self.name_label, 34)
        bar.addWidget(self.chrono_label, 16)
        root.addWidget(self.header)

        # ── Board ──────────────────────────────────────────────────────────────
        # The column titles and lane rows live in one `content` widget so the heat
        # transition can fade the whole table as a unit while the header bar and
        # background stay put — the same split the browser has between `#scoreboard`
        # and the `.timing-content` table it fades.
        self.content = QWidget()
        content = QVBoxLayout(self.content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        self.header_row = HeaderRow(cfg)
        content.addWidget(self.header_row, 1)

        self.rows = []
        for lane in range(1, cfg.num_lanes + 1):
            row = LaneRow(lane, cfg)
            self.rows.append(row)
            content.addWidget(row, 2)

        self._content_opacity = QGraphicsOpacityEffect(self.content)
        self._content_opacity.setOpacity(1.0)
        self.content.setGraphicsEffect(self._content_opacity)
        self._content_fade = QPropertyAnimation(self._content_opacity, b'opacity', self)
        self._content_fade.setEasingCurve(QEasingCurve.InOutQuad)
        root.addWidget(self.content, 1)
        self.header.scale_children = self._scale_header

        # ── Status overlay ─────────────────────────────────────────────────────
        # Shown until the first connection; also covers a mid-meet drop so the TV
        # says why it is frozen instead of silently showing stale times.
        #
        # Two lines: a headline anyone in the stands can read, and a dimmer detail
        # line for whoever is fixing it. The detail carries a live elapsed count,
        # which is the only thing on screen that distinguishes "still trying" from
        # "crashed" — the question a black screen always raises.
        self.status_box = QWidget(self)
        status_layout = QVBoxLayout(self.status_box)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)
        self.status = QLabel('')
        self.status.setAlignment(Qt.AlignCenter)
        self.status_detail = QLabel('')
        self.status_detail.setAlignment(Qt.AlignCenter)
        status_layout.addStretch(1)
        status_layout.addWidget(self.status)
        status_layout.addWidget(self.status_detail)
        status_layout.addStretch(1)
        self.status_box.hide()

        self.apply_theme()

    # ── Appearance ─────────────────────────────────────────────────────────────

    def apply_theme(self):
        cfg = self.cfg
        self.setStyleSheet(f"background-color: {cfg.color('bg')};")
        self.header.setStyleSheet(
            f"background-color: {cfg.color('header_bg')};"
            f"border-bottom: 2px solid {cfg.color('header_border')};")
        for label in (self.title_label, self.name_label):
            label.setStyleSheet(
                f"color: {cfg.color('header_value')}; background: transparent; border: none;")
            label.setFont(QFont(cfg.family))
        for cell in (self.event_cell, self.heat_cell):
            cell.cfg = cfg
            cell.apply_theme()
        # The running clock uses the *digits* font (Settings → Display → Theme →
        # Digit Font), not the timing font — same split as the browser, where the
        # chrono is typically a seven-segment face and lane times are not.
        self.chrono_label.setStyleSheet(
            f"color: {cfg.color('time')}; background: transparent; border: none;")
        self.chrono_label.setFont(QFont(cfg.digits_family))
        self.status_box.setStyleSheet(f"background-color: {cfg.color('bg')};")
        self.status.setStyleSheet(
            f"color: {cfg.color('header_value')}; background: transparent;")
        self.status.setFont(QFont(cfg.family))
        self.status_detail.setStyleSheet(
            f"color: {cfg.color('th_text')}; background: transparent;")
        self.status_detail.setFont(QFont(cfg.family))
        self.header_row.apply_theme()
        for row in self.rows:
            row.apply_theme()

    def keyPressEvent(self, event):   # noqa: N802 — Qt naming
        """Operator keys: leave the board without an SSH session.

        The kiosk has no window decorations and no menu, so these are the only way
        back to the desktop from the TV itself.

        * **Ctrl+Q** quits. Deliberately two-handed: a stray keypress must not take
          the board down mid-meet. It exits with status 0, which
          ``start-scoreboard.sh`` reads as "the operator meant it" and does not
          relaunch — the desktop icon does that.
        * **F11** / **Ctrl+F** toggle fullscreen, for a quick look at the desktop.
          F11 is the Linux-wide convention and the one to reach for; Ctrl+F is a
          second binding for hands used to it. It normally means Find, but this
          app has nothing to search, so the key is free.
        * **Esc** leaves fullscreen (never quits), the conventional escape hatch.
        """
        key  = event.key()
        ctrl = bool(event.modifiers() & Qt.ControlModifier)
        if ctrl and key == Qt.Key_Q:
            QApplication.instance().quit()
        elif key == Qt.Key_F11 or (ctrl and key == Qt.Key_F):
            self.set_fullscreen(not self.isFullScreen())
        elif key == Qt.Key_Escape and self.isFullScreen():
            self.set_fullscreen(False)
        else:
            super().keyPressEvent(event)

    def set_fullscreen(self, fullscreen: bool):
        """Enter or leave fullscreen, remembering the windowed size ourselves.

        ``showNormal()`` is supposed to restore the pre-fullscreen geometry, but
        the kiosk goes fullscreen before the window is ever shown normally, so Qt
        has nothing recorded and falls back to a default box. Tracking the size
        here makes Esc/F11 land at a usable size on the first press.
        """
        if fullscreen:
            if not self.isFullScreen():
                self._windowed_size = self.size()
            self.showFullScreen()
        else:
            self.showNormal()
            if self._windowed_size is not None:
                self.resize(self._windowed_size)

    def _scale_header(self, height: int):
        """Size the top bar's text from the bar's own height."""
        px = max(10, int(height * 0.55))
        self.title_label.set_max_px(px)
        self.name_label.set_max_px(px)
        self.chrono_label.set_max_px(px)
        for cell in (self.event_cell, self.heat_cell):
            cell.set_pixel_size(px)

    def resizeEvent(self, event):     # noqa: N802 — Qt naming
        super().resizeEvent(event)
        # Rows and the header bar scale themselves from their own resizeEvents —
        # see LaneRow.set_row_height for why reading their height from here does
        # not work. This handles only what belongs to the window.
        if self._col_fraction < 1.0:
            self._apply_col_fraction(self._col_fraction)   # widths are width-relative
        self.status_box.setGeometry(self.rect())
        font = self.status.font()
        font.setPixelSize(max(16, int(self.height() * 0.055)))
        self.status.setFont(font)
        font = self.status_detail.font()
        font.setPixelSize(max(11, int(self.height() * 0.028)))
        self.status_detail.setFont(font)

    # ── State ──────────────────────────────────────────────────────────────────

    def set_config(self, cfg: Config):
        """Adopt a freshly fetched config (after a ``reload`` event).

        Lane count changes need the rows rebuilt, which the app handles by
        recreating the window; everything else is a restyle in place.
        """
        self.cfg = cfg
        self.header_row.cfg = cfg
        for row in self.rows:
            row.cfg = cfg
        self.setWindowTitle(cfg.meet_title or 'Splouch')
        self.title_label.setText(cfg.meet_title)
        self.apply_theme()
        self.refresh()

    def set_status(self, text: str, detail: str = ''):
        """Show (or clear, with ``''``) the full-screen status message.

        *text* is the headline, sized to be read from the stands. *detail* is a
        dimmer second line for whoever is troubleshooting — the server address, a
        retry count. Pass a single space as *text* to blank the board with no
        message (the operator's display-overlay toggle).
        """
        self.status.setText(text)
        self.status_detail.setText(detail)
        self.status_detail.setVisible(bool(detail))
        self.status_box.setVisible(bool(text))
        if text:
            self.status_box.setGeometry(self.rect())
            self.status_box.raise_()

    def status_text(self) -> str:
        """The current headline, or ``''`` when no status is showing."""
        return self.status.text() if self.status_box.isVisible() else ''

    # ── Heat transition ────────────────────────────────────────────────────────

    def _drop_stale_timing(self, keep=()):
        """Forget the previous heat's times, places and deltas.

        A new heat has none yet, and they are not merely invisible: the columns
        may be collapsed now, but the operator can reopen them, and `refresh()`
        repaints from the snapshot. Without this the last heat's results would
        reappear under the next heat's names.

        *keep* is the frame that triggered the heat change. Anything it carries
        belongs to the **new** heat and must survive — a console is free to send
        the heat number and a lane time in one packet, and wiping those would
        discard data we had just been given.
        """
        stale = [key for key in self.snapshot
                 if key.startswith(('lane_time', 'lane_place', 'lane_delta',
                                    'lane_running'))
                 and key not in keep]
        for key in stale:
            del self.snapshot[key]

    def _has_results(self) -> bool:
        """True when finished times are on screen — something worth fading out."""
        return any(row.place_label.text() or row.time_label.text()
                   for row in self.rows)

    def begin_heat_transition(self):
        """Results → next heat, in the browser's five steps.

        1. podium tints fade back to the row stripes
        2. the timing columns close
        3. the table fades out
        4. the new heat is painted while it is invisible
        5. the table fades back in

        Each step is 500ms, so the whole thing is about two seconds — which is why
        it only runs when there are results to clear. Loading a heat onto an empty
        board collapses the columns outright; there is nothing to dissolve.

        While the transition runs the table is *paused*: frames still merge into
        the snapshot, they just are not painted until step 4. Otherwise the next
        heat's names would appear on the outgoing results.
        """
        if not self._has_results():
            self.set_columns_visible(False, animate=False)
            return

        token = self._transition_token = self._transition_token + 1
        self.paused = True
        self.stop_clock()

        for row in self.rows:                       # step 1
            row.fade_podium_out(_PODIUM_FADE_MS)
        QTimer.singleShot(_PODIUM_FADE_MS, lambda: self._transition_collapse(token))

    def _transition_collapse(self, token):
        if token != self._transition_token:
            return
        self.set_columns_visible(False)              # step 2
        QTimer.singleShot(_COL_ANIM_MS, lambda: self._transition_fade_out(token))

    def _transition_fade_out(self, token):
        if token != self._transition_token:
            return
        self._fade_content(0.0, lambda: self._transition_swap(token))   # step 3

    def _transition_swap(self, token):
        if token != self._transition_token:
            return
        self.paused = False
        for row in self.rows:                        # step 4, while invisible
            row.clear()
        self.refresh()
        self._fade_content(1.0, None)                # step 5

    def _fade_content(self, target: float, done):
        self._content_fade.stop()
        try:
            self._content_fade.finished.disconnect()
        except TypeError:
            pass                                     # nothing connected
        self._content_fade.setDuration(_CONTENT_FADE_MS)
        self._content_fade.setStartValue(self._content_opacity.opacity())
        self._content_fade.setEndValue(target)
        if done is not None:
            self._content_fade.finished.connect(done)
        self._content_fade.start()

    def cancel_heat_transition(self):
        """Abandon a transition mid-flight and show the current state at once.

        Called when a race starts during the sequence — a swimmer on the blocks
        outranks an animation.
        """
        self._transition_token += 1
        self._content_fade.stop()
        self._content_opacity.setOpacity(1.0)
        if self.paused:
            self.paused = False
            self.refresh()

    # ── Column reveal ──────────────────────────────────────────────────────────

    def _animated_cells(self):
        for container in [self.header_row, *self.rows]:
            yield from container.animated_cells()

    def _apply_col_fraction(self, fraction):
        """Squeeze the timing columns to *fraction* of their natural width.

        Driven by ``maximumWidth`` rather than layout stretch: these cells use
        ``QSizePolicy.Ignored``, which carries the Expand flag, so a stretch of 0
        would not reliably close them.
        """
        self._col_fraction = float(fraction)
        width = max(1, self.width())
        for cell, weight in self._animated_cells():
            if self._col_fraction >= 1.0:
                cell.setMaximumWidth(QWIDGETSIZE_MAX)   # hand control back to the layout
            else:
                natural = width * weight / _COL_TOTAL_WEIGHT
                cell.setMaximumWidth(int(natural * self._col_fraction))

    def set_columns_visible(self, visible: bool, animate: bool = True):
        """Slide the timing columns open or shut.

        Idempotent: re-asserting the current state does not restart the animation,
        so repeated ``columns_state`` frames cannot make the board stutter.
        """
        target = 1.0 if visible else 0.0
        self._col_anim.stop()
        if not animate or self._col_fraction == target:
            self._apply_col_fraction(target)
            return
        self._col_anim.setStartValue(self._col_fraction)
        self._col_anim.setEndValue(target)
        self._col_anim.start()

    @property
    def columns_visible(self) -> bool:
        return self._col_fraction >= 1.0

    # ── Live clock ─────────────────────────────────────────────────────────────

    def _tick_clock(self):
        """Repaint the header chrono and every running lane from the local clock.

        All running lanes show the *same* value — the console's race clock — which
        is what the browser does too. There is no independent per-lane timer: a
        lane's own elapsed time only becomes meaningful at its split, and that
        arrives as ``lane_time<i>``.
        """
        if self._clock_base is None:
            return
        elapsed = int((time.monotonic() - self._clock_at) * 100)
        text = fmt_clock(self._clock_base + elapsed)
        self.chrono_label.setText(text)
        for row in self.rows:
            if row.running:
                row.time_label.setText(text)

    def _sync_clock(self):
        """Run the ticker only while at least one lane is actually swimming."""
        if any(row.running for row in self.rows):
            if not self._clock_timer.isActive():
                self._clock_timer.start()
        else:
            self._clock_timer.stop()

    def stop_clock(self):
        """Freeze every lane at its last time — race over, or board reset."""
        self._clock_timer.stop()
        self._clock_base = None
        for row in self.rows:
            row.running = False

    def apply_update(self, data: dict):
        """Merge a partial ``update_scoreboard`` frame and redraw what changed."""
        if not isinstance(data, dict):
            return
        self.snapshot.update(data)

        # Running flags first: they decide whether the rows redrawn below take
        # their time from `lane_time<i>` or leave it to the ticker.
        #
        # A lane pauses at every wall. The console drops `lane_running<i>` and
        # sends the split in `lane_time<i>`, which stays on screen for a few
        # seconds so it can be read, then the flag comes back and the lane
        # rejoins the clock. Freezing the split is the whole point of the flag —
        # without it the lap time would be overwritten before anyone saw it.
        was_racing = any(row.running for row in self.rows)
        for key, value in data.items():
            if not key.startswith('lane_running'):
                continue
            match = _LANE_SUFFIX.search(key)
            if not match:
                continue
            lane = int(match.group(1))
            if 1 <= lane <= len(self.rows):
                self.rows[lane - 1].running = bool(value)

        # A new heat empties the board back to a start list; the race starting
        # brings the timing columns back. Collapsing is instant because it happens
        # while the previous heat's numbers are being cleared anyway — only the
        # reveal is worth animating.
        if 'current_event' in data or 'current_heat' in data:
            heat = (data.get('current_event', self.snapshot.get('current_event')),
                    data.get('current_heat',  self.snapshot.get('current_heat')))
            if heat != self._heat_key:
                first_heat = self._heat_key is None
                self._heat_key = heat
                # Retire the previous heat's numbers now; the rows keep showing
                # them until step 4 repaints, which is what fades out.
                self._drop_stale_timing(keep=data)
                if first_heat:
                    self.set_columns_visible(False, animate=False)
                else:
                    self.begin_heat_transition()
        if not was_racing and any(row.running for row in self.rows):
            # A race outranks any animation still in flight.
            self.cancel_heat_transition()
            self.set_columns_visible(True)

        if 'current_event' in data:
            self.event_cell.set_text(self.cfg.labels.get('event', 'EVENT'),
                                     str(data['current_event']))
        if 'current_heat' in data:
            self.heat_cell.set_text(self.cfg.labels.get('heat', 'HEAT'),
                                    str(data['current_heat']))
        if 'event_name' in data:
            self.name_label.setText(data['event_name'])
        if 'running_time' in data:
            # Re-base the local clock on the console's authority. Between these
            # frames the ticker interpolates; it never free-runs for long.
            hundredths = parse_clock(data['running_time'])
            if hundredths is None:
                # Unrecognised format — show whatever the console said rather than
                # blanking the header.
                self.chrono_label.setText(data['running_time'])
            else:
                self._clock_base = hundredths
                self._clock_at   = time.monotonic()
                # Paint it now. The ticker only runs while a lane is swimming, so
                # relying on it alone would freeze the header during the seconds
                # when every lane is paused at a wall.
                self.chrono_label.setText(fmt_clock(hundredths))

        # Lane keys are `lane_<field><n>` — the lane is the trailing digits, which
        # is the only part of the name that is stable across fields
        # (`lane_time3`, `lane_delta_seconds3`, `lane_name_alt3`).
        touched = set()
        for key in data:
            if not key.startswith('lane_'):
                continue
            match = _LANE_SUFFIX.search(key)
            if match:
                touched.add(int(match.group(1)))
        if not self.paused:
            for row in self.rows:
                if row.lane in touched:
                    row.update_from(self.snapshot)

        self._sync_clock()
        if self._clock_timer.isActive():
            self._tick_clock()      # paint now rather than up to 50ms from now

    def refresh(self):
        for row in self.rows:
            row.update_from(self.snapshot)

    def reset(self):
        self.stop_clock()
        self.cancel_heat_transition()
        self._heat_key = None
        self.set_columns_visible(True, animate=False)
        self.snapshot.clear()
        self.event_cell.set_text('', '')
        self.heat_cell.set_text('', '')
        self.name_label.setText('')
        self.chrono_label.setText('')
        for row in self.rows:
            row.clear()
