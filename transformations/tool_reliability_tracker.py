import json
import re
import os
import tempfile
from pathlib import Path

DESCRIPTION = "Tracks reliability of tools"

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT / "transformations" / ".runtime"
RELIABILITY_FILE = RUNTIME_DIR / "tool_reliability.json"

ERROR_RE = re.compile(r"\b(error|traceback|exception|not found|invalid|failed|timed out|TIMEOUT)\b", re.IGNORECASE)

def nal_revise(f1, c1, f2, c2):
    w1 = c1 / (1 - c1) if c1 < 1.0 else 1e10
    w2 = c2 / (1 - c2) if c2 < 1.0 else 1e10
    t = w1 + w2
    return round((w1*f1+w2*f2)/t, 4), round(t/(t+1), 4)

def transform(messages, tools):
    # Only look at last 50 messages to avoid timeout
    recent = messages[-50:]
    
    # Quick scan: are there any tool results?
    has_tool_results = any(m.get("role") == "tool" for m in recent)
    if not has_tool_results:
        return messages, tools
    
    # Build call_id -> name map from last 50 messages only
    call_map = {}
    for m in recent:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls", []):
            if isinstance(tc, dict):
                tid = tc.get("id", "")
                nm = tc.get("function", {}).get("name", "")
                if tid and nm:
                    call_map[tid] = nm
    
    # Collect updates
    updates = []
    for m in recent:
        if m.get("role") != "tool":
            continue
        c = m.get("content", "")
        if not c:
            continue
        tid = m.get("tool_call_id", "")
        if not tid:
            continue
        nm = call_map.get(tid)
        if nm:
            ok = not bool(ERROR_RE.search(c))
            updates.append((nm, ok))
    
    if not updates:
        return messages, tools
    
    # Load once
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    scores = {}
    try:
        txt = RELIABILITY_FILE.read_text().strip()
        if txt:
            scores = json.loads(txt)
    except Exception:
        scores = {}
    
    for nm, ok in updates:
        if nm not in scores:
            scores[nm] = {"f": 0.5, "c": 0.0, "calls": 0, "successes": 0, "failures": 0}
        s = scores[nm]
        n = s.get("calls", 0)
        if n < 1:
            s["f"] = 1.0 if ok else 0.0
            s["c"] = 0.5
        else:
            nf, nc = nal_revise(s["f"], s["c"], 1.0 if ok else 0.0, 0.5)
            s["f"] = nf; s["c"] = nc
        s["calls"] = n + 1
        if ok: s["successes"] = s.get("successes", 0) + 1
        else: s["failures"] = s.get("failures", 0) + 1
    
    # Write once atomically
    try:
        fd, tmp = tempfile.mkstemp(dir=str(RUNTIME_DIR), suffix=".json.tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(scores, f, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, str(RELIABILITY_FILE))
    except Exception:
        try: os.unlink(tmp)
        except: pass
    
    return messages, tools
