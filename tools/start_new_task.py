import os
import importlib.util
from datetime import datetime
from pathlib import Path

DESCRIPTION = "Start a new task by overwriting memory/tasks/current_tasks.txt. ALWAYS call this before beginning any new user-requested work. Required fields: person, requestchannel, taskcontent, completionsendcriterium, originalUserMessage."

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

def run(person, requestchannel, taskcontent, completionsendcriterium, originalUserMessage=""):
    """
    person: str - who requested the task (e.g. "Patrick Hammer")
    requestchannel: str - channel the request came from (e.g. "mattermost")
    taskcontent: str - description of the task to perform
    completionsendcriterium: str - criteria that determine when the task is complete and a send-back is warranted
    originalUserMessage: str - the original user message from which the task was inferred (default "")
    Overwrites memory/tasks/current_tasks.txt with the new task.
    Sends a structured bold notification to the request channel.
    returns: str - success message
    """
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

    # Send a structured bold notification to the request channel
    notification = (
        f"**🆕 NEW TASK STARTED**\n"
        f"**━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━**\n"
        f"**👤 Person:** {person}\n"
        f"**📍 Channel:** {requestchannel}\n"
        f"**📝 Task:** {taskcontent}\n"
        f"**✅ Completion Criterion:** {completionsendcriterium}\n"
        f"**🕐 Started:** {now}\n"
        f"**━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━**"
    )

    send_status = "not sent"
    try:
        send_status = _send_to_channel(requestchannel, notification)
    except Exception as e:
        send_status = f"send failed: {e}"

    return f"SUCCESS, RETURN: New task started at {now}.\n  Person: {person}\n  Channel: {requestchannel}\n  Task: {taskcontent}\n  Completion criterion: {completionsendcriterium}\n  Original message: {originalUserMessage}\n  Written to: {TASK_FILE}\n  Channel notification: {send_status}"
