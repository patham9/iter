import os
import json
import importlib.util
from datetime import datetime
from pathlib import Path

DESCRIPTION = "Start a new task by overwriting memory/tasks/current_tasks.txt. ALWAYS call this before beginning any new user-requested work. Required fields: person, requestchannel, taskcontent, completionsendcriterium, originalUserMessage."

# State file to track the last request params
STATE_FILE = Path(__file__).resolve().parent / "_start_new_task_state.json"

def _send_to_channel(channel, content):
    """Send a message through a channel module (same mechanism as send.py)."""
    path = Path("channels") / (channel + ".py")
    if not path.is_file():
        return f"Channel file not found: {path}"
    spec = importlib.util.spec_from_file_location("channel_" + channel, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "send"):
        return f"Channel {channel} cannot send"
    module.send(content)
    return "SUCCESS"

def _load_state():
    """Load the last request params from state file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None

def _save_state(params):
    """Save the current request params to state file."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(params, f)
    except IOError:
        pass

def run(person, requestchannel, taskcontent, completionsendcriterium, originalUserMessage=""):
    """
    person: str - who requested the task (e.g. "Patrick Hammer")
    requestchannel: str - channel the request came from (e.g. "mattermost")
    taskcontent: str - description of the task to perform
    completionsendcriterium: str - criteria that determine when the task is complete and a send-back is warranted
    originalUserMessage: str - the original user message from which the task was inferred (default "")
    Overwrites memory/tasks/current_tasks.txt with the new task.
    Sends a structured bold notification to the request channel.
    If all params match the previous call, returns SUCCESS without overwriting or notifying.
    returns: str - success message
    """
    # Build current params dict
    current_params = {
        "person": person,
        "requestchannel": requestchannel,
        "taskcontent": taskcontent,
        "completionsendcriterium": completionsendcriterium,
        "originalUserMessage": originalUserMessage,
    }

    # Check for duplicate request — if all params match the last call, skip
    last_state = _load_state()
    if last_state is not None:
        all_match = all(
            last_state.get(key) == value
            for key, value in current_params.items()
        )
        if all_match:
            return "SUCCESS"

    # Save current params as the new last state
    _save_state(current_params)

    ROOT = Path(__file__).resolve().parent.parent
    TASKS_DIR = ROOT / "memory" / "tasks"
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    TASK_FILE = TASKS_DIR / "current_tasks.txt"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = f"""# Current Task (started {now})
# =============================================
# Person:               {person}
# Request Channel:      {requestchannel}
# Task Content:         {taskcontent}
# Completion Criterion: {completionsendcriterium}
# Original User Message: {originalUserMessage}
# =============================================
"""
    TASK_FILE.write_text(content)

    # DISABLED: # Send a structured bold notification to the request channel
    # DISABLED: notification = (
    # DISABLED:     f"**🆕 NEW TASK STARTED**\n"
    # DISABLED:     f"**━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━**\n"
    # DISABLED:     f"**👤 Person:** {person}\n"
    # DISABLED:     f"**📍 Channel:** {requestchannel}\n"
    # DISABLED:     f"**📝 Task:** {taskcontent}\n"
    # DISABLED:     f"**✅ Completion Criterion:** {completionsendcriterium}\n"
    # DISABLED:     f"**🕐 Started:** {now}\n"
    # DISABLED:     f"**━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━**"
    # DISABLED: )

    # DISABLED: send_status = "not sent"
    # DISABLED: try:
    # DISABLED:     send_status = _send_to_channel(requestchannel, notification)
    # DISABLED: except Exception as e:
    # DISABLED:     send_status = f"send failed: {e}"
    send_status = "disabled per user request 2026-10-12"

    return f"SUCCESS, RETURN: New task started at {now}.\n  Person: {person}\n  Channel: {requestchannel}\n  Task: {taskcontent}\n  Completion criterion: {completionsendcriterium}\n  Original message: {originalUserMessage}\n  Written to: {TASK_FILE}\n  Channel notification: {send_status}"
