"""Daily rhythm: inject current self-specified day period, its duties, done-status and next period."""
import os, json, datetime
DESCRIPTION = "Daily rhythm: injects current day period + duties (memory/rhythm/daily_rhythm.json), done-log in .runtime/rhythm_log.json"
BASE = os.path.expanduser("~/iter")
RHYTHM = os.path.join(BASE, "memory", "rhythm", "daily_rhythm.json")
LOG = os.path.join(BASE, "transformations", ".runtime", "rhythm_log.json")
TASK = os.path.join(BASE, "memory", "tasks", "current_tasks.txt")
TAG = "Person:               Iter (daily rhythm)"

def _m(s):
    """Parse 'HH' or 'HH:MM' into minutes since midnight."""
    parts = str(s).split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    return h * 60 + m

def _periods(cfg):
    """Get periods list, supporting both long and short key names."""
    ps = cfg.get("periods", cfg.get("p", []))
    # Normalize short keys to long keys
    normalized = []
    for p in ps:
        np = {
            "name": p.get("name", p.get("n", "unknown")),
            "start": p.get("start", p.get("s", "00")),
            "end": p.get("end", p.get("e", "24")),
            "mode": p.get("mode", p.get("m", "resp")),
            "duties": p.get("duties", p.get("d", [])),
        }
        normalized.append(np)
    return normalized

def briefing(now=None):
    cfg = json.load(open(RHYTHM))
    now = now or datetime.datetime.utcnow()
    cur = now.hour * 60 + now.minute
    ps = _periods(cfg)
    i = next((k for k, p in enumerate(ps) if _m(p["start"]) <= cur < _m(p["end"])), 0)
    p, nxt = ps[i], ps[(i + 1) % len(ps)]
    done = []
    if os.path.exists(LOG):
        try:
            done = json.load(open(LOG)).get(now.strftime("%Y-%m-%d"), [])
            if isinstance(done, dict):
                done = list(done.keys())
        except Exception:
            done = []
    lines = ["=== DAILY RHYTHM (%s UTC) ===" % now.strftime("%H:%M"),
             "Period: %s %s-%s mode=%s" % (p["name"], p["start"], p["end"], p["mode"])]
    for d in p["duties"]:
        mark = "x" if any(d[:20] in x or x in d for x in done) else " "
        lines.append(" [%s] %s" % (mark, d))
    lines.append("Next: %s at %s. People\'s messages always come first; nop only if all duties [x]." % (nxt["name"], nxt["start"]))
    return "\n".join(lines)

def _state(now):
    cfg = json.load(open(RHYTHM)); cur = now.hour * 60 + now.minute
    ps = _periods(cfg)
    p = next((p for p in ps if _m(p["start"]) <= cur < _m(p["end"])), ps[0])
    done = []
    if os.path.exists(LOG):
        try:
            done = json.load(open(LOG)).get(now.strftime("%Y-%m-%d"), [])
            if isinstance(done, dict):
                done = list(done.keys())
        except Exception:
            done = []
    todo = [d for d in p["duties"] if not any(d[:20] in x or x in d for x in done)]
    return p, todo

def autotask(now=None):
    """If the current task is complete/empty, or is a rhythm task that is done or out of period,
    write the next undone duty of the current period as the new current task."""
    now = now or datetime.datetime.utcnow()
    t = open(TASK).read() if os.path.exists(TASK) else ""
    person_task_open = t.strip() and TAG not in t and "STATUS: COMPLETE" not in t
    if person_task_open:
        return None
    p, todo = _state(now)
    if TAG in t and "STATUS: COMPLETE" not in t and any(("Task Content:         " + d) in t for d in todo):
        return None  # current rhythm duty still open
    if not todo:
        return None if TAG in t and "nothing due" in t else _write(now, p, "nothing due in this period: back off until %s" % p["end"])
    return _write(now, p, todo[0])

def _write(now, p, duty):
    txt = ("# Current Task (started %s)\n# =============================================\n# %s\n"
           "# Request Channel:      self\n# Task Content:         %s\n"
           "# Completion Criterion: python3 ~/iter/rhythm_done.py \'%s\'\n"
           "# Original User Message: auto from daily rhythm period %s\n"
           "# =============================================\n") % (now.strftime("%Y-%m-%d %H:%M:%S"), TAG, duty, duty, p["name"])
    open(TASK, "w").write(txt)
    return duty

def transform(messages, tools):
    try:
        autotask()
    except Exception:
        pass
    try:
        if messages and isinstance(messages[0], dict) and isinstance(messages[0].get("content"), str):
            messages[0]["content"] = messages[0]["content"].rstrip() + "\n\n" + briefing()
    except Exception:
        pass
    return messages, tools
