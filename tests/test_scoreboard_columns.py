"""The column reveal, and the overflow rule that makes it safe.

Time / delta / place collapse when a heat loads and slide open when the race
starts. It is purely cosmetic — the contrast is the point: between heats the
board is a calm start list, then the race begins and the timing columns arrive.
The operator's toggle on /operator drives the same mechanism via `columns_state`.

Needs PySide6 (`uv run pytest tests/`); skips without it.
"""
import pytest

pytest.importorskip('PySide6', reason='needs the `scoreboard` extra (PySide6)')

from PySide6.QtCore import QAbstractAnimation      # noqa: E402
from PySide6.QtGui import QFontMetrics             # noqa: E402

from scoreboard.board import BoardWindow         # noqa: E402
from scoreboard.theme import Config              # noqa: E402

# `qt_app` comes from tests/conftest.py — session-scoped, fonts already loaded.


@pytest.fixture
def board(qt_app):
    window = BoardWindow(Config({'num_lanes': 6}))
    window.resize(1920, 1080)
    window.show()
    qt_app.processEvents()
    yield window
    window.stop_clock()
    window.close()


def _timing_widths(board):
    row = board.rows[0]
    return (row.time_label.width(), row.delta_label.width(), row.place_label.width())


def _seek(board, qt_app, fraction):
    """Drive the animation to a point in time — deterministic, no sleeping."""
    anim = board._col_anim
    anim.setCurrentTime(int(anim.duration() * fraction))
    qt_app.processEvents()


def _run_transition(board, qt_app):
    """Drive the sequence deterministically instead of sleeping through 2s."""
    board._transition_collapse(board._transition_token)
    board._col_anim.setCurrentTime(board._col_anim.duration())
    board._transition_fade_out(board._transition_token)
    board._content_fade.setCurrentTime(board._content_fade.duration())
    qt_app.processEvents()


def test_an_idle_board_shows_every_column(board):
    """Before any heat arrives the board must look finished, not half-drawn."""
    assert board.columns_visible
    assert all(w > 0 for w in _timing_widths(board))


def test_a_new_heat_collapses_the_timing_columns(board, qt_app):
    board.apply_update({'current_event': '3', 'current_heat': '1',
                        'lane_name1': 'Roy, Zoé'})
    qt_app.processEvents()
    assert not board.columns_visible
    assert _timing_widths(board) == (0, 0, 0)
    # The freed width goes to the name, which is the visual point of collapsing.
    assert board.rows[0].name_cell.width() > 900


def test_the_race_starting_slides_them_open(board, qt_app):
    board.apply_update({'current_event': '3', 'current_heat': '1'})
    qt_app.processEvents()
    assert _timing_widths(board) == (0, 0, 0)

    board.apply_update({'running_time': '0.00', 'lane_running1': True})
    assert board._col_anim.state() == QAbstractAnimation.Running, 'reveal not animated'

    _seek(board, qt_app, 0.5)
    half = _timing_widths(board)
    assert all(0 < w for w in half), 'columns should be partly open mid-animation'

    _seek(board, qt_app, 1.0)
    assert board.columns_visible
    assert all(w > h for w, h in zip(_timing_widths(board), half))


def test_the_next_heat_collapses_them_again(board, qt_app):
    board.apply_update({'current_event': '3', 'current_heat': '1',
                        'running_time': '0.00', 'lane_running1': True})
    _seek(board, qt_app, 1.0)
    assert board.columns_visible

    # A lane with a time on screen means there is something to dissolve, so the
    # collapse now waits behind the podium fade rather than snapping shut.
    board.apply_update({'lane_running1': False, 'current_heat': '2'})
    qt_app.processEvents()
    _run_transition(board, qt_app)
    assert not board.columns_visible


def test_an_event_change_collapses_them_too(board, qt_app):
    """The trigger is the (event, heat) pair, not the heat alone.

    Moving from event 3 heat 1 to event 4 heat 1 is a new race with a new start
    list, even though the heat number is unchanged. The browser treats it the same
    way — either field changing drops it into the intro state.
    """
    board.apply_update({'current_event': '3', 'current_heat': '1',
                        'running_time': '0.00', 'lane_running1': True})
    _seek(board, qt_app, 1.0)
    assert board.columns_visible

    board.apply_update({'lane_running1': False, 'current_event': '4'})
    qt_app.processEvents()
    _run_transition(board, qt_app)
    assert not board.columns_visible, 'an event change must collapse the columns'


