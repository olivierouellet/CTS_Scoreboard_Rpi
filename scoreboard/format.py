"""Value formatting shared by the board's cells.

Kept Qt-free and separate from ``board.py`` so it can be tested in CI without
PySide6 installed — these are pure string functions with no widget involvement.
"""
import re

# `1:05.23`, `59.99`, `5.23` — the clock format every console string uses.
_CLOCK = re.compile(r'^(?:(\d+):)?(\d{1,2})\.(\d{2})$')


def parse_clock(text):
    """Clock string to hundredths of a second, or ``None`` if unparseable.

    Mirrors ``parseHundredths`` in the browser templates. Used to re-base the
    locally interpolated clock each time the console sends a new ``running_time``.
    """
    if not text:
        return None
    match = _CLOCK.match(text.strip())
    if not match:
        return None
    minutes, seconds, hundredths = match.groups()
    return int(minutes or 0) * 6000 + int(seconds) * 100 + int(hundredths)


def fmt_clock(hundredths: int) -> str:
    """Hundredths to a clock string, exactly as ``formatHundredths`` renders it.

    Note the asymmetry, which is intentional and matches the browser: seconds are
    zero-padded only once there is a minutes part — `5.23`, but `1:05.23`.
    """
    hundredths = max(0, int(hundredths))
    frac    = hundredths % 100
    seconds = (hundredths // 100) % 60
    minutes = hundredths // 6000
    if minutes:
        return f'{minutes}:{seconds:02d}.{frac:02d}'
    return f'{seconds}.{frac:02d}'


def fmt_delta(seconds) -> str:
    """Signed delta vs seed time, formatted exactly as the browser formats it.

    The server sends the value as seconds (``lane_delta_seconds<i>``), but its own
    formatter — ``meet_data._delta_html`` — works in integer hundredths and
    switches to ``m:ss.hh`` once the gap passes a minute. We convert back to
    hundredths and mirror that, so the Qt display and the web scoreboard never
    disagree about the same swimmer.

    Only a badly wrong seed time produces a gap over a minute, which is precisely
    when a seeding error is most visible on the TV.

    Returns ``''`` when there is no delta (no seed time, or an unparseable value).
    """
    if seconds is None:
        return ''
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return ''

    # Round-trip through hundredths: the server derived `seconds` from an integer
    # number of hundredths, so this recovers the original value exactly.
    hundredths = round(value * 100)
    sign = '-' if hundredths < 0 else '+'
    hundredths = abs(hundredths)

    minutes = hundredths // 6000
    secs    = (hundredths // 100) % 60
    frac    = hundredths % 100
    if minutes:
        return f'{sign}{minutes}:{secs:02d}.{frac:02d}'
    return f'{sign}{secs}.{frac:02d}'
