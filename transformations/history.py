import time
import hashlib
from pathlib import Path

DESCRIPTION = 'History: appends new conversation messages (deduplicated by content hash) as MeTTa atoms to monthly ~/PeTTa/repos/mettaclaw/memory/history_MM_YYYY.metta (read by episodes tool).'

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = Path.home() / "PeTTa" / "repos" / "mettaclaw" / "memory"
STATE_FILE = ROOT / "memory" / "_history_state"

def history_file(t=None):
    t = time.localtime() if t is None else t
    return HISTORY_DIR / time.strftime("history_%m_%Y.metta", t)

def _escape_metta(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

def _load_state():
    """Load the set of content hashes already written."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8", errors="replace") as f:
                return set(line.strip() for line in f if line.strip())
        except Exception:
            pass
    return set()

def _save_hash(h):
    """Append a hash to the state file."""
    with open(STATE_FILE, "a", encoding="utf-8") as f:
        f.write(h + "\n")

def _content_hash(role, content, ts_str):
    """Hash based on content only (not timestamp) so the same message
    at different steps won't be re-written."""
    key = f"{role}:{content}"
    return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()

def transform(messages, tools):
    ts_str = time.strftime('%Y-%m-%d %H:%M:%S')

    seen = _load_state()

    history_lines = []
    new_hashes = []

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "system":
            continue

        # Compute content-based hash (no timestamp) for dedup
        if content:
            h = _content_hash(role, content, ts_str)
            if h in seen:
                continue  # Already written — skip
            seen.add(h)
            new_hashes.append(h)

        if role == "user" and content:
            history_lines.append(
                '("' + ts_str + '" "HUMAN_MESSAGE: ' + _escape_metta(content) + '")'
            )

        elif role == "assistant":
            if content:
                history_lines.append(
                    '("' + ts_str + '" "ASSISTANT: ' + _escape_metta(content) + '")'
                )

            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args_str = fn.get("arguments", "{}")
                    # Dedup tool calls too
                    tc_key = f"tool_call:{name}:{args_str}"
                    tc_h = hashlib.sha256(tc_key.encode("utf-8", errors="replace")).hexdigest()
                    if tc_h in seen:
                        continue
                    seen.add(tc_h)
                    new_hashes.append(tc_h)
                    history_lines.append(
                        '("' + ts_str + '" "TOOL_CALL: ' + name + " " + _escape_metta(args_str) + '")'
                    )

        elif role == "tool" and content:
            history_lines.append(
                '("' + ts_str + '" "TOOL_RESULT: ' + _escape_metta(content) + '")'
            )

    # Append only new unique lines
    if history_lines:
        with open(history_file(), "a", encoding="utf-8") as f:
            for line in history_lines:
                f.write(line + "\n")

    # Persist hashes
    for h in new_hashes:
        _save_hash(h)

    return messages, tools
