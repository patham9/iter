"""
Transcript — persists all textual communication messages (user + assistant send)
to a queryable file. Excludes control messages injected by iter.py.
State = SHA-256 hashes of current context window messages only.
Pruning is automatic: messages that scroll out of context can never reappear.
"""
import os, json, hashlib

DESCRIPTION = "Maintains transcript of textual communication messages only."
LOG_PATH = os.path.expanduser("~/iter/transcript.txt")
STATE_PATH = os.path.expanduser("~/iter/.transcript_state")

# Control message patterns from iter.py — these are injected as user messages
# but are NOT real user communication. They all appear after "Step <timestamp>: "
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

def _h(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def _is_control(content):
    """Check if a user message is a control message injected by iter.py."""
    return any(p in content for p in CONTROL_PATTERNS)

def transform(messages, tools):
    try:
        prev_hashes = set()
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH) as f:
                prev_hashes = set(l.strip() for l in f if l.strip())

        current_hashes = set()
        lines_to_write = []

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if role == "user" and isinstance(content, str) and content.strip():
                # Exclude control messages from iter.py
                if _is_control(content):
                    continue
                h = _h(content)
                current_hashes.add(h)
                if h not in prev_hashes:
                    lines_to_write.append(content)

            elif role == "assistant":
                # Log all send tool calls — these are real communication
                for tc in (msg.get("tool_calls", []) if isinstance(msg, dict) else []):
                    if isinstance(tc, dict):
                        fn = tc.get("function", {})
                        if fn.get("name") == "send":
                            try:
                                args = json.loads(fn.get("arguments", "{}"))
                                line = f"[send -> {args.get('channel', '')}] {args.get('content', '')}"
                                h = _h(line)
                                current_hashes.add(h)
                                if h not in prev_hashes:
                                    lines_to_write.append(line)
                            except (json.JSONDecodeError, KeyError):
                                pass

        if lines_to_write:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                for line in lines_to_write:
                    f.write(line + "\n")

        with open(STATE_PATH, "w") as f:
            for h in current_hashes:
                f.write(h + "\n")

    except Exception:
        pass
    return messages, tools
