"""`shared/templates/scoreboard_base.html` — one base, two servers.

The Pi's `live-mobile.html` and the cloud's now extend the same file, so a change
that suits one can silently break the other. Both are rendered here from their real
context and checked for the things that differ *on purpose*.

What makes this worth a test: the two pages fail in opposite directions. The cloud
must never animate its columns (it has no operator to collapse them) and must never
show the idle meet title (the phone already picked the meet). The Pi must do both.
Each behaviour rides on CSS source order, which no amount of reading catches once
the file is 200 lines long.
"""
import os
import re
import sys

import pytest
from jinja2 import Environment, FileSystemLoader

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'server'))

import state   # noqa: E402

_LABELS = {'event': 'Event', 'heat': 'Heat', 'lane': 'Lane', 'name': 'Name',
           'club': 'Club', 'time': 'Time', 'delta': 'Δ', 'place': '#'}
_FLAGS = {f'show_{k}': True for k in
          ('lane_header', 'name_header', 'club_header', 'time_header',
           'delta_header', 'position_header', 'name', 'club', 'delta', 'position')}


def _render(own_dir, template, **extra):
    env = Environment(loader=FileSystemLoader(
        [os.path.join(REPO, own_dir), os.path.join(REPO, 'shared', 'templates')]))
    env.globals['url_for'] = lambda name, **kw: '/static/' + kw.get('filename', '')
    return env.get_template(template).render(
        num_lanes=6, labels=_LABELS,
        theme_colors=state.DEFAULT_THEME_COLORS,
        theme_fonts=state.DEFAULT_THEME_FONTS,
        **_FLAGS, **extra)


@pytest.fixture(scope='module')
def pi():
    return _render('server/templates', 'live-mobile.html',
                   meet_title='Coupe du Printemps',
                   carousel_images=['a.jpg'], carousel_interval=10)


@pytest.fixture(scope='module')
def cloud():
    return _render('cloud/templates', 'live-mobile.html', meet_id='abc123')


# ── Shared skeleton ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('probe', [
    'id="lane_num1"',        # the pulse target
    'id="row1"',
    'id="current_event"', 'id="current_heat"', 'id="event_name"',
    'id="meet_datetime"',
    'id="lane_name1"', 'id="lane_name_alt1"', 'id="lane_club1"',
    'id="lane_time1"', 'id="lane_delta1"', 'id="lane_place1"',
    'id="timing-bg"',
])
def test_both_pages_share_the_skeleton(pi, cloud, probe):
    assert probe in pi
    assert probe in cloud


def test_both_pages_bind_the_lane_pulse(pi, cloud):
    """Neither view has a running clock, so the pulse is the only progress signal."""
    for html in (pi, cloud):
        assert 'bindLanePulse(socket)' in html
        assert 'lane-pulsing' in html


def test_pulse_helpers_are_defined_once(pi, cloud):
    """They live in the base. A page redefining them would shadow the shared copy
    and quietly drift from the other surface."""
    for html in (pi, cloud):
        assert html.count('function updateAllLanePulses()') == 1
        assert html.count('var meet_live') == 1


# ── Deliberate divergence ──────────────────────────────────────────────────────

def _last_transition_rule(html):
    """The winning `transition` for the optional columns, by CSS source order."""
    style = re.search(r'<style>(.*?)</style>', html, re.S).group(1)
    hits = re.findall(r'\.timing-anim\s*{\s*transition:\s*([^;]+)|'
                      r'\.delta-column\s*{\s*transition:\s*([^;]+)', style)
    assert hits, 'no column transition rule found at all'
    winner = hits[-1]
    return (winner[0] or winner[1]).strip()


def test_cloud_columns_never_animate(cloud):
    """No operator can collapse them there, and an orientation flip must not slide
    them. The base's `transition: none` has to survive."""
    assert _last_transition_rule(cloud) == 'none'


def test_pi_columns_animate(pi):
    """`columns_state` collapses instantly and expands over 0.5s. The Pi re-declares
    `.timing-anim` in extra_style; if that block ever renders *before* the base's
    `transition: none`, the expand goes instant and the regression is invisible."""
    assert _last_transition_rule(pi).startswith('width 0.5s')
    assert 'class="place-column timing-anim"' in pi


def test_idle_title_present_but_hidden_by_default(pi, cloud):
    """Hidden in the markup on both; only the Pi reveals it, via set_header_mode."""
    marker = 'id="header_meet_title_wrap" style="display:none;"'
    assert marker in pi
    assert marker in cloud
    assert 'set_header_mode(false)' in pi                # Pi flips it on at load
    assert 'function set_header_mode' not in cloud       # cloud has no such mode


@pytest.mark.parametrize('feature', [
    'carousel-overlay', 'test-overlay', 'collapse_cols',
    'build_scoreboard_bg', 'brief_results',
])
def test_pi_only_features_stay_off_the_cloud(pi, cloud, feature):
    """Operator-driven, LAN-only, and deliberately not relayed — notes/cloud_parity.md."""
    assert feature in pi
    assert feature not in cloud


def test_only_the_cloud_joins_a_room(pi, cloud):
    """The Pi serves one meet and pushes on connect (docs/api.md §2); emitting
    join_meet there would talk to a handler that does not exist."""
    assert "emit('join_meet'" in cloud
    assert "emit('join_meet'" not in pi
    assert 'var MEET_ID   = ""' in pi
