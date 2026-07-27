import datetime
import io
import os
import re
import subprocess
import tarfile
import time
import tomllib

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

import bus
import state
from web import require_login

router = APIRouter(tags=['System'])


class TimeSet(BaseModel):
    # The pattern is advertised in the schema for /docs; enforcement is done in
    # the validator so a bad value yields the app's friendly single-line error
    # rather than Pydantic's regex-echoing default.
    date: str = Field(json_schema_extra={'pattern': r'^\d{4}-\d{2}-\d{2}$'})
    time: str = Field(json_schema_extra={'pattern': r'^\d{2}:\d{2}(:\d{2})?$'})

    @field_validator('date')
    @classmethod
    def _check_date(cls, v):
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', v):
            raise ValueError('Invalid date or time format')
        return v

    @field_validator('time')
    @classmethod
    def _check_time(cls, v):
        if not re.match(r'^\d{2}:\d{2}(:\d{2})?$', v):
            raise ValueError('Invalid date or time format')
        return v

_VERSION_RE = re.compile(r'^v\d{4}\.\d{2}\.\d+$')


def _update_config():
    """Load the update-dropdown settings from update_config.toml at the repo root.

    Read fresh on each call so edits take effect without restarting the server.
    Returns (extra_branches, max_versions); max_versions == 0 means no limit.
    """
    try:
        with open(os.path.join(state.app_dir, 'update_config.toml'), 'rb') as f:
            cfg = tomllib.load(f)
    except Exception:
        cfg = {}
    return (cfg.get('extra_branches') or [], int(cfg.get('max_versions') or 0))


def _find_uv():
    import shutil
    uv = shutil.which('uv')
    if uv:
        return uv
    for p in [os.path.expanduser('~/.local/bin/uv'),
              os.path.expanduser('~/.cargo/bin/uv'),
              '/usr/local/bin/uv']:
        if os.path.isfile(p):
            return p
    return 'uv'


_UV = _find_uv()


# ── Time ───────────────────────────────────────────────────────────────────────

@router.get('/time_status', dependencies=[Depends(require_login)])
def route_time_status():
    now          = datetime.datetime.now()
    ntp_active   = False
    synchronized = False
    timezone     = ''
    try:
        result = subprocess.run(['timedatectl'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            ll = line.lower()
            if 'ntp service' in ll:
                ntp_active = 'active' in ll
            if 'system clock synchronized' in ll:
                synchronized = 'yes' in ll
            if 'time zone' in ll:
                m = re.search(r'Time zone:\s+\S+\s+\((\w+)', line)
                if m:
                    timezone = m.group(1)
    except Exception:
        pass
    return {
        'date':         now.strftime('%Y-%m-%d'),
        'time':         now.strftime('%H:%M:%S'),
        'timezone':     timezone,
        'ntp_active':   ntp_active,
        'synchronized': synchronized,
    }


@router.post('/time_sync', dependencies=[Depends(require_login)])
def route_time_sync():
    try:
        subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'true'], timeout=5, check=True)
        subprocess.run(['sudo', 'systemctl', 'restart', 'systemd-timesyncd'], timeout=5)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.post('/time_set', dependencies=[Depends(require_login)])
async def route_time_set(body: TimeSet):
    return await run_in_threadpool(_time_set, body.date, body.time)


def _time_set(date_str, time_str):
    # date/time formats are already validated by the TimeSet model.
    if len(time_str) == 5:
        time_str += ':00'
    try:
        subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'false'], timeout=5, check=True)
        subprocess.run(['sudo', 'timedatectl', 'set-time', f'{date_str} {time_str}'],
                       timeout=5, check=True)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ── App / OS update ────────────────────────────────────────────────────────────

def _run_cmd_blocking(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True)
    return proc.stdout, proc.returncode


