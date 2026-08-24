import os
from datetime import datetime

DESCRIPTION = "Search transcript history for entries around a given timestamp. Returns surrounding context lines."

HISTORY_PATH = os.path.expanduser("~/PeTTa/repos/mettaclaw/memory/history.metta")


def _parse_timestamp(line):
    """Extract timestamp from a history line like ('2026-08-14 22:45:27' ..."""
    idx = line.find('"')
    if idx < 0:
        return None
    end = line.find('"', idx + 1)
    if end < 0:
        return None
    ts_str = line[idx + 1:end]
    try:
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _read_line_at_byte(f, pos):
    """Seek to byte pos, skip partial line, read and return next full line + new pos."""
    f.seek(pos)
    if pos > 0:
        f.readline()  # skip partial line
    raw = f.readline()
    if raw:
        return raw.decode('utf-8', errors='replace').strip(), f.tell()
    return None, pos


def run(time_string, k=10):
    time_string = time_string.replace(r'\"', '').replace('"', '').strip()
    k = int(k)

    if not os.path.isfile(HISTORY_PATH):
        return f"No history.metta found at {HISTORY_PATH}"

    try:
        target = datetime.strptime(time_string, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "Invalid time format. Use: YYYY-MM-DD HH:MM:SS"

    file_size = os.path.getsize(HISTORY_PATH)
    if file_size == 0:
        return "File is empty"

    with open(HISTORY_PATH, 'rb') as f:
        # Full-range binary search on byte offsets (file is chronologically ordered)
        lo = 0
        hi = file_size
        best_pos = None
        best_diff = None
        best_line = None

        while lo < hi:
            mid = (lo + hi) // 2
            if mid == lo:
                break
            line, next_pos = _read_line_at_byte(f, mid)
            if line is None:
                lo = mid + 1
                continue

            ts = _parse_timestamp(line)
            if ts is None:
                # Try advancing a few lines
                found_ts = None
                p = next_pos
                for _ in range(3):
                    line2, p = _read_line_at_byte(f, p)
                    if line2 is None:
                        break
                    t2 = _parse_timestamp(line2)
                    if t2 is not None:
                        found_ts = t2
                        break
                if found_ts is None:
                    lo = mid + 1
                    continue
                ts = found_ts

            diff = abs((ts - target).total_seconds())
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_pos = mid
                best_line = line

            if ts < target:
                lo = next_pos
            elif ts > target:
                hi = mid
            else:
                best_pos = mid
                best_line = line
                break

        if best_pos is None:
            return f"No timestamped entries found near {time_string}"

        # Collect k lines before and after
        chunk_size = 20000
        start_byte = max(0, best_pos - chunk_size)
        f.seek(start_byte)
        if start_byte > 0:
            f.readline()  # skip partial line

        collected = []
        for _ in range(k + k + 1):
            raw = f.readline()
            if not raw:
                break
            collected.append(raw.decode('utf-8', errors='replace').rstrip('\n'))

        # Find the best match line index in collected
        best_idx = 0
        best_d = None
        for i, line in enumerate(collected):
            ts = _parse_timestamp(line)
            if ts is not None:
                d = abs((ts - target).total_seconds())
                if best_d is None or d < best_d:
                    best_d = d
                    best_idx = i

        # Show k lines around best match
        start_show = max(0, best_idx - k)
        end_show = min(len(collected), best_idx + k + 1)
        result_lines = []
        for i in range(start_show, end_show):
            result_lines.append(f"{collected[i][:500]}")
        return "\n".join(result_lines)
