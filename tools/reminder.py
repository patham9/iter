import os
from datetime import datetime
from pathlib import Path

DESCRIPTION = "Create a reminder/alarm. Usage: run(when='2026-08-19 09:00:00', channel='terminal', message='Submit NeurIPS paper')"

def run(when, channel="terminal", message=""):
    """
    when: str - datetime in format 'YYYY-MM-DD HH:MM:SS'
    channel: str - channel to send reminder to (default 'terminal')
    message: str - reminder message text
    Creates an alarm file in memory/alarms/ named by Unix timestamp.
    """
    ROOT = Path(__file__).resolve().parent.parent
    ALARMS_DIR = ROOT / "memory" / "alarms"
    ALARMS_DIR.mkdir(parents=True, exist_ok=True)

    dt = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    ts = int(dt.timestamp())
    alarm_file = ALARMS_DIR / str(ts)
    alarm_file.write_text(f"{channel}\n{message}")
    return f"SUCCESS, RETURN: Reminder set for {when} (timestamp {ts}) -> {alarm_file}\n  Channel: {channel}\n  Message: {message}"
