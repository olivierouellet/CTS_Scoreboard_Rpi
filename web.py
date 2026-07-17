"""Shared FastAPI web helpers for the local Tremplin server.

Centralises Jinja templating (with the global template context that Flask used to
inject via ``@app.context_processor``), the login dependency, and small
Flask-shaped helpers (``redirect``, ``save_upload``) so the route modules read
close to their former selves.
"""
import os
import shutil

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

import state

templates = Jinja2Templates(directory=os.path.join(state.app_dir, 'templates'))


def _url_for(name, **kw):
    """Flask-compatible ``url_for`` for the handful of endpoints templates use."""
    if name == 'static':
        return '/static/' + kw.get('filename', '')
    if name == 'appearance.serve_image':
        return '/images/' + kw.get('filename', '')
    return '/' + (kw.get('filename') or '')


templates.env.globals['url_for'] = _url_for


def _globals():
    """Template values formerly provided by Flask's context_processor.

    Recomputed per render so live settings changes take effect immediately.
    """
    return dict(
        splash_url=state.settings.get('splash_url', ''),
        labels=state.load_locale(),
        show_lane_header=state.settings.get('show_lane_header', True),
        show_name_header=state.settings.get('show_name_header', True),
        show_club_header=state.settings.get('show_club_header', True),
        show_time_header=state.settings.get('show_time_header', True),
        show_delta_header=state.settings.get('show_delta_header', True),
        show_position_header=state.settings.get('show_position_header', True),
        show_name=state.settings.get('show_name', True),
        show_club=state.settings.get('show_club', True),
        show_delta=state.settings.get('show_delta', True),
        show_position=state.settings.get('show_position', True),
        show_podium=state.settings.get('show_podium', True),
        num_lanes=int(state.settings.get('num_lanes', 6)),
        intro_timeout=int(state.settings.get('intro_timeout', 300)),
        results_timeout=int(state.settings.get('results_timeout', 300)),
        server_update_timeout=int(state.settings.get('server_update_timeout', 300)),
        finish_debounce=float(state.settings.get('finish_debounce', 3.0)),
        split_min_duration=float(state.settings.get('split_min_duration', 1.0)),
        pool_length=int(state.settings.get('pool_length', 25)),
        touchpad_sides=int(state.settings.get('touchpad_sides', 1)),
        lenex_pool_length=int(state.lenex_meet_info.get('pool_length_lenex') or 0),
        theme_colors={**state.DEFAULT_THEME_COLORS, **state.settings.get('theme_colors', {})},
        theme_fonts={**state.DEFAULT_THEME_FONTS,  **state.settings.get('theme_fonts',  {})},
    )


def render(request: Request, name: str, **ctx):
    """Render a template, merging in the global context."""
    return templates.TemplateResponse(request, name, {**_globals(), **ctx})


def redirect(url: str, status_code: int = 303):
    """See-Other redirect (GET on the target), matching Flask's post-action nav."""
    return RedirectResponse(url, status_code=status_code)


def require_login(request: Request):
    """FastAPI dependency: allow the request only when a session user is set.

    Unauthenticated requests get a 302 to /login (browser navigations follow it;
    XHR endpoints are only ever hit from the already-authenticated settings page).
    """
    if not request.session.get('user'):
        raise HTTPException(status_code=302, detail='login required',
                            headers={'Location': '/login'})


def save_upload(upload, dest: str):
    """Persist a Starlette UploadFile to *dest* (replacement for Flask's file.save)."""
    upload.file.seek(0)
    with open(dest, 'wb') as f:
        shutil.copyfileobj(upload.file, f)
