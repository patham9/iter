"""
Person Context Transformation

Detects who sent the most recent message and injects their preferred
address style into the system message before each model call.

For Kevin Binder:
  - Reads current X-rank from memory/people/kevin_binder_rank.txt
  - Injects "Address this user as X{rank}" and "Use lowercase register."

For others:
  - No special injection (standard capitalization, normal name)

The rank files are updated by the agent (not this transformation) when
a person provides tier 1 (+1) or tier 2 (+0.5) input.
"""
import os
import re
from pathlib import Path

DESCRIPTION = "Injects sender's preferred address style into system message."

ROOT = Path(__file__).resolve().parent.parent
RANK_FILES = {
    "kevin binder": ROOT / "memory" / "people" / "kevin_binder_rank.txt",
}

# Pattern to detect sender from iter.py user messages:
# "Step 2026-10-08 19:09:40: [mattermost] [2026-10-08 19:09:24] <Kevin Binder> ..."
SENDER_PATTERN = re.compile(r'<([^>]+)>')


def _detect_sender(messages):
    """Scan user messages from newest to oldest for a <Name> sender pattern."""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        # Look for the <Sender Name> pattern in the message
        match = SENDER_PATTERN.search(content)
        if match:
            return match.group(1).strip()
    return None


def _read_rank(rank_file):
    """Read a rank value from a state file."""
    try:
        if rank_file.exists():
            val = rank_file.read_text().strip()
            rank = float(val)
            if rank == int(rank):
                return str(int(rank))
            return str(rank)
    except Exception:
        pass
    return None


def transform(messages, tools):
    try:
        if not messages:
            return messages, tools

        sender = _detect_sender(messages)
        if not sender:
            return messages, tools

        # Build the context injection based on sender
        injection = None
        sender_lower = sender.lower()

        if "kevin binder" in sender_lower:
            rank = _read_rank(RANK_FILES["kevin binder"])
            if rank is None:
                rank = "29"
            injection = (
                f"PERSON CONTEXT: The user who sent the most recent message is {sender}. "
                f"Address this user as X{rank}. Use lowercase register in your response. "
                f"Artifacts (files, code, formal outputs) should still use proper capitalization."
            )
        # Add more people here as needed

        if injection:
            # Append to the first message (system message)
            first_msg = messages[0]
            if isinstance(first_msg, dict):
                content = first_msg.get("content", "")
                if isinstance(content, str):
                    first_msg["content"] = content.rstrip() + "\n\n" + injection
                elif isinstance(content, list):
                    first_msg["content"] = content + [{"type": "text", "text": "\n\n" + injection}]

    except Exception:
        pass

    return messages, tools
