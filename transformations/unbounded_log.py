"""
Unbounded Output Log — appends each message to a file exactly once.
Excludes control messages injected by iter.py (not starting with [ — they start with "Step <timestamp>: [CONTROL...").
State = SHA-256 hashes of current context window messages only.
"""
import os, hashlib

DESCRIPTION = "Unbounded output log: append all messages to a queryable file."
LOG_PATH = os.path.expanduser("~/iter/unbounded_log.txt")
STATE_PATH = os.path.expanduser("~/iter/.log_state")

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
        with open(LOG_PATH, "a") as f:
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if not isinstance(content, str) or not content.strip():
                    continue
                # Exclude control messages — they start with "Step <ts>: [CONTROL..."
                if role == "user" and _is_control(content):
                    continue
                h = _h(content)
                current_hashes.add(h)
                if h not in prev_hashes:
                    f.write(f"[{role}] {content}\n")

        with open(STATE_PATH, "w") as f:
            for h in current_hashes:
                f.write(h + "\n")
    except Exception:
        pass
    return messages, tools
