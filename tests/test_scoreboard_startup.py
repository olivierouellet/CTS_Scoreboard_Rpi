"""The kiosk must stay alive while the server is still booting.

At a meet both Pis power up together and the kiosk usually wins — it has no
service to start. Everything here guards one invariant: **no server call may
block the GUI thread**, because a server that is reachable but not yet answering
does not fail fast, it hangs for the full timeout. Before the first paint that is
a blank TV, not a stale one.

Needs PySide6, so it skips where the `scoreboard` extra is not installed (CI).
Run it on a dev machine or the kiosk itself:

    uv run pytest tests/test_scoreboard_startup.py
"""
import socket
import threading
import time

import pytest

pytest.importorskip('PySide6', reason='needs the `scoreboard` extra (PySide6)')

from PySide6.QtCore import QTimer                       # noqa: E402

from scoreboard.app import ScoreboardApp              # noqa: E402
from scoreboard.board import BoardWindow              # noqa: E402
from scoreboard.theme import Config                   # noqa: E402

# `qt_app` comes from tests/conftest.py — session-scoped, fonts already loaded.

# Generous enough to absorb a slow CI box, tiny next to the 10s fetch timeout
# it is guarding against.
_MAX_STARTUP_SECONDS = 2.0


@pytest.fixture
def hanging_server():
    """A server that accepts the connection then never answers.

    This is the case that matters. A refused connection (nothing listening at
    all) returns instantly and would hide the bug entirely.
    """
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', 0))
    srv.listen(8)

    held = []          # keep the accepted sockets open, so clients stay hung

    def accept_forever():
        while True:
            try:
                held.append(srv.accept())
            except OSError:
                return        # fixture teardown closed the listener
    threading.Thread(target=accept_forever, daemon=True).start()

    yield f'http://127.0.0.1:{srv.getsockname()[1]}'

    srv.close()
    for conn, _ in held:
        conn.close()


def test_startup_does_not_block_on_an_unresponsive_server(qt_app, hanging_server):
    started = time.monotonic()
    app = ScoreboardApp(hanging_server, fullscreen=False)
    elapsed = time.monotonic() - started
    try:
        assert elapsed < _MAX_STARTUP_SECONDS, (
            f'construction blocked for {elapsed:.1f}s — a server call is running '
            f'inline on the GUI thread')
        assert app.window.isVisible(), 'the board must be on screen regardless'
        assert app.window.status.isVisible(), 'and must say what it is waiting for'
    finally:
        app.link.stop()


def test_board_stays_responsive_while_the_server_hangs(qt_app, hanging_server):
    """Frames and keypresses must still be handled during the hang."""
    app = ScoreboardApp(hanging_server, fullscreen=False)
    try:
        QTimer.singleShot(150, qt_app.quit)
        qt_app.exec()                     # let the retry timer fire at least once

        started = time.monotonic()
        app._on_frame('update_scoreboard', {'lane_name1': 'Roy, Zoé'})
        assert time.monotonic() - started < _MAX_STARTUP_SECONDS, 'render blocked'
        assert app.window.rows[0].name_label.text() == 'Roy, Zoé'
    finally:
        app.link.stop()


def test_config_retries_do_not_pile_up_threads(qt_app, hanging_server):
    """Each retry must be a no-op while a fetch is still in flight.

    The retry interval (5s) is shorter than the fetch timeout (10s), so without
    the in-flight guard every tick would spawn another thread against a server
    that is merely slow.
    """
    app = ScoreboardApp(hanging_server, fullscreen=False)
    try:
        before = threading.active_count()
        for _ in range(20):
            app.config_loader.request()
        assert threading.active_count() <= before + 1, 'spawned overlapping fetches'
    finally:
        app.link.stop()


# ── Theme fidelity ─────────────────────────────────────────────────────────────
# Everything an operator can set under Settings → Display → Theme must actually
# reach a widget. A key the display quietly ignores is invisible in review — it
# only shows up as "I changed the colour and nothing happened" on meet day, which
# is how `header_label` and the Digit Font were both missed at first.

def _themed_board(qt_app, colors=None, fonts=None):
    import state
    import web
    state.settings['theme_colors'] = colors or {}
    state.settings['theme_fonts'] = fonts or {}
    window = BoardWindow(Config(web.display_config()))
    window.resize(1920, 1080)
    window.show()
    qt_app.processEvents()
    return window


