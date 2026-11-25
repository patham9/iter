import time
import json
import hashlib
from pathlib import Path

DESCRIPTION = 'Transcript: appends new user messages and own actions/sends (deduplicated) as timestamped lines to ~/iter/transcript.txt (read by search_transcript and warmstart_briefing).'

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPT = ROOT / "transcript.txt"
DEDUP_FILE = ROOT / ".transcript_dedup"

def _content_hash(line):
    """Hash only the content part (after timestamp) so identical messages
    at different times get the same hash and are properly deduplicated."""
    # Lines look like: [2026-11-10 23:24:09] [send -> mattermost] <content>
    # or: [2026-11-10 23:24:09] <user content>
    # Strip the leading [timestamp] to get the content portion
    import re
    stripped = re.sub(r'^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*', '', line)
    return hashlib.sha256(stripped.encode("utf-8", errors="replace")).hexdigest()

def transform(messages, tools):
    ts_str = time.strftime('%Y-%m-%d %H:%M:%S')

    # Load existing hashes
    seen_hashes = set()
    if DEDUP_FILE.exists():
        try:
            with open(DEDUP_FILE, "r", encoding="utf-8", errors="replace") as f:
                seen_hashes = set(line.strip() for line in f if line.strip())
        except Exception:
            seen_hashes = set()

    transcript_lines = []

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "user" and content:
            if any(tag in content for tag in [
                "[irc]",
                "[ALARM]",
                "[NO ADDITIONAL",
                "[TASK COMPLETED",
                "[mattermost]",
                "[terminal]"
            ]):
                transcript_lines.append(f"[{ts_str}] {content}")

        elif role == "assistant":
            tool_calls = msg.get("tool_calls", [])

            for tc in tool_calls:
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    name = fn.get("name", "")

                    if name == "send":
                        try:
                            args = json.loads(fn.get("arguments", "{}"))
                            ch = args.get("channel", "")
                            txt = args.get("content", "")
                            transcript_lines.append(f"[{ts_str}] [send -> {ch}] {txt.replace(chr(10), chr(32))}")
                        except (json.JSONDecodeError, KeyError):
                            pass

    # Filter out already-written lines using content hash (excludes timestamp)
    unique_lines = []
    new_hashes = []
    for line in transcript_lines:
        h = _content_hash(line)
        if h not in seen_hashes:
            seen_hashes.add(h)
            new_hashes.append(h)
            unique_lines.append(line)

    # APPEND only unique lines
    if unique_lines:
        with open(TRANSCRIPT, "a", encoding="utf-8") as f:
            for line in unique_lines:
                f.write(line + "\n")

    # Persist updated hash set
    if new_hashes:
        with open(DEDUP_FILE, "a", encoding="utf-8") as f:
            for h in new_hashes:
                f.write(h + "\n")

    return messages, tools