def test_repeated_heat_frames_do_not_re_collapse(board, qt_app):
    """`current_heat` is resent constantly; only a *change* may collapse."""
    board.apply_update({'current_event': '3', 'current_heat': '1'})
    board.apply_update({'running_time': '0.00', 'lane_running1': True})
    _seek(board, qt_app, 1.0)

    board.apply_update({'current_event': '3', 'current_heat': '1',
                        'running_time': '12.00'})
    qt_app.processEvents()
    assert board.columns_visible, 'a repeated heat frame collapsed the board mid-race'


def test_operator_toggle_uses_the_same_mechanism(board, qt_app):
    board.set_columns_visible(False, animate=False)
    assert not board.columns_visible

    board.set_columns_visible(True)
    _seek(board, qt_app, 1.0)
    assert board.columns_visible
    assert all(w > 0 for w in _timing_widths(board))


def test_re_asserting_the_current_state_does_not_re_animate(board):
    """Repeated `columns_state` frames must not make the board stutter."""
    board.set_columns_visible(True, animate=False)
    board.set_columns_visible(True)
    assert board._col_anim.state() != QAbstractAnimation.Running


def test_reset_restores_the_idle_look(board, qt_app):
    board.apply_update({'current_event': '3', 'current_heat': '1'})
    qt_app.processEvents()
    assert not board.columns_visible

    board.reset()
    assert board.columns_visible


# ── Overflow ───────────────────────────────────────────────────────────────────

def test_no_cell_paints_outside_its_column(board, qt_app):
    """Every cell shrinks to fit, and elides rather than being cut mid-glyph.

    Qt clips a label to its own rect, so an oversized value never reaches the
    neighbouring cell — it is truncated through a character instead, which reads
    as corruption: `1:12.44` next to a clipped delta rendered as `1:12.44).06`.
    Below the font floor the text is elided, so it ends in `…` rather than a
    half-drawn glyph.
    """
    board.apply_update({
        'current_event': '3', 'current_heat': '1',
        **{f'lane_name{i}': 'Vandenbroucke-Mortensen, Alexandra' for i in range(1, 7)},
        **{f'lane_club{i}': 'CN Saint-Jean-sur-Richelieu' for i in range(1, 7)},
        **{f'lane_time{i}': '1:12.44' for i in range(1, 7)},
        **{f'lane_place{i}': str(i) for i in range(1, 7)},
        **{f'lane_delta_seconds{i}': -12.34 for i in range(1, 7)},
    })
    board.set_columns_visible(True, animate=False)
    qt_app.processEvents()

    overflowing = []
    for row in board.rows:
        cells = ((row.lane_label, 'lane'), (row.name_label, 'name'),
                 (row.club_label, 'club'), (row.time_label, 'time'),
                 (row.delta_label, 'delta'), (row.place_label, 'place'))
        for label, name in cells:
            if not label.isVisible() or not label.text():
                continue
            drawn  = label.displayed_text()
            needed = QFontMetrics(label.font()).horizontalAdvance(drawn)
            if needed > label.width():
                overflowing.append(f'lane {row.lane} {name}: '
                                   f'{needed}px of text in {label.width()}px')
    assert not overflowing, 'cells painting outside their column: ' + '; '.join(overflowing)


def test_headers_shrink_to_fit_too(board, qt_app):
    """Translated headers are long — `COULOIR` in a lane column six units wide."""
    board.header_row.cells['lane'].setText('COULOIR')
    board.header_row.cells['place'].setText('CLASSEMENT')
    qt_app.processEvents()
    for key in ('lane', 'place'):
        label = board.header_row.cells[key]
        needed = QFontMetrics(label.font()).horizontalAdvance(label.displayed_text())
        assert needed <= label.width(), f'{key} header overflows its column'


# ── Heat transition ────────────────────────────────────────────────────────────
# Results → next heat is a five-step dissolve, mirroring mode_to_intro() in
# scoreboard.html: podium tints fade, columns close, the table fades out, the new
# heat is painted while invisible, the table fades back in. 500ms per step.

def _finish_a_heat(board, qt_app, event='3', heat='1'):
    board.apply_update({'current_event': event, 'current_heat': heat,
                        'lane_name1': 'Roy, Zoé', 'lane_name2': 'Côté, Léa'})
    board.apply_update({'running_time': '0.00',
                        'lane_running1': True, 'lane_running2': True})
    qt_app.processEvents()
    board.apply_update({'lane_running1': False, 'lane_running2': False,
                        'lane_time1': '58.12', 'lane_place1': '1',
                        'lane_time2': '59.03', 'lane_place2': '2'})
    board.cancel_heat_transition()
    board.set_columns_visible(True, animate=False)
    qt_app.processEvents()