def _run_update(target=None):
    state._update_log_lines = []
    state._update_log_done  = None

    def emit(text, error=False):
        state._update_log_lines.append({'text': text, 'error': error})

    try:
        emit('$ git fetch --tags\n')
        out, rc = _run_cmd_blocking(['git', 'fetch', '--tags'], cwd=state.app_dir)
        if out:
            emit(out)
        if rc != 0:
            emit(f'\nCommand failed (exit code {rc})\n', error=True)
            state._update_log_done = False
            return

        # uv sync rewrites uv.lock locally; discard that drift so it
        # doesn't block the checkout/pull below.
        _run_cmd_blocking(['git', 'checkout', '--', 'uv.lock'], cwd=state.app_dir)

        extra_refs, _ = _update_config()
        if not target or target == 'master':
            cmds  = [['git', 'checkout', 'master'], ['git', 'pull'], [_UV, 'sync']]
            label = 'Development (master) installed'
        elif target in extra_refs:
            # Branch: force the local branch to match origin so repeated deploys
            # pick up new commits (a plain checkout of an existing branch would
            # stay on the stale local tip). origin/<branch> was refreshed by the
            # fetch above.
            cmds  = [['git', 'checkout', '-B', target, f'origin/{target}'], [_UV, 'sync']]
            label = f'Branch {target} installed'
        else:
            cmds  = [['git', 'checkout', target], [_UV, 'sync']]
            label = f'Version {target} installed'

        for cmd in cmds:
            emit('$ ' + ' '.join(cmd) + '\n')
            out, rc = _run_cmd_blocking(cmd, cwd=state.app_dir)
            if out:
                emit(out)
            if rc != 0:
                emit(f'\nCommand failed (exit code {rc})\n', error=True)
                state._update_log_done = False
                return

        emit(f'\n{label}. Restarting service…\n')
        state._update_log_done = True
        time.sleep(2)
        subprocess.run(['sudo', 'systemctl', 'restart', 'tremplin'])
    except Exception as e:
        emit(f'\nError: {e}\n', error=True)
        state._update_log_done = False
    finally:
        state._update_in_progress = False


def _run_os_update():
    state._os_update_log_lines = []
    state._os_update_log_done  = None

    def emit(text, error=False):
        state._os_update_log_lines.append({'text': text, 'error': error})

    try:
        for cmd in [['sudo', 'apt-get', 'update'],
                    ['sudo', 'apt-get', 'upgrade', '-y']]:
            emit('$ ' + ' '.join(cmd) + '\n')
            out, rc = _run_cmd_blocking(cmd)
            if out:
                emit(out)
            if rc != 0:
                emit(f'\nCommand failed (exit code {rc})\n', error=True)
                state._os_update_log_done = False
                return
        emit('\nOS update complete.\n')
        state._os_update_log_done = True
    except Exception as e:
        emit(f'\nError: {e}\n', error=True)
        state._os_update_log_done = False
    finally:
        state._os_update_in_progress = False


@router.get('/version_list', dependencies=[Depends(require_login)])
def route_version_list():
    try:
        r = subprocess.run(['git', 'describe', '--tags', '--exact-match', 'HEAD'],
                           capture_output=True, text=True, cwd=state.app_dir, timeout=8)
        current = r.stdout.strip() if r.returncode == 0 else ''
        subprocess.run(['git', 'fetch', '--tags'], capture_output=True,
                       cwd=state.app_dir, timeout=20)
        r = subprocess.run(['git', 'tag', '-l', '--sort=-version:refname'],
                           capture_output=True, text=True, cwd=state.app_dir, timeout=8)
        extra_refs, max_versions = _update_config()
        tags = [t.strip() for t in r.stdout.splitlines()
                if t.strip() and _VERSION_RE.match(t.strip())]
        if max_versions > 0:
            tags = tags[:max_versions]
        branches = []
        for ref in extra_refs:
            chk = subprocess.run(['git', 'rev-parse', '--verify', '--quiet',
                                  f'refs/remotes/origin/{ref}'],
                                 capture_output=True, cwd=state.app_dir, timeout=8)
            if chk.returncode == 0:
                branches.append(ref)
        return {'ok': True, 'current': current, 'versions': tags, 'branches': branches}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.post('/update_start', dependencies=[Depends(require_login)])
async def route_update_start(request: Request):
    if state._update_in_progress:
        return JSONResponse({'error': 'Update already in progress'}, status_code=409)
    state._update_in_progress = True
    try:
        data = await request.json()
    except Exception:
        data = {}
    target = (data or {}).get('target') or None
    bus.run_bg(_run_update, target)
    return {'ok': True}


@router.post('/os_update_start', dependencies=[Depends(require_login)])
def route_os_update_start():
    if state._os_update_in_progress:
        return JSONResponse({'error': 'OS update already in progress'}, status_code=409)
    state._os_update_in_progress = True
    bus.run_bg(_run_os_update)
    return {'ok': True}


@router.get('/update_log', dependencies=[Depends(require_login)])
def route_update_log():
    return {'lines': state._update_log_lines, 'done': state._update_log_done}


@router.get('/os_update_log', dependencies=[Depends(require_login)])
def route_os_update_log():
    return {'lines': state._os_update_log_lines, 'done': state._os_update_log_done}


# ── RTC (Adafruit PiRTC DS3231) ──────────────────────────────────────────────────

_RTC_SCRIPT = os.path.join(state.app_dir, 'scripts', 'rtc_setup.sh')


@router.get('/rtc_status', dependencies=[Depends(require_login)])
def route_rtc_status():
    configured = False
    active     = False

    for config_txt in ('/boot/firmware/config.txt', '/boot/config.txt'):
        try:
            with open(config_txt) as f:
                if any(line.strip() == 'dtoverlay=i2c-rtc,ds3231' for line in f):
                    configured = True
                    break
        except OSError:
            continue

    try:
        with open('/sys/class/rtc/rtc0/name') as f:
            name = f.read().lower()
        if 'ds3231' in name or 'rtc-ds1307' in name:
            active = True
    except OSError:
        pass

    return {'configured': configured, 'active': active}