def test_every_theme_colour_reaches_a_widget(qt_app, settle_podium):
    import state
    # A distinct sentinel per key, so we can tell which widget took which colour.
    sentinels = {k: f'#{i:02x}00{i:02x}'
                 for i, k in enumerate(state.DEFAULT_THEME_COLORS, 1)}
    w = _themed_board(qt_app, colors=sentinels)
    w.apply_update({'current_event': '3', 'current_heat': '1',
                    'lane_time1': '2:20.92', 'lane_place1': '1',
                    'lane_delta_seconds1': -0.46, 'lane_delta_better1': True})
    # The heat is over, so the podium is released — but it fades in, so wait for it
    # to land before reading the row's colour back.
    settle_podium(w)

    applied = {
        'bg':            w.styleSheet(),
        'header_bg':     w.header.styleSheet(),
        'header_border': w.header.styleSheet(),
        # `header_label` is the small EVENT/HEAT word; `header_value` is every
        # other header text — title, the numbers themselves, and the wall clock.
        'header_label':  w.event_cell.label.styleSheet(),
        'header_value':  w.event_cell.value.styleSheet() + w.wall_clock.styleSheet(),
        'th_bg':         w.header_row.styleSheet(),
        'th_text':       w.header_row.cells['lane'].styleSheet(),
        # rows[0] is lane 1 but holds place 1, so the podium tint overrides its
        # base colour — use un-placed lanes to check the row stripes.
        'row_odd':       w.rows[2].styleSheet(),      # lane 3
        'row_even':      w.rows[1].styleSheet(),      # lane 2
        'row_text':      w.rows[0].lane_label.styleSheet(),
        'time':          w.rows[0].time_label.styleSheet(),
        'delta_better':  w.rows[0].delta_label.styleSheet(),
        'podium_gold':   w.rows[0].styleSheet(),
    }
    missing = [k for k, css in applied.items() if sentinels[k] not in css.lower()]
    assert not missing, f'theme colours set in Settings but ignored by the TV: {missing}'
    w.close()


def test_the_three_theme_fonts_land_on_the_right_widgets(qt_app):
    """family / timing / digits are three separate settings, not one."""
    w = _themed_board(qt_app, fonts={'family': 'Roboto Mono',
                                     'timing': 'Share Tech Mono',
                                     'digits': 'DSEG7Classic'})
    assert w.rows[0].name_label.font().family() == 'Roboto Mono'
    assert w.rows[0].club_label.font().family() == 'Roboto Mono'
    assert w.rows[0].time_label.font().family() == 'Share Tech Mono'
    assert w.rows[0].delta_label.font().family() == 'Share Tech Mono'
    # The running clock follows Digit Font, matching the browser's `--font-digits`.
    # Note the resolved name gains a space: the file calls itself "DSEG7 Classic".
    assert w.chrono_label.font().family() == 'DSEG7 Classic'


def test_the_digit_font_reaches_the_lane_numbers_and_places(qt_app):
    """`tbody td:first-child, [id^="lane_place"]` take `--font-digits` in the CSS.

    Both went to the main family for a while, which on the stock theme is the
    difference between a seven-segment board and a monospace one — and no test
    noticed, because the running clock was using the digit font correctly.
    """
    w = _themed_board(qt_app, fonts={'family': 'Roboto Mono',
                                     'timing': 'Share Tech Mono',
                                     'digits': 'DSEG7Classic'})
    assert w.rows[0].lane_label.font().family() == 'DSEG7 Classic'
    assert w.rows[0].place_label.font().family() == 'DSEG7 Classic'


def test_the_time_column_title_follows_the_times_it_names(qt_app):
    """`#time-column` shares a CSS rule with `.td_time` — time colour, timing font.

    It is the one column heading that is not `th_text`.
    """
    w = _themed_board(qt_app, colors={'time': '#ff8800', 'th_text': '#123456'},
                      fonts={'family': 'Roboto Mono', 'timing': 'Share Tech Mono'})
    time_title = w.header_row.cells['time']
    assert '#ff8800' in time_title.styleSheet().lower()
    assert time_title.font().family() == 'Share Tech Mono'
    # Every other title stays on th_text in the main family.
    assert '#123456' in w.header_row.cells['lane'].styleSheet().lower()
    assert w.header_row.cells['lane'].font().family() == 'Roboto Mono'
    w.close()


def test_a_config_reload_does_not_shrink_the_waiting_message(qt_app):
    """The waiting screen is the one thing on a stuck board, so it has to be legible.

    `apply_theme` assigns a fresh QFont and a QFont carries a size, so a restyle
    dropped these to ~13px. They are plain QLabels sized from the window height in
    `resizeEvent`, not FitLabels, so they cannot re-fit themselves.

    This is precisely the sequence at every boot: the window opens before `/config`
    answers and shows the waiting message, then the first config arrives and restyles
    it.
    """
    import web
    w = _themed_board(qt_app)
    w.set_status('Waiting for the timing server', 'splouch.local · retrying · 3 s')
    qt_app.processEvents()
    headline = w.status.font().pixelSize()
    detail   = w.status_detail.font().pixelSize()
    assert headline > 0 and detail > 0
    assert headline > detail, 'the headline is the one read from the stands'

    w.set_config(Config(web.display_config()))
    qt_app.processEvents()

    assert w.status.font().pixelSize() == headline, 'the headline shrank'
    assert w.status_detail.font().pixelSize() == detail, 'the detail line shrank'
    w.close()
