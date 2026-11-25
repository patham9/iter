"""Shared validator: an episode timestamp must be a real entry/Step/message time in history."""
import re
import subprocess
from datetime import datetime
from pathlib import Path

HISTORY_DIR = Path.home() / "PeTTa" / "repos" / "mettaclaw" / "memory"
LEGACY = HISTORY_DIR / "history.metta"
FMT = "%Y-%m-%d %H:%M:%S"

TRANSCRIPT = Path.home() / "iter" / "transcript.txt"
TSRE = r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}"

def _patterns(path, ts):
    t = re.escape(ts)
    if path.name == "transcript.txt":
        return [rf"^\[{t}\] ",
                rf"^\[{TSRE}\] Step {t}: ",
                rf"^\[{TSRE}\] Step {TSRE}: \[[a-z]+\] \[{t}\] <"]
    return [rf'^\("{t}" ',
            rf'^\("{TSRE}" "(TOOL_RESULT: )?Step {t}: ',
            rf'^\("{TSRE}" "(TOOL_RESULT: )?Step {TSRE}: \[[a-z]+\] \[{t}\] <']

def _grep(path, ts):
    # Anchored to line start, so a timestamp that is only quoted inside some entry does not count.
    cmd = ["grep", "-E", "-m1", "-q"] + sum([["-e", p] for p in _patterns(path, ts)], []) + [str(path)]
    try:
        return subprocess.run(cmd, timeout=60).returncode == 0
    except Exception:
        return False

def check_episode(ts):
    """Return None if valid, else an error string."""
    ts = (ts or "").strip()
    try:
        dt = datetime.strptime(ts, FMT)
    except ValueError:
        return f"EPISODE-REJECTED: '{ts}' is not of format YYYY-MM-DD HH:MM:SS"
    monthly = HISTORY_DIR / dt.strftime("history_%m_%Y.metta")
    for p in (monthly, LEGACY, TRANSCRIPT):
        if p.exists() and _grep(p, ts):
            return None
    return f"EPISODE-REJECTED: '{ts}' is not a real entry/Step/message time in {monthly.name}, history.metta or transcript.txt; memory unchanged"