def _run_rtc(action):
    state._rtc_log_lines = []
    state._rtc_log_done  = None

    def emit(text, error=False):
        state._rtc_log_lines.append({'text': text, 'error': error})

    try:
        emit(f'$ sudo bash scripts/rtc_setup.sh {action}\n')
        out, rc = _run_cmd_blocking(['sudo', 'bash', _RTC_SCRIPT, action])
        if out:
            emit(out)
        if rc != 0:
            emit(f'\nCommand failed (exit code {rc})\n', error=True)
            state._rtc_log_done = False
            return
        state._rtc_log_done = True
    except Exception as e:
        emit(f'\nError: {e}\n', error=True)
        state._rtc_log_done = False
    finally:
        state._rtc_in_progress = False


@router.post('/rtc_install_start', dependencies=[Depends(require_login)])
def route_rtc_install_start():
    if state._rtc_in_progress:
        return JSONResponse({'error': 'RTC setup already in progress'}, status_code=409)
    state._rtc_in_progress = True
    bus.run_bg(_run_rtc, 'enable')
    return {'ok': True}


@router.post('/rtc_remove_start', dependencies=[Depends(require_login)])
def route_rtc_remove_start():
    if state._rtc_in_progress:
        return JSONResponse({'error': 'RTC setup already in progress'}, status_code=409)
    state._rtc_in_progress = True
    bus.run_bg(_run_rtc, 'disable')
    return {'ok': True}


@router.get('/rtc_log', dependencies=[Depends(require_login)])
def route_rtc_log():
    return {'lines': state._rtc_log_lines, 'done': state._rtc_log_done}


@router.get('/logs_download', dependencies=[Depends(require_login)])
def route_logs_download():
    text = '\n'.join(state._log_ring) + '\n'
    ts   = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
    return Response(
        content=text, media_type='text/plain',
        headers={'Content-Disposition': f'attachment; filename="tremplin-log-{ts}.log"'})


@router.post('/logs_save', dependencies=[Depends(require_login)])
def route_logs_save():
    try:
        os.makedirs(state.LOGS_DIR, exist_ok=True)
        name = 'tremplin-log-' + datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S') + '.log'
        path = os.path.join(state.LOGS_DIR, name)
        with open(path, 'w') as f:
            f.write('\n'.join(state._log_ring) + '\n')
        return {'ok': True, 'path': path}
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


@router.post('/system_reboot', dependencies=[Depends(require_login)])
def route_system_reboot():
    def _reboot():
        time.sleep(1)
        subprocess.run(['sudo', 'reboot'])
    bus.run_bg(_reboot)
    return {'ok': True}


@router.post('/system_shutdown', dependencies=[Depends(require_login)])
def route_system_shutdown():
    def _shutdown():
        time.sleep(1)
        subprocess.run(['sudo', 'poweroff'])
    bus.run_bg(_shutdown)
    return {'ok': True}


@router.get('/backup_download', dependencies=[Depends(require_login)])
def route_backup_download():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        tar.add(state.SCOREBOARD_DIR, arcname='Tremplin')
    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    return Response(
        content=buf.getvalue(), media_type='application/gzip',
        headers={'Content-Disposition':
                 f'attachment; filename="tremplin_backup_{date_str}.tar.gz"'})


@router.post('/backup_restore', dependencies=[Depends(require_login)])
async def route_backup_restore(request: Request):
    form = await request.form()
    f = form.get('backup_file')
    if not f or not getattr(f, 'filename', '').endswith('.tar.gz'):
        return JSONResponse({'ok': False, 'error': 'Please upload a .tar.gz backup file'},
                            status_code=400)
    data = await f.read()
    # Extracting the tarball is blocking; run it off the event loop.
    return await run_in_threadpool(_restore_backup, data)


def _restore_backup(data):
    try:
        buf = io.BytesIO(data)
        with tarfile.open(fileobj=buf, mode='r:gz') as tar:
            members = tar.getmembers()
            # Validate all paths stay within home dir (no path traversal)
            home = os.path.expanduser('~')
            for m in members:
                dest = os.path.normpath(os.path.join(home, m.name))
                if not dest.startswith(home):
                    return JSONResponse({'ok': False, 'error': 'Invalid archive path'},
                                        status_code=400)
            tar.extractall(path=home)
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)
    # Restart after a short delay so the response can be sent first
    def _restart():
        time.sleep(1)
        subprocess.run(['sudo', 'systemctl', 'restart', 'tremplin'])
    bus.run_bg(_restart)
    return {'ok': True}
