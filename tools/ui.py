"""Optional Iter dynamic tool: update the terminal's pinned side panel.

Copy this file to tools/ui_panel.py. It uses the same persistent UI
state as log.py; changes appear even during an ongoing inference.
"""

DESCRIPTION = "Set or clear the persistent right-side terminal panel (not a chat send). Content supports ANSI SGR colors: JSON \\u001b[31m red, \\u001b[92m green, \\u001b[38;5;208m orange, \\u001b[0m reset; also 24-bit RGB. Empty content clears the panel."


def run(title: str, content: str) -> str:
    import log

    if content:
        log.pin(content, title)
        return "Terminal pinned panel updated."
    log.clear_pin()
    return "Terminal pinned panel cleared."
