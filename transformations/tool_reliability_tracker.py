import json
import re
import shutil
from pathlib import Path

DESCRIPTION = "Tracks reliability of tools"

ROOT = Path(__file__).resolve().parent.parent

# Canonical reliability state lives here.
RUNTIME_DIR = ROOT / "transformations" / ".runtime"
RELIABILITY_FILE = RUNTIME_DIR / "tool_reliability.json"

def nal_revise(f1, c1, f2, c2):
    """NAL truth revision formula."""
    w1 = c1 / (1 - c1) if c1 < 1.0 else 1e10
    w2 = c2 / (1 - c2) if c2 < 1.0 else 1e10
    f_new = (w1 * f1 + w2 * f2) / (w1 + w2)
    c_new = (w1 + w2) / (w1 + w2 + 1)
    return round(f_new, 4), round(c_new, 4)

def update_reliability(tool_name, success):
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    # Load only from the protected runtime copy.
    if RELIABILITY_FILE.exists():
        try:
            with open(RELIABILITY_FILE, "r") as f:
                scores = json.load(f)
        except (json.JSONDecodeError, IOError):
            return
    else:
        scores = {}
    if tool_name not in scores:
        scores[tool_name] = {
            "f": 0.5,
            "c": 0.0,
            "calls": 0,
            "successes": 0,
            "failures": 0,
        }
    s = scores[tool_name]
    calls = s.get("calls", 0)
    if calls < 1:
        if success:
            s["f"] = 1.0
            s["c"] = 0.5
        else:
            s["f"] = 0.0
            s["c"] = 0.5
    else:
        obs_f = 1.0 if success else 0.0
        new_f, new_c = nal_revise(s["f"], s["c"], obs_f, 0.5)
        s["f"] = new_f
        s["c"] = new_c
    s["calls"] = calls + 1
    if success:
        s["successes"] = s.get("successes", 0) + 1
    else:
        s["failures"] = s.get("failures", 0) + 1
    scores[tool_name] = s
    try:
        # Write authoritative copy.
        with open(RELIABILITY_FILE, "w") as f:
            json.dump(scores, f, indent=2)
        # Mirror it into memory/config for the agent to see.
    except IOError:
        pass

# Use regex patterns for error detection - match error words as standalone tokens
# not as substrings of larger words (e.g., "failed" should not match "failures" column header)
ERROR_PATTERNS = [
    re.compile(r'\berror\b', re.IGNORECASE),
    re.compile(r'\btraceback\b', re.IGNORECASE),
    re.compile(r'\bexception\b', re.IGNORECASE),
    re.compile(r'\bnot found\b', re.IGNORECASE),
    re.compile(r'\binvalid\b', re.IGNORECASE),
    re.compile(r'\bfailed\b', re.IGNORECASE),
    re.compile(r'\btimed out\b', re.IGNORECASE),
    re.compile(r'\bTIMEOUT\b'),
]

def has_error(content):
    for pattern in ERROR_PATTERNS:
        if pattern.search(content):
            return True
    return False

def transform(messages, tools):
    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if not content:
            continue
        tool_call_id = msg.get("tool_call_id", "")
        if not tool_call_id:
            continue
        for j in range(i):
            prev = messages[j]
            if prev.get("role") != "assistant":
                continue
            for tc in prev.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    if tool_name:
                        success = not has_error(content)
                        update_reliability(tool_name, success)
                    break
    return messages, tools
