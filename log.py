"""Iter terminal console: persistent input + color-coded live events.

Linux/Unix interactive TTY: curses full-screen display with a fixed input bar,
scrollable output, and an asynchronous input queue. Works in screen/tmux/SSH.
Everything sent to the LLM and all tool returns are controlled by iter.py;
this module is display/input only. No third-party packages required.

Non-TTY, TERM=dumb, or ITER_TUI=0: regular ANSI/text logging. The legacy
channels/terminal.py input path continues to work in that mode.

Environment: ITER_TUI=0, ITER_UI_WIDTH=144, ITER_LOG_LINES=1200,
ITER_INPUT_CHARS=1200, ITER_ARGS_CHARS=240, ITER_RESULT_CHARS=260,
ITER_SEND_CHARS=2000, ITER_PIN_FILE=.iter-ui-pin.json,
ITER_PIN_PANEL=1, ITER_PIN_WIDTH=40, NO_COLOR, FORCE_COLOR=1.
Pinned panel supports [fg=orange]text[/] (and [fg=#RRGGBB]), plus ANSI SGR
foreground/background colors (8/16/256/RGB), with safe curses mapping.
"""

import atexit
from collections import deque
import datetime
import json
import os
from pathlib import Path
import queue
import re
import shutil
import sys
import threading
import time
import unicodedata

try:
    import curses
except ImportError:
    curses = None

TERMINAL_INPUT_CHARS = int(os.getenv("ITER_INPUT_CHARS", "1200"))
TERMINAL_ARGS_CHARS = int(os.getenv("ITER_ARGS_CHARS", "240"))
TERMINAL_RESULT_CHARS = int(os.getenv("ITER_RESULT_CHARS", "260"))
TERMINAL_SEND_CHARS = int(os.getenv("ITER_SEND_CHARS", "2000"))
_MAX_LINES = max(100, int(os.getenv("ITER_LOG_LINES", "1200")))
_MAX_WIDTH = max(40, int(os.getenv("ITER_UI_WIDTH", "240")))
_PIN_FILE = Path(os.getenv("ITER_PIN_FILE", ".iter-ui-pin.json"))
_PIN_DESIRED_WIDTH = max(26, int(os.getenv("ITER_PIN_WIDTH", "40")))
_PIN_PANEL = os.getenv("ITER_PIN_PANEL", "1") != "0"
_PIN_MAX_CHARS = max(1000, int(os.getenv("ITER_PIN_CHARS", "20000")))
_TTY = sys.stdin.isatty() and sys.stdout.isatty()
_TUI_REQUESTED = os.getenv("ITER_TUI", "1") != "0" and _TTY and os.getenv("TERM", "") not in ("", "dumb")
_COLOR = "NO_COLOR" not in os.environ and ((sys.stdout.isatty() and os.getenv("TERM", "") != "dumb") or os.getenv("FORCE_COLOR") == "1")
_ASCII = os.getenv("ITER_ASCII", "0") == "1"

_ANSI_RE = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)?|[PX^_][\s\S]*?\x1b\\|\[[0-?]*[ -/]*[@-~]|[()][0-9A-Za-z]|.)")
_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")

# Agents often emit literal "\\u001b", "\\x1b", "\\033", or even just
# "[93m" rather than an actual ESC control character. Only recognize
# tightly-scoped SGR colors in the pinned panel; never run raw terminal escapes.
_TEXT_SGR_RE = re.compile(
    r"(?<!\x1b)(?:\\(?:u001[bB]|x1[bB]|033|e))?\\?\[([0-9]{1,3}(?:;[0-9]{1,3}){0,8})m"
)
_PANEL_TAG_RE = re.compile(
    r"\[(?:(fg|color|bg)=([#a-zA-Z0-9_-]+)|(bold)|(\/|\/fg|\/color|\/bg|reset))\]",
    re.IGNORECASE,
)
_PANEL_COLOR_NAMES = {
    "black": 0, "red": 9, "green": 10, "yellow": 11, "blue": 12,
    "magenta": 13, "cyan": 14, "white": 15, "gray": 245,
    "grey": 245, "orange": 208, "pink": 213, "purple": 135,
    "violet": 141, "aqua": 51, "mint": 120,
}


