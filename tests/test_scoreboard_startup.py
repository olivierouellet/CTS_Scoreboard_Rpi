"""The kiosk must stay alive while the server is still booting.

At a meet both Pis power up together and the kiosk usually wins — it has no
service to start. Everything here guards one invariant: **no server call may
block the GUI thread**, because a server that is reachable but not yet answering
does not fail fast, it hangs for the full timeout. Before the first paint that is
a blank TV, not a stale one.

Needs PyQt5, so it skips where the `scoreboard` extra is not installed (CI).
Run it on a dev machine or the kiosk itself:

    uv run --extra scoreboard pytest tests/test_scoreboard_startup.py
"""
import os
import socket
import sys
import threading
import time

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip('PyQt5', reason='needs the `scoreboard` extra (PyQt5)')

from PyQt5.QtCore import QTimer                       # noqa: E402
from PyQt5.QtWidgets import QApplication              # noqa: E402

from scoreboard.app import ScoreboardApp              # noqa: E402

# Generous enough to absorb a slow CI box, tiny next to the 10s fetch timeout
# it is guarding against.
_MAX_STARTUP_SECONDS = 2.0


@pytest.fixture(scope='module')
def qt_app():
    yield QApplication.instance() or QApplication([])


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
        qt_app.exec_()                     # let the retry timer fire at least once

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
