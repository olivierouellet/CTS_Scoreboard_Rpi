"""The scoreboard window — header bar plus one row per lane.

Layout mirrors ``server/templates/scoreboard.html`` so the TV looks the same
before and after the migration: LANE · NAME · CLUB · TIME · DELTA · PLACE, with
the same theme colours, the same labels, and the same column-visibility flags.

Two things differ from the browser, deliberately:

* Names shrink to fit instead of being ellipsised (see :mod:`scoreboard.widgets`).
* Deltas come from the structured ``lane_delta_seconds<i>`` / ``lane_delta_better<i>``
  fields rather than the HTML ``lane_delta<i>`` blob, as ``docs/api.md`` §5.1
  instructs native clients to do.
"""
import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                             QSizePolicy, QVBoxLayout, QWidget)

from .format import fmt_delta
from .theme import Config
from .widgets import FitLabel

# Column stretch weights, chosen to match the browser's vw widths.
_W_LANE, _W_NAME, _W_CLUB, _W_TIME, _W_DELTA, _W_PLACE = 6, 38, 20, 17, 9, 6

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
        self.setAutoFillBackground(True)
        self.setFrameShape(QFrame.NoFrame)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(10)

        self.lane_label = QLabel(str(lane))
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

        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignCenter)

        self.delta_label = QLabel()
        self.delta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.place_label = QLabel()
        self.place_label.setAlignment(Qt.AlignCenter)

        for widget, weight in ((self.lane_label,  _W_LANE),
                               (self.name_cell,   _W_NAME),
                               (self.club_label,  _W_CLUB),
                               (self.time_label,  _W_TIME),
                               (self.delta_label, _W_DELTA),
                               (self.place_label, _W_PLACE)):
            widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            row.addWidget(widget, weight)

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

    def set_row_height(self, height: int):
        """Rescale fonts to the row height (called on window resize)."""
        main = int(height * _FONT_MAIN)
        alt  = int(height * _FONT_ALT)
        for label in (self.lane_label, self.club_label, self.time_label,
                      self.delta_label, self.place_label):
            font = label.font()
            font.setPixelSize(max(8, main))
            label.setFont(font)
        self.name_label.set_max_px(main)
        self.alt_label.set_max_px(max(8, alt))

    def _style_delta(self, better):
        color = self.cfg.color('delta_better' if better else 'delta_worse')
        self.delta_label.setStyleSheet(f'color: {color}; background: transparent;')

    def _podium_bg(self, place: str):
        """Tint the top three rows when `show_podium` is on, as the browser does."""
        key = {'1': 'podium_gold', '2': 'podium_silver', '3': 'podium_bronze'}.get(
            (place or '').strip())
        bg = self.cfg.color(key) if (key and self.cfg.show_podium) else self._base_bg
        self.setStyleSheet(f'background-color: {bg};')

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
        self.time_label.setText(snapshot.get(f'lane_time{i}', ''))

        self.delta_label.setText(fmt_delta(snapshot.get(f'lane_delta_seconds{i}')))
        self._style_delta(snapshot.get(f'lane_delta_better{i}'))

        place = snapshot.get(f'lane_place{i}', '')
        self.place_label.setText((place or '').strip())
        self._podium_bg(place)


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
        self.label = QLabel()
        self.value = QLabel()
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
            font = part.font()
            font.setPixelSize(max(10, px))
            part.setFont(font)

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
            label = QLabel()
            label.setAlignment(align)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            row.addWidget(label, weight)
            self.cells[key] = label

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

    def set_row_height(self, height: int):
        for label in self.cells.values():
            font = label.font()
            font.setPixelSize(max(8, int(height * _FONT_MAIN)))
            label.setFont(font)


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
        self.setWindowTitle(cfg.meet_title or 'Splouch')

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ─────────────────────────────────────────────────────────
        self.header = QFrame()
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
        self.chrono_label = QLabel()
        self.chrono_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        bar.addWidget(self.title_label, 30)
        bar.addWidget(self.event_cell, 10)
        bar.addWidget(self.heat_cell, 10)
        bar.addWidget(self.name_label, 34)
        bar.addWidget(self.chrono_label, 16)
        root.addWidget(self.header)

        # ── Board ──────────────────────────────────────────────────────────────
        self.header_row = HeaderRow(cfg)
        root.addWidget(self.header_row, 1)

        self.rows = []
        for lane in range(1, cfg.num_lanes + 1):
            row = LaneRow(lane, cfg)
            self.rows.append(row)
            root.addWidget(row, 2)

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

    def resizeEvent(self, event):     # noqa: N802 — Qt naming
        super().resizeEvent(event)
        # Font sizes track the window, so the same code drives a 1080p TV and a
        # 4K one without a second layout.
        if self.rows:
            row_h = self.rows[0].height()
            self.header_row.set_row_height(self.header_row.height())
            for row in self.rows:
                row.set_row_height(row_h)
        head_h = self.header.height()
        self.title_label.set_max_px(int(head_h * 0.55))
        self.name_label.set_max_px(int(head_h * 0.55))
        for cell in (self.event_cell, self.heat_cell):
            cell.set_pixel_size(int(head_h * 0.55))
        font = self.chrono_label.font()
        font.setPixelSize(max(10, int(head_h * 0.55)))
        self.chrono_label.setFont(font)
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

    def apply_update(self, data: dict):
        """Merge a partial ``update_scoreboard`` frame and redraw what changed."""
        if not isinstance(data, dict):
            return
        self.snapshot.update(data)

        if 'current_event' in data:
            self.event_cell.set_text(self.cfg.labels.get('event', 'EVENT'),
                                     str(data['current_event']))
        if 'current_heat' in data:
            self.heat_cell.set_text(self.cfg.labels.get('heat', 'HEAT'),
                                    str(data['current_heat']))
        if 'event_name' in data:
            self.name_label.setText(data['event_name'])
        if 'running_time' in data:
            self.chrono_label.setText(data['running_time'])

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
        for row in self.rows:
            if row.lane in touched:
                row.update_from(self.snapshot)

    def refresh(self):
        for row in self.rows:
            row.update_from(self.snapshot)

    def reset(self):
        self.snapshot.clear()
        self.event_cell.set_text('', '')
        self.heat_cell.set_text('', '')
        self.name_label.setText('')
        self.chrono_label.setText('')
        for row in self.rows:
            row.clear()
