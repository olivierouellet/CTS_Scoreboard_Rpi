"""`shared/templates/` — one phone board, served by both servers.

`live-mobile.html` is a single file now: the Pi and the cloud render the same
template, differing only in whether `MEET_ID` is set. `results.html` (cloud) also
extends the same base, so a base change reaches three pages at once.

What the tests are for. The page reached its current shape by deleting things —
the carousel, the test banner, the operator column collapse, the timed revert on
implied results, the idle meet title, the synthesized row gradient — because this
view is for operators verifying a pool setup and for spectators falling back from
the native apps. Neither wants chrome, and both want the screen to match the last
frame received. Re-adding any of it, or letting the two servers drift apart again,
is what these guard against.
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
           'club': 'Club', 'time': 'Time', 'delta': 'Δ', 'place': '#',
           'waiting_results': 'Waiting for results…'}
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
    """As the Pi serves it: one meet, so no room to join."""
    return _render('server/templates', 'live-mobile.html')


@pytest.fixture(scope='module')
def cloud():
    """As the cloud serves it: many meets, joined by id."""
    return _render('cloud/templates', 'live-mobile.html', meet_id='abc123')


@pytest.fixture(scope='module')
def cloud_results():
    """The other page on the same base — base changes must not break it."""
    return _render('cloud/templates', 'results.html', meet_id='abc123')


# ── One template, two servers ──────────────────────────────────────────────────

def test_there_is_exactly_one_live_mobile_template():
    """It lives in shared/. A copy reappearing under server/ or cloud/ would win
    over the shared one — the loaders are own-first — and drift silently."""
    assert os.path.isfile(os.path.join(REPO, 'shared/templates/live-mobile.html'))
    for d in ('server/templates', 'cloud/templates'):
        assert not os.path.exists(os.path.join(REPO, d, 'live-mobile.html')), \
            f'{d}/live-mobile.html shadows the shared template'


def test_the_only_difference_is_the_room_join(pi, cloud):
    """Same file, so the rendered pages may differ only where MEET_ID does."""
    assert "emit('join_meet'" in pi and "emit('join_meet'" in cloud   # the call is in both
    assert 'var MEET_ID   = ""' in pi                                 # …guarded off here
    assert 'var MEET_ID   = "abc123"' in cloud
    assert 'if (MEET_ID) socket.emit' in pi


@pytest.mark.parametrize('probe', [
    'id="lane_num1"',        # the pulse target
    'id="row1"',
    'id="current_event"', 'id="current_heat"', 'id="event_name"',
    'id="meet_datetime"',
    'id="lane_name1"', 'id="lane_name_alt1"', 'id="lane_club1"',
    'id="lane_time1"', 'id="lane_delta1"', 'id="lane_place1"',
])
def test_all_three_pages_share_the_skeleton(pi, cloud, cloud_results, probe):
    for html in (pi, cloud, cloud_results):
        assert probe in html


def test_shared_symbols_are_defined_once(pi, cloud, cloud_results):
    """The merge loop and the state machine are the highest-risk shared code — the
    two surfaces had drifted here before (the cloud could not retrigger the
    time-locked animation). One definition each, on every page."""
    for html in (pi, cloud, cloud_results):
        for symbol in ('function applyScoreboardFrame(',
                       'function apply_state_transition(',
                       'function reset_state(',
                       'function updateAllLanePulses(',
                       'var VALID_FIELDS',
                       'var meet_live'):
            assert html.count(symbol) == 1, f'{symbol} defined {html.count(symbol)}x'


def test_lock_animation_retriggers(pi, cloud):
    """Re-adding a class that is still set does not restart its animation, so both
    classes come off before the reflow. Without this a lane that finishes twice
    shows the lock effect only once."""
    for html in (pi, cloud):
        i = html.index("} else if (was) {")
        block = html[i:html.index("add('time-locked')", i)]
        assert "remove('time-locked')" in block, 'stale class is never cleared'
        assert block.index("remove('time-locked')") < block.index('void tel.offsetWidth')


def test_intro_clears_the_previous_heat(pi, cloud):
    """The server refreshes names/clubs on an event change but not times, deltas or
    places. Without this the last heat's numbers sit under the new swimmers."""
    for html in (pi, cloud):
        intro = html[html.index('function mode_to_intro()'):html.index('function mode_to_running()')]
        for field in ('lane_time', 'lane_delta', 'lane_place'):
            assert f"'{field}'" in intro or f"'{field}'+" in intro or f"'{field}' +" in intro


# ── Deliberately absent ────────────────────────────────────────────────────────

@pytest.mark.parametrize('removed, why', [
    ('carousel-overlay',    'operator image overlay — Pi-local, never relayed'),
    ('test-overlay',        'test-session banner'),
    ('collapse_cols',       'operator column collapse'),
    ('expand_cols',         'duplicated the CSS column widths'),
    ('build_scoreboard_bg', 'synthesized row-stripe gradient'),
    ('set_header_mode',     'idle meet title'),
    ('results_implicit',    'timed revert after implied results'),
])
def test_removed_chrome_stays_removed(pi, cloud, removed, why):
    """Each of these was cut on purpose: this board shows the last frame received
    and nothing else. Re-adding one means re-opening that decision, not patching a
    regression."""
    for html in (pi, cloud):
        assert removed not in html, f'{removed} is back ({why})'


def test_columns_never_animate(pi, cloud, cloud_results):
    """Nothing on a phone collapses them and an orientation flip must not slide
    them. `timing_display.css` is shared with the kiosk, which does animate."""
    for html in (pi, cloud, cloud_results):
        style = re.search(r'<style>(.*?)</style>', html, re.S).group(1)
        rules = re.findall(r'\.delta-column\s*{\s*transition:\s*([^;]+)', style)
        assert rules and rules[-1].strip() == 'none'
        assert 'timing-anim' not in html


def test_results_page_reacts_to_meet_live_its_own_way(cloud_results):
    """It shares `meet_live` with the live board but not the response: no lane runs
    on a results screen, so it shows the waiting message instead of pulsing."""
    assert 'function bindLanePulse' in cloud_results   # defined by the base…
    assert 'bindLanePulse(' not in cloud_results.split('function bindLanePulse')[1]
    assert "sock.on('meet_live'" in cloud_results       # …but wired by hand here
    assert 'showWaiting()' in cloud_results
