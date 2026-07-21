import collections
import glob
import hashlib
import json
import os
import os.path
import queue
import re
import sys

import tomllib

from parsers.hytek_parser import HytekParser
from parsers.lenex_parser import load_lenex
from console_decoders import make_decoder

try:
    import pty, fcntl, termios
    _PTY_AVAILABLE = True
except ImportError:
    _PTY_AVAILABLE = False

# ── Paths ──────────────────────────────────────────────────────────────────────

app_dir           = os.path.dirname(os.path.abspath(__file__))
SCOREBOARD_DIR    = os.path.expanduser('~/TremplinData')
settings_file     = os.path.join(SCOREBOARD_DIR, 'settings.json')
_settings_default = os.path.join(app_dir, 'settings.default.json')

SESSIONS_FOLDER        = os.path.join(app_dir, 'recorded')
CUSTOM_SESSIONS_FOLDER = os.path.join(SCOREBOARD_DIR, 'recorded')
IMAGES_DIR             = os.path.join(SCOREBOARD_DIR, 'images')
ICONS_DIR              = os.path.join(SCOREBOARD_DIR, 'icons')
HOME_ICON_PATH         = os.path.join(ICONS_DIR, 'home_icon.png')
HOME_ICON_512_PATH     = os.path.join(ICONS_DIR, 'home_icon_512.png')
PICKER_DIR             = os.path.join(SCOREBOARD_DIR, 'picker')
MEET_FOLDER            = os.path.join(SCOREBOARD_DIR, 'meet')
LOGS_DIR               = os.path.join(SCOREBOARD_DIR, 'logs')
CUSTOM_LOCALE_FOLDER          = os.path.join(SCOREBOARD_DIR, 'locale')
THEME_FOLDER           = os.path.join(app_dir, 'themes')
CUSTOM_THEME_FOLDER    = os.path.join(SCOREBOARD_DIR, 'themes')
CUSTOM_DECODERS_FOLDER = os.path.join(SCOREBOARD_DIR, 'console_decoders')

# ── Theme / locale defaults ────────────────────────────────────────────────────

DEFAULT_THEME_COLORS = {
    'bg': '#0d0d0d', 'header_bg': '#1a1a1a', 'header_border': '#2e2e2e',
    'header_label': '#ffffff', 'header_value': '#e0e0e0',
    'th_text': '#666666', 'th_bg': '#1a1a1a',
    'row_odd': '#141414', 'row_even': '#202020', 'row_text': '#e0e0e0',
    'time': '#FFD700', 'delta_better': '#4CAF50', 'delta_worse': '#808080',
    'podium_gold': '#545454', 'podium_silver': '#424242', 'podium_bronze': '#343434',
    'schedule_event': '#3b9eff', 'schedule_time': '#FFD700',
    'schedule_name': '#e0e0e0', 'schedule_club': '#666666',
}
DEFAULT_THEME_FONTS = {'family': 'Overpass Mono', 'digits': 'DSEG7Classic', 'timing': 'Overpass Mono'}

_FALLBACK_LABELS = {
    'event': 'EVENT', 'heat': 'HEAT', 'lane': 'LANE',
    'place': 'PLACE', 'time': 'TIME', 'name': 'NAME', 'club': 'CLUB',
    'chrono': 'CHRONO',
}

_STROKE_ALIASES = [
    ('individual medley', 'medley'),
    ('breaststroke',      'breaststroke'),
    ('backstroke',        'backstroke'),
    ('butterfly',         'butterfly'),
    ('freestyle',         'freestyle'),
    ('medley',            'medley'),
    ('breast',            'breaststroke'),
    ('back',              'backstroke'),
    ('free',              'freestyle'),
    ('fly',               'butterfly'),
    ('im',                'medley'),
]

_GENDER_PATTERNS = [
    (r"\bwomen(?:'s)?\b", 'women'),
    (r"\bgirls?(?:'s)?\b", 'girls'),
    (r"\bmen(?:'s)?\b", 'men'),
    (r"\bboys?(?:'s)?\b", 'boys'),
    (r"\bmixed\b", 'mixed'),
]

