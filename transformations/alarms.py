DESCRIPTION = "Alarm clock: checks alarms/ (outside memory) for triggered alarms and fires them as messages. Supports recurring alarms via recur= line. Sends directly to channel programmatically."
import time
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALARMS_DIR = ROOT / "alarms"
CHANNELS_DIR = ROOT / "channels"

DAILY = 86400
WEEKLY = 604800

def _parse_interval(recur_spec):
    """Parse recurrence spec into seconds, or None if one-shot."""
    recur_spec = recur_spec.strip().lower()
    if recur_spec in ("daily", "day", "d"):
        return DAILY
    elif recur_spec in ("weekly", "week", "w"):
        return WEEKLY
    else:
        try:
            return int(recur_spec)
        except ValueError:
            return None

def next_trigger(trigger_time, recur_spec, now=None):
    """Compute next trigger time given a recurrence spec.
    
    Advances forward from trigger_time in interval steps until we find
    a time strictly in the future (past now). This prevents drift when
    alarms are created with wrong timestamps or fire late.
    """
    if now is None:
        now = time.time()
    interval = _parse_interval(recur_spec)
    if interval is None:
        return None  # one-shot, no recurrence
    # Advance from the original trigger time in steps until past now
    next_time = trigger_time + interval
    while next_time <= now:
        next_time += interval
    return next_time

def _send_to_channel(channel, msg):
    """Try to send directly to the channel programmatically."""
    try:
        mod = importlib.import_module(f"channels.{channel}")
        mod.send(msg)
        return True
    except Exception as e:
        # Log but don't crash — fall back to message injection
        try:
            log_path = ROOT / ".runtime" / "alarm_send_errors.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | channel={channel} | error={e}\n")
        except Exception:
            pass
        return False

PENDING = ROOT / ".runtime" / "pending_alarms.json"
TRANSCRIPT = ROOT / "transcript.txt"

def _load_pending():
    import json
    try:
        return json.loads(PENDING.read_text())
    except Exception:
        return []

def _save_pending(items):
    import json
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(items, indent=1))

def _cleared(item):
    """Cleared only if a real send to the alarm's channel, after firing, contains the clear tag."""
    tag = item["tag"]
    fired = item["fired"]
    marker = f"[send -> {item['channel']}]"
    try:
        with open(TRANSCRIPT, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 2_000_000))
            tail = f.read().decode("utf-8", "replace").splitlines()
    except Exception:
        return False
    for line in tail:
        if marker in line and tag in line and line[1:20] >= fired:
            return True
    return False

def _check_pending(messages):
    items = _load_pending()
    keep = []
    for it in items:
        if _cleared(it):
            continue
        keep.append(it)
        messages.append({"role": "user", "content":
            f"Step {time.strftime('%Y-%m-%d %H:%M:%S')}: [ALARM PENDING since {it['fired']}] {it['msg']}\n"
            f"⚠ NOT CLEARED. Deliver it now via send to channel '{it['channel']}'. The sent message MUST contain the tag {it['tag']} — "
            f"only that clears this alarm; it will repeat every cycle until then."})
    if keep != items:
        _save_pending(keep)

def transform(messages, tools):
    ALARMS_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    _check_pending(messages)

    for alarm_file in sorted(ALARMS_DIR.glob("*")):
        try:
            stem, _, label = alarm_file.name.partition("_")
            target_time = float(stem)
        except ValueError:
            continue

        if now >= target_time:
            content = alarm_file.read_text().strip()
            lines = content.split("\n")

            # Parse alarm: optional channel, message, optional recur=<spec>
            # Format A: channel\nmessage\nrecur=...  (3+ lines)
            # Format B: message\nrecur=...  (2 lines, no channel)
            # Format C: message  (1 line)
            recur_spec = None
            channel = "terminal"
            msg = content

            # Check if any line is a recur= line
            non_recur_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("recur="):
                    recur_spec = stripped[len("recur="):]
                else:
                    non_recur_lines.append(line)

            if len(non_recur_lines) >= 2:
                channel, msg = non_recur_lines[0], non_recur_lines[1]
            elif len(non_recur_lines) == 1:
                msg = non_recur_lines[0]

            # Send directly to channel programmatically
            sent_ok = _send_to_channel(channel, msg)

            # Also inject into messages for awareness
            status = "sent" if sent_ok else "failed_send"
            messages.append({
                "role": "user",
                "content": f"Step {time.strftime('%Y-%m-%d %H:%M:%S')}: [{channel}] [ALARM] [{status}] {msg}\n⚡ ACT ON THIS ALARM IMMEDIATELY — execute the brief/task described above right now, do not defer to later cycles."
            })

            # Register as pending until cleared by a sent message containing the tag
            tag = "#clear-" + (label or stem)
            if channel != "terminal":
                pend = _load_pending()
                pend.append({"tag": tag, "channel": channel, "msg": msg,
                             "fired": time.strftime('%Y-%m-%d %H:%M:%S')})
                _save_pending(pend)
                messages[-1]["content"] += f"\nTo clear: your send to '{channel}' must contain {tag}. Until then it stays in context."

            # Delete the fired alarm
            alarm_file.unlink()

            # Recreate for next cycle if recurring
            if recur_spec:
                next_time = next_trigger(target_time, recur_spec, now=now)
                if next_time and next_time > now:
                    if channel != "terminal":
                        recurring_content = f"{channel}\n{msg}\nrecur={recur_spec}"
                    else:
                        recurring_content = f"{msg}\nrecur={recur_spec}"
                    next_name = str(int(next_time)) + ("_" + label if label else "")
                    next_file = ALARMS_DIR / next_name
                    same = [f for f in ALARMS_DIR.glob(str(int(next_time)) + "*")
                            if f.read_text().strip() == recurring_content.strip()]
                    if same:
                        continue  # identical alarm already scheduled (e.g. by recurring_alarms.py)
                    if next_file.exists():
                        next_file = ALARMS_DIR / (next_name + "_" + str(int(now)))  # never overwrite different content
                    next_file.write_text(recurring_content)

    return messages, tools
