#! /usr/bin/python3
import asyncio
import datetime
import glob
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import bus
import state
from meet_data import _get_next_heats, send_event_info
from web import NotAuthenticated, render, templates
from worker import main_thread_worker

from routes.scoreboard import router as scoreboard_router
from routes.meet       import router as meet_router
from routes.settings   import router as settings_router
from routes.debug      import router as debug_router
from routes.system     import router as system_router
from routes.network    import router as network_router
from routes.appearance import router as appearance_router

SECRET_KEY = 'rimnqiuqnewiornhf7nfwenjmqvliwynhtmlfnlsklrmqwe'


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Capture the event loop so the serial worker thread can broadcast onto it.
    bus.set_loop(asyncio.get_running_loop())
    state.install_log_capture()
    import relay
    from console_decoders import load_custom_decoders
    from routes.settings import _load_meet_file
    state.load_settings()
    load_custom_decoders(state.CUSTOM_DECODERS_FOLDER)
    relay.start()
    _register_locale_aliases()
    _last = state.settings.get('last_meet_file', '')
    if _last:
        _path = os.path.join(state.MEET_FOLDER, _last)
        if os.path.isfile(_path):
            _load_meet_file(_path)
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.mount('/static', StaticFiles(directory=os.path.join(state.app_dir, 'static')), name='static')

app.include_router(scoreboard_router)
app.include_router(meet_router)
app.include_router(settings_router)
app.include_router(debug_router)
app.include_router(system_router)
app.include_router(network_router)
app.include_router(appearance_router)


@app.exception_handler(NotAuthenticated)
async def _redirect_to_login(request: Request, exc: NotAuthenticated):
    return RedirectResponse('/login', status_code=303)


# ── Auth ───────────────────────────────────────────────────────────────────────

@app.get('/login')
async def route_login_form(request: Request):
    return templates.TemplateResponse(request, 'login.html', {})


@app.post('/login')
async def route_login(request: Request,
                      username: str = Form(''), password: str = Form('')):
    if (username == state.settings['username'] and
            password == state.settings['password']):
        request.session['user'] = username
        return RedirectResponse(request.query_params.get('next') or '/', status_code=303)
    return templates.TemplateResponse(request, 'login.html', {'login_failed': True},
                                      status_code=401)


@app.get('/logout')
async def route_logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse('/', status_code=303)


# ── WebSocket endpoints ─────────────────────────────────────────────────────────

@app.websocket('/ws/scoreboard')
async def ws_scoreboard(ws: WebSocket):
    await bus.manager.connect(ws, '/scoreboard')
    state._scoreboard_clients[id(ws)] = {
        'ip': ws.client.host if ws.client else '',
        'at': datetime.datetime.now().strftime('%H:%M:%S'),
    }
    if state.main_thread is None:
        state.main_thread = bus.run_bg(main_thread_worker)
    await bus.manager.send(ws, 'test_mode',       {'active': state._test_session is not None})
    await bus.manager.send(ws, 'display_overlay', {'active': state._overlay_active})
    await bus.manager.send(ws, 'columns_state',   {'hidden': state._cols_hidden})
    send_event_info()
    try:
        while True:
            msg = await ws.receive_json()
            ev, d = msg.get('event'), msg.get('data') or {}
            if ev == 'set_overlay':
                state._overlay_active = bool(d.get('active', False))
                bus.emit('/scoreboard', 'display_overlay', {'active': state._overlay_active})
            elif ev == 'set_columns':
                state._cols_hidden = bool(d.get('hidden', False))
                bus.emit('/scoreboard', 'columns_state', {'hidden': state._cols_hidden})
            elif ev == 'adjust_splits':
                lane  = int(d.get('lane', 0))
                delta = int(d.get('delta', 0))
                if 1 <= lane <= 12 and delta != 0:
                    new_val = state._decoder.adjust_splits(lane, delta)
                    bus.emit('/scoreboard', 'update_scoreboard', {f'lane_splits{lane}': new_val})
            elif ev == 'next_heat':
                event_list = sorted(state.event_info.events.keys())
                try:
                    event_tuple = event_list[event_list.index(state._decoder.last_event_sent) + 1]
                except Exception:
                    event_tuple = event_list[0] if event_list else (0, 0)
                state._decoder.last_event_sent = event_tuple
                send_event_info()
            elif ev == 'ping':
                await bus.manager.send(ws, 'pong')
    except WebSocketDisconnect:
        pass
    finally:
        bus.manager.disconnect(ws, '/scoreboard')
        state._scoreboard_clients.pop(id(ws), None)


@app.websocket('/ws/results')
async def ws_results(ws: WebSocket):
    await bus.manager.connect(ws, '/results')
    if state._last_results_snapshot:
        await bus.manager.send(ws, 'results_snapshot', state._last_results_snapshot)
    ev, ht = state._decoder.last_event_sent if state._decoder.last_event_sent != (0, 0) else (0, 0)
    await bus.manager.send(ws, 'next_heats',
                           {'heats': _get_next_heats(ev, ht,
                                                     num_lanes=int(state.settings.get('num_lanes', 6)))})
    try:
        while True:
            msg = await ws.receive_json()   # results is receive-only apart from heartbeat
            if msg.get('event') == 'ping':
                await bus.manager.send(ws, 'pong')
    except WebSocketDisconnect:
        pass
    finally:
        bus.manager.disconnect(ws, '/results')


@app.websocket('/ws/settings')
async def ws_settings(ws: WebSocket):
    await bus.manager.connect(ws, '/settings')
    if state.main_thread is None and state._test_session is None:
        state.main_thread = bus.run_bg(main_thread_worker)
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get('event') == 'ping':
                await bus.manager.send(ws, 'pong')
    except WebSocketDisconnect:
        pass
    finally:
        bus.manager.disconnect(ws, '/settings')


# ── Locale URL aliases ─────────────────────────────────────────────────────────

def _register_locale_aliases():
    import tomllib
    seen = set()
    for path in glob.glob(os.path.join('locales', '*.toml')) + \
                glob.glob(os.path.join(state.CUSTOM_LOCALE_FOLDER, '*.toml')):
        try:
            with open(path, 'rb') as f:
                aliases = tomllib.load(f).get('aliases', {})
            for alias, target in aliases.items():
                if alias in seen:
                    continue
                seen.add(alias)
                def make_redirect(t):
                    async def view():
                        return RedirectResponse(t, status_code=303)
                    return view
                app.add_api_route('/' + alias, make_redirect(target), methods=['GET'])
        except Exception:
            pass


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    try:
        uvicorn.run(app, host='0.0.0.0', port=5000)
    except Exception:
        traceback.print_exc()
