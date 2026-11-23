"""
Skills Transformation (tier 2 of the context: the skills index)

Indexes files under ./skills/ by path and first-line DESCRIPTION only,
and appends the index to the system message. Moved out of the iter core;
tier 1 (memory/ and its character limit) stays in the core.
"""
import os
import re
from pathlib import Path

DESCRIPTION = "Skills index: appends ./skills/ files (path + first-line DESCRIPTION, _-prefixed parts exempt) to the system message, max MAX_SKILLS."

MAX_SKILLS = int(os.getenv("MAX_SKILLS", "30"))


def load_skills():
    """Index Markdown skills by their path and first-line DESCRIPTION only."""
    Path("skills").mkdir(exist_ok=True)
    paths = [path for path in sorted(Path("skills").rglob("*"))
             if path.is_file() and not any(part.startswith("_") for part in path.relative_to("skills").parts)]
    entries = []
    for path in paths[:MAX_SKILLS]:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as file:
                first_line = file.readline().strip()
            description = (first_line if re.fullmatch(r'DESCRIPTION="(?:[^"\\]|\\.)*"', first_line)
                           else "[DESCRIPTION FIRST LINE MISSING]")
        except OSError as error:
            description = f"[READ ERROR: {type(error).__name__}: {error}]"
        entries.append(f"./{path.as_posix()}: {description}")
    return "./skills/:\n" + "\n".join(entries), max(0, len(paths) - MAX_SKILLS)


def transform(messages, tools):
    skills, omitted = load_skills()
    if messages and isinstance(messages[0], dict) and isinstance(messages[0].get("content"), str):
        messages[0]["content"] = messages[0]["content"] + "\n\n" + skills
    if omitted > 0:
        messages.append({"role": "user", "content": f"[SKILL LIMIT REACHED: {omitted} Markdown skills are omitted. Consolidate or remove skills if they are needed.]"})
    return messages, tools
