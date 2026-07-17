import glob
import os
import re
import select
import shutil
import signal
import struct
import subprocess

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

import bus
import state
from meet_data import send_event_info
from parsers.lenex_parser import load_lenex
from web import redirect, require_login, save_upload
from worker import _cleanup_test_meet, _list_sessions, _restart_worker

router = APIRouter()

_TERMINAL_ALLOWED_CMDS = {
    'bash':         ['bash'],
    'raspi-config': ['sudo', 'raspi-config'],
    'logs':         ['journalctl', '-u', 'tremplin', '-f'],
    'dmesg-tty':    ['bash', '-c', 'dmesg | grep -i tty'],
    'serial-ports': ['python3', '-m', 'serial.tools.list_ports', '-v'],
}


@router.get('/test_status', dependencies=[Depends(require_login)])
async def route_test_status():
    return {
        'playing':        state._test_session is not None,
        'session':        os.path.basename(state._test_session) if state._test_session else '',
        'recording':      state._record_handle is not None,
        'sessions':       _list_sessions(),
        'speed':          state.in_speed,
        'has_meet':       bool(state._active_meet_file) and not state._test_meet_active,
        'test_meet':      state._test_meet_active,
        'test_meet_name': state._active_meet_file if state._test_meet_active else '',
    }


@router.post('/test_play', dependencies=[Depends(require_login)])
async def route_test_play(request: Request):
    name = (await request.json()).get('name', '')
    for s in _list_sessions():
        if s['name'] == name:
            bus.emit('/scoreboard', 'test_mode', {'active': True})
            bus.run_bg(_restart_worker, s['path'])
            companion = os.path.splitext(s['path'])[0] + '.lxf'
            if os.path.exists(companion):
                all_companions = {
                    os.path.basename(os.path.splitext(sess['path'])[0] + '.lxf')
                    for sess in _list_sessions()
                }
                for f in glob.glob(os.path.join(state.MEET_FOLDER, '*.lxf')):
                    if os.path.basename(f) in all_companions:
                        try:
                            os.remove(f)
                        except Exception:
                            pass
                if state._test_meet_active:
                    state.lenex_event_names.clear()
                    state.lenex_start_list.clear()
                    state.lenex_heat_times.clear()
                    state.lenex_meet_info.clear()
                    state.lenex_event_distances.clear()
                    state._test_meet_active = False
                if not state._active_meet_file:
                    try:
                        dest = os.path.join(state.MEET_FOLDER, os.path.basename(companion))
                        shutil.copy2(companion, dest)
                        data = load_lenex(dest)
                        state.lenex_event_names.update(data.event_names)
                        state.lenex_start_list.update(data.start_list)
                        state.lenex_heat_times.update(data.heat_times)
                        state.lenex_meet_info.update(data.meet_info)
                        state.lenex_event_distances.update(data.event_distances)
                        send_event_info()
                        state._test_meet_active = True
                    except Exception as e:
                        print(f'[test] Failed to load companion LXF: {e}')
            return {'ok': True}
    return JSONResponse({'error': 'Session not found'}, status_code=404)


@router.post('/test_stop', dependencies=[Depends(require_login)])
async def route_test_stop():
    _cleanup_test_meet()
    bus.emit('/scoreboard', 'test_mode', {'active': False})
    bus.run_bg(_restart_worker, None)
    return {'ok': True}


@router.post('/test_meet_upload', dependencies=[Depends(require_login)])
async def route_test_meet_upload(request: Request):
    if state._test_session is None:
        return {'ok': False, 'error': 'No test session is running'}
    if state._test_meet_active:
        return {'ok': False, 'error': 'Test meet already loaded'}
    meet_files = glob.glob(os.path.join(state.MEET_FOLDER, '*.lxf')) + \
                 glob.glob(os.path.join(state.MEET_FOLDER, '*.csv'))
    if meet_files:
        return {'ok': False, 'error': 'A real meet file is already loaded'}
    file = (await request.form()).get('meet_file')
    if not file or not file.filename:
        return {'ok': False, 'error': 'No file provided'}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.csv', '.lxf'):
        return {'ok': False, 'error': 'File must be .lxf or .csv'}
    dest = os.path.join(state.MEET_FOLDER, os.path.basename(file.filename))
    save_upload(file, dest)
    try:
        if ext == '.csv':
            state.event_info.load(dest)
        else:
            data = load_lenex(dest)
            state.lenex_event_names.update(data.event_names)
            state.lenex_start_list.update(data.start_list)
            state.lenex_heat_times.update(data.heat_times)
            state.lenex_meet_info.update(data.meet_info)
            state.lenex_event_distances.update(data.event_distances)
        send_event_info()
        state._test_meet_active = True
        return {'ok': True, 'name': os.path.basename(file.filename)}
    except Exception as e:
        try:
            os.remove(dest)
        except Exception:
            pass
        return {'ok': False, 'error': str(e)}


@router.post('/test_set_speed', dependencies=[Depends(require_login)])
async def route_test_set_speed(request: Request):
    try:
        state.in_speed = float((await request.json()).get('speed', 1.0))
        state.in_speed = max(0.1, min(state.in_speed, 100.0))
    except (TypeError, ValueError):
        pass
    return {'speed': state.in_speed}