# ── Settings ───────────────────────────────────────────────────────────────────

settings = {
    'meet_title': '',
    'serial_port': 'COM1',
    'username': 'score',
    'password': 'swimming',
    'splash_url': '',
    'locale': 'en',
    'label_style': 'long',
    'num_lanes': 8,
    'show_lane_header': True,
    'show_name_header': True,
    'show_club_header': True,
    'show_time_header': True,
    'show_delta_header': True,
    'show_position_header': True,
    'show_name': True,
    'show_club': True,
    'show_delta': True,
    'show_position': True,
    'show_podium': True,
    'results_sort': 'lane',
    'active_theme': 'default',
    'theme_colors': {
        'bg': '#0d0d0d', 'header_bg': '#1a1a1a', 'header_border': '#2e2e2e',
        'header_label': '#ffffff', 'header_value': '#e0e0e0',
        'th_text': '#666666', 'th_bg': '#1a1a1a',
        'row_odd': '#141414', 'row_even': '#202020', 'row_text': '#e0e0e0',
        'time': '#FFD700', 'delta_better': '#4CAF50', 'delta_worse': '#808080',
        'podium_gold': '#545454', 'podium_silver': '#424242', 'podium_bronze': '#343434',
    },
    'theme_fonts': {'family': 'Overpass Mono', 'digits': 'DSEG7Classic', 'timing': 'Overpass Mono'},
    'intro_timeout': 300,
    'results_timeout': 300,
    'server_update_timeout': 300,
    'finish_debounce': 3.0,
    'split_min_duration': 1.0,
    'pool_length': 25,
    'touchpad_sides': 1,
    'carousel_interval': 10,
    'console_type': 'cts_gen6',
    # Per-meet cloud appearance overrides, keyed by meet_uid(). See
    # CLOUD_PROFILE_FIELDS / apply_meet_profile().
    'meet_profiles': {},
}

# ── Meet data ──────────────────────────────────────────────────────────────────
# The loaded meet (the LENEX dicts + the Hytek parser) lives in a single immutable
# snapshot, `meet`. Publishing a new meet swaps that one reference — atomic in
# CPython — so a reader on another thread (the worker mid-race, the relay) never
# sees a half-updated dict. Read it as `state.meet.start_list`,
# `state.meet.event_info`, …; a function that touches several fields should pin the
# snapshot once (`m = state.meet`) so it sees a consistent view even if a swap lands
# mid-read. Writers must go through set_lenex / load_event_info / clear_meet — the
# published snapshot is never mutated in place.

class _Meet:
    __slots__ = ('event_names', 'start_list', 'heat_times', 'meet_info',
                 'event_distances', 'event_info')

    def __init__(self, event_names=None, start_list=None, heat_times=None,
                 meet_info=None, event_distances=None, event_info=None):
        self.event_names     = event_names     or {}
        self.start_list      = start_list      or {}
        self.heat_times      = heat_times      or {}
        self.meet_info       = meet_info       or {}
        self.event_distances = event_distances or {}
        self.event_info      = event_info if event_info is not None else HytekParser()


meet = _Meet()


def set_lenex(data):
    """Publish a LENEX meet atomically (from a parsers.lenex_parser result)."""
    global meet
    meet = _Meet(event_names=data.event_names, start_list=data.start_list,
                 heat_times=data.heat_times, meet_info=data.meet_info,
                 event_distances=data.event_distances)


def load_event_info(path):
    """Load a Hytek CSV into a fresh parser and publish it atomically."""
    global meet
    p = HytekParser()
    p.load(path)
    meet = _Meet(event_info=p)


def clear_meet():
    """Drop the loaded meet atomically."""
    global meet
    meet = _Meet()

# Cloud-appearance overrides that travel per meet (not Pi-global). Keyed by
# meet_uid() in settings['meet_profiles']; the active values are mirrored into
# settings so the relay metadata and the Meet tab read them directly.
CLOUD_PROFILE_FIELDS = ('cloud_meet_title', 'meet_location', 'meet_sport',
                        'app_window_title', 'cloud_label_style',
                        'active_picker_image', 'active_home_icon')
