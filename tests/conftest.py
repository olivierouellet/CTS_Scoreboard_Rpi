"""Shared test setup.

Nothing here imports PySide6 at module level — most of the suite is deliberately
Qt-free so it runs in CI without the `scoreboard` extra, and importing Qt here
would break that. The `qt_app` fixture skips instead.
"""
import os
import sys
import tempfile

import pytest

# Offscreen rendering, and a throwaway cache dir. ScoreboardApp reads the cached
# config at startup and writes it after every successful fetch, so without this a
# test run leaves a stale lane count in the developer's real ~/.cache that the
# next run silently picks up.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('XDG_CACHE_HOME', tempfile.mkdtemp(prefix='splouch-test-'))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO, os.path.join(REPO, 'server')):
    if path not in sys.path:
        sys.path.insert(0, path)

# Module-level so the QApplication outlives every fixture scope. A fixture that
# only yields it holds the sole Python reference, so PySide destroys the C++ object
# at teardown — and Qt discards all fonts registered via addApplicationFont along
# with it. The next module then gets a fresh, font-less application while
# `fonts._APP_FONTS_LOADED` still reports them as loaded, and every family
# silently resolves to the monospace fallback.
_QT_APP = None


@pytest.fixture(scope='session')
def qt_app():
    """A single QApplication for the whole session, with the bundled fonts loaded."""
    global _QT_APP
    pytest.importorskip('PySide6', reason='needs the `scoreboard` extra (PySide6)')
    from PySide6.QtWidgets import QApplication

    from scoreboard.fonts import load_app_fonts
    if _QT_APP is None:
        _QT_APP = QApplication.instance() or QApplication([])
        # Mirror main(): register fonts before anything resolves a family, since
        # resolve_family() memoises its answers.
        load_app_fonts()
    return _QT_APP
