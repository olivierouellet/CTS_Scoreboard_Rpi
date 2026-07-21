import ipaddress
import subprocess

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import state
from web import require_login

router = APIRouter()


def _nmcli(*args, timeout=8):
    return subprocess.run(['nmcli'] + list(args),
                          capture_output=True, text=True, timeout=timeout)


@router.get('/wifi_status', dependencies=[Depends(require_login)])
def route_wifi_status():
    try:
        r       = _nmcli('radio', 'wifi')
        enabled = r.returncode == 0 and 'enabled' in r.stdout.lower()

        r2       = _nmcli('-t', '-f', 'DEVICE,TYPE', '--escape', 'no', 'device')
        wifi_dev = eth_dev = ''
        for line in r2.stdout.splitlines():
            parts = line.split(':')
            if len(parts) < 2:
                continue
            dev, typ = parts[0], parts[1]
            if typ == 'wifi' and not wifi_dev:
                wifi_dev = dev
            elif typ == 'ethernet' and not eth_dev:
                eth_dev = dev

        def get_ip(device):
            if not device:
                return ''
            r = _nmcli('-t', '-f', 'IP4.ADDRESS', '--escape', 'no', 'dev', 'show', device)
            for line in r.stdout.splitlines():
                if line.startswith('IP4.ADDRESS'):
                    return line.split(':')[-1].split('/')[0]
            return ''

        # IN-USE is the correct field for dev wifi (not ACTIVE); active AP is marked with '*'
        r3   = _nmcli('-t', '-f', 'IN-USE,SSID', '--escape', 'no', 'dev', 'wifi')
        ssid = ''
        for line in r3.stdout.splitlines():
            if line.startswith('*:'):
                ssid = line.split(':', 1)[1]
                break

        return {
            'enabled': enabled,
            'ssid':    ssid,
            'wifi_ip': get_ip(wifi_dev) if enabled else '',
            'eth_ip':  get_ip(eth_dev),
        }
    except FileNotFoundError:
        return JSONResponse({'error': 'nmcli not found'}, status_code=503)
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


@router.get('/wifi_scan', dependencies=[Depends(require_login)])
def route_wifi_scan():
    try:
        r     = _nmcli('--color', 'no', '-f', 'ACTIVE,SSID,SIGNAL,SECURITY',
                       'dev', 'wifi', 'list', timeout=20)
        lines = r.stdout.splitlines()
        if len(lines) < 2:
            return {'networks': []}
        hdr = lines[0]
        col = {name: hdr.index(name) for name in ('ACTIVE', 'SSID', 'SIGNAL', 'SECURITY')}
        networks, seen = [], set()
        for line in lines[1:]:
            if len(line) <= col['SECURITY']:
                continue
            ssid     = line[col['SSID']   : col['SIGNAL']  ].strip()
            signal   = line[col['SIGNAL'] : col['SECURITY']].strip()
            security = line[col['SECURITY']:               ].strip()
            active   = line[col['ACTIVE'] : col['SSID']   ].strip()
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            networks.append({
                'ssid':     ssid,
                'signal':   int(signal) if signal.isdigit() else 0,
                'security': '' if security in ('--', '') else security,
                'active':   '*' in active,
            })
        networks.sort(key=lambda n: n['signal'], reverse=True)
        return {'networks': networks}
    except FileNotFoundError:
        return JSONResponse({'error': 'nmcli not found'}, status_code=503)
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


@router.post('/wifi_toggle', dependencies=[Depends(require_login)])
def route_wifi_toggle():
    try:
        r            = _nmcli('radio', 'wifi')
        currently_on = 'enabled' in r.stdout.lower()
        st           = 'off' if currently_on else 'on'
        subprocess.run(['sudo', 'nmcli', 'radio', 'wifi', st],
                       capture_output=True, timeout=8)
        return {'enabled': not currently_on}
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


@router.get('/cloud_status', dependencies=[Depends(require_login)])
def route_cloud_status():
    import relay
    return relay.status()


@router.post('/cloud_toggle', dependencies=[Depends(require_login)])
def route_cloud_toggle():
    import relay
    if relay.status()['running']:
        relay.stop()
    else:
        relay.start()
    return relay.status()


@router.post('/wifi_connect', dependencies=[Depends(require_login)])
async def route_wifi_connect(request: Request):
    data = await request.json()
    # nmcli connect can take up to 30 s — run it off the event loop so live
    # scoreboard broadcasts keep flowing while it works.
    return await run_in_threadpool(_wifi_connect, data.get('ssid', ''), data.get('password', ''))


def _wifi_connect(ssid, password):
    if not ssid:
        return JSONResponse({'error': 'No SSID provided'}, status_code=400)
    try:
        # Remove any stale connection profile for this SSID first. nmcli
        # otherwise reuses an existing profile (e.g. from a previous attempt
        # on an open network) that lacks 802-11-wireless-security.key-mgmt,
        # which then fails validation once a password is supplied.
        subprocess.run(['sudo', 'nmcli', 'connection', 'delete', ssid],
                       capture_output=True, timeout=8)

        cmd = ['dev', 'wifi', 'connect', ssid]
        if password:
            cmd += ['password', password]
        r = _nmcli(*cmd, timeout=30)
        if r.returncode == 0:
            return {'ok': True}
        return JSONResponse({'error': (r.stderr or r.stdout).strip()}, status_code=400)
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


@router.post('/eth_dhcp_set', dependencies=[Depends(require_login)])
def route_eth_dhcp_set():
    try:
        r = subprocess.run(
            ['sudo', 'nmcli', 'con', 'mod', 'tremplin-eth',
             'ipv4.method', 'auto', 'ipv4.addresses', '', 'ipv4.gateway', ''],
            capture_output=True, text=True, timeout=8)
        if r.returncode != 0:
            return {'ok': False, 'error': r.stderr.strip() or 'nmcli error'}
        subprocess.run(['sudo', 'nmcli', 'con', 'up', 'tremplin-eth'],
                       capture_output=True, timeout=8)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.post('/eth_ip_set', dependencies=[Depends(require_login)])
async def route_eth_ip_set(request: Request):
    data = await request.json()
    return await run_in_threadpool(_eth_ip_set, data.get('ip', '').strip(),
                                    data.get('prefix', '24').strip())


def _eth_ip_set(ip_str, prefix_str):
    try:
        ipaddress.IPv4Address(ip_str)
        prefix = int(prefix_str)
        if not (1 <= prefix <= 32):
            raise ValueError
    except Exception:
        return {'ok': False, 'error': 'Invalid IP address or prefix length'}
    cidr = f'{ip_str}/{prefix}'
    try:
        r = subprocess.run(
            ['sudo', 'nmcli', 'con', 'mod', 'tremplin-eth', 'ipv4.addresses', cidr],
            capture_output=True, text=True, timeout=8)
        if r.returncode != 0:
            return {'ok': False, 'error': r.stderr.strip() or 'nmcli error'}
        subprocess.run(['sudo', 'nmcli', 'con', 'up', 'tremplin-eth'],
                       capture_output=True, timeout=8)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@router.get('/clients', dependencies=[Depends(require_login)])
async def route_clients():
    # Browser tabs connected to the scoreboard WebSocket, shown in the Network tab.
    # async so it runs on the event loop — the same context that mutates
    # _scoreboard_clients (the WS connect/disconnect handlers) — so this snapshot
    # can't be preempted mid-iteration by a connect/disconnect.
    return {'clients': list(state._scoreboard_clients.values())}
