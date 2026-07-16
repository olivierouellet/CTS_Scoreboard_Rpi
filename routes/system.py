import datetime
import io
import os
import re
import subprocess
import tarfile
import tomllib

import flask
import flask_login
from flask import Blueprint

import state
from extensions import socketio

bp = Blueprint('system', __name__)

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

@bp.route('/time_status')
@flask_login.login_required
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
    return flask.jsonify({
        'date':         now.strftime('%Y-%m-%d'),
        'time':         now.strftime('%H:%M:%S'),
        'timezone':     timezone,
        'ntp_active':   ntp_active,
        'synchronized': synchronized,
    })


@bp.route('/time_sync', methods=['POST'])
@flask_login.login_required
def route_time_sync():
    try:
        subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'true'], timeout=5, check=True)
        subprocess.run(['sudo', 'systemctl', 'restart', 'systemd-timesyncd'], timeout=5)
        return flask.jsonify({'ok': True})
    except Exception as e:
        return flask.jsonify({'ok': False, 'error': str(e)})


@bp.route('/time_set', methods=['POST'])
@flask_login.login_required
def route_time_set():
    data     = flask.request.get_json()
    date_str = data.get('date', '')
    time_str = data.get('time', '')
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str) or \
       not re.match(r'^\d{2}:\d{2}(:\d{2})?$', time_str):
        return flask.jsonify({'ok': False, 'error': 'Invalid date or time format'})
    if len(time_str) == 5:
        time_str += ':00'
    try:
        subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'false'], timeout=5, check=True)
        subprocess.run(['sudo', 'timedatectl', 'set-time', f'{date_str} {time_str}'],
                       timeout=5, check=True)
        return flask.jsonify({'ok': True})
    except Exception as e:
        return flask.jsonify({'ok': False, 'error': str(e)})


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
        socketio.sleep(2)
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


@bp.route('/version_list')
@flask_login.login_required
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
        return flask.jsonify({'ok': True, 'current': current,
                              'versions': tags, 'branches': branches})
    except Exception as e:
        return flask.jsonify({'ok': False, 'error': str(e)})


@bp.route('/update_start', methods=['POST'])
@flask_login.login_required
def route_update_start():
    if state._update_in_progress:
        return flask.jsonify({'error': 'Update already in progress'}), 409
    state._update_in_progress = True
    data   = flask.request.get_json(force=True, silent=True) or {}
    target = data.get('target') or None
    socketio.start_background_task(_run_update, target)
    return flask.jsonify({'ok': True})


@bp.route('/os_update_start', methods=['POST'])
@flask_login.login_required
def route_os_update_start():
    if state._os_update_in_progress:
        return flask.jsonify({'error': 'OS update already in progress'}), 409
    state._os_update_in_progress = True
    socketio.start_background_task(_run_os_update)
    return flask.jsonify({'ok': True})


@bp.route('/update_log')
@flask_login.login_required
def route_update_log():
    return flask.jsonify({'lines': state._update_log_lines, 'done': state._update_log_done})


@bp.route('/os_update_log')
@flask_login.login_required
def route_os_update_log():
    return flask.jsonify({'lines': state._os_update_log_lines, 'done': state._os_update_log_done})


# ── RTC (Adafruit PiRTC DS3231) ──────────────────────────────────────────────────

_RTC_SCRIPT = os.path.join(state.app_dir, 'scripts', 'rtc_setup.sh')


@bp.route('/rtc_status')
@flask_login.login_required
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

    return flask.jsonify({'configured': configured, 'active': active})


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


@bp.route('/rtc_install_start', methods=['POST'])
@flask_login.login_required
def route_rtc_install_start():
    if state._rtc_in_progress:
        return flask.jsonify({'error': 'RTC setup already in progress'}), 409
    state._rtc_in_progress = True
    socketio.start_background_task(_run_rtc, 'enable')
    return flask.jsonify({'ok': True})


@bp.route('/rtc_remove_start', methods=['POST'])
@flask_login.login_required
def route_rtc_remove_start():
    if state._rtc_in_progress:
        return flask.jsonify({'error': 'RTC setup already in progress'}), 409
    state._rtc_in_progress = True
    socketio.start_background_task(_run_rtc, 'disable')
    return flask.jsonify({'ok': True})


@bp.route('/rtc_log')
@flask_login.login_required
def route_rtc_log():
    return flask.jsonify({'lines': state._rtc_log_lines, 'done': state._rtc_log_done})


@bp.route('/logs_download')
@flask_login.login_required
def route_logs_download():
    text = '\n'.join(state._log_ring) + '\n'
    ts   = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
    return flask.Response(
        text, mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="tremplin-log-{ts}.log"'})


@bp.route('/logs_save', methods=['POST'])
@flask_login.login_required
def route_logs_save():
    try:
        os.makedirs(state.LOGS_DIR, exist_ok=True)
        name = 'tremplin-log-' + datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S') + '.log'
        path = os.path.join(state.LOGS_DIR, name)
        with open(path, 'w') as f:
            f.write('\n'.join(state._log_ring) + '\n')
        return flask.jsonify({'ok': True, 'path': path})
    except Exception as e:
        return flask.jsonify({'ok': False, 'error': str(e)}), 500


@bp.route('/system_reboot', methods=['POST'])
@flask_login.login_required
def route_system_reboot():
    def _reboot():
        socketio.sleep(1)
        subprocess.run(['sudo', 'reboot'])
    socketio.start_background_task(_reboot)
    return flask.jsonify({'ok': True})


@bp.route('/system_shutdown', methods=['POST'])
@flask_login.login_required
def route_system_shutdown():
    def _shutdown():
        socketio.sleep(1)
        subprocess.run(['sudo', 'poweroff'])
    socketio.start_background_task(_shutdown)
    return flask.jsonify({'ok': True})


@bp.route('/backup_download')
@flask_login.login_required
def route_backup_download():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        tar.add(state.SCOREBOARD_DIR, arcname='Tremplin')
    buf.seek(0)
    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    return flask.send_file(buf, as_attachment=True,
                           download_name=f'tremplin_backup_{date_str}.tar.gz',
                           mimetype='application/gzip')


@bp.route('/backup_restore', methods=['POST'])
@flask_login.login_required
def route_backup_restore():
    f = flask.request.files.get('backup_file')
    if not f or not f.filename.endswith('.tar.gz'):
        return flask.jsonify({'ok': False, 'error': 'Please upload a .tar.gz backup file'}), 400
    try:
        buf = io.BytesIO(f.read())
        with tarfile.open(fileobj=buf, mode='r:gz') as tar:
            members = tar.getmembers()
            # Validate all paths stay within home dir (no path traversal)
            home = os.path.expanduser('~')
            for m in members:
                dest = os.path.normpath(os.path.join(home, m.name))
                if not dest.startswith(home):
                    return flask.jsonify({'ok': False, 'error': 'Invalid archive path'}), 400
            tar.extractall(path=home)
    except Exception as e:
        return flask.jsonify({'ok': False, 'error': str(e)}), 500
    # Restart after a short delay so the response can be sent first
    def _restart():
        socketio.sleep(1)
        subprocess.run(['sudo', 'systemctl', 'restart', 'tremplin'])
    socketio.start_background_task(_restart)
    return flask.jsonify({'ok': True})