def test_the_table_pauses_so_the_new_heat_does_not_leak(board, qt_app):
    """The outgoing results stay on screen until the fade hides them."""
    _finish_a_heat(board, qt_app)
    board.apply_update({'current_heat': '2', 'lane_name1': 'Nguyen, An'})
    qt_app.processEvents()

    assert board.paused
    assert board.rows[0].name_label.text() == 'Roy, Zoé', 'next heat leaked early'
    assert board.rows[0].time_label.text() == '58.12', 'results cleared too early'


def test_the_podium_tint_fades_before_anything_moves(board, qt_app):
    _finish_a_heat(board, qt_app)
    gold = board.cfg.color('podium_gold')
    assert board.rows[0]._current_bg == gold

    board.apply_update({'current_heat': '2'})
    qt_app.processEvents()
    anim = board.rows[0]._podium_anim
    assert anim is not None, 'podium tint did not start fading'

    anim.setCurrentTime(anim.duration())
    assert board.rows[0]._current_bg.lower() == board.rows[0]._base_bg.lower()
    # Nothing else has moved yet.
    assert board._content_opacity.opacity() == 1.0
    assert board.columns_visible


def test_the_new_heat_appears_only_once_invisible(board, qt_app):
    _finish_a_heat(board, qt_app)
    board.apply_update({'current_heat': '2', 'lane_name1': 'Nguyen, An'})
    qt_app.processEvents()
    _run_transition(board, qt_app)

    assert not board.paused
    assert board.rows[0].name_label.text() == 'Nguyen, An'
    # The previous heat's times must be gone, not merely hidden behind the
    # collapsed columns — the operator can reopen them at any moment.
    assert board.rows[0].time_label.text() == ''
    assert board.rows[0].place_label.text() == ''
    assert not any(k.startswith('lane_time') for k in board.snapshot)
    assert not board.columns_visible, 'a start list keeps the timing columns shut'


def test_the_table_fades_back_in(board, qt_app):
    _finish_a_heat(board, qt_app)
    board.apply_update({'current_heat': '2'})
    qt_app.processEvents()
    _run_transition(board, qt_app)

    board._content_fade.setCurrentTime(board._content_fade.duration())
    qt_app.processEvents()
    assert board._content_opacity.opacity() == 1.0


def test_a_race_starting_cuts_the_transition_short(board, qt_app):
    """A swimmer on the blocks outranks an animation."""
    _finish_a_heat(board, qt_app)
    board.apply_update({'current_heat': '2', 'lane_name1': 'Nguyen, An'})
    qt_app.processEvents()
    assert board.paused

    board.apply_update({'running_time': '0.00', 'lane_running1': True})
    qt_app.processEvents()
    assert not board.paused, 'transition was not cancelled'
    assert board._content_opacity.opacity() == 1.0, 'board left half-faded'
    assert board.rows[0].name_label.text() == 'Nguyen, An'


def test_loading_a_heat_onto_an_empty_board_skips_the_dissolve(board, qt_app):
    """Two seconds of dissolve to clear nothing would just look slow."""
    board.apply_update({'current_event': '3', 'current_heat': '1',
                        'lane_name1': 'Roy, Zoé'})
    qt_app.processEvents()
    assert not board.paused
    assert not board.columns_visible
    assert board._content_opacity.opacity() == 1.0


def test_text_below_the_font_floor_is_elided_not_cut(board, qt_app):
    """A 27-character club in an 8vw column cannot fit even at `min_px`.

    Qt would cut it through a glyph, which reads as corruption. Eliding says
    "there is more" instead. `text()` still returns the full string, so nothing
    downstream sees the shortened version.
    """
    long_club = 'CN Saint-Jean-sur-Richelieu'
    board.apply_update({'current_event': '3', 'current_heat': '1',
                        'lane_club1': long_club})
    board.set_columns_visible(True, animate=False)
    qt_app.processEvents()

    label = board.rows[0].club_label
    assert label.text() == long_club, 'the full value must still be readable in code'
    assert label.displayed_text() != long_club, 'should have been elided'
    assert label.displayed_text().endswith('…')
    assert (QFontMetrics(label.font()).horizontalAdvance(label.displayed_text())
            <= label.width())


def test_a_name_that_fits_is_never_elided(board, qt_app):
    """Shrink-to-fit is the point; eliding is only the last resort."""
    name = 'Vandenbroucke-Mortensen, Alexandra'
    board.apply_update({'current_event': '3', 'current_heat': '1',
                        'lane_name1': name})
    qt_app.processEvents()
    label = board.rows[0].name_label
    assert label.displayed_text() == name, 'a name that fits must stay whole'
