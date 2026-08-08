"""The test-session badge.

A recorded session replays real console traffic, so the board looks exactly like a
live race — the operator is watching it to check the board. The badge therefore
has to be unmissable *without* covering anything: the browser draws a small pill
at the bottom centre (`.test-overlay` in timing_display.css) and so do we.

This started as a bug: `test_mode` reused the full-screen status overlay, which is
opaque, so starting a test hid the entire scoreboard behind the words TEST SESSION.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'server'))

import state                                  # noqa: E402
from scoreboard.theme import DEFAULT_STRINGS, Config   # noqa: E402


# ── Qt-free ────────────────────────────────────────────────────────────────────

def test_the_badge_text_is_a_display_string():
    assert 'test_session' in DEFAULT_STRINGS


@pytest.mark.parametrize('code', ['en', 'fr', 'es'])
def test_every_locale_translates_it(code):
    strings = state.display_strings(code)
    assert strings.get('test_session'), f'{code} has no test_session'


def test_the_server_ships_it_in_config(monkeypatch):
    import web
    monkeypatch.setitem(state.settings, 'locale', 'fr')
    cfg = Config(web.display_config())
    assert cfg.strings['test_session'].startswith('⚠')
    assert 'TEST' in cfg.strings['test_session'].upper()


# ── Qt ─────────────────────────────────────────────────────────────────────────

pytest.importorskip('PySide6', reason='needs the `scoreboard` extra (PySide6)')

from scoreboard.board import BoardWindow      # noqa: E402


@pytest.fixture
def board(qt_app):
    window = BoardWindow(Config({
        'num_lanes': 6,
        'display_strings': {'test_session': '⚠ SESSION DE TEST'}}))
    window.resize(1920, 1080)
    window.show()
    qt_app.processEvents()
    yield window
    window.stop_clock()
    window.close()


def test_the_badge_appears_and_disappears(board, qt_app):
    assert not board.test_badge.isVisible()

    board.set_test_mode(True)
    qt_app.processEvents()
    assert board.test_badge.isVisible()
    assert board.test_badge.text() == '⚠ SESSION DE TEST', 'should use the locale string'

    board.set_test_mode(False)
    qt_app.processEvents()
    assert not board.test_badge.isVisible()


def test_it_does_not_cover_the_board(board, qt_app):
    """The whole point. The status overlay is opaque and full-screen; the badge
    must not be that, or a test session hides the thing being tested."""
    board.apply_update({'lane_name1': 'Roy, Zoé', 'lane_time1': '1:12.44'})
    board.set_test_mode(True)
    qt_app.processEvents()

    assert not board.status_box.isVisible(), 'the full-screen overlay must stay down'
    assert board.rows[0].name_label.isVisible()
    assert board.rows[0].name_label.text() == 'Roy, Zoé'

    badge = board.test_badge.geometry()
    assert badge.height() < board.height() * 0.1, 'badge is a pill, not a curtain'
    assert badge.width() < board.width() * 0.5


def test_it_sits_at_the_bottom_centre(board, qt_app):
    """Matching `.test-overlay`'s `bottom: 2.5vh; left: 50%` in the browser."""
    board.set_test_mode(True)
    qt_app.processEvents()
    badge = board.test_badge.geometry()

    assert abs(badge.center().x() - board.width() // 2) <= 2, 'not centred'
    assert badge.bottom() < board.height(), 'runs off the bottom of the screen'
    assert badge.top() > board.height() * 0.8, 'not near the bottom'


def test_it_follows_a_resize(board, qt_app):
    board.set_test_mode(True)
    qt_app.processEvents()
    board.resize(3840, 2160)
    qt_app.processEvents()

    badge = board.test_badge.geometry()
    assert abs(badge.center().x() - board.width() // 2) <= 2
    assert badge.top() > board.height() * 0.8


def test_it_falls_back_when_the_server_sends_no_string(qt_app):
    """A server older than this key must not produce a blank badge."""
    window = BoardWindow(Config({'num_lanes': 4}))
    window.resize(1920, 1080)
    window.show()
    try:
        window.set_test_mode(True)
        qt_app.processEvents()
        assert window.test_badge.text() == DEFAULT_STRINGS['test_session']
    finally:
        window.close()


def test_a_config_reload_does_not_shrink_the_badge(board, qt_app):
    """`apply_theme` assigns a fresh QFont, and a QFont carries a size.

    The badge is a plain QLabel sized from the window in `_place_test_badge`, so
    unlike a FitLabel it cannot re-fit itself — the size has to survive the restyle.
    A reload while a test session is running used to drop it to ~13px.
    """
    board.set_test_mode(True)
    qt_app.processEvents()
    before = board.test_badge.font().pixelSize()
    assert before > 0

    board.set_config(Config({
        'num_lanes': 6,
        'display_strings': {'test_session': '⚠ SESSION DE TEST'}}))
    qt_app.processEvents()

    assert board.test_badge.font().pixelSize() == before, 'the badge shrank'
    assert board.test_badge.font().bold(), 'and it must stay bold'