_PROFILE_DEFAULTS = {'cloud_label_style': 'short'}


def _profile_field(f):
    return settings.get(f, _PROFILE_DEFAULTS.get(f, ''))


def uid_from_meet_info(meet_info, fallback_file=''):
    """meet_uid() for an arbitrary parsed meet, without touching global state.

    Lets callers (e.g. the "update file" guard) compute a candidate file's uid
    and compare it to the loaded meet before committing the swap.
    """
    name  = meet_info.get('name', '')
    dates = sorted(d for d in (s.get('date', '') for s in meet_info.get('sessions', [])) if d)
    basis = (name + '|' + '|'.join(dates)).strip('|')
    if not basis:
        basis = fallback_file
    if not basis:
        return ''
    return hashlib.sha1(basis.encode('utf-8')).hexdigest()[:12]


def meet_uid():
    """Stable identifier for the currently loaded meet.

    LENEX: a hash of the meet name plus its session dates — stable across
    re-exports and distinct for each day of a meet split into separate files.
    Otherwise (Hytek CSV, no sessions) falls back to the loaded file name.
    Returns '' when nothing is loaded.
    """
    return uid_from_meet_info(meet.meet_info, _active_meet_file)


def apply_meet_profile(uid):
    """Load a meet's saved cloud-appearance overrides into the active settings.

    A meet with no profile yet is seeded from the current values, so a freshly
    loaded meet starts from what's already on screen (usually only the title
    needs changing). Returns the active_home_icon so the caller can re-render it.
    """
    profiles = settings.setdefault('meet_profiles', {})
    if uid and uid in profiles:
        for f in CLOUD_PROFILE_FIELDS:
            settings[f] = profiles[uid].get(f, _PROFILE_DEFAULTS.get(f, ''))
    elif uid:
        profiles[uid] = {f: _profile_field(f) for f in CLOUD_PROFILE_FIELDS}
    return settings.get('active_home_icon', '')


def save_meet_profile(uid):
    """Persist the active cloud-appearance overrides into the meet's profile."""
    if not uid:
        return
    profiles = settings.setdefault('meet_profiles', {})
    profiles[uid] = {f: _profile_field(f) for f in CLOUD_PROFILE_FIELDS}

# ── Console log capture ──────────────────────────────────────────────────────
# Keep the most recent console output (the same lines that go to the journal) in
# a RAM ring buffer so the operator can download it or save it to flash on demand
# — without writing to flash continuously, which matters on SD-card Pis.

_log_ring = collections.deque(maxlen=10000)


class _LogTee:
    """Wrap a stream so complete lines are also captured into _log_ring."""

    def __init__(self, stream):
        self._stream = stream
        self._buf    = ''

    def write(self, s):
        self._stream.write(s)
        self._buf += s
        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            _log_ring.append(line)
        return len(s)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def install_log_capture():
    """Tee stdout/stderr into the ring buffer. Idempotent; call once at startup."""
    if not isinstance(sys.stdout, _LogTee):
        sys.stdout = _LogTee(sys.stdout)
    if not isinstance(sys.stderr, _LogTee):
        sys.stderr = _LogTee(sys.stderr)


# ── Runtime state ──────────────────────────────────────────────────────────────

update      = {}

_last_results_snapshot      = {}
_results_prev_race_finished = False

_worker_stop        = False
_worker_gen         = 0
_test_session       = None
_record_handle      = None
_debug_serial       = False
_serial_status      = {'state': 'idle', 'msg': ''}
_finish_timer_gen   = 0
_scoreboard_clients = {}
_test_meet_active   = False
_overlay_active     = False
_cols_hidden        = False
_pty_fd             = None
_pty_pid            = None
main_thread         = None

# The decoder is owned by a single thread — the serial/playback worker. Other
# threads that need a decoder operation (WS adjust_splits/next_heat, the reset
# debounce) post a callable here instead of calling the decoder directly; the
# worker drains this queue between packets. So the decoder is never touched
# concurrently and needs no lock. See worker._drain_cmds and its command handlers.
_worker_cmds = queue.Queue()

