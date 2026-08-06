"""Application entry point — wires the server link to the board window.

Startup order is deliberate: the window opens *before* the server is reachable.
At a meet the TV Pi and the server Pi power up together, and a display that waits
for a successful HTTP call before drawing anything looks broken for the first
thirty seconds. Instead the board opens with fallback theming and a status
message, then adopts the real config once ``GET /config`` answers.
"""
import argparse
import os
import sys

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication

from .board import BoardWindow
from .client import ServerLink, fetch_config
from .fonts import load_app_fonts
from .theme import Config

DEFAULT_SERVER = os.environ.get('SPLOUCH_SERVER', 'http://splouch.local')

# Re-fetch /config this often after a failure, until it succeeds.
_CONFIG_RETRY_MS = 5000


class ScoreboardApp:
    """Owns the window, the link, and the config-refresh policy."""

    def __init__(self, server: str, fullscreen: bool = True):
        self.server  = server
        self.config  = Config()
        self.window  = BoardWindow(self.config)
        self.link    = ServerLink(server)
        self._have_config = False

        self.link.frame.connect(self._on_frame)
        self.link.connected.connect(self._on_connected)

        self.window.set_status(f'Connecting to {server}…')
        if fullscreen:
            self.window.showFullScreen()
        else:
            self.window.resize(1280, 720)
            self.window.show()

        self._config_timer = QTimer()
        self._config_timer.setInterval(_CONFIG_RETRY_MS)
        self._config_timer.timeout.connect(self._load_config)
        self._load_config()
        self.link.start()

    # ── Config ─────────────────────────────────────────────────────────────────

    def _load_config(self):
        """Fetch /config; keep retrying on a timer until it lands.

        A lane-count change alters the number of rows, which means rebuilding the
        window rather than restyling it — so it is handled separately from a
        pure theme change.
        """
        try:
            raw = fetch_config(self.server)
        except Exception as e:
            if not self._have_config:
                print(f'[scoreboard] config fetch failed ({e}) — retrying', flush=True)
                self._config_timer.start()
            return

        self._config_timer.stop()
        self._have_config = True
        new_config = Config(raw)

        if new_config.num_lanes != self.config.num_lanes:
            was_full = self.window.isFullScreen()
            snapshot = dict(self.window.snapshot)
            status   = self.window.status.text() if self.window.status.isVisible() else ''
            self.window.close()
            self.window = BoardWindow(new_config)
            self.window.snapshot.update(snapshot)
            self.window.refresh()
            self.window.set_status(status)
            if was_full:
                self.window.showFullScreen()
            else:
                self.window.resize(1280, 720)
                self.window.show()
        else:
            self.window.set_config(new_config)

        self.config = new_config

    # ── Server events (docs/api.md §2 `/ws/scoreboard`) ────────────────────────

    def _on_connected(self, ok: bool):
        if ok:
            self.window.set_status('')
            # The server's per-connection state (theme, lane count) may have moved
            # while we were away; a reconnect is the cheapest place to resync.
            self._load_config()
        else:
            self.window.set_status(f'Reconnecting to {self.server}…')

    def _on_frame(self, event: str, data):
        if event == 'update_scoreboard':
            self.window.apply_update(data or {})
        elif event == 'reload':
            # Settings or theme changed — re-fetch config and redraw.
            self._load_config()
        elif event == 'test_mode':
            active = bool((data or {}).get('active'))
            self.window.set_status('⚠ TEST SESSION' if active else '')
        elif event == 'display_overlay':
            # The operator blanked the board (medal ceremony, announcements).
            self.window.set_status(' ' if (data or {}).get('active') else '')
        elif event in ('race_finished', 'columns_state'):
            # race_finished: results confirmed — the board already shows final
            # times, so nothing to redraw yet.
            # columns_state: the browser collapses optional columns during a race;
            # the native board keeps them, since it has no reflow cost.
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='scoreboard', description='Splouch Qt scoreboard (TV display)')
    parser.add_argument('--server', default=DEFAULT_SERVER,
                        help=f'Splouch server base URL (default: {DEFAULT_SERVER})')
    parser.add_argument('--windowed', action='store_true',
                        help='run in a window instead of fullscreen (development)')
    args = parser.parse_args(argv)

    # Crisp text on a 4K TV: scale by the display's real DPI rather than
    # rendering at 1080p and upscaling, which is what the browser kiosk did.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    qt_app = QApplication(sys.argv[:1])
    qt_app.setApplicationName('Splouch Scoreboard')
    load_app_fonts()   # needs the QApplication — Qt has no font database before it

    app = ScoreboardApp(args.server, fullscreen=not args.windowed)
    try:
        return qt_app.exec_()
    finally:
        app.link.stop()
