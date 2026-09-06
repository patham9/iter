"""Recall the supersession-resolved PeTTa journal view (read-only)."""
import importlib.util
from pathlib import Path

DESCRIPTION = "Recall the resolved PeTTa journal view (read-only). Optional arg: limit (int, default 20)."

def _journal():
    p = Path(__file__).resolve().parent.parent / "_petta_journal.py"
    spec = importlib.util.spec_from_file_location("_petta_journal", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def run(limit=20):
    j = _journal()
    try:
        limit = int(limit)
    except Exception:
        limit = 20
    r = j.recall(limit=limit)
    return "\n".join(r.get("view", [])) if r.get("ok") else "FAIL"
