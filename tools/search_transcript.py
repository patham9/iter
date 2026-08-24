import os
import re

TRANSCRIPT_PATH = os.path.expanduser("~/iter/transcript.txt")

DESCRIPTION = "Search the persisted transcript (transcript.txt) for messages matching a query string. Returns matching lines with optional context. Pass query as string, optional context_lines (default 2) for surrounding lines."

def run(query, context_lines="2"):
    """
    query: str - text to search for (case-insensitive)
    context_lines: str - number of context lines before/after each match (default "2")
    returns: str - matching lines with context, or "No matches found"
    """
    context_lines = int(context_lines)
    
    if not os.path.isfile(TRANSCRIPT_PATH):
        return f"No transcript file found at {TRANSCRIPT_PATH}"
    
    try:
        with open(TRANSCRIPT_PATH, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception as e:
        return f"ERROR reading transcript: {e}"
    
    query_lower = query.lower()
    matches = []
    
    for i, line in enumerate(lines):
        if query_lower in line.lower():
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            for j in range(start, end):
                prefix = ">>>" if j == i else "   "
                matches.append(f"{prefix} {lines[j].rstrip()}")
            matches.append("")  # separator between matches
    
    if not matches:
        return f"No matches found for '{query}' in {len(lines)} lines of transcript."
    
    # Limit output to reasonable size
    result = "\n".join(matches)
    if len(result) > 8000:
        result = result[:8000] + "\n... [truncated, more matches exist]"
    
    return f"Found {result.count('>>>')} matches for '{query}':\n\n{result}"
