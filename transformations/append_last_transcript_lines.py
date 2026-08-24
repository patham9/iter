"""
Append last 6 transcript lines to the system message.
Reads ~/iter/transcript.txt, takes last 6 lines, appends them
after a "transcript:" header to the first message (system message) content.
"""
import os

DESCRIPTION = "Append last 6 transcript lines to system message."

TRANSCRIPT_PATH = os.path.expanduser("~/iter/transcript.txt")
NUM_LINES = 6

def transform(messages, tools):
    try:
        if not messages:
            return messages, tools

        # Read last N lines from transcript file
        if not os.path.exists(TRANSCRIPT_PATH):
            return messages, tools

        with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

        last_lines = lines[-NUM_LINES:] if len(lines) >= NUM_LINES else lines
        transcript_block = "transcript:\n" + "".join(last_lines).rstrip()

        # Find first message (system message) and append
        first_msg = messages[0]
        if isinstance(first_msg, dict):
            content = first_msg.get("content", "")
            if isinstance(content, str):
                first_msg["content"] = content.rstrip() + "\n\n" + transcript_block
            elif isinstance(content, list):
                # Handle list-style content (some APIs use parts)
                # Append as a new text part
                first_msg["content"] = content + [{"type": "text", "text": "\n\n" + transcript_block}]

    except Exception:
        pass

    return messages, tools
