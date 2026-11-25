"""
Crontab Context Transformation

Shows the currently active crontab lines in every cycle, so jobs running
outside the agent's context are always visible. Flags lines whose
referenced script/file no longer exists.
"""
import os
import re
import subprocess

DESCRIPTION = "Crontab context: shows active cronjobs each cycle and flags lines whose script is missing."


def _lines():
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=3)
    except Exception as e:
        return None, f"crontab -l failed: {e}"
    if out.returncode != 0:
        msg = (out.stderr or "").strip()
        return [], ("no crontab" if "no crontab" in msg else msg[:120])
    return [l for l in out.stdout.splitlines() if l.strip() and not l.lstrip().startswith("#")], None


def _missing(line):
    miss = []
    for tok in re.findall(r"(~?/[\w./-]+\.(?:sh|py|metta|pl))", line):
        if not os.path.exists(os.path.expanduser(tok)):
            miss.append(tok)
    return miss


def briefing():
    lines, err = _lines()
    head = "=== CRONTAB (active jobs, outside context control) ==="
    if lines is None or (not lines and err):
        return f"{head}\n {err}"
    if not lines:
        return f"{head}\n (none)"
    rows = []
    for l in lines:
        m = _missing(l)
        tag = f" [DEAD: missing {', '.join(m)}]" if m else ""
        rows.append(" " + (l if len(l) <= 110 else l[:107] + "...") + tag)
    return head + "\n" + "\n".join(rows)


def transform(messages, tools):
    try:
        if messages and isinstance(messages[0], dict):
            content = messages[0].get("content", "")
            if isinstance(content, str):
                messages[0]["content"] = content.rstrip() + "\n\n" + briefing()
    except Exception:
        pass
    return messages, tools
