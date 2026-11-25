import os
import json
import time
import subprocess
import sys
import requests
import websocket
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime" / "mattermost"
INBOX = RUNTIME / "inbox"
OUTBOX = RUNTIME / "outbox"
FILE_OUTBOX = RUNTIME / "file_outbox"
REACT_OUTBOX = RUNTIME / "react_outbox"
PID = RUNTIME / "pid"
DOWNLOADS = RUNTIME / "downloads"

#===============================================================================
MM_URL = "https://chat.singularitynet.io"
CHANNEL_ID = "8fjrmabjx7gupy7e5kjznpt5qh" # MeTTaClaw
#CHANNEL_ID = "iu96fuh54jftfm1zcpjiczprna" # MeTTaClaw - experimental
BOT_TOKEN = ""
#===============================================================================

_headers = {"Authorization": f"Bearer {BOT_TOKEN}"}
_bot_user_id = None
_seen_post_ids = set()
_bot_post_ids = set()  # track our own sent post IDs for reaction matching

# Typing indicator state
_typing_active = False
_typing_last_sent = 0.0
_typing_started = 0.0
_TYPING_INTERVAL = 4   # re-send every 4s
_TYPING_TIMEOUT = 480  # auto-stop after 480s


def ensure_daemon():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(exist_ok=True)
    OUTBOX.mkdir(exist_ok=True)
    try:
        os.kill(int(PID.read_text()), 0)
        return
    except Exception:
        pass
    process = subprocess.Popen(
        [sys.executable, __file__, "--daemon"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    PID.write_text(str(process.pid))


def stop_daemon():
    try:
        pid = int(PID.read_text())
        os.kill(pid, 15)
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        PID.unlink(missing_ok=True)
        return "Mattermost daemon stopped"
    except FileNotFoundError:
        return "No daemon running"
    except Exception as e:
        return f"Error stopping daemon: {e}"


def restart_daemon():
    stop_daemon()
    time.sleep(0.5)
    ensure_daemon()
    return "Mattermost daemon restarted"


def daemon_status():
    try:
        pid = int(PID.read_text())
        os.kill(pid, 0)
        return f"Running (PID {pid})"
    except FileNotFoundError:
        return "Not running"
    except ProcessLookupError:
        return "Not running (stale PID file)"
    except Exception:
        return "Unknown status"


NO_CONTACT_FILE = ROOT.parent / "memory" / "config" / "no_contact_restrictions.txt"

def _check_no_contact(content):
    """Return blocking reason if content addresses a no-contact-restricted person."""
    try:
        lines = NO_CONTACT_FILE.read_text().splitlines()
    except FileNotFoundError:
        return None
    low = (content or "").lower()
    for line in lines:
        handle = line.split("#")[0].strip().lower()
        if handle and handle in low:
            return f"no-contact restriction on '{handle}' active (see memory/config/no_contact_restrictions.txt)"
    return None

def _log_blocked(content, reason):
    try:
        from pathlib import Path as _P
        logp = RUNTIME / "blocked_sends.log"
        logp.parent.mkdir(parents=True, exist_ok=True)
        with open(logp, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + f" | {reason} | {content[:200]!r}\n")
    except Exception:
        pass

def receive():
    ensure_daemon()
    messages = []
    for path in sorted(INBOX.glob("*")):
        try:
            messages.append(path.read_text())
            path.unlink()
        except FileNotFoundError:
            pass
    return "\n".join(messages)

def send(content):
    ensure_daemon()
    reason = _check_no_contact(content)
    if reason:
        _log_blocked(content, reason)
        raise RuntimeError(f"SEND-BLOCKED: {reason}")
    (OUTBOX / str(time.time_ns())).write_text(content)

def send_file(filepath, message=""):
    ensure_daemon()
    reason = _check_no_contact(message or "")
    if reason:
        _log_blocked(message or "", reason)
        raise RuntimeError(f"SEND-BLOCKED: {reason}")
    import json as _json
    (FILE_OUTBOX / str(time.time_ns())).write_text(
        _json.dumps({"file": str(filepath), "message": message})
    )
def react(post_id, emoji_name):
    """Queue a reaction to be sent to a specific post by the bot.
    emoji_name should be a Mattermost emoji name like 'thumbsup', 'check', etc.
    """
    ensure_daemon()
    (REACT_OUTBOX / str(time.time_ns())).write_text(
        json.dumps({"post_id": post_id, "emoji_name": emoji_name})
    )


def _get_bot_user_id():
    r = requests.get(f"{MM_URL}/api/v4/users/me", headers=_headers)
    return r.json()["id"]

def _get_display_name(user_id):
    r = requests.get(f"{MM_URL}/api/v4/users/{user_id}", headers=_headers)
    u = r.json()
    if u.get("first_name") or u.get("last_name"):
        return f"{u.get('first_name','')} {u.get('last_name','')}".strip()
    return u["username"]

def _get_post_snippet(post_id, maxlen=120):
    """Return shortened text of a post (for reaction messages)."""
    try:
        r = requests.get(f"{MM_URL}/api/v4/posts/{post_id}", headers=_headers, timeout=5)
        msg = " ".join(r.json().get("message", "").split())
        if len(msg) > maxlen:
            msg = msg[:maxlen].rstrip() + "..."
        return msg or "(no text)"
    except Exception:
        return "(text unavailable)"


def _download_file(file_id):
    try:
        DOWNLOADS.mkdir(parents=True, exist_ok=True)
        meta_r = requests.get(f"{MM_URL}/api/v4/files/{file_id}/info", headers=_headers)
        meta_r.raise_for_status()
        meta = meta_r.json()
        filename = meta.get("name", file_id)
        dl_r = requests.get(f"{MM_URL}/api/v4/files/{file_id}", headers=_headers)
        dl_r.raise_for_status()
        safe_name = filename.replace("/", "_").replace("\\", "_")
        filepath = DOWNLOADS / safe_name
        filepath.write_bytes(dl_r.content)
        return f"Downloaded: {filepath} ({len(dl_r.content)} bytes)"
    except Exception as e:
        return f"Download failed for {file_id}: {e}"

def _start_typing():
    global _typing_active, _typing_last_sent, _typing_started
    _typing_active = True
    _typing_started = time.time()
    _typing_last_sent = 0.0  # force immediate send

def _stop_typing():
    global _typing_active
    _typing_active = False

def _send_typing():
    """Send typing indicator to Mattermost if active and interval elapsed."""
    global _typing_last_sent
    if not _typing_active:
        return
    now = time.time()
    if now - _typing_started > _TYPING_TIMEOUT:
        _stop_typing()
        return
    if now - _typing_last_sent >= _TYPING_INTERVAL:
        try:
            requests.post(
                f"{MM_URL}/api/v4/users/me/typing",
                headers=_headers,
                json={"channel_id": CHANNEL_ID},
                timeout=5,
            )
            _typing_last_sent = now
        except Exception:
            pass

def daemon():
    global _bot_user_id
    RUNTIME.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(exist_ok=True)
    OUTBOX.mkdir(exist_ok=True)
    FILE_OUTBOX.mkdir(exist_ok=True)
    REACT_OUTBOX.mkdir(exist_ok=True)
    PID.write_text(str(os.getpid()))

    ws_url = MM_URL.replace("https", "wss") + "/api/v4/websocket"
    ws = websocket.WebSocket()
    ws.connect(ws_url, header=[f"Authorization: Bearer {BOT_TOKEN}"])
    _bot_user_id = _get_bot_user_id()
    last_ping = time.time()

    while True:
        _send_typing()
        # Send outgoing messages from outbox
        outbox_items = sorted(OUTBOX.glob("*"))
        if outbox_items:
            # Brief typing indicator before message lands
            _start_typing()
            _send_typing()
            time.sleep(2)
        for path in outbox_items:
            try:
                content = path.read_text()
                path.unlink()
                resp = requests.post(
                    f"{MM_URL}/api/v4/posts",
                    headers=_headers,
                    json={"channel_id": CHANNEL_ID, "message": content},
                )
                # Track our own post IDs for reaction detection
                if resp.status_code == 201:
                    post_id = resp.json().get("id")
                    if post_id:
                        _bot_post_ids.add(post_id)
            except FileNotFoundError:
                pass
        if outbox_items:
            _stop_typing()
        # Send outgoing files from file_outbox
        for path in sorted(FILE_OUTBOX.glob("*")):
            try:
                meta = json.loads(path.read_text())
                path.unlink()
                filepath = meta.get("file")
                msg = meta.get("message", "")
                if filepath and os.path.exists(filepath):
                    with open(filepath, 'rb') as f:
                        files = {'files': (os.path.basename(filepath), f, 'application/octet-stream')}
                        data = {'channel_id': CHANNEL_ID}
                        upload_resp = requests.post(
                            f"{MM_URL}/api/v4/files",
                            headers=_headers,
                            data=data,
                            files=files
                        )
                    if upload_resp.status_code == 201:
                        file_id = upload_resp.json()['file_infos'][0]['id']
                        requests.post(
                            f"{MM_URL}/api/v4/posts",
                            headers=_headers,
                            json={"channel_id": CHANNEL_ID, "message": msg, "file_ids": [file_id]},
                        )
            except Exception as e:
                import traceback
                with open(str(RUNTIME / 'file_outbox_errors.log'), 'a') as log:
                    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} ERROR: {e}\n{traceback.format_exc()}\n")
        # Send outgoing reactions from react_outbox
        for path in sorted(REACT_OUTBOX.glob("*")):
            try:
                meta = json.loads(path.read_text())
                path.unlink()
                post_id = meta.get("post_id")
                emoji_name = meta.get("emoji_name")
                if post_id and emoji_name:
                    requests.post(
                        f"{MM_URL}/api/v4/users/{_bot_user_id}/posts/{post_id}/reactions/{emoji_name}",
                        headers=_headers,
                    )
            except FileNotFoundError:
                pass
            except Exception as e:
                import traceback
                with open(str(RUNTIME / "reaction_errors.log"), "a") as log:
                    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} ERROR: {e}\n{traceback.format_exc()}\n")
        # Receive incoming messages via WebSocket
        try:
            if time.time() - last_ping > 25:
                ws.ping()
                last_ping = time.time()
            ws.settimeout(1)
            event = json.loads(ws.recv())
            if event.get("event") == "posted":
                post = json.loads(event["data"]["post"])
                if post["channel_id"] == CHANNEL_ID and post["user_id"] != _bot_user_id:
                    if post["id"] not in _seen_post_ids:
                        _seen_post_ids.add(post["id"])
                        sender = _get_display_name(post["user_id"])
                        ts = time.strftime('%Y-%m-%d %H:%M:%S')
                        msg = post.get("message", "")
                        # Handle file attachments
                        file_ids = post.get("file_ids", [])
                        download_info = ""
                        if file_ids:
                            dl_results = []
                            for fid in file_ids:
                                dl_results.append(_download_file(fid))
                            download_info = "\n[File downloads: " + " | ".join(dl_results) + "]"
                        (INBOX / str(time.time_ns())).write_text(f"[{ts}] <{sender}> {msg}{download_info} [post_id={post['id']}]")
                        # Typing only when sending (see outbox flush below)
            elif event.get("event") == "reaction_added":
                # Handle reactions to messages (both ours and others')
                try:
                    reaction = event["data"]["reaction"]
                    if isinstance(reaction, str):
                        reaction = json.loads(reaction)
                    reacted_post_id = reaction.get("post_id")
                    reactor_id = reaction.get("user_id")
                    emoji_name = reaction.get("emoji_name", "?")
                    # Only log reactions from others (not our own)
                    if reactor_id != _bot_user_id:
                        # Try to get display name of reactor
                        try:
                            reactor_name = _get_display_name(reactor_id)
                        except Exception:
                            reactor_name = "someone"
                        ts = time.strftime('%Y-%m-%d %H:%M:%S')
                        # Mark if it was a reaction to our message
                        target = "our message" if reacted_post_id in _bot_post_ids else "a message"
                        (INBOX / str(time.time_ns())).write_text(
                            f"[{ts}] <{reactor_name}> [reacted with :{emoji_name}: to {target}: \"{_get_post_snippet(reacted_post_id)}\" (post_id={reacted_post_id})]"
                        )
                except Exception:
                    pass
            elif event.get("event") == "reaction_removed":
                # Handle reaction removals (optional, just skip for now)
                pass
        except (websocket.WebSocketTimeoutException, json.JSONDecodeError, KeyError, BlockingIOError, OSError):
            pass
        time.sleep(0.1)


if __name__ == "__main__" and "--daemon" in sys.argv:
    daemon()