def _panel_color_code(kind, value):
    """Return safe SGR for an agent-friendly [fg=orange] / [bg=#ffaa00] tag."""
    value = value.lower()
    if value in _PANEL_COLOR_NAMES:
        index = _PANEL_COLOR_NAMES[value]
    elif value.isdigit() and 0 <= int(value) <= 255:
        index = int(value)
    elif re.fullmatch(r"#[0-9a-f]{6}", value):
        components = (int(value[i:i + 2], 16) for i in (1, 3, 5))
        return f"\x1b[{38 if kind in ('fg', 'color') else 48};2;" + ";".join(map(str, components)) + "m"
    else:
        return ""  # Leave unknown tags visibly unchanged in the panel.
    return f"\x1b[{38 if kind in ('fg', 'color') else 48};5;{index}m"


def _normalize_panel_colors(value):
    """Turn literal ANSI codes and friendly color tags into real, safe SGR."""
    value = str(value)
    def replace_tag(match):
        if match.group(3):
            return "\x1b[1m"
        if match.group(4):
            return "\x1b[0m"
        code = _panel_color_code(match.group(1).lower(), match.group(2))
        return code or match.group(0)
    value = _PANEL_TAG_RE.sub(replace_tag, value)
    return _TEXT_SGR_RE.sub(lambda match: "\x1b[" + match.group(1) + "m", value)


def _clean(value):
    value = _ANSI_RE.sub("", str(value))
    return "".join("    " if c == "\t" else c for c in value
                   if c == "\n" or c == "\t" or unicodedata.category(c) != "Cc")



def _clean_sgr(value):
    """Keep only safe ANSI SGR styles; neutralize every other escape/control."""
    value = _normalize_panel_colors(value)
    parts = []
    offset = 0
    for match in _ANSI_RE.finditer(value):
        parts.append(_clean(value[offset:match.start()]))
        token = match.group(0)
        if len(token) <= 80 and _SGR_RE.fullmatch(token):
            parts.append(token)
        offset = match.end()
    parts.append(_clean(value[offset:]))
    return "".join(parts)


def _clip(value, maximum):
    value = _clean(value).strip()
    if maximum >= 0 and len(value) > maximum:
        return value[:maximum].rstrip() + f" … [display clipped; {len(value)} chars]"
    return value


def _cw(char):
    if unicodedata.combining(char) or unicodedata.category(char) in ("Cf", "Mn", "Me"):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1


def _take_width(text, width):
    if width <= 0:
        return ""
    end = 0
    used = 0
    for c in text:
        n = _cw(c)
        if used + n > width:
            break
        used += n
        end += 1
    return text[:end]


def _wrap(text, width):
    width = max(5, width)
    output = []
    for raw in _clean(text).split("\n"):
        line = raw.strip()
        if not line:
            output.append("")
            continue
        while line:
            piece = _take_width(line, width)
            if len(piece) == len(line):
                output.append(piece)
                break
            # Prefer spaces, but don't drop arbitrary long unbroken identifiers.
            space = piece.rfind(" ")
            if space > len(piece) // 3:
                output.append(piece[:space].rstrip())
                line = line[space + 1:].lstrip()
            else:
                output.append(piece)
                line = line[len(piece):].lstrip()
    return output or [""]


def _time_label():
    return datetime.datetime.now().strftime("%H:%M:%S")


def _arguments_display(name, args):
    if not isinstance(args, dict):
        return _clip(args, TERMINAL_ARGS_CHARS)
    obj = dict(args)
    if name == "send":
        for key in ("message", "text", "content"):
            if key in obj:
                obj[key] = "<shown below>"
    return _clip(json.dumps(obj, ensure_ascii=False, separators=(", ", ": "), default=str), TERMINAL_ARGS_CHARS)


def _send_message(args):
    if isinstance(args, dict):
        for key in ("message", "text", "content"):
            if args.get(key) is not None:
                return str(args[key])
    return None


# Main-thread log events; UI keyboard loop operates concurrently. `text`
# is never modified beyond display sanitation/truncation.
_LOCK = threading.RLock()
_ROWS = deque(maxlen=_MAX_LINES)       # (timestamp, label, body, color, detail)
_INPUT_QUEUE = queue.Queue()
_SCREEN = None
_INPUT_THREAD = None
_ACTIVE = False
_MODEL = ""
_SESSION = ""
_PHASE = "READY"
_PHASE_START = 0.0
_COMPOSER = ""
_CURSOR = 0
_HISTORY = []
_HISTORY_INDEX = None
_SCROLL = 0                         # number of visual rows above latest
_SHUTDOWN = False
_COLOR_PAIRS = {}
_PIN_TITLE = "PINNED"
_PIN_TEXT = ""
_PIN_TIME = ""
_PIN_SCROLL = 0
_PIN_MTIME = None
_PIN_VISIBLE = _PIN_PANEL
_PIN_ROWS_CACHE = (None, None)
_PIN_ANSI_PAIRS = {}
_PIN_PAIR_NEXT = len(_PALETTE) + 1 if "_PALETTE" in globals() else 10

