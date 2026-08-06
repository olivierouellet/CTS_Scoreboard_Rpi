"""Application entry point — wires the server link to the board window.

Startup order is deliberate: the window opens *before* the server is reachable.
At a meet the TV Pi and the server Pi power up together, and the kiosk usually
wins — it has no service to start. So the board draws immediately with fallback
theming and a status message, then adopts the real config once ``GET /config``
answers.

That only holds because **nothing blocking runs on the GUI thread**. Both server
calls are asynchronous: ``ConfigLoader`` fetches ``/config`` in a worker thread,
``ServerLink`` runs the WebSocket in another. An inline ``fetch_config()`` here
would defeat the whole design — a server that is reachable but not yet answering
blocks for the full timeout, and before the first paint that means a blank TV,
not merely a stale one.
"""
import argparse
import os
import sys
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication

from .board import BoardWindow
from .client import ConfigLoader, ServerLink
from .fonts import load_app_fonts
from .theme import Config

DEFAULT_SERVER = os.environ.get('SPLOUCH_SERVER', 'http://splouch.local')

# Re-fetch /config this often after a failure, until it succeeds.
_CONFIG_RETRY_MS = 5000

# How often to refresh the "waiting" line's elapsed count.
_WAIT_TICK_MS = 1000

# Headlines are English-only: they are shown *before* GET /config lands, which is
# what carries the meet's locale and labels. Translating them would need new keys
# in the server's locale files. See scoreboard/README.md.
_WAITING = 'Waiting for the timing server'
_LOST    = 'Lost connection to the timing server'


def _host_of(url: str) -> str:
    """`http://splouch.local` -> `splouch.local` — the scheme is noise on a TV."""
    return url.split('://', 1)[-1].rstrip('/')


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

        self._waiting_since = time.monotonic()
        self._waiting_head  = _WAITING
        self.window.set_status(_WAITING, _host_of(server))
        self._show(self.window, fullscreen)

        # Ticks the elapsed count on the waiting screen. Without it the TV looks
        # identical whether the app is retrying or has hung, which is exactly the
        # ambiguity a black screen creates at a meet.
        self._wait_timer = QTimer()
        self._wait_timer.setInterval(_WAIT_TICK_MS)
        self._wait_timer.timeout.connect(self._tick_waiting)
        self._wait_timer.start()

        self.config_loader = ConfigLoader(server)
        self.config_loader.loaded.connect(self._on_config)
        self.config_loader.failed.connect(self._on_config_failed)

        self._config_timer = QTimer()
        self._config_timer.setInterval(_CONFIG_RETRY_MS)
        self._config_timer.timeout.connect(self.config_loader.request)
        self.config_loader.request()
        self.link.start()

    @staticmethod
    def _show(window, fullscreen: bool):
        """Show *window*, sizing it first so F11/Esc has a sane windowed size.

        ``showNormal()`` restores the geometry the window had before it went
        fullscreen — with no prior resize that is a useless 100px box, so set one
        even on the kiosk path where it is never seen directly.
        """
        window.resize(1280, 720)
        window.set_fullscreen(fullscreen)
        if not fullscreen:
            window.show()

    # ── Waiting screen ─────────────────────────────────────────────────────────

    def _tick_waiting(self):
        """Refresh the elapsed count under the waiting headline."""
        seconds = int(time.monotonic() - self._waiting_since)
        if seconds < 60:
            elapsed = f'{seconds} s'
        else:
            elapsed = f'{seconds // 60} min {seconds % 60:02d} s'
        self.window.set_status(self._waiting_head,
                               f'{_host_of(self.server)} · retrying · {elapsed}')

    def _start_waiting(self, headline: str):
        self._waiting_head  = headline
        self._waiting_since = time.monotonic()
        self._tick_waiting()
        self._wait_timer.start()

    def _stop_waiting(self):
        self._wait_timer.stop()
        self.window.set_status('')

    # ── Config ─────────────────────────────────────────────────────────────────

    def _on_config_failed(self, reason: str):
        """A /config fetch failed — keep retrying until the server appears.

        Only noisy about it before the first success; after that the board already
        has usable config and a failed refresh is not worth a log line per retry.
        """
        if not self._have_config:
            print(f'[scoreboard] config fetch failed ({reason}) — retrying', flush=True)
            self._config_timer.start()

    def _on_config(self, raw: dict):
        """Apply a freshly fetched config.

        A lane-count change alters the number of rows, which means rebuilding the
        window rather than restyling it — so it is handled separately from a
        pure theme change.
        """
        self._config_timer.stop()
        self._have_config = True
        new_config = Config(raw)

        if new_config.num_lanes != self.config.num_lanes:
            was_full = self.window.isFullScreen()
            snapshot = dict(self.window.snapshot)
            status   = self.window.status_text()
            detail   = self.window.status_detail.text()

            # Build and show the replacement BEFORE closing the old window.
            # Closing the only visible window emits QApplication::lastWindowClosed,
            # which quits the app under the default quitOnLastWindowClosed — and
            # because that is a *clean* exit (status 0), start-scoreboard.sh would
            # treat it as a deliberate quit and not restart. Overlapping the two
            # windows keeps the count above zero and the signal unfired.
            old_window  = self.window
            self.window = BoardWindow(new_config)
            self.window.snapshot.update(snapshot)
            self.window.refresh()
            self.window.set_status(status, detail)
            self._show(self.window, was_full)
            old_window.close()
            old_window.deleteLater()
        else:
            self.window.set_config(new_config)

        self.config = new_config

    # ── Server events (docs/api.md §2 `/ws/scoreboard`) ────────────────────────

    def _on_connected(self, ok: bool):
        if ok:
            self._stop_waiting()
            # The server's per-connection state (theme, lane count) may have moved
            # while we were away; a reconnect is the cheapest place to resync.
            self.config_loader.request()
        else:
            # Distinguish "never connected" from "the link dropped mid-meet" —
            # the second means the board on screen is stale, which matters more.
            self._start_waiting(_LOST if self._have_config else _WAITING)

    def _on_frame(self, event: str, data):
        if event == 'update_scoreboard':
            self.window.apply_update(data or {})
        elif event == 'reload':
            # Settings or theme changed — re-fetch config and redraw.
            self.config_loader.request()
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
