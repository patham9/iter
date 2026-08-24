import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime" / "irc"
INBOX = RUNTIME / "inbox"
OUTBOX = RUNTIME / "outbox"
PID = RUNTIME / "pid"

IRC_HOST = "irc.quakenet.org"
IRC_PORT = 6667
NICK = "Iter"
CHANNEL = "##metta"

def ensure_daemon():
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        INBOX.mkdir(exist_ok=True)
        OUTBOX.mkdir(exist_ok=True)
        try:
            pid_val = int(PID.read_text().strip())
            os.kill(pid_val, 0)
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
    except Exception:
        pass

def receive():
    ensure_daemon()
    messages = []
    try:
        for path in sorted(INBOX.glob("*")):
            try:
                messages.append(path.read_text())
                path.unlink()
            except (FileNotFoundError, OSError):
                pass
    except Exception:
        pass
    return "\n".join(messages)

def send(content):
    ensure_daemon()
    try:
        (OUTBOX / str(time.time_ns())).write_text(content)
    except Exception:
        pass

def daemon():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(exist_ok=True)
    OUTBOX.mkdir(exist_ok=True)
    PID.write_text(str(os.getpid()))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect((IRC_HOST, IRC_PORT))
    except Exception:
        time.sleep(30)
        return
    sock.settimeout(0.1)

    def irc_send(line):
        try:
            sock.sendall((line + "\r\n").encode("utf-8"))
        except Exception:
            pass

    def irc_recv():
        try:
            data = sock.recv(4096)
            if not data:
                return ""
            return data.decode("utf-8", errors="replace")
        except (socket.timeout, BlockingIOError, OSError):
            return ""

    irc_send(f"NICK {NICK}")
    irc_send(f"USER {NICK} 0 * :Iter Agent")
    buf = ""

    while True:
        data = irc_recv()
        if data:
            buf += data
            while "\r\n" in buf:
                line, buf = buf.split("\r\n", 1)
                line = line.strip()
                if not line:
                    continue
                if line.startswith("PING"):
                    rest = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ""
                    irc_send(f"PONG {rest}")
                    continue
                parts = line.split()
                if len(parts) > 1 and parts[1] == "001":
                    irc_send(f"JOIN {CHANNEL}")
                    try:
                        (INBOX / str(time.time_ns())).write_text(f"[IRC] Connected and joined {CHANNEL}")
                    except Exception:
                        pass
                    continue
                if "PRIVMSG" in line:
                    try:
                        prefix, cmd, args = line.split(" ", 2)
                        target, msg = args.split(" ", 1)
                        msg = msg.lstrip(":")
                        sender = prefix.lstrip(":").split("!")[0]
                        (INBOX / str(time.time_ns())).write_text(f"<{sender}> {msg}")
                    except Exception:
                        pass
                    continue
        for path in sorted(OUTBOX.glob("*")):
            try:
                content = path.read_text()
                path.unlink()
                irc_send(f"PRIVMSG {CHANNEL} :{content}")
            except (FileNotFoundError, OSError):
                pass
        time.sleep(0.1)

if __name__ == "__main__" and "--daemon" in sys.argv:
    daemon()