_PALETTE = {
    "cyan": (51, 6),       # bright aqua
    "green": (120, 2),     # mint
    "pink": (213, 5),      # hot magenta
    "violet": (141, 5),    # lavender
    "blue": (81, 4),      # electric blue
    "yellow": (220, 3),    # amber
    "red": (203, 1),       # coral
    "muted": (245, 7),     # steel grey
    "white": (255, 7),
}
_ANSI_COLORS = {
    "cyan": "96", "green": "92", "pink": "95", "violet": "95",
    "blue": "94", "yellow": "93", "red": "91", "muted": "90", "white": "97"
}


def _attr(name, bold=False):
    if not _COLOR_PAIRS:
        return curses.A_BOLD if bold else curses.A_NORMAL
    attr = curses.color_pair(_COLOR_PAIRS.get(name, _COLOR_PAIRS["white"]))
    return attr | (curses.A_BOLD if bold else 0)



def _rgb_to_xterm(r, g, b):
    """Choose the closest xterm-256 palette color to an RGB triplet."""
    levels = (0, 95, 135, 175, 215, 255)
    coords = tuple(min(range(6), key=lambda i: abs(levels[i] - c)) for c in (r, g, b))
    cube = 16 + coords[0] * 36 + coords[1] * 6 + coords[2]
    cube_err = sum((v - levels[i]) ** 2 for v, i in zip((r, g, b), coords))
    gray_index = min(range(24), key=lambda i: sum((v - (8 + 10 * i)) ** 2 for v in (r, g, b)))
    gray_err = sum((v - (8 + 10 * gray_index)) ** 2 for v in (r, g, b))
    return cube if cube_err <= gray_err else 232 + gray_index


