"""Font registration and family resolution.

The web clients load their faces over CSS ``@font-face`` from
``shared/static/fonts/``, which holds **woff2** — a browser-only container that
Qt's font database cannot read. So the Qt display resolves its families in three
steps:

1. Register any TTF/OTF found in ``shared/static/fonts/`` (drop the desired faces
   there and they are picked up automatically — woff2 files are ignored).
2. Otherwise use the family if the system already has it (the kiosk installs
   ``fonts-overpass``, which provides the default *Overpass Mono*).
3. Otherwise fall back to the platform's monospace face, so a missing font
   degrades to a readable board instead of Qt's proportional default.

Resolution is cached: it is called once per label restyle, and querying the font
database is not free.
"""
import os

_APP_FONTS_LOADED = False
_RESOLVED: dict[str, str] = {}

# Where the browser clients keep their faces; shared with the Qt display.
_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'shared', 'static', 'fonts')


def load_app_fonts() -> list[str]:
    """Register bundled TTF/OTF faces with Qt. Returns the families added.

    Safe to call more than once; only the first call touches the font database.
    Call it after the QApplication exists — Qt has no font database before that.
    """
    global _APP_FONTS_LOADED
    if _APP_FONTS_LOADED:
        return []
    _APP_FONTS_LOADED = True

    from PyQt5.QtGui import QFontDatabase

    added = []
    try:
        names = sorted(os.listdir(_FONT_DIR))
    except OSError:
        return added

    for name in names:
        if not name.lower().endswith(('.ttf', '.otf')):
            continue
        font_id = QFontDatabase.addApplicationFont(os.path.join(_FONT_DIR, name))
        if font_id != -1:
            added.extend(QFontDatabase.applicationFontFamilies(font_id))
    if added:
        print(f'[scoreboard] loaded bundled fonts: {", ".join(sorted(set(added)))}',
              flush=True)
    return added


def resolve_family(family: str) -> str:
    """Return *family* if Qt can render it, else a monospace fallback.

    A scoreboard in a proportional font is unreadable at a distance — the digits
    jitter as times tick — so the fallback is deliberately monospace rather than
    Qt's default.
    """
    if not family:
        family = 'monospace'
    if family in _RESOLVED:
        return _RESOLVED[family]

    resolved = family
    try:
        from PyQt5.QtGui import QFontDatabase
        if family not in QFontDatabase().families():
            from PyQt5.QtGui import QFont
            fallback = QFont()
            fallback.setStyleHint(QFont.Monospace)
            fallback.setFamily('monospace')
            resolved = QFont(fallback.defaultFamily()).family() or 'monospace'
            print(f'[scoreboard] font "{family}" unavailable — using {resolved}',
                  flush=True)
    except Exception:
        pass

    _RESOLVED[family] = resolved
    return resolved