# Lanes currently emitting lane_running=True — worker-thread state. Consoles only
# send the running flag on transitions (start/split/finish), streaming just the
# clock in between, so the debounced board-wipe must consult this rather than the
# momentary packet to avoid clearing a heat that is mid-race.
_running_lanes = set()

in_speed = 1.0

_update_in_progress    = False
_active_meet_file      = ''   # basename of the currently loaded meet file
_active_meet_uid       = ''   # meet_uid() of the currently loaded meet
_os_update_in_progress = False
_update_log_lines      = []
_update_log_done       = None
_os_update_log_lines   = []
_os_update_log_done    = None

_rtc_in_progress       = False
_rtc_log_lines         = []
_rtc_log_done          = None

# ── Init ───────────────────────────────────────────────────────────────────────

def _ensure_data_dirs():
    for d in (SCOREBOARD_DIR, MEET_FOLDER, IMAGES_DIR, ICONS_DIR, PICKER_DIR,
              CUSTOM_SESSIONS_FOLDER, CUSTOM_LOCALE_FOLDER, CUSTOM_THEME_FOLDER,
              CUSTOM_DECODERS_FOLDER):
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(settings_file) and os.path.exists(_settings_default):
        import shutil
        shutil.copy2(_settings_default, settings_file)

_ensure_data_dirs()

# ── Locale / theme utilities ───────────────────────────────────────────────────

def _locale_path(code):
    custom = os.path.join(CUSTOM_LOCALE_FOLDER, code + '.toml')
    return custom if os.path.exists(custom) else os.path.join('locales', code + '.toml')

def load_locale(style=None):
    code  = settings.get('locale', 'fr')
    style = style or settings.get('label_style', 'long')
    try:
        with open(_locale_path(code), 'rb') as f:
            data = tomllib.load(f)
        return {k: v[style] for k, v in data['labels'].items()}
    except Exception:
        return dict(_FALLBACK_LABELS)

def load_preview_strings():
    code = settings.get('locale', 'fr')
    try:
        with open(_locale_path(code), 'rb') as f:
            return tomllib.load(f).get('preview', {})
    except Exception:
        return {}

def _mobile_strings():
    code = settings.get('locale', 'en')
    try:
        with open(_locale_path(code), 'rb') as f:
            return tomllib.load(f).get('mobile', {})
    except Exception:
        return {}

def _read_locale_name(path, fallback):
    try:
        with open(path, 'rb') as f:
            return tomllib.load(f).get('meta', {}).get('name', fallback)
    except Exception:
        return fallback

def list_locales():
    result = []
    for path in sorted(glob.glob(os.path.join('locales', '*.toml'))):
        code = os.path.splitext(os.path.basename(path))[0]
        result.append((code, _read_locale_name(path, code)))
    return result

def list_custom_locales():
    result = []
    for path in sorted(glob.glob(os.path.join(CUSTOM_LOCALE_FOLDER, '*.toml'))):
        code = os.path.splitext(os.path.basename(path))[0]
        result.append((code, _read_locale_name(path, code)))
    return result

def _read_theme_name(path, fallback):
    try:
        with open(path, 'rb') as f:
            return tomllib.load(f).get('name', fallback)
    except Exception:
        return fallback

def list_builtin_themes():
    return [(os.path.splitext(os.path.basename(p))[0],
             _read_theme_name(p, os.path.splitext(os.path.basename(p))[0]))
            for p in sorted(glob.glob(os.path.join(THEME_FOLDER, '*.toml')))]

def list_custom_themes():
    return [(os.path.splitext(os.path.basename(p))[0],
             _read_theme_name(p, os.path.splitext(os.path.basename(p))[0]))
            for p in sorted(glob.glob(os.path.join(CUSTOM_THEME_FOLDER, '*.toml')))]

def load_theme(code):
    path = os.path.join(CUSTOM_THEME_FOLDER, code + '.toml')
    if not os.path.exists(path):
        path = os.path.join(THEME_FOLDER, code + '.toml')
    try:
        with open(path, 'rb') as f:
            data = tomllib.load(f)
        colors = {**DEFAULT_THEME_COLORS, **data.get('colors', {})}
        fonts  = {**DEFAULT_THEME_FONTS,  **data.get('fonts',  {})}
        return colors, fonts
    except Exception:
        return dict(DEFAULT_THEME_COLORS), dict(DEFAULT_THEME_FONTS)