def _xterm_to_rgb(index):
    if index < 16:
        first = ((0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
                 (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
                 (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
                 (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255))
        return first[index]
    if index < 232:
        i = index - 16
        levels = (0, 95, 135, 175, 215, 255)
        return levels[i // 36], levels[(i // 6) % 6], levels[i % 6]
    v = 8 + 10 * (index - 232)
    return (v, v, v)


def _terminal_color(index):
    count = curses.COLORS
    if count >= 256:
        return index
    if count >= 16:
        targets = range(16)
    else:
        targets = range(8)
    rgb = _xterm_to_rgb(index)
    return min(targets, key=lambda i: sum((a - b) ** 2 for a, b in zip(rgb, _xterm_to_rgb(i))))


def _sgr_attr(foreground, background, bold, fallback):
    """Resolve a parsed SGR style to a curses attribute (no raw escapes)."""
    global _PIN_PAIR_NEXT
    if not _COLOR_PAIRS or not _COLOR:
        return curses.A_BOLD if bold else curses.A_NORMAL
    if foreground is None and background is None:
        return _attr(fallback, bold)
    if foreground is None:
        foreground = _PALETTE[fallback][0]
    fg = _terminal_color(foreground)
    bg = _terminal_color(background) if background is not None else -1
    key = (fg, bg)
    number = _PIN_ANSI_PAIRS.get(key)
    if number is None:
        if _PIN_PAIR_NEXT >= curses.COLOR_PAIRS:
            return _attr(fallback, bold)  # Terminals may have very few pairs.
        number = _PIN_PAIR_NEXT
        try:
            curses.init_pair(number, fg, bg)
        except curses.error:
            return _attr(fallback, bold)
        _PIN_ANSI_PAIRS[key] = number
        _PIN_PAIR_NEXT += 1
    return curses.color_pair(number) | (curses.A_BOLD if bold else 0)


def _apply_sgr(params, state):
    """Update [fg, bg, bold] with ANSI SGR color/reset sequences."""
    values = [int(v) if v else 0 for v in params.split(";")]
    i = 0
    while i < len(values):
        v = values[i]
        if v == 0:
            state[:] = [None, None, None]
        elif v == 1:
            state[2] = True
        elif v == 22:
            state[2] = False
        elif 30 <= v <= 37:
            state[0] = v - 30
        elif 90 <= v <= 97:
            state[0] = 8 + v - 90
        elif v == 39:
            state[0] = None
        elif 40 <= v <= 47:
            state[1] = v - 40
        elif 100 <= v <= 107:
            state[1] = 8 + v - 100
        elif v == 49:
            state[1] = None
        elif v in (38, 48) and i + 2 < len(values):
            target = 0 if v == 38 else 1
            mode = values[i + 1]
            if mode == 5:
                if 0 <= values[i + 2] <= 255:
                    state[target] = values[i + 2]
                i += 2
            elif mode == 2 and i + 4 < len(values):
                rgb = values[i + 2:i + 5]
                if all(0 <= c <= 255 for c in rgb):
                    state[target] = _rgb_to_xterm(*rgb)
                i += 4
        i += 1

def _style(text, color, bold=False):
    if not _COLOR:
        return text
    return f"\033[{1 if bold else 0};{_ANSI_COLORS.get(color, '97')}m{text}\033[0m"


def _put(y, x, text, attr=0, limit=None):
    """Draw in bounded cells, protecting curses' lower-right corner."""
    if _SCREEN is None:
        return
    height, width = _SCREEN.getmaxyx()
    if y < 0 or y >= height or x >= width - 1 or x < 0:
        return
    available = min(width - 1 - x, limit if limit is not None else width)
    fragment = _take_width(str(text).replace("\n", " "), available)
    try:
        _SCREEN.addstr(y, x, fragment, attr)
    except (curses.error, ValueError):
        pass


def _pin_layout(limit):
    """Return (left_width, border_x, right_x, right_width), or None."""
    if not _PIN_VISIBLE or limit < 94:
        return None
    side = min(_PIN_DESIRED_WIDTH, max(26, limit - 60))
    border = limit - side - 2
    if border < 58:
        return None
    return border, border + 1, border + 3, side - 1


def _pin_rows(width):
    """Wrap pinned text while preserving safe inline ANSI SGR color styles.

    Returns rows of (text, fg-index-or-None, bg-index-or-None, bold, fallback).
    """
    global _PIN_ROWS_CACHE
    width = max(6, width)
    key = (_PIN_TEXT, width)
    if _PIN_ROWS_CACHE[0] == key:
        return _PIN_ROWS_CACHE[1]
    if not _PIN_TEXT:
        rows = [[("Nothing pinned yet", None, None, False, "muted")]]
        _PIN_ROWS_CACHE = (key, rows)
        return rows
    rows = []
    state = [None, None, None]  # foreground, background, bold
    for original in _PIN_TEXT.split("\n"):
        visible = _ANSI_RE.sub("", original).strip()
        heading = visible.startswith("#")
        fallback = "cyan" if heading else "green" if visible.startswith(("- ", "* ", "• ")) else "blue"
        default_bold = heading
        # Preserve the previous Markdown-heading display, when no ANSI markup.
        if heading and not _SGR_RE.search(original):
            original = original.lstrip().lstrip("#").strip()
        current = []
        current_width = 0
        def flush():
            nonlocal current, current_width
            rows.append(current)
            current = []
            current_width = 0
        at = 0
        for match in _SGR_RE.finditer(original):
            plain = original[at:match.start()]
            for ch in plain:
                cw = _cw(ch)
                if current_width + cw > width and current:
                    flush()
                style = (state[0], state[1], default_bold if state[2] is None else state[2], fallback)
                if current and current[-1][1:] == style:
                    current[-1] = (current[-1][0] + ch, *style)
                else:
                    current.append((ch, *style))
                current_width += cw
            _apply_sgr(match.group(1), state)
            at = match.end()
        for ch in original[at:]:
            cw = _cw(ch)
            if current_width + cw > width and current:
                flush()
            style = (state[0], state[1], default_bold if state[2] is None else state[2], fallback)
            if current and current[-1][1:] == style:
                current[-1] = (current[-1][0] + ch, *style)
            else:
                current.append((ch, *style))
            current_width += cw
        flush()
    _PIN_ROWS_CACHE = (key, rows)
    return rows


def _read_pin_file(force=False):
    """Notice external updates (e.g. an agent-created tool), even during inference."""
    global _PIN_TITLE, _PIN_TEXT, _PIN_TIME, _PIN_SCROLL, _PIN_MTIME
    try:
        stat = _PIN_FILE.stat()
        if stat.st_size > 1024 * 1024:
            return
        stamp = (stat.st_mtime_ns, stat.st_size)
        if not force and stamp == _PIN_MTIME:
            return
        data = json.loads(_PIN_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        title = _clean(data.get("title", "PINNED"))[:64].replace("\n", " ").strip()
        message = _clean_sgr(data.get("text", ""))[:_PIN_MAX_CHARS]
        when = _clean(data.get("updated_at", ""))[:40].replace("\n", " ")
        if (title, message, when) != (_PIN_TITLE, _PIN_TEXT, _PIN_TIME):
            _PIN_SCROLL = 0
        _PIN_TITLE, _PIN_TEXT, _PIN_TIME = title or "PINNED", message, when
        _PIN_MTIME = stamp
    except (OSError, ValueError, TypeError):
        pass


def pin(text, title="PINNED"):
    """Pin display-only information, keeping it visible across log events/restarts.

    This is UI state, NOT an agent-memory or conversation mutation.
    """
    global _PIN_TITLE, _PIN_TEXT, _PIN_TIME, _PIN_SCROLL, _PIN_MTIME
    message = _clean_sgr(text)[:_PIN_MAX_CHARS]
    with _LOCK:
        _PIN_TITLE = _clean(title).replace("\n", " ")[:64] or "PINNED"
        _PIN_TEXT = message
        _PIN_TIME = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _PIN_SCROLL = 0
        record = {"title": _PIN_TITLE, "text": _PIN_TEXT, "updated_at": _PIN_TIME}
        temp = _PIN_FILE.with_name(_PIN_FILE.name + f".{os.getpid()}.tmp")
        try:
            temp.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, _PIN_FILE)
            stat = _PIN_FILE.stat()
            _PIN_MTIME = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        if _ACTIVE:
            _render()


def clear_pin():
    """Clear the persistent display panel."""
    pin("", "PINNED")


def _paint_line(y, bg, foreground="white"):
    h, w = _SCREEN.getmaxyx()
    if 0 <= y < h:
        _put(y, 0, " " * (w - 1), _attr(bg))


def _init_curses():
    global _SCREEN, _ACTIVE, _INPUT_THREAD
    if not _TUI_REQUESTED or curses is None:
        return False
    try:
        _SCREEN = curses.initscr()
        curses.noecho()
        curses.cbreak()
        _SCREEN.keypad(True)
        _SCREEN.nodelay(True)
        try:
            curses.curs_set(1)
        except curses.error:
            pass
        if curses.has_colors() and _COLOR:
            _PIN_ANSI_PAIRS.clear()
            global _PIN_PAIR_NEXT
            _PIN_PAIR_NEXT = len(_PALETTE) + 1
            _COLOR_PAIRS.clear()
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                pass
            for index, (name, (c256, c8)) in enumerate(_PALETTE.items(), 1):
                try:
                    curses.init_pair(index, c256 if curses.COLORS >= 256 else c8, -1)
                    _COLOR_PAIRS[name] = index
                except curses.error:
                    pass
        _ACTIVE = True
        _render()
        _INPUT_THREAD = threading.Thread(target=_input_loop, daemon=True, name="iter-terminal-input")
        _INPUT_THREAD.start()
        return True
    except BaseException:
        _restore_terminal()
        return False


def _restore_terminal():
    global _ACTIVE, _SCREEN, _SHUTDOWN
    with _LOCK:
        if _SCREEN is None:
            return
        _SHUTDOWN = True
        _ACTIVE = False
        try:
            _SCREEN.keypad(False)
            curses.nocbreak()
            curses.echo()
            curses.endwin()
        except curses.error:
            pass
        _SCREEN = None


atexit.register(_restore_terminal)


def terminal_ui_active():
    """True when the persistent input bar owns terminal stdin."""
    return _ACTIVE


def poll_input():
    """Return next completed terminal line, or empty string (nonblocking)."""
    try:
        return _INPUT_QUEUE.get_nowait()
    except queue.Empty:
        return ""


def _input_loop():
    """Nonblocking keyboard reader: survives long LLM/tool network requests."""
    global _PHASE
    last_tick = 0
    while not _SHUTDOWN:
        key = None
        with _LOCK:
            if not _ACTIVE:
                break
            try:
                key = _SCREEN.get_wch()
            except curses.error:
                pass
            if key is not None:
                _handle_key(key)
            now = time.monotonic()
            if key is not None or now - last_tick >= 0.35:
                _render()
                last_tick = now
        time.sleep(0.025 if key is not None else 0.06)


def _handle_key(key):
    global _COMPOSER, _CURSOR, _SCROLL, _HISTORY_INDEX, _PIN_VISIBLE, _PIN_SCROLL
    if isinstance(key, str):
        if key in ("\n", "\r"):
            message = _COMPOSER.strip()
            if message:
                _INPUT_QUEUE.put(message)
                _HISTORY.append(message)
                if len(_HISTORY) > 200:
                    del _HISTORY[0]
                # The queued text also appears in the log, without waiting for
                # the agent to finish its current inference.
                _ROWS.append((_time_label(), "QUEUED", message, "yellow", False))
                _SCROLL = 0
            _COMPOSER, _CURSOR, _HISTORY_INDEX = "", 0, None
        elif key in ("\x7f", "\b", "\x08"):
            if _CURSOR:
                _COMPOSER = _COMPOSER[:_CURSOR-1] + _COMPOSER[_CURSOR:]
                _CURSOR -= 1
        elif key == "\x15":  # Ctrl-U: clear composer
            _COMPOSER, _CURSOR = "", 0
        elif key == "\x01":  # Ctrl-A: start of input
            _CURSOR = 0
        elif key == "\x05":  # Ctrl-E: end of input
            _CURSOR = len(_COMPOSER)
        elif key == "\x0c":  # Ctrl-L: redraw
            _SCREEN.clear()
        elif key.isprintable():
            _COMPOSER = _COMPOSER[:_CURSOR] + key + _COMPOSER[_CURSOR:]
            _CURSOR += 1
    elif key in (curses.KEY_BACKSPACE,):
        if _CURSOR:
            _COMPOSER = _COMPOSER[:_CURSOR-1] + _COMPOSER[_CURSOR:]
            _CURSOR -= 1
    elif key == curses.KEY_DC:
        _COMPOSER = _COMPOSER[:_CURSOR] + _COMPOSER[_CURSOR+1:]
    elif key == curses.KEY_LEFT:
        _CURSOR = max(0, _CURSOR - 1)
    elif key == curses.KEY_RIGHT:
        _CURSOR = min(len(_COMPOSER), _CURSOR + 1)
    elif key == curses.KEY_HOME:
        _CURSOR = 0
    elif key == curses.KEY_END:
        _CURSOR = len(_COMPOSER)
    elif key == curses.KEY_UP:
        if _HISTORY:
            _HISTORY_INDEX = len(_HISTORY) - 1 if _HISTORY_INDEX is None else max(0, _HISTORY_INDEX - 1)
            _COMPOSER = _HISTORY[_HISTORY_INDEX]
            _CURSOR = len(_COMPOSER)
    elif key == curses.KEY_DOWN:
        if _HISTORY_INDEX is not None:
            _HISTORY_INDEX += 1
            if _HISTORY_INDEX >= len(_HISTORY):
                _HISTORY_INDEX = None
                _COMPOSER = ""
            else:
                _COMPOSER = _HISTORY[_HISTORY_INDEX]
            _CURSOR = len(_COMPOSER)
    elif key == curses.KEY_F2:
        _PIN_VISIBLE = not _PIN_VISIBLE
    elif key == curses.KEY_F3:
        _PIN_SCROLL = max(0, _PIN_SCROLL - max(3, _SCREEN.getmaxyx()[0] // 2))
    elif key == curses.KEY_F4:
        _PIN_SCROLL += max(3, _SCREEN.getmaxyx()[0] // 2)
    elif key == curses.KEY_PPAGE:
        _SCROLL += max(3, _SCREEN.getmaxyx()[0] - 10)
    elif key == curses.KEY_NPAGE:
        _SCROLL = max(0, _SCROLL - max(3, _SCREEN.getmaxyx()[0] - 10))
    elif key == curses.KEY_RESIZE:
        try:
            curses.update_lines_cols()
        except curses.error:
            pass


def _visual_rows(width):
    """Render event records as colored visual lines, preserving hard breaks."""
    rows = []
    body_width = max(6, width - 21)
    for stamp, name, message, color, detail in _ROWS:
        chunks = _wrap(message, body_width)
        for i, chunk in enumerate(chunks):
            rows.append((stamp if i == 0 and not detail else "",
                         name if i == 0 else "", chunk, color, detail, i != 0))
    return rows


def _render():
    if not _ACTIVE or _SCREEN is None:
        return
    height, width = _SCREEN.getmaxyx()
    if height < 9 or width < 38:
        _SCREEN.erase()
        _put(0, 0, "ITER · enlarge terminal to at least 38×9", _attr("yellow", True))
        _SCREEN.refresh()
        return
    limit = min(width - 1, _MAX_WIDTH)
    _read_pin_file()
    layout = _pin_layout(limit)
    left_width = layout[0] if layout else limit
    _SCREEN.erase()

    # Header: permanently visible, with contextual inference state.
    _put(0, 1, "◈  I T E R", _attr("red", True))
    _put(0, 15, "// AUTONOMOUS CONSOLE", _attr("muted"))
    phase = _PHASE
    if phase == "THINKING":
        phase = f"THINKING {time.monotonic() - _PHASE_START:.0f}s"
    phase_color = "violet" if _PHASE == "THINKING" else "green" if _PHASE == "READY" else "yellow"
    _put(0, max(35, limit - len(phase) - 3), phase, _attr(phase_color, True))
    _put(1, 2, f"MODEL  {_MODEL}", _attr("blue"), max(5, limit - 27))
    _put(1, max(2, limit - 22), f"SESSION {_SESSION[:8]}", _attr("muted"))
    _put(2, 0, "─" * limit, _attr("cyan"))

    # Log pane: content as well as labels is colored, according to event kind.
    top, bottom = 3, height - 5
    available = bottom - top + 1
    visual = _visual_rows(left_width)
    max_scroll = max(0, len(visual) - available)
    scroll = min(_SCROLL, max_scroll)
    end = max(0, len(visual) - scroll)
    begin = max(0, end - available)
    for y, (stamp, name, body, color, detail, continuation) in enumerate(visual[begin:end], top):
        _put(y, 1, stamp, _attr("muted"))
        if name:
            marker = "┆" if detail else "◆"
            _put(y, 11, marker, _attr(color, True))
            _put(y, 13, name[:8].ljust(8), _attr(color, True))
        elif continuation:
            _put(y, 11, "│", _attr("muted"))
        _put(y, 22, body, _attr(color, False), max(1, left_width - 22))

    # Right-hand pinned panel, wholly independent of scrolling event rows.
    if layout:
        _, border_x, right_x, right_width = layout
        for y in range(3, bottom + 1):
            _put(y, border_x, "│", _attr("muted"))
        _put(3, right_x, "◈ PINNED // " + _PIN_TITLE, _attr("cyan", True), right_width)
        _put(4, right_x, (_PIN_TIME or "Awaiting ui_panel"), _attr("muted"), right_width)
        _put(5, right_x, "─" * right_width, _attr("muted"), right_width)
        content_top = 6
        content_height = max(0, bottom - content_top + 1)
        lines = _pin_rows(max(6, right_width - 1))
        max_pin_scroll = max(0, len(lines) - content_height)
        # F3 = up, F4 = down. New panel updates reset scroll to the top.
        pin_scroll = min(_PIN_SCROLL, max_pin_scroll)
        for i, segments in enumerate(lines[pin_scroll:pin_scroll + content_height]):
            x = right_x
            for body, fg, bg, bold, fallback in segments:
                _put(content_top + i, x, body, _sgr_attr(fg, bg, bold, fallback),
                     max(0, right_width - (x - right_x)))
                x += sum(_cw(ch) for ch in body)
        if max_pin_scroll:
            progress = f"{pin_scroll + 1}-{min(len(lines), pin_scroll + content_height)}/{len(lines)}"
            _put(bottom, max(right_x, limit - len(progress) - 1), progress, _attr("yellow"))

    # Dedicated composer below log: never overwritten by output.
    _put(height-4, 0, "─" * limit, _attr("cyan"))
    _put(height-3, 2, "MESSAGE  ❯", _attr("cyan", True))
    _put(height-3, 17, "Enter send · ↑↓ history · PgUp/PgDn logs · F2 panel · F3/F4 panel scroll",
         _attr("muted"), max(1, limit - 17))
    _put(height-2, 2, "❯", _attr("yellow", True))
    composer_width = max(1, limit - 6)
    start = 0
    # Horizontal scrolling keeps the insertion cursor visible.
    while sum(_cw(c) for c in _COMPOSER[start:_CURSOR]) > composer_width - 1:
        start += 1
    shown = _take_width(_COMPOSER[start:], composer_width)
    _put(height-2, 5, shown, _attr("yellow", True), composer_width)
    if not _COMPOSER:
        _put(height-2, 5, "Type while Iter runs…", _attr("muted"), composer_width)
    cursor_x = 5 + sum(_cw(c) for c in _COMPOSER[start:_CURSOR])
    _put(height-1, 2, f"● ONLINE  |  {len(_INPUT_QUEUE.queue)} pending",
         _attr("green"))
    if scroll:
        _put(height-1, max(30, limit - 20), f"↑ {scroll} lines above", _attr("yellow"))
    else:
        _put(height-1, max(30, limit - 21), _time_label(), _attr("muted"))
    try:
        _SCREEN.move(height-2, min(cursor_x, limit - 1))
    except curses.error:
        pass
    _SCREEN.refresh()


def _append(label, message, color="muted", detail=False):
    global _SCROLL
    message = _clean(message)
    with _LOCK:
        _ROWS.append((_time_label(), str(label).upper(), message, color, detail))
        if _ACTIVE:
            _render()
        else:
            _print_event(label, message, color, detail)


def _print_event(label, message, color, detail=False):
    """Streaming fallback for non-interactive terminals and redirected stdout."""
    width = min(_MAX_WIDTH, max(40, shutil.get_terminal_size(fallback=(100, 24)).columns))
    prefix = (" " * 12 if detail else f"{_time_label()}  ") + f"{label.upper():<9} "
    for index, part in enumerate(_wrap(message, width - len(prefix) - 1)):
        leader = prefix if index == 0 else " " * len(prefix)
        sys.stdout.write(_style(leader + part, color, bold=False) + "\n")
    sys.stdout.flush()


def _phase(phase):
    global _PHASE, _PHASE_START
    with _LOCK:
        _PHASE = phase
        _PHASE_START = time.monotonic()


def header(model, session_id, history_count):
    global _MODEL, _SESSION
    _MODEL, _SESSION = str(model), str(session_id)
    with _LOCK:
        _read_pin_file(force=True)
        if _init_curses():
            _ROWS.append((_time_label(), "SYSTEM", f"Ready · {history_count} history messages · input active", "cyan", False))
            _render()
        else:
            _print_event("ITER", f"{model} · session {str(session_id)[:8]} · {history_count} messages", "cyan")
            _print_event("NOTICE", "Classic streaming mode (no fixed input bar)", "yellow")


def tool_call(name, args, ret, failed):
    if name == "send":
        _append("SEND", name, "cyan")
        msg = _send_message(args)
        if msg is not None:
            _append("MESSAGE", _clip(msg, TERMINAL_SEND_CHARS), "cyan", True)
    else:
        _append("TOOL", name, "pink")
        _append("ARGS", _arguments_display(name, args), "violet", True)
    if ret is not None and str(ret) not in ("", "None"):
        _append("ERROR" if failed else "RESULT", _clip(ret, TERMINAL_RESULT_CHARS), "red" if failed else "green", True)
    elif failed:
        _append("ERROR", "Tool failed", "red", True)


def llm_start():
    _phase("THINKING")
    _append("INFER", "Generating tool calls", "violet")


def llm_complete(duration, response):
    _phase("READY")
    usage = getattr(response, "usage", None)
    tokens = ""
    if usage is not None:
        in_tokens = getattr(usage, "prompt_tokens", None)
        out_tokens = getattr(usage, "completion_tokens", None)
        if in_tokens is not None or out_tokens is not None:
            tokens = f" · tokens {in_tokens or '?'}→{out_tokens or '?'}"
    try:
        calls = len(response.choices[0].message.tool_calls or [])
    except (AttributeError, IndexError, TypeError):
        calls = 0
    _append("LLM ✓", f"{duration:.1f}s{tokens} · {calls} tool call(s)", "blue")


def wait(seconds):
    _phase("WAITING")
    _append("STANDBY", f"Checking for input for up to {seconds}s", "muted")


def incoming(message):
    _phase("READY")
    _append("INPUT", _clip(message, TERMINAL_INPUT_CHARS), "cyan")


def status(message):
    _append("STATUS", _clip(message, TERMINAL_INPUT_CHARS), "muted")


def warning(label, message):
    _append(label, _clip(message, TERMINAL_INPUT_CHARS), "yellow")


def error(label, message):
    _append(label, _clip(message, TERMINAL_RESULT_CHARS), "red")


def failure(message):
    _phase("ERROR")
    _append("FAILURE", _clip(message, TERMINAL_RESULT_CHARS), "red")


def retry(message):
    _append("RETRY", _clip(message, TERMINAL_RESULT_CHARS), "yellow")


def stopped():
    _append("OFFLINE", "Iter stopped", "muted")
    _restore_terminal()
    sys.stdout.write("\nIter stopped.\n")
    sys.stdout.flush()
