import json
import re
import os



def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _mkdirs(path):
    current = ""
    for part in str(path).split("/"):
        if not part:
            current = "/" if not current else current
            continue
        current = (current.rstrip("/") + "/" + part) if current else part
        try:
            os.mkdir(current)
        except OSError:
            pass

DESCRIPTION = "Tracks reliability of tools"

ROOT = "/work/iter"
RUNTIME_DIR = ROOT + "/transformations/.runtime"
RELIABILITY_FILE = RUNTIME_DIR + "/tool_reliability.json"
STATE_FILE = RUNTIME_DIR + "/tool_reliability_state.txt"

def nal_revise(f1, c1, f2, c2):
    w1 = c1 / (1 - c1) if c1 < 1.0 else 1e10
    w2 = c2 / (1 - c2) if c2 < 1.0 else 1e10
    f_new = (w1 * f1 + w2 * f2) / (w1 + w2)
    c_new = (w1 + w2) / (w1 + w2 + 1)
    return round(f_new, 4), round(c_new, 4)

def update_reliability(tool_name, success):
    try:
        _mkdirs(RUNTIME_DIR)
    except OSError:
        pass
    if _exists(RELIABILITY_FILE):
        try:
            with open(RELIABILITY_FILE, "r") as f:
                scores = json.loads(f.read())
        except Exception:
            return
    else:
        scores = {}
    if tool_name not in scores:
        scores[tool_name] = {"f": 0.5, "c": 0.0, "calls": 0, "successes": 0, "failures": 0}
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
        with open(RELIABILITY_FILE, "w") as f:
            f.write(json.dumps(scores))
    except Exception:
        pass

ERROR_KEYWORDS = [
    "error", "traceback", "exception", "not found",
    "invalid", "failed", "timed out", "timeout"
]

def has_error(content):
    lower = content.lower()
    for kw in ERROR_KEYWORDS:
        if kw in lower:
            return True
    return False

def transform(messages, tools):
    try:
        with open(STATE_FILE, "r") as file:
            previous_ids = set(line.strip() for line in file if line.strip())
    except Exception:
        previous_ids = set()

    current_ids = set()
    for i in range(len(messages)):
        msg = messages[i]
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if not content:
            continue
        tool_call_id = msg.get("tool_call_id", "")
        if not tool_call_id:
            continue
        current_ids.add(tool_call_id)
        if tool_call_id in previous_ids:
            continue
        for j in range(i):
            prev = messages[j]
            if not isinstance(prev, dict):
                continue
            if prev.get("role") != "assistant":
                continue
            tcs = prev.get("tool_calls", [])
            for tc in tcs:
                if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")
                    if tool_name:
                        success = not has_error(content)
                        update_reliability(tool_name, success)
                    break

    try:
        _mkdirs(RUNTIME_DIR)
    except OSError:
        pass
    try:
        with open(STATE_FILE, "w") as file:
            file.write("\n".join(current_ids))
    except Exception:
        pass
    return messages, tools