def load_event_translations():
    try:
        with open(_locale_path(settings.get('locale', 'en')), 'rb') as f:
            return tomllib.load(f).get('event_name', {})
    except Exception:
        return {}

def translate_event_name(raw, ev):
    if not ev or not raw:
        return raw
    s    = raw.strip()
    unit = ev.get('unit', 'm')
    sep  = ev.get('separator', '  —  ')

    gender = ''
    for pat, key in _GENDER_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            gender = ev.get(key, key)
            break

    age   = ''
    s_rest = s
    age_m = re.search(
        r'\b(\d+)\s*(?:[Uu](?:nder)?|&\s*[Uu]nder|[Aa]nd\s+[Uu]nder)\b'
        r'|\b[Uu](\d+)\b', s)
    if age_m:
        num    = age_m.group(1) or age_m.group(2)
        age    = '< ' + num
        s_rest = s[:age_m.start()] + s[age_m.end():]
    else:
        range_m = re.search(r'\b(\d{1,2}-\d{1,2})\b', s)
        if range_m:
            age    = range_m.group(1)
            s_rest = s[:range_m.start()] + s[range_m.end():]
        elif re.search(r'\bopen\b', s, re.IGNORECASE):
            age    = ev.get('open', 'Open')
            s_rest = re.sub(r'\bopen\b', '', s, flags=re.IGNORECASE)
        elif re.search(r'\bsenior\b', s, re.IGNORECASE):
            age    = ev.get('senior', 'Senior')
            s_rest = re.sub(r'\bsenior\b', '', s, flags=re.IGNORECASE)

    is_relay = bool(re.search(r'\brelay\b', s_rest, re.IGNORECASE))

    dist   = ''
    dist_m = re.search(r'\b(\d+[xX]\d+|\d+)\b', s_rest)
    if dist_m:
        dist = dist_m.group(1)

    stroke = ''
    for alias, key in _STROKE_ALIASES:
        if re.search(r'\b' + re.escape(alias) + r'\b', s_rest, re.IGNORECASE):
            stroke = ev.get(key, alias)
            break

    left_parts = []
    if dist:
        left_parts.append(dist + ' ' + unit)
    if stroke:
        left_parts.append(stroke)
    if is_relay and ev.get('relay'):
        left_parts.append(ev['relay'])
    left = ' '.join(left_parts)

    right = ' '.join(p for p in [gender, age] if p)

    if left and right:
        return left + sep + right
    return left or right or raw

# ── Settings loader ────────────────────────────────────────────────────────────

def load_settings():
    try:
        with open(settings_file, 'rt') as f:
            settings.update(json.load(f))
    except Exception:
        pass
    csv_files = glob.glob(os.path.join(MEET_FOLDER, '*.csv'))
    if csv_files:
        try:
            load_event_info(max(csv_files, key=os.path.getmtime))
        except Exception:
            pass
    lxf_files = glob.glob(os.path.join(MEET_FOLDER, '*.lxf'))
    if lxf_files:
        try:
            set_lenex(load_lenex(max(lxf_files, key=os.path.getmtime)))
        except Exception:
            pass
    _decoder.configure(settings)


def save_settings():
    """Persist the settings dict to disk atomically.

    Serialize a top-level snapshot to a string first (so a concurrent write
    from another handler thread can't corrupt the output mid-dump), then write
    a temp file and os.replace it into place — a crash or power loss mid-write
    (a real risk on the Pi) can't leave a truncated settings.json.
    """
    data = json.dumps(dict(settings), sort_keys=True, indent=4)
    tmp = settings_file + '.tmp'
    with open(tmp, 'wt') as f:
        f.write(data)
    os.replace(tmp, settings_file)

# ── Decoder (initialized after settings dict is defined) ──────────────────────

_decoder = make_decoder(settings.get('console_type', 'cts_gen6'), settings)