@router.post('/test_record_start', dependencies=[Depends(require_login)])
async def route_test_record_start(request: Request):
    if state._record_handle:
        state._record_handle.close()
    name = (await request.json()).get('name', 'recording').strip()
    code = re.sub(r'[^a-z0-9_-]', '_', name.lower()) or 'recording'
    path = os.path.join(state.CUSTOM_SESSIONS_FOLDER, code + '.cts')
    state._record_handle = open(path, 'wt')
    return {'ok': True, 'file': code + '.cts'}


@router.post('/test_record_stop', dependencies=[Depends(require_login)])
async def route_test_record_stop():
    if state._record_handle:
        state._record_handle.close()
        state._record_handle = None
    return {'ok': True}


@router.post('/test_session_delete', dependencies=[Depends(require_login)])
async def route_test_session_delete(request: Request):
    name = (await request.json()).get('name', '')
    path = os.path.join(state.CUSTOM_SESSIONS_FOLDER, name)
    if os.path.isfile(path) and (path.endswith('.cts') or
                                  path.endswith('.raw') or
                                  path.endswith('.cap')):
        if state._test_session == path:
            bus.run_bg(_restart_worker, None)
        os.remove(path)
    return redirect('/settings')


@router.post('/test_session_upload', dependencies=[Depends(require_login)])
async def route_test_session_upload(request: Request):
    file = (await request.form()).get('session_file')
    if file and (file.filename.endswith('.cts') or
                 file.filename.endswith('.raw') or
                 file.filename.endswith('.cap')):
        save_upload(file, os.path.join(state.CUSTOM_SESSIONS_FOLDER,
                                       os.path.basename(file.filename)))
    return redirect('/settings')


@router.get('/serial_status', dependencies=[Depends(require_login)])
async def route_serial_status():
    return state._serial_status


@router.get('/debug_status', dependencies=[Depends(require_login)])
async def route_debug_status():
    return {'enabled': state._debug_serial}


@router.post('/debug_toggle', dependencies=[Depends(require_login)])
async def route_debug_toggle():
    state._debug_serial = not state._debug_serial
    return {'enabled': state._debug_serial}


@router.get('/debug/seed_times')
async def route_debug_seed_times():
    return {
        'lane_seed_times': state._decoder.lane_seed_times,
        'last_event_sent': state._decoder.last_event_sent,
        'lenex_loaded':    bool(state.lenex_start_list),
    }


# ── Terminal (PTY) ─────────────────────────────────────────────────────────────

def _pty_reader():
    while state._pty_fd is not None:
        try:
            r, _, _ = select.select([state._pty_fd], [], [], 0.05)
            if r:
                data = os.read(state._pty_fd, 4096)
                if data:
                    bus.emit('/terminal', 'output', data.decode('utf-8', errors='replace'))
                else:
                    break
        except OSError:
            break
        except Exception:
            break
    state._pty_fd = state._pty_pid = None
    bus.emit('/terminal', 'exit', {})


@router.post('/terminal_start', dependencies=[Depends(require_login)])
async def route_terminal_start(request: Request):
    if not state._PTY_AVAILABLE:
        return {'ok': False, 'error': 'PTY not available on this platform'}
    if state._pty_fd is not None:
        return {'ok': True}
    try:
        import fcntl
        import pty
        import termios
        data    = await request.json()
        cmd_key = (data or {}).get('cmd', 'bash')
        cmd     = _TERMINAL_ALLOWED_CMDS.get(cmd_key)
        if cmd is None:
            return {'ok': False, 'error': f'Unknown command: {cmd_key}'}
        master_fd, slave_fd = pty.openpty()
        winsize = struct.pack('HHHH', 24, 80, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
        TIOCSCTTY = getattr(termios, 'TIOCSCTTY', 0x540E)

        def _preexec():
            os.setsid()
            fcntl.ioctl(0, TIOCSCTTY, 0)

        env  = {**os.environ, 'TERM': 'xterm-256color'}
        proc = subprocess.Popen(
            cmd,
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            close_fds=True, preexec_fn=_preexec, env=env
        )
        os.close(slave_fd)
        state._pty_fd  = master_fd
        state._pty_pid = proc.pid
        bus.run_bg(_pty_reader)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.post('/terminal_stop', dependencies=[Depends(require_login)])
async def route_terminal_stop():
    if state._pty_pid:
        try:
            os.kill(state._pty_pid, signal.SIGTERM)
        except Exception:
            pass
    if state._pty_fd:
        try:
            os.close(state._pty_fd)
        except Exception:
            pass
    state._pty_fd = state._pty_pid = None
    return {'ok': True}


def _terminal_input(data):
    if state._pty_fd is not None:
        try:
            os.write(state._pty_fd, data.encode('utf-8'))
        except OSError:
            pass


def _terminal_resize(data):
    if state._pty_fd is not None:
        try:
            import fcntl
            import termios
            winsize = struct.pack('HHHH', data['rows'], data['cols'], 0, 0)
            fcntl.ioctl(state._pty_fd, termios.TIOCSWINSZ, winsize)
        except Exception:
            pass


@router.websocket('/ws/terminal')
async def ws_terminal(ws: WebSocket):
    await bus.manager.connect(ws, '/terminal')
    try:
        while True:
            msg = await ws.receive_json()
            ev, d = msg.get('event'), msg.get('data')
            if ev == 'input':
                _terminal_input(d)
            elif ev == 'resize':
                _terminal_resize(d)
    except WebSocketDisconnect:
        pass
    finally:
        bus.manager.disconnect(ws, '/terminal')
