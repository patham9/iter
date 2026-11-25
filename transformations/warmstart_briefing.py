"""
Warmstart Briefing: inject recent cross-channel communication into system message.
(Current task is NOT injected here; memory/tasks/current_tasks.txt is already loaded as a memory file.)
Solves inter-cycle amnesia by ensuring each cycle wakes with context of what
was happening. Like a discrete simulator — the curve exists even if intermediate
points weren't computed. This transformation computes the next point.
"""
import os
import re

DESCRIPTION = "Inject warmstart briefing (recent communication across all channels, head+tail truncated) into system message."

BASE = os.path.expanduser("~/iter")
TASKS_PATH = os.path.join(BASE, "memory", "tasks", "current_tasks.txt")
TRANSCRIPT_PATH = os.path.join(BASE, "transcript.txt")
WARMSTART_PATH = os.path.join(BASE, "memory", "warmstart.md")
NUM_TRANSCRIPT_LINES = 12
HEAD_CHARS = 200
TAIL_CHARS = 200
# incoming: "Step <ts>: [channel] ..." with lowercase channel name (excludes NO ADDITIONAL / TASK COMPLETED / uppercase system prompts)
INCOMING_RE = re.compile(r"Step [0-9: -]+: \[[a-z][\w:.-]*\] ")

def _clip(l):
    if len(l) <= HEAD_CHARS + TAIL_CHARS + 20:
        return l
    return l[:HEAD_CHARS] + " [...] " + l[-TAIL_CHARS:]

def transform(messages, tools):
    try:
        if not messages:
            return messages, tools

        parts = []

        # Recent communication, all channels: incoming msgs + own sends
        if os.path.exists(TRANSCRIPT_PATH):
            with open(TRANSCRIPT_PATH, "rb") as f:
                f.seek(0, 2); size = f.tell()
                f.seek(max(0, size - 400000))
                lines = f.read().decode("utf-8", "ignore").splitlines()
            comm = [l for l in lines if "[send -> " in l or INCOMING_RE.search(l)]
            recent = [_clip(l) for l in comm[-NUM_TRANSCRIPT_LINES:]]
            if recent:
                parts.append("=== WARMSTART: RECENT COMMUNICATION (all channels) ===\n" + "\n".join(recent))

        if not parts:
            return messages, tools

        briefing = "\n\n".join(parts)

        first_msg = messages[0]
        if isinstance(first_msg, dict):
            content = first_msg.get("content", "")
            if isinstance(content, str):
                first_msg["content"] = content.rstrip() + "\n\n" + briefing
            elif isinstance(content, list):
                first_msg["content"] = content + [{"type": "text", "text": "\n\n" + briefing}]
    except Exception:
        pass

    return messages, tools
