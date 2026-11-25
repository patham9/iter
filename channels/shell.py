"""Shell channel: send(cmd) starts a background job (max K at once).
When a job finishes, receive() returns "(input, result)" as a deferred message.
Results are head+tail truncated."""
import os, subprocess, sys, time, json
from pathlib import Path

K = 4
TIMEOUT = 3600
MAXOUT = 3000
ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime" / "shell"
INBOX = RUNTIME / "inbox"
RUNNING = RUNTIME / "running"

def _dirs():
    INBOX.mkdir(parents=True, exist_ok=True)
    RUNNING.mkdir(parents=True, exist_ok=True)

def _alive(pidfile):
    try:
        os.kill(int(json.loads(pidfile.read_text())["pid"]), 0)
        return True
    except Exception:
        return False

def _running():
    _dirs()
    jobs = []
    for f in RUNNING.glob("*"):
        if _alive(f):
            jobs.append(f)
        else:
            try: f.unlink()
            except FileNotFoundError: pass
    return jobs

def _post(text):
    _dirs()
    tmp = INBOX / (".tmp" + str(time.time_ns()))
    tmp.write_text(text)
    tmp.rename(INBOX / str(time.time_ns()))

def send(content):
    cmd = content.strip()
    jobs = _running()
    if len(jobs) >= K:
        names = ", ".join(json.loads(j.read_text())["cmd"][:40] for j in jobs)
        _post(f"(input: {cmd!r}, result: REJECTED, {len(jobs)}/{K} jobs already running: {names})")
        return
    jid = str(time.time_ns())
    p = subprocess.Popen([sys.executable, __file__, "--run", jid, cmd],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    (RUNNING / jid).write_text(json.dumps({"pid": p.pid, "cmd": cmd, "start": time.time()}))

def receive():
    _dirs()
    out = []
    for f in sorted(INBOX.glob("[0-9]*")):
        try:
            out.append(f.read_text()); f.unlink()
        except FileNotFoundError:
            pass
    return "\n".join(out)

def _run(jid, cmd):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=TIMEOUT, errors="replace", stdin=subprocess.DEVNULL)
        res, code = (r.stdout + (("\n[stderr] " + r.stderr) if r.stderr else "")).strip(), r.returncode
    except subprocess.TimeoutExpired:
        res, code = f"TIMEOUT after {TIMEOUT}s", -1
    except Exception as e:
        res, code = f"ERROR {type(e).__name__}: {e}", -1
    if len(res) > MAXOUT:
        h = MAXOUT // 2
        res = res[:h] + f"\n[... {len(res)-MAXOUT} chars cut ...]\n" + res[-h:]
    _post(f"(input: {cmd!r}, exit: {code}, {time.time()-t0:.1f}s, result: {res})")
    try: (RUNNING / jid).unlink()
    except FileNotFoundError: pass

if __name__ == "__main__" and len(sys.argv) >= 4 and sys.argv[1] == "--run":
    _run(sys.argv[2], sys.argv[3])
