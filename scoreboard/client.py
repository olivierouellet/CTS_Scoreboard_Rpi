"""Server link — config fetch plus the ``/ws/scoreboard`` receive loop.

Mirrors the reconnect idiom in ``server/relay.py``: the sync ``websocket-client``
library in a daemon thread, a ``recv()`` timeout that doubles as the heartbeat
cadence, and a staleness window that forces a reconnect when the link goes
silently half-open (which is what a pool-deck switch reboot looks like from here).

The thread never touches Qt widgets. It emits :class:`ServerLink` signals, which
Qt queues onto the GUI thread — the only safe way to cross that boundary.
"""
import json
import threading
import time
import urllib.request

from PyQt5.QtCore import QObject, pyqtSignal

# recv() timeout: how often we heartbeat an otherwise idle link.
_PING_EVERY = 20
# No inbound traffic (pong included) for this long => treat the link as dead.
_STALE = 50
# Delay between reconnect attempts. The kiosk usually boots before the server, so
# this loop is the normal startup path, not just an error path.
_RETRY_EVERY = 3


def _ws_url(base: str) -> str:
    """Turn ``http://splouch.local`` into ``ws://splouch.local/ws/scoreboard``."""
    base = base.strip().rstrip('/')
    if base.startswith('https://'):
        base = 'wss://' + base[len('https://'):]
    elif base.startswith('http://'):
        base = 'ws://' + base[len('http://'):]
    elif not base.startswith(('ws://', 'wss://')):
        base = 'ws://' + base
    return base + '/ws/scoreboard'


def fetch_config(base: str, timeout: float = 10.0) -> dict:
    """GET /config — display config for native clients (docs/api.md §6).

    Raises on failure; the caller decides whether to retry or fall back to
    defaults, because a first-boot failure and a mid-meet failure want different
    handling.
    """
    base = base.strip().rstrip('/')
    with urllib.request.urlopen(base + '/config', timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


class ServerLink(QObject):
    """Owns the WebSocket thread and re-publishes frames as Qt signals.

    ``frame`` carries every server event verbatim (``event``, ``data``) so the
    board can grow new handlers without touching this class. ``connected`` drives
    the "waiting for server" overlay.
    """

    frame     = pyqtSignal(str, object)
    connected = pyqtSignal(bool)

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self._base   = base_url
        self._stop   = threading.Event()
        self._thread = None
        self._ws     = None
        self._lock   = threading.Lock()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def send(self, event: str, data=None):
        """Fire-and-forget a client→server event (``set_overlay``, ``next_heat``…).

        Safe to call from the GUI thread: a dead link is dropped silently rather
        than blocking the UI, and the receive loop will reconnect on its own.
        """
        with self._lock:
            ws = self._ws
        if ws is None:
            return
        try:
            ws.send(json.dumps({'event': event, 'data': data or {}}))
        except Exception:
            pass

    # ── Background thread ──────────────────────────────────────────────────────

    def _run(self):
        from websocket import WebSocketTimeoutException, create_connection

        url = _ws_url(self._base)
        while not self._stop.is_set():
            ws = None
            try:
                ws = create_connection(url, timeout=15)
                ws.settimeout(_PING_EVERY)       # recv() unblocks so we can heartbeat
                ws.enable_multithreading = True  # send() is called from the GUI thread
                with self._lock:
                    self._ws = ws
                self.connected.emit(True)
                print(f'[scoreboard] connected to {url}', flush=True)

                last_rx = time.time()
                while not self._stop.is_set():
                    try:
                        raw = ws.recv()
                    except WebSocketTimeoutException:
                        if time.time() - last_rx > _STALE:
                            print('[scoreboard] link stale — reconnecting', flush=True)
                            break
                        try:
                            ws.send(json.dumps({'event': 'ping', 'data': {}}))
                        except Exception:
                            break               # send failed => link is dead
                        continue
                    if not raw:
                        break
                    last_rx = time.time()
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    event = msg.get('event')
                    if not event or event == 'pong':
                        continue
                    self.frame.emit(event, msg.get('data'))

            except Exception as e:
                if not self._stop.is_set():
                    print(f'[scoreboard] connect failed: {e}', flush=True)
            finally:
                with self._lock:
                    self._ws = None
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass
                if not self._stop.is_set():
                    self.connected.emit(False)

            self._stop.wait(_RETRY_EVERY)
