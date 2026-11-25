import subprocess
from pathlib import Path

DESCRIPTION = "Batch-upload all dashboard HTML files to server (runs last alphabetically)"

# Each dashboard writes its HTML to /tmp/; this transformation uploads them all at once.
DASHBOARDS = [
    ("atomspace", "/tmp/dashboard_atomspace.html", "dashboard_atomspace.html"),
    ("gallery",   "/tmp/dashboard_gallery.html",   "dashboard_gallery.html"),
    ("runtime",    "/tmp/dashboard_runtime.html",    "dashboard_runtime.html"),
    ("context",    "/tmp/dashboard_context.html",    "dashboard_context.html"),
]

REMOTE_BASE = "/var/www/html-nonlang.dev/MeTTaSoul/mb"
SSH_OPTS = "-p 51357 -i ~/.ssh/max_nonlanguage_ed25519 -o StrictHostKeyChecking=no"


def transform(messages, tools):
    cmds = []
    for _label, local_path, remote_name in DASHBOARDS:
        p = Path(local_path)
        if not p.exists():
            continue
        remote_path = f"{REMOTE_BASE}/{remote_name}"
        cmds.append(
            f'scp -P 51357 -i ~/.ssh/max_nonlanguage_ed25519 -o StrictHostKeyChecking=no '
            f'"{local_path}" max@wreading.xyz:"{remote_path}" && '
            f'ssh {SSH_OPTS} max@wreading.xyz "chmod 644 {remote_path}" && '
            f'rm -f "{local_path}"'
        )
    if cmds:
        batch_cmd = " ; ".join(cmds)
        try:
            subprocess.Popen(
                ["bash", "-c", batch_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    return messages, tools
