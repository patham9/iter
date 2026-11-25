import re
from datetime import datetime
from pathlib import Path

DESCRIPTION = "Search transcript history for entries around a given timestamp. Returns surrounding context lines. Reads only the monthly file history_MM_YYYY.metta matching the queried time."

TS_RE = re.compile(r'^\("(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"')
HISTORY_DIR = Path.home() / "PeTTa" / "repos" / "mettaclaw" / "memory"
LEGACY = HISTORY_DIR / "history.metta"

def month_file(dt):
    return HISTORY_DIR / dt.strftime("history_%m_%Y.metta")

def extract_timestamp(line):
    m = TS_RE.search(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

def _scan(path, target, k):
    lines = []
    best_i = best_diff = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            lines.append(line[:500])
            ts = extract_timestamp(line)
            if ts is None:
                continue
            d = abs((ts - target).total_seconds())
            if best_diff is None or d < best_diff:
                best_diff, best_i = d, len(lines) - 1
    if best_i is None:
        return None
    lo, hi = max(0, best_i - k), min(len(lines), best_i + k + 1)
    return "".join(f"{i+1}:{lines[i]}" for i in range(lo, hi))

def _legacy_bsearch(path, target, k):
    # old months not yet split: binary search on the sorted legacy file (fast, no full scan)
    size = path.stat().st_size
    with open(path, "rb") as f:
        lo, hi = 0, size
        while hi - lo > 4096:
            mid = (lo + hi) // 2
            f.seek(mid); f.readline()
            ts = None
            for _ in range(50):
                raw = f.readline()
                if not raw:
                    break
                ts = extract_timestamp(raw.decode("utf-8", "replace"))
                if ts:
                    break
            if ts is None or ts >= target:
                hi = mid
            else:
                lo = mid
        f.seek(max(0, lo - 200000)); f.readline()
        chunk = f.read(400000 + (hi - lo)).decode("utf-8", "replace").splitlines(True)
    best_i = best_diff = None
    for i, line in enumerate(chunk):
        ts = extract_timestamp(line)
        if ts:
            d = abs((ts - target).total_seconds())
            if best_diff is None or d < best_diff:
                best_diff, best_i = d, i
    if best_i is None:
        return None
    lo, hi = max(0, best_i - k), min(len(chunk), best_i + k + 1)
    return "".join(f"~:{chunk[i][:500]}" for i in range(lo, hi))

def run(time_string, k=10):
    time_string = time_string.replace(r'\"', '').replace('"', '').strip()
    k = int(k)
    try:
        target = datetime.strptime(time_string, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "Invalid time format. Use: YYYY-MM-DD HH:MM:SS"
    mf = month_file(target)
    if mf.is_file():
        r = _legacy_bsearch(mf, target, k)
        if r:
            return f"[{mf.name}]\n" + r.replace("~:", "")
    if LEGACY.is_file():
        r = _legacy_bsearch(LEGACY, target, k)
        if r:
            return f"[{LEGACY.name} legacy, {mf.name} not present]\n" + r
    return f"No entries found near {time_string} ({mf.name} missing)"
