"""The Display tab's two forms, and which one owns the meet title.

The Title heads the splash screen on the TV display, so it sits at the top of the
Splash Screen card rather than with the column settings. That card is a *separate
form* posting `splash_settings_submit`, so moving the input means moving its
handler too — and making sure the move does not lose the `reload` broadcast that
tells displays to re-read `/config`.

Qt-free: this is the server, driven through the real route function.
"""
import asyncio
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'server'))

import bus                                     # noqa: E402
import state                                   # noqa: E402
from routes.settings import route_settings     # noqa: E402

TEMPLATE = os.path.join(REPO, 'server', 'templates', 'settings.html')


class _FakeRequest:
    """Enough of a Starlette Request for the settings POST path."""

    def __init__(self, form):
        self._form = form
        self.method = 'POST'
        self.session = {'user': 'test'}
        self.url = type('U', (), {'path': '/settings'})()
        self.cookies = {}
        self.headers = {}

    async def form(self):
        return self._form


def _post(form, monkeypatch):
    """Run the settings route and report which reload channels were emitted."""
    emitted = []
    monkeypatch.setattr(bus, 'emit', lambda channel, event, data=None:
                        emitted.append((channel, event)))
    monkeypatch.setattr(state, 'save_settings', lambda: None)
    try:
        asyncio.run(route_settings(_FakeRequest(form)))
    except Exception:
        # Rendering the template needs a real Request; the settings-writing half
        # has already run by then, which is the half under test.
        pass
    return emitted


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setitem(state.settings, 'meet_title', 'Old title')
    monkeypatch.setitem(state.settings, 'carousel_interval', 10)
    return state.settings


# ── The form the input lives in ────────────────────────────────────────────────

def _form_body(form_id):
    html = open(TEMPLATE, encoding='utf-8').read()
    return html.split(f'id="{form_id}"')[1].split('</form>')[0]


def test_the_title_input_is_in_the_splash_form():
    splash = _form_body('splash-settings-form')
    assert 'name="meet_title"' in splash
    assert 'name="meet_title"' not in _form_body('display-settings-form')


def test_the_title_is_the_first_field_of_the_splash_card():
    splash = _form_body('splash-settings-form')
    assert splash.index('name="meet_title"') < splash.index('t.disp_splash_screen')


def test_the_title_auto_submits_like_the_rest_of_that_card():
    """The Splash Screen card has no Update button — every field saves on change."""
    splash = _form_body('splash-settings-form')
    after_input = splash.split('name="meet_title"')[1][:250]
    assert '_fsubmit' in after_input


# ── The handler that reads it ──────────────────────────────────────────────────

def test_the_splash_form_saves_the_title(settings, monkeypatch):
    _post({'splash_settings_submit': '1', 'meet_title': 'Championnat provincial'},
          monkeypatch)
    assert settings['meet_title'] == 'Championnat provincial'


def test_the_display_form_no_longer_touches_the_title(settings, monkeypatch):
    """It is not in that form any more, so a post from it must leave it alone."""
    _post({'display_settings_submit': '1', 'locale': 'fr'}, monkeypatch)
    assert settings['meet_title'] == 'Old title'


def test_saving_the_title_tells_the_displays_to_re_read_config(settings, monkeypatch):
    """Without this the TV keeps the old title until something else reloads.

    `/config` carries `meet_title`, and a native client only re-reads it on
    `reload` — the browser gets a fresh render on navigation, so this gap was
    invisible before the Qt display existed.
    """
    emitted = _post({'splash_settings_submit': '1', 'meet_title': 'New title'},
                    monkeypatch)
    assert ('/scoreboard', 'reload') in emitted


def test_changing_the_carousel_also_triggers_a_reload(settings, monkeypatch):
    """Same reason: `/config` carries `carousel_images` and `carousel_interval`.

    Compared as an int deliberately: a catch-all branch further down the handler
    re-writes any matching key with the raw form *string*, so this setting can
    land as `'25'` rather than `25`. Pre-existing, and harmless because every
    reader coerces — `display_config()` and `Config` both do.
    """
    emitted = _post({'splash_settings_submit': '1', 'carousel_interval': '25'},
                    monkeypatch)
    assert int(settings['carousel_interval']) == 25
    assert ('/scoreboard', 'reload') in emitted


def test_a_string_interval_still_reaches_the_display_as_a_number(settings,
                                                                 monkeypatch):
    """Guards the coercion the test above relies on."""
    from scoreboard.theme import Config
    monkeypatch.setitem(state.settings, 'carousel_interval', '25')
    import web
    assert Config(web.display_config()).carousel_interval == 25


def test_an_unchanged_title_does_not_broadcast(settings, monkeypatch):
    """The card auto-submits on blur, so no-op posts are routine."""
    emitted = _post({'splash_settings_submit': '1', 'meet_title': 'Old title'},
                    monkeypatch)
    assert emitted == []
