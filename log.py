"""Compact ANSI terminal UI for Iter. No agent state or history is modified here."""

import datetime
import json
import os
import re
import shutil
import sys
import textwrap

# Terminal display settings affect ONLY logging, not agent history or tool returns.
TERMINAL_INPUT_CHARS = int(os.getenv("ITER_INPUT_CHARS", "1200"))
TERMINAL_ARGS_CHARS = int(os.getenv("ITER_ARGS_CHARS", "240"))
TERMINAL_RESULT_CHARS = int(os.getenv("ITER_RESULT_CHARS", "260"))
TERMINAL_SEND_CHARS = int(os.getenv("ITER_SEND_CHARS", "2000"))

# --------------------------------------------------------------------
# 0a. Compact POSIX / ANSI terminal UI:
# --------------------------------------------------------------------
_USE_COLOR = ((sys.stdout.isatty() and os.getenv("TERM", "") != "dumb")
              or os.getenv("FORCE_COLOR") == "1") and "NO_COLOR" not in os.environ

class C:
    RESET = "\033[0m" if _USE_COLOR else ""
    BOLD = "\033[1m" if _USE_COLOR else ""
    DIM = "\033[2m" if _USE_COLOR else ""
    CYAN = "\033[36m" if _USE_COLOR else ""
    GREEN = "\033[32m" if _USE_COLOR else ""
    YELLOW = "\033[33m" if _USE_COLOR else ""
    RED = "\033[31m" if _USE_COLOR else ""
    MAGENTA = "\033[35m" if _USE_COLOR else ""
    BLUE = "\033[34m" if _USE_COLOR else ""

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _clean(value):
    """Neutralize control sequences from models, channels, and tool output."""
    value = str(value)
    return _CONTROL_RE.sub("", _ANSI_RE.sub("", value)).replace("\r", "")


def _clip(value, max_chars):
    value = _clean(value).strip()
    if max_chars >= 0 and len(value) > max_chars:
        return value[:max_chars].rstrip() + f" … [display clipped, {len(value)} chars]"
    return value


def _time_label():
    return datetime.datetime.now().strftime("%H:%M:%S")


def _width():
    return max(65, min(shutil.get_terminal_size(fallback=(110, 24)).columns, 180))


def _write(kind, line, color="", indent=False):
    """Consistent timestamped prefix; multi-line content wraps at terminal width."""
    prefix = f"{_time_label()}  {kind:<8} " if not indent else " " * 19
    available = max(25, _width() - len(prefix) - 2)
    lines = _clean(line).splitlines() or [""]
    for paragraph_index, paragraph in enumerate(lines):
        wrapped = textwrap.wrap(paragraph, width=available,
                                break_long_words=True, break_on_hyphens=False,
                                replace_whitespace=False, drop_whitespace=False) or [""]
        for i, part in enumerate(wrapped):
            leader = prefix if not indent and paragraph_index == 0 and i == 0 else " " * len(prefix)
            print(f"{C.DIM}{leader[:8]}{C.RESET}{color}{leader[8:]}{part}{C.RESET}", flush=True)


def _line(kind, message, color=""):
    _write(kind, message, color)


def _detail(message, color=""):
    _write("", message, color, indent=True)


def _status(message):
    _line("·", message, C.DIM)


def _arguments_display(tool_name, args):
    if not isinstance(args, dict):
        return _clip(args, TERMINAL_ARGS_CHARS)
    summary = dict(args)
    if tool_name == "send":
        for key in ("message", "text", "content"):
            if key in summary:
                summary[key] = "<shown below>"
    return _clip(json.dumps(summary, ensure_ascii=False, separators=(", ", ": "), default=str),
                 TERMINAL_ARGS_CHARS)


def _send_message(args):
    if not isinstance(args, dict):
        return None
    for key in ("message", "text", "content"):
        if key in args and args[key] is not None:
            return str(args[key])
    return None


def tool_call(name, args, ret, failed):
    _line("TOOL →", f"{name}  {_arguments_display(name, args)}", C.MAGENTA)
    if name == "send":
        msg = _send_message(args)
        if msg is not None:
            _detail("MESSAGE: " + _clip(msg, TERMINAL_SEND_CHARS), C.CYAN + C.BOLD)
    if ret and ret != "None":
        _detail(("ERROR: " if failed else "RESULT: ") +
                _clip(ret, TERMINAL_RESULT_CHARS), C.RED if failed else C.GREEN)
    elif failed:
        _detail("ERROR: tool failed", C.RED)


def llm_complete(duration, response):
    usage = response.usage
    usage_str = ""
    if usage is not None:
        in_tok = getattr(usage, "prompt_tokens", None)
        out_tok = getattr(usage, "completion_tokens", None)
        if in_tok is not None or out_tok is not None:
            usage_str = f"  tokens {in_tok if in_tok is not None else '?'}→{out_tok if out_tok is not None else '?'}"
    calls = len(response.choices[0].message.tool_calls or [])
    _line("LLM ✓", f"{duration:.1f}s{usage_str}  ·  {calls} tool call(s)", C.BLUE)


def wait(seconds):
    _line("IDLE", f"Waiting up to {seconds}s for input", C.DIM)


def header(model, session_id, history_count):
    bar = "─" * min(_width() - 2, 100)
    print(f"\n{C.BOLD}{C.CYAN}ITER{C.RESET}  {C.DIM}{model}{C.RESET}")
    print(f"{C.DIM}{bar}{C.RESET}", flush=True)
    _status(f"session {session_id[:8]}  ·  {history_count} history messages  ·  Ctrl-C to exit")

def incoming(message):
    _line("INPUT ◀", _clip(message, TERMINAL_INPUT_CHARS), C.CYAN + C.BOLD)


def status(message):
    _status(message)


def warning(label, message):
    _line(label, message, C.YELLOW)


def error(label, message):
    _line(label, _clip(message, TERMINAL_RESULT_CHARS), C.RED)


def failure(message):
    _line("ERROR !", _clip(message, TERMINAL_RESULT_CHARS), C.RED + C.BOLD)


def llm_start():
    _line("LLM …", "Generating tool calls", C.DIM)


def retry(message):
    _line("RETRY", message, C.YELLOW)


def stopped():
    print(f"\n{C.DIM}ITER stopped.{C.RESET}", flush=True)
