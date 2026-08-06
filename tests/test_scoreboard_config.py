"""Config normalisation for the Qt display.

Deliberately Qt-free: `scoreboard.theme` must import without PyQt5 so this runs
in CI and on a dev machine that never installs the `scoreboard` extra. The
widget behaviour (shrink-to-fit, frame merging) needs a QApplication and is
covered separately — see scoreboard/README.md.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoreboard.theme import DEFAULT_COLORS, DEFAULT_FONTS, Config  # noqa: E402


def test_empty_config_falls_back_to_defaults():
    """First boot: the board must draw before the server ever answers."""
    cfg = Config()
    assert cfg.num_lanes == 8
    assert cfg.meet_title == ''
    assert cfg.color('bg') == DEFAULT_COLORS['bg']
    assert cfg.show_name and cfg.show_club and cfg.show_delta


def test_server_values_override_defaults_per_key():
    """A partial theme_colors block overrides only the keys it names."""
    cfg = Config({'theme_colors': {'time': '#00ff00'}})
    assert cfg.color('time') == '#00ff00'
    assert cfg.color('bg') == DEFAULT_COLORS['bg']


def test_show_flags_default_true_but_honour_false():
    cfg = Config({'show_club': False, 'show_delta_header': False})
    assert cfg.show_club is False
    assert cfg.show_delta_header is False
    assert cfg.show_name is True          # unspecified => visible


def test_lane_count_is_clamped():
    """The board has 12 rows of hardware at most; a bad value must not crash it."""
    assert Config({'num_lanes': 99}).num_lanes == 12
    # 0 and None are both "unset" — a zero-lane board is meaningless, so both
    # fall back to the 8-lane default rather than rendering an empty screen.
    assert Config({'num_lanes': 0}).num_lanes == 8
    assert Config({'num_lanes': None}).num_lanes == 8


def test_null_theme_blocks_do_not_wipe_defaults():
    """`theme_fonts: null` reaches us as None — merging it must not explode."""
    cfg = Config({'theme_colors': None, 'theme_fonts': None, 'labels': None})
    assert cfg.color('row_text') == DEFAULT_COLORS['row_text']
    assert cfg.fonts['family'] == DEFAULT_FONTS['family']
    assert cfg.labels['lane'] == 'LANE'


def test_labels_are_taken_from_the_server_locale():
    cfg = Config({'labels': {'lane': 'COULOIR', 'name': 'NOM'}})
    assert cfg.labels['lane'] == 'COULOIR'
    assert cfg.labels['time'] == 'TIME'   # untranslated keys keep the fallback


# ── Carousel (Settings → Display → Splash Screen) ──────────────────────────────

def test_carousel_defaults_are_empty_and_sane():
    cfg = Config()
    assert cfg.carousel_images == []
    assert cfg.carousel_interval == 10


def test_carousel_values_come_from_the_server():
    cfg = Config({'carousel_images': ['a.png', 'b.png'], 'carousel_interval': 4})
    assert cfg.carousel_images == ['a.png', 'b.png']
    assert cfg.carousel_interval == 4


@pytest.mark.parametrize('bad', [0, -5, None, ''])
def test_a_zero_or_missing_interval_falls_back(bad):
    """A zero interval would spin the carousel timer as fast as Qt allows."""
    assert Config({'carousel_interval': bad}).carousel_interval >= 1


def test_a_null_image_list_does_not_crash():
    assert Config({'carousel_images': None}).carousel_images == []


def test_config_endpoint_exposes_the_carousel(monkeypatch, tmp_path):
    """`/live` builds this list for its template; native clients need it too."""
    import state
    import web
    (tmp_path / 'sponsor.png').write_bytes(b'x')
    (tmp_path / 'nested').mkdir()                 # directories must be skipped
    monkeypatch.setattr(state, 'IMAGES_DIR', str(tmp_path))
    monkeypatch.setitem(state.settings, 'carousel_interval', 7)

    cfg = web.display_config()
    assert cfg['carousel_images'] == ['sponsor.png']
    assert cfg['carousel_interval'] == 7
