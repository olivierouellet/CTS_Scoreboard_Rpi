"""Custom widgets — chiefly the shrink-to-fit label.

This is the reason the display stopped being a web page. CSS can only *truncate*
an overlong swimmer name (`text-overflow: ellipsis`); it cannot shrink it. Qt
measures text before drawing it, so :class:`FitLabel` picks the largest pixel size
at which the whole name fits and nobody named "Vandenbroucke-Mortensen" loses
their surname on the TV.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import QLabel


class FitLabel(QLabel):
    """A QLabel whose font shrinks (never grows past *max_px*) to fit its width.

    The height drives the natural size — a lane row is a fixed fraction of the
    screen — and the width is the constraint we solve against. ``min_px`` stops
    the search before the text becomes unreadable; past that we let it clip
    rather than render a 4px name.
    """

    def __init__(self, text='', *, max_px=48, min_px=10, parent=None):
        super().__init__(text, parent)
        self._max_px = max_px
        self._min_px = min_px
        self.setTextFormat(Qt.PlainText)

    def set_max_px(self, px: int):
        """Set the ceiling font size (called on resize, from the row height)."""
        px = max(self._min_px, int(px))
        if px != self._max_px:
            self._max_px = px
            self._refit()

    def setText(self, text):          # noqa: N802 — Qt naming
        super().setText(text if text is not None else '')
        self._refit()

    def resizeEvent(self, event):     # noqa: N802 — Qt naming
        super().resizeEvent(event)
        self._refit()

    def _refit(self):
        text = self.text()
        font = self.font()
        if not text:
            font.setPixelSize(self._max_px)
            self.setFont(font)
            return

        avail = max(1, self.width() - 2)   # 1px breathing room each side

        # Widest-first: the common case is a name that already fits, so check the
        # ceiling before paying for a search.
        font.setPixelSize(self._max_px)
        if QFontMetrics(font).horizontalAdvance(text) <= avail:
            self.setFont(font)
            return

        # Binary search the largest pixel size that fits. Text advance is monotonic
        # in font size, so this is exact, and ~6 iterations for any realistic range.
        lo, hi, best = self._min_px, self._max_px, self._min_px
        while lo <= hi:
            mid = (lo + hi) // 2
            font.setPixelSize(mid)
            if QFontMetrics(font).horizontalAdvance(text) <= avail:
                best, lo = mid, mid + 1
            else:
                hi = mid - 1
        font.setPixelSize(best)
        self.setFont(font)
