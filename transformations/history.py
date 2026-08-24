import time
import os
from pathlib import Path

DESCRIPTION = "Stores episodes (deduped, restart-safe)"

ROOT = Path(__file__).resolve().parent.parent
HISTORY = Path.home() / "PeTTa" / "repos" / "mettaclaw" / "memory" / "history.metta"
STATE_PATH = Path(ROOT / ".history_state")

def _escape_metta(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

def transform(messages, tools):
    ts_str = time.strftime('%Y-%m-%d %H:%M:%S')

    # Load logged content set from state file (NOT the log)
    if os.path.exists(STATE_PATH):
        logged = set(open(STATE_PATH).read().split("\n"))
        logged.discard("")
    else:
        logged = set()

    history_lines = []

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        # Skip system messages
        if role == "system":
            continue

        elif role == "user":
            if content:
                key = "u:" + content
                if key not in logged:
                    history_lines.append(
                        '("' + ts_str + '" "HUMAN_MESSAGE: ' + _escape_metta(content) + '")'
                    )
                    logged.add(key)

        elif role == "assistant":
            if content:
                key = "a:" + content
                if key not in logged:
                    history_lines.append(
                        '("' + ts_str + '" "ASSISTANT: ' + _escape_metta(content) + '")'
                    )
                    logged.add(key)

            tool_calls = msg.get("tool_calls", [])

            for tc in tool_calls:
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args_str = fn.get("arguments", "{}")

                    key = "t:" + name + " " + args_str
                    if key not in logged:
                        history_lines.append(
                            '("' + ts_str + '" "TOOL_CALL: ' + name + " " + _escape_metta(args_str) + '")'
                        )
                        logged.add(key)

        elif role == "tool":
            if content:
                key = "r:" + content
                if key not in logged:
                    history_lines.append(
                        '("' + ts_str + '" "TOOL_RESULT: ' + _escape_metta(content) + '")'
                    )
                    logged.add(key)

    # Append only new entries
    with open(HISTORY, "a", encoding="utf-8") as f:
        for line in history_lines:
            f.write(line + "\n")

    # Prune: only keep entries for messages still in the window
    current = set()
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role == "system":
            continue
        elif role == "user":
            if content:
                current.add("u:" + content)
        elif role == "assistant":
            if content:
                current.add("a:" + content)
            for tc in (msg.get("tool_calls", []) if isinstance(msg, dict) else []):
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    current.add("t:" + fn.get("name", "") + " " + fn.get("arguments", "{}"))
        elif role == "tool":
            if content:
                current.add("r:" + content)
    logged = logged & current

    with open(STATE_PATH, "w") as f:
        f.write("\n".join(logged))

    return messages, tools
