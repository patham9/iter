"""
Unbounded Output Log - appends each message to a file exactly once.
Excludes control messages injected by iter.py.
State = string keys of current context window messages only (like history.py).
"""
import os, json



def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False

DESCRIPTION = "Unbounded output log: append all messages to a queryable file."
LOG_PATH = "/work/iter/unbounded_log.txt"
STATE_PATH = "/work/iter/.log_state"

CONTROL_PATTERNS = [
    "[NO ADDITIONAL",
    "[TASK COMPLETED",
    "[NO NEW USER",
    "[TOOL LIMIT",
    "[MEMORY FOLDER",
    "[OUTPUT TOKEN",
    "[YOUR PREVIOUS",
    "[NOT DELIVERED",
    "[ALARM]",
]

def _is_control(content):
    return any(p in content for p in CONTROL_PATTERNS)

def transform(messages, tools):
    try:
        prev_keys = set()
        if _exists(STATE_PATH):
            with open(STATE_PATH) as f:
                prev_keys = set(l.strip() for l in f if l.strip())

        current_keys = set()
        with open(LOG_PATH, "a") as f:
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", "unknown")
                content = msg.get("content", "")

                # Log user messages (skip control messages)
                if role == "user":
                    if isinstance(content, str) and content.strip():
                        if _is_control(content):
                            continue
                        key = "u:" + content
                        current_keys.add(key)
                        if key not in prev_keys:
                            f.write("[user] " + content + "\n")

                # Log assistant text content
                elif role == "assistant":
                    if isinstance(content, str) and content.strip():
                        tool_ids = [str(tc.get("id", "")) for tc in msg.get("tool_calls", []) if isinstance(tc, dict)]
                        key = "a:" + ("|".join(tool_ids) if tool_ids else content)
                        current_keys.add(key)
                        if key not in prev_keys:
                            f.write("[assistant] " + content + "\n")

                    # Log send tool calls with their message content
                    for tc in (msg.get("tool_calls", []) if isinstance(msg, dict) else []):
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            name = fn.get("name", "")
                            args_str = fn.get("arguments", "{}")
                            if name == "send":
                                try:
                                    args = json.loads(args_str)
                                    line = "[send -> " + str(args.get("channel", "")) + "] " + str(args.get("message", ""))
                                    key = "s:" + str(tc.get("id", line))
                                    current_keys.add(key)
                                    if key not in prev_keys:
                                        f.write(line + "\n")
                                except:
                                    pass
                            else:
                                key = "t:" + str(tc.get("id", name + " " + args_str))
                                current_keys.add(key)
                                if key not in prev_keys:
                                    f.write("[tool_call] " + name + " " + args_str + "\n")

                # Log tool results
                elif role == "tool":
                    if isinstance(content, str) and content.strip():
                        key = "r:" + str(msg.get("tool_call_id", content[:200]))
                        current_keys.add(key)
                        if key not in prev_keys:
                            f.write("[tool_result] " + content[:500] + "\n")

        with open(STATE_PATH, "w") as f:
            for key in current_keys:
                f.write(key + "\n")
    except Exception:
        pass
    return messages, tools
