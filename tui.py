"""Iter terminal console: persistent input + color-coded live events.

Linux/Unix interactive TTY: curses full-screen display with a fixed input bar,
scrollable output, and an asynchronous input queue. Works in screen/tmux/SSH.
The log supports mouse-wheel scrolling, a clickable/draggable in-pane scrollbar,
and PageUp/PageDown. Mouse support depends on terminal and multiplexer settings.
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



def _clip_split(text):
    """Split text at the clip marker. Return (main, marker) or (text, None)."""
    idx = text.find(" … [display clipped")
    if idx < 0:
        return text, None
    return text[:idx], text[idx:]

def _disp_width(text):
    """Return the display width of text (accounting for wide chars)."""
    return sum(_cw(c) for c in text)

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
    """Return the FULL (unclipped) args display string."""
    if not isinstance(args, dict):
        return str(args)
    obj = dict(args)
    if name == "send":
        for key in ("message", "text", "content"):
            if key in obj:
                obj[key] = "<shown below>"
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "), default=str)


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
_LOG_DRAGGING = False                # dragging the log's own scrollbar
_SELECTING = False                   # dragging in log area to select text
_SEL_START = None                    # (visual_row, col) of selection start
_SEL_END = None                      # (visual_row, col) of selection end
_ROW_COUNTER = 0                       # unique ID per _ROWS entry
_EXPANDED = set()                     # set of expanded row IDs (clipped → full)
_MOUSE_SCROLL_LINES = 3
_SHUTDOWN = False
_COLOR_PAIRS = {}
_PIN_TITLE = "PINNED"
_PIN_TEXT = ""
_PIN_TIME = ""
_PIN_SCROLL = 0
_PIN_MTIME = None
_PIN_VISIBLE = _PIN_PANEL
_PIN_RESIZING = False
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
            mouse_events = (getattr(curses, "BUTTON4_PRESSED", 0) |
                            getattr(curses, "BUTTON5_PRESSED", 0) |
                            curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED |
                            curses.BUTTON1_CLICKED |
                            getattr(curses, "BUTTON1_MOVED", 0) |
                            getattr(curses, "BUTTON3_CLICKED", 0) |
                            getattr(curses, "REPORT_MOUSE_POSITION", 0))
            curses.mousemask(mouse_events)
            curses.mouseinterval(0)
            # Explicitly enable button-event tracking ([?1002h) so the
            # terminal reports mouse position continuously while a button is
            # held — not only on press/release.  GNOME Terminal and many
            # others need this even when curses.mousemask includes
            # REPORT_MOUSE_POSITION.
            try:
                sys.stdout.write('[?1002h'); sys.stdout.flush()
            except Exception:
                pass
        except (curses.error, AttributeError):
            pass  # PageUp/PageDown always work when mouse reporting is unavailable.
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
            sys.stdout.write('[?1002l')
            sys.stdout.flush()
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


def _scroll_thumb(total_rows, visible_rows, scroll):
    """Scrollbar thumb (height, zero-based top) for a bottom-relative scroll offset."""
    if total_rows <= visible_rows or visible_rows <= 0:
        return visible_rows, 0
    max_scroll = total_rows - visible_rows
    thumb_height = max(1, min(visible_rows, visible_rows * visible_rows // total_rows))
    travel = visible_rows - thumb_height
    thumb_top = round((max_scroll - min(max(0, scroll), max_scroll)) * travel / max_scroll)
    return thumb_height, thumb_top

def _paste_from_clipboard():
    """Read system clipboard via tkinter (lazy import; no third-party deps)."""
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        return text
    except Exception:
        return None

def _handle_mouse():
    """Wheel scrolls the pane under the pointer; click/drag the log scrollbar."""
    global _SCROLL, _PIN_SCROLL, _LOG_DRAGGING, _COMPOSER, _CURSOR
    global _SELECTING, _SEL_START, _SEL_END, _EXPANDED
    global _PIN_RESIZING, _PIN_DESIRED_WIDTH
    try:
        _id, x, y, _z, buttons = curses.getmouse()
    except curses.error:
        return
    height, width = _SCREEN.getmaxyx()
    if height < 9 or width < 38:
        return
    limit = min(width - 1, _MAX_WIDTH)
    layout = _pin_layout(limit)
    left_width = layout[0] if layout else limit
    top, bottom = 3, height - 5
    visible = bottom - top + 1
    log_total = len(_visual_rows(left_width - 2))
    log_max = max(0, log_total - visible)
    over_panel = bool(layout and x >= layout[2] and top <= y <= bottom)
    wheel_up = bool(buttons & getattr(curses, "BUTTON4_PRESSED", 0))
    wheel_down = bool(buttons & getattr(curses, "BUTTON5_PRESSED", 0))

    if wheel_up or wheel_down:
        step = _MOUSE_SCROLL_LINES if wheel_up else -_MOUSE_SCROLL_LINES
        if over_panel:
            pin_height = max(0, bottom - 6 + 1)
            pin_total = len(_pin_rows(max(6, layout[3] - 1)))
            _PIN_SCROLL = max(0, min(max(0, pin_total - pin_height), _PIN_SCROLL + step))
        else:
            _SCROLL = max(0, min(log_max, _SCROLL + step))
        return

    on_bar = x == left_width - 1 and top <= y <= bottom
    on_sep = bool(layout and x == layout[1] and top <= y <= bottom)
    pressed = bool(buttons & curses.BUTTON1_PRESSED)
    clicked = bool(buttons & curses.BUTTON1_CLICKED)
    released = bool(buttons & curses.BUTTON1_RELEASED)
    moved = bool(buttons & getattr(curses, "REPORT_MOUSE_POSITION", 0))
    # Drag the separator to resize the pinned panel width.
    if (pressed or clicked) and on_sep:
        _PIN_RESIZING = pressed
    if _PIN_RESIZING and (moved or released):
        new_side = limit - x - 1
        _PIN_DESIRED_WIDTH = max(26, min(limit - 62, new_side))
    if released:
        _PIN_RESIZING = False
    if (pressed or clicked) and on_bar:
        _LOG_DRAGGING = pressed
    if (pressed or clicked) and on_bar or _LOG_DRAGGING and (moved or released):
        thumb_height, _ = _scroll_thumb(log_total, visible, _SCROLL)
        travel = visible - thumb_height
        if travel and log_max:
            position = max(0, min(travel, y - top - (thumb_height - 1) / 2))
            _SCROLL = round(log_max * (1 - position / travel))
        else:
            _SCROLL = 0
    if released:
        _LOG_DRAGGING = False


    # Left-click in log area: start text selection (character-level).
    in_log = (top <= y <= bottom and 22 <= x < left_width - 1
              and not on_bar and not over_panel)
    if pressed and in_log and not _SELECTING:
        _SELECTING = True
        log_total = len(_visual_rows(left_width - 2))
        _scroll = min(_SCROLL, max(0, log_total - visible))
        _end = max(0, log_total - _scroll)
        _begin = max(0, _end - visible)
        _row = _begin + (y - top)
        _col = max(0, x - 22)
        _SEL_START = (_row, _col)
        _SEL_END = (_row, _col)
    # Live drag: while selecting, ANY mouse event updates the selection end.
    # We do NOT require pressed/moved/released bits because many terminals
    # (GNOME Terminal) send position-only events during drag with no button
    # state bits set.
    if _SELECTING and not released:
        log_total2 = len(_visual_rows(left_width - 2))
        _scroll2 = min(_SCROLL, max(0, log_total2 - visible))
        _end2 = max(0, log_total2 - _scroll2)
        _begin2 = max(0, _end2 - visible)
        # Clamp coordinates to the log pane so dragging outside still works.
        clamped_y = max(top, min(bottom, y))
        clamped_x = max(22, min(left_width - 2, x))
        _row2 = _begin2 + (clamped_y - top)
        _col2 = max(0, clamped_x - 22)
        _SEL_END = (_row2, _col2)
    if released and _SELECTING:
        # Simple click (no drag) on an expandable row: toggle expansion.
        if _SEL_START == _SEL_END:
            log_total_r = len(_visual_rows(left_width - 2))
            _scroll_r = min(_SCROLL, max(0, log_total_r - visible))
            _end_r = max(0, log_total_r - _scroll_r)
            _begin_r = max(0, _end_r - visible)
            _vrow_r = _begin_r + (y - top)
            visual_r = _visual_rows(left_width - 2)
            if 0 <= _vrow_r < len(visual_r):
                _rid = visual_r[_vrow_r][6]
                _ftext = visual_r[_vrow_r][7]
                if _ftext is not None and _rid:
                    if _rid in _EXPANDED:
                        _EXPANDED.discard(_rid)
                    else:
                        _EXPANDED.add(_rid)
                    _SEL_START, _SEL_END = None, None
                    _SELECTING = False
                    _render()
                    return
        _SELECTING = False
    # Click outside log without drag: clear selection.
    if pressed and not in_log and not on_bar and not over_panel and y < height - 5:
        _SEL_START, _SEL_END = None, None

    # Right-click: copy selection in log, or paste into composer.
    right_clicked = bool(buttons & getattr(curses, "BUTTON3_CLICKED", 0))
    if right_clicked and y == height - 2:
        text = _paste_from_clipboard()
        if text:
            global _COMPOSER, _CURSOR
            text = text.strip("")
            _COMPOSER = _COMPOSER[:_CURSOR] + text + _COMPOSER[_CURSOR:]
            _CURSOR += len(text)
    elif right_clicked and top <= y <= bottom:
        sel = _sel_text()
        if sel:
            _copy_to_clipboard(sel)
            _SEL_START, _SEL_END = None, None
            _SELECTING = False

def _handle_key(key):
    global _COMPOSER, _CURSOR, _SCROLL, _HISTORY_INDEX, _PIN_VISIBLE, _PIN_SCROLL
    if key == curses.KEY_MOUSE:
        _handle_mouse()
        return
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
                _ROWS.append((_time_label(), "QUEUED", message, "yellow", False, 0, None))
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



def _sel_text():
    """Return selected text (character-level), or ''."""
    if _SEL_START is None or _SEL_END is None:
        return ""
    if _SCREEN is None:
        return ""
    height, width = _SCREEN.getmaxyx()
    limit = min(width - 1, _MAX_WIDTH)
    layout = _pin_layout(limit)
    lw = layout[0] if layout else limit
    visual = _visual_rows(lw - 2)
    sr, sc = _SEL_START
    er, ec = _SEL_END
    if (sr, sc) > (er, ec):
        sr, sc, er, ec = er, ec, sr, sc
    text_parts = []
    for i in range(sr, er + 1):
        if 0 <= i < len(visual):
            body = visual[i][2]
            if i == sr and i == er:
                text_parts.append(body[sc:ec])
            elif i == sr:
                text_parts.append(body[sc:])
            elif i == er:
                text_parts.append(body[:ec])
            else:
                text_parts.append(body)
    return "\n".join(text_parts)


def _copy_to_clipboard(text):
    """Write *text* to the system clipboard via tkinter."""
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
    except Exception:
        pass


def _visual_rows(width):
    """Render event records as colored visual lines, preserving hard breaks."""
    rows = []
    body_width = max(6, width - 21)
    for stamp, name, message, color, detail, row_id, full_text in _ROWS:
        text = full_text if full_text is not None and row_id in _EXPANDED else message
        chunks = _wrap(text, body_width)
        for i, chunk in enumerate(chunks):
            rows.append((stamp if i == 0 and not detail else "",
                         name if i == 0 else "", chunk, color, detail, i != 0,
                         row_id, full_text))
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
    _put(0, 1, "◈  I T E R", _attr("pink", True))
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
    visual = _visual_rows(left_width - 2)
    max_scroll = max(0, len(visual) - available)
    scroll = min(_SCROLL, max_scroll)
    end = max(0, len(visual) - scroll)
    begin = max(0, end - available)
    for y, (stamp, name, body, color, detail, continuation, _rid, _ftext) in enumerate(visual[begin:end], top):
        _put(y, 1, stamp, _attr("muted"))
        if name:
            marker = "┆" if detail else "◆"
            _put(y, 11, marker, _attr(color, True))
            _put(y, 13, name[:8].ljust(8), _attr(color, True))
        elif continuation:
            _put(y, 11, "│", _attr("muted"))
        # Highlight selected characters with reverse video.
        vis_idx = begin + (y - top)
        body_attr = _attr(color, False)
        if _SEL_START is not None and _SEL_END is not None:
            sr, sc = _SEL_START
            er, ec = _SEL_END
            if (sr, sc) > (er, ec):
                sr, sc, er, ec = er, ec, sr, sc
            max_col = min(len(body), left_width - 23)
            if sr <= vis_idx <= er:
                if vis_idx == sr and vis_idx == er:
                    c1, c2 = min(sc, ec), max(sc, ec)
                    c1 = min(c1, max_col)
                    c2 = min(c2, max_col)
                    _put(y, 22, body[:c1], body_attr, max(1, left_width - 23))
                    if c2 > c1:
                        _put(y, 22 + c1, body[c1:c2], body_attr | curses.A_REVERSE, max(1, left_width - 23 - c1))
                    _put(y, 22 + c2, body[c2:], body_attr, max(1, left_width - 23 - c2))
                elif vis_idx == sr:
                    c1 = min(sc, max_col)
                    _put(y, 22, body[:c1], body_attr, max(1, left_width - 23))
                    _put(y, 22 + c1, body[c1:], body_attr | curses.A_REVERSE, max(1, left_width - 23 - c1))
                elif vis_idx == er:
                    c2 = min(ec, max_col)
                    _put(y, 22, body[:c2], body_attr | curses.A_REVERSE, max(1, left_width - 23))
                    _put(y, 22 + c2, body[c2:], body_attr, max(1, left_width - 23 - c2))
                else:
                    _put(y, 22, body, body_attr | curses.A_REVERSE, max(1, left_width - 23))
            else:
                _put(y, 22, body, body_attr, max(1, left_width - 23))
        else:
            marker_idx = body.find(" … [display clipped")
            if marker_idx >= 0:
                main = body[:marker_idx]
                marker = body[marker_idx:]
                w = _disp_width(main)
                _put(y, 22, main, body_attr, max(1, left_width - 23))
                _put(y, 22 + w, marker, _attr("lime", False), max(1, left_width - 23 - w))
            else:
                _put(y, 22, body, body_attr, max(1, left_width - 23))

    # Native terminal scrollback does not cover curses' fullscreen buffer.
    # Draw a scrollbar that controls this pane's real scroll offset instead.
    if max_scroll:
        thumb_height, thumb_top = _scroll_thumb(len(visual), available, scroll)
        for i in range(available):
            selected = thumb_top <= i < thumb_top + thumb_height
            _put(top + i, left_width - 1, "┃" if selected else "│",
                 _attr("cyan" if selected else "muted"))

    # Right-hand pinned panel, wholly independent of scrolling event rows.
    if layout:
        _, border_x, right_x, right_width = layout
        sep_attr = _attr("cyan", True) if _PIN_RESIZING else _attr("muted")
        for y in range(3, bottom + 1):
            _put(y, border_x, "│", sep_attr)
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
    _put(height-3, 17, "Enter send · ↑↓ history · Wheel/PgUp/PgDn logs · F2 panel · F3/F4 panel scroll · Left-drag select · Drag separator resize · Right-click copy/paste",
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


def _append(label, message, color="muted", detail=False, full_text=None):
    global _SCROLL, _ROW_COUNTER
    message = _clean(message)
    with _LOCK:
        if _ACTIVE and _SCROLL > 0 and _SCREEN is not None:
            height, width = _SCREEN.getmaxyx()
            limit = min(width - 1, _MAX_WIDTH)
            layout = _pin_layout(limit)
            left_width = layout[0] if layout else limit
            _SCROLL += len(_wrap(message, max(6, left_width - 23)))
        _ROW_COUNTER += 1
        _ROWS.append((_time_label(), str(label).upper(), message, color, detail, _ROW_COUNTER, full_text))
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
        marker_idx = part.find(" … [display clipped")
        if marker_idx >= 0:
            main = part[:marker_idx]
            marker = part[marker_idx:]
            sys.stdout.write(_style(leader + main, color, bold=False))
            sys.stdout.write(_style(marker, "lime", bold=False) + "\n")
        else:
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
            _ROWS.append((_time_label(), "SYSTEM", f"Ready · {history_count} history messages · input active", "cyan", False, 0, None))
            _render()
        else:
            _print_event("ITER", f"{model} · session {str(session_id)[:8]} · {history_count} messages", "cyan")
            _print_event("NOTICE", "Classic streaming mode (no fixed input bar)", "yellow")


def tool_call(name, args, ret, failed):
    if name == "send":
        _append("SEND", name, "cyan")
        msg = _send_message(args)
        if msg is not None:
            clipped = _clip(msg, TERMINAL_SEND_CHARS)
            _append("MESSAGE", clipped, "cyan", True,
                    full_text=str(msg) if "display clipped" in clipped else None)
    else:
        _append("TOOL", name, "pink")
        args_full = _arguments_display(name, args)
        args_clipped = _clip(args_full, TERMINAL_ARGS_CHARS)
        _append("ARGS", args_clipped, "violet", True,
                full_text=args_full if "display clipped" in args_clipped else None)
    if ret is not None and str(ret) not in ("", "None"):
        clipped = _clip(ret, TERMINAL_RESULT_CHARS)
        _append("ERROR" if failed else "RESULT", clipped,
                "red" if failed else "green", True,
                full_text=str(ret) if "display clipped" in clipped else None)
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
            tokens = f" · tokens {in_tokens or '?'} → {out_tokens or '?'}"
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
    sys.stdout.write("\nIter stopped!\n")
    sys.stdout.flush()
