import os
import time



def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _mkdirs(path):
    current = ""
    for part in str(path).split("/"):
        if not part:
            current = "/" if not current else current
            continue
        current = (current.rstrip("/") + "/" + part) if current else part
        try:
            os.mkdir(current)
        except OSError:
            pass

DESCRIPTION = "Start a new task by overwriting memory/tasks/current_tasks.txt. ALWAYS call this before beginning any new user-requested work. Required fields: person, requestchannel, taskcontent, completionsendcriterium, originalUserMessage."

def _send_to_channel(channel, content):
    """Send a message through a channel by executing channel module directly."""
    path = "channels/" + channel + ".py"
    if not _exists(path):
        return f"Channel file not found: {path}"
    # Read and exec the channel module
    with open(path, 'r') as f:
        src = f.read()
    ns = {}
    exec(src, ns)
    if "send" not in ns:
        return f"Channel {channel} cannot send"
    ns["send"](content)
    return "SUCCESS"

def run(person, requestchannel, taskcontent, completionsendcriterium, originalUserMessage=""):
    ROOT = "/work/iter"
    TASKS_DIR = ROOT + "/memory/tasks"
    try:
        _mkdirs(TASKS_DIR)
    except:
        pass
    TASK_FILE = TASKS_DIR + "/current_tasks.txt"

    now = time.localtime()
    now_str = "%04d-%02d-%02d %02d:%02d:%02d" % (now[0], now[1], now[2], now[3], now[4], now[5])

    content = f"""# Current Task (started {now_str})
# =============================================
# Person:               {person}
# Request Channel:      {requestchannel}
# Task Content:         {taskcontent}
# Completion Criterion: {completionsendcriterium}
# Original User Message: {originalUserMessage}
# =============================================
"""
    with open(TASK_FILE, 'w') as f:
        f.write(content)

    notification = (
        f"**NEW TASK STARTED**\n"
        f"**Person:** {person}\n"
        f"**Channel:** {requestchannel}\n"
        f"**Task:** {taskcontent}\n"
        f"**Completion Criterion:** {completionsendcriterium}\n"
        f"**Started:** {now_str}"
    )

    send_status = "not sent"
    try:
        send_status = _send_to_channel(requestchannel, notification)
    except Exception as e:
        send_status = f"send failed: {e}"

    return f"SUCCESS, RETURN: New task started at {now_str}.\n  Person: {person}\n  Channel: {requestchannel}\n  Task: {taskcontent}\n  Completion criterion: {completionsendcriterium}\n  Original message: {originalUserMessage}\n  Written to: {TASK_FILE}\n  Channel notification: {send_status}"
