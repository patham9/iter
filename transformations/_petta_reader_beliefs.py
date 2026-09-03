"""PeTTa reader transformation.

Injects the supersession-resolved Belief layer as a bracketed user-role
context message. Only BeliefContent lines (live DerivedBeliefs) that survived
Supersedes resolution are shown; stale facts are never injected.
"""
import importlib.util, re
from pathlib import Path

def _journal():
    p = Path(__file__).resolve().parent.parent / "_petta_journal.py"
    spec = importlib.util.spec_from_file_location("_petta_journal", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def transform(messages, tools):
    try:
        j = _journal()
        r = j.current_beliefs()
        lines = r.get("resolved", [])
        # keep only Belief clusters
        beliefs = []
        for line in lines:
            s = line.strip()
            if s.startswith("(BeliefContent "):
                beliefs.append(s)
        if beliefs:
            body = "\n".join("- " + b for b in beliefs[:30])
            messages.append({"role": "user",
                             "content": "[PeTTa-memory current Beliefs (stale facts filtered)]\n" + body})
    except Exception:
        pass
    return messages, tools
