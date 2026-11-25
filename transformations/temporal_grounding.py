"""
Temporal Grounding Transformation

Injects the current date/time into the system message so the agent
can resolve relative time references (today, yesterday, etc.)
without conscious lookup. Lean: just the timestamp. Everything else
is derived through reasoning when needed.
"""
import datetime
from pathlib import Path

DESCRIPTION = "Temporal grounding: injects current date/time so relative references (today, yesterday, etc.) resolve automatically."


def _ord(n):
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def briefing(now=None):
    """Build the temporal context block — lean: just today."""
    now = now or datetime.datetime.utcnow()
    today = now.strftime("%A, %B %d{} %Y".format(_ord(now.day)))
    return f"=== TEMPORAL CONTEXT ({now.strftime('%H:%M UTC')}) ===\nToday: {today}"


def transform(messages, tools):
    try:
        if messages and isinstance(messages[0], dict):
            content = messages[0].get("content", "")
            if isinstance(content, str):
                messages[0]["content"] = content.rstrip() + "\n\n" + briefing()
    except Exception:
        pass
    return messages, tools
