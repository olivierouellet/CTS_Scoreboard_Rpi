import re


def parse_time_hundredths(s: str):
    """Parse a time string to integer hundredths of a second.

    Handles:
      SS.HH          →  e.g. "58.21"
      M:SS.HH        →  e.g. "0:58.21"
      HH:MM:SS.hh    →  e.g. "00:00:58.21"  (Lenex entrytime format)

    Returns None for empty, zero, or unparseable input.
    """
    if not s:
        return None
    s = s.strip()
    m = re.match(r'^(\d+):(\d{2}):(\d{2})\.(\d{2})$', s)
    if m:
        val = (int(m.group(1)) * 360000 + int(m.group(2)) * 6000
               + int(m.group(3)) * 100 + int(m.group(4)))
        return val if val > 0 else None
    m = re.match(r'^(?:(\d+):)?(\d{1,2})\.(\d{2})$', s)
    if not m:
        return None
    val = (int(m.group(1)) if m.group(1) else 0) * 6000 + int(m.group(2)) * 100 + int(m.group(3))
    return val if val > 0 else None
