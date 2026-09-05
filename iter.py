import copy
import datetime
import hashlib
import inspect
import json
import os
import queue
import sys
import openai
import time
import importlib.util
import signal
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

# --------------------------------------------------------------------
# 0. Configuration:
# --------------------------------------------------------------------
MAX_MEMORY_CHARS = 3000 #When memory turns into an index
LLM_TIMEOUT = 600
KEEP_REASONING_IN_EPISODE = True
PRINT_CALLS = False
MAX_TOOL_CALLS = 10
MAX_TOOL_OUTPUT_CHARS = 5000
MAX_EXPERIENCE_SIZE = 100   #20 percent
RETAIN_EXPERIENCE_SIZE = 80 #jumps
MAX_FAST_STEPS = 50
TURN_WATCHDOG_THRESHOLD = MAX_FAST_STEPS - 5  # emit checkpoint reminder at this step

# --- M1 Step 1.1: Tier-1 mechanical checkpoint (flag-guarded, default ON) ---
ITER_CHECKPOINT_ENABLED = os.getenv("ITER_CHECKPOINT_ENABLED", "1") == "1"
CHECKPOINT_TOOL_SNAPSHOT = 5       # number of recent tool calls to include
CHECKPOINT_OUTPUT_CHARS = 200     # truncate each tool output to this many chars
CHECKPOINT_DIR = Path("checkpoints")  # root dir for checkpoint files
CHECKPOINT_CHANNEL = os.getenv("ITER_CHECKPOINT_CHANNEL", "protocosmo2")

# --- M2 Step 2.1: Threaded LLM call wrapper (flag ITER_CONCURRENCY_ENABLED, default OFF) ---
ITER_CONCURRENCY_ENABLED = os.getenv("ITER_CONCURRENCY_ENABLED", "0") == "1"
ITER_PROMOTE_SECONDS = int(os.getenv("ITER_PROMOTE_SECONDS", "30"))
# --- M3 Step 3.1: BACKGROUND_DEADLINE (R13: bounded background lifetime) ---
BACKGROUND_DEADLINE = max(2 * ITER_PROMOTE_SECONDS, 300)
# --- M3 Step 3.5: Branch step budget + branch checkpoint queuing (R20) ---
BRANCH_STEP_BUDGET = int(os.getenv("ITER_BRANCH_STEP_BUDGET", "25"))
SLOW_STEP_DELAY = 10
ERROR_RECOVERY_TIME = 1 #after how long to retry when exception occurs
RETURN_VALUE_PRESERVE = 0
RETURN_VALUE_PRESERVE_MESSAGES = 10
DEFAULT_DELAY = 0 #default delay added irregard of whether in slow mode
MAX_TOKENS = 2524
INIT_WAIT = 10
MAX_TOOLS = 30
MAX_TOOL_DESCRIPTION_CHARS = 500
DYNAMIC_TIMEOUT = 5
MODEL = os.getenv("LLM_MODEL", "mlx-community/gemma-4-26b-a4b-it-4bit")
BASE_URL = os.getenv("BASE_URL", "http://192.168.64.1:2277/v1")
API_KEY = os.getenv("AI_API_KEY", "dummy")

# --------------------------------------------------------------------
# 1. Dynamic execution:
# --------------------------------------------------------------------
def dynamic_worker():
    path = Path(sys.argv[2])
    function = sys.argv[3]
    result_path = Path(sys.argv[4])
    payload_path = Path(sys.argv[5])
    try:
        payload = json.loads(payload_path.read_text())
        spec = importlib.util.spec_from_file_location("_dynamic_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if function == "__description__":
            result = str(module.DESCRIPTION)
        elif function == "__tool_metadata__":
            parameters = inspect.signature(module.run).parameters.values()
            description = str(module.DESCRIPTION)
            if len(description) > MAX_TOOL_DESCRIPTION_CHARS:
                description = description[:MAX_TOOL_DESCRIPTION_CHARS] + " [DESCRIPTION TRUNCATED]"
            result = {"description": description, "parameters": [parameter.name for parameter in parameters]}
        else:
            result = getattr(module, function)(*payload.get("args", []), **payload.get("kwargs", {}))
            if function != "transform" and result is not None:
                result = str(result)
        output = {"ok": True, "result": result}
    except BaseException as error:
        output = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    try:
        result_path.write_text(json.dumps(output, ensure_ascii=False))
    except BaseException as error:
        result_path.write_text(json.dumps({"ok": False, "error": f"Result serialization failed: {type(error).__name__}: {error}"}, ensure_ascii=False))

def invoke_dynamic(path, function, *args, **kwargs):
    result_fd, result_file = tempfile.mkstemp(prefix="iter-result-", suffix=".json")
    payload_fd, payload_file = tempfile.mkstemp(prefix="iter-payload-", suffix=".json")
    try:
        os.close(result_fd)
        os.close(payload_fd)
        Path(payload_file).write_text(json.dumps({"args": args, "kwargs": kwargs}, ensure_ascii=False))
        inherit_stdin = Path(path).stem == "terminal" and function == "receive"
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--invoke", str(Path(path).resolve()), function, result_file, payload_file],
            stdin=None if inherit_stdin else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=not inherit_stdin,
            close_fds=True
        )
        try:
            process.wait(timeout=DYNAMIC_TIMEOUT)
        except subprocess.TimeoutExpired:
            if inherit_stdin:
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
            return {"ok": False, "error": f"TIMEOUT after {DYNAMIC_TIMEOUT}s"}
        try:
            return json.loads(Path(result_file).read_text())
        except Exception:
            return {"ok": False, "error": f"Dynamic process exited with code {process.returncode} without a valid result"}
    finally:
        for file in (result_file, payload_file):
            try:
                os.unlink(file)
            except FileNotFoundError:
                pass

if len(sys.argv) > 1 and sys.argv[1] == "--invoke":
    dynamic_worker()
    sys.exit(0)

# --------------------------------------------------------------------
# 2. Runtime helpers:
# --------------------------------------------------------------------
def get_current_time():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def receive():
    events = []
    paths = [path for path in sorted(Path("channels").glob("*.py")) if not path.name.startswith("_")]
    for path in paths:
        try:
            result = invoke_dynamic(path, "receive")
            if not result["ok"]:
                raise RuntimeError(result["error"])
            event = result["result"]
            if event:
                events.append("[" + path.stem + "] " + str(event))
        except Exception as error:
            events.append(f"[CHANNEL ERROR in {path}: {type(error).__name__}: {error}. Repair {path} if needed.]")
    return "\n".join(events)

def resume_claimed():
    """Resume channel claims once at process startup.

    Channels without a recovery hook are ignored. A channel that implements
    ``resume`` remains responsible for validating that exactly one durable
    claim exists and for failing closed on ambiguous state.
    """
    events = []
    paths = [path for path in sorted(Path("channels").glob("*.py")) if not path.name.startswith("_")]
    for path in paths:
        result = invoke_dynamic(path, "resume")
        if not result["ok"]:
            if "AttributeError" in result["error"] and "resume" in result["error"]:
                continue
            if "exactly one active request is required for resume" in result["error"]:
                continue
            events.append(f"[CHANNEL RECOVERY ERROR in {path}: {result['error']}. Repair {path} if needed.]")
            continue
        event = result["result"]
        if event:
            events.append("[" + path.stem + "] " + str(event))
    return "\n".join(events)

def slow_wait_for_input():
    for second in range(SLOW_STEP_DELAY):
        time.sleep(1)
        event_append = receive()
        if event_append:
            return event_append
    return ""

def save_experience(experience):
    with open("experience.tmp", "w", encoding="utf-8") as file:
        json.dump(experience, file, ensure_ascii=False, indent=2)
    os.replace("experience.tmp", "experience.json")

# --- M1 Step 1.1: Tier-1 mechanical checkpoint extraction ---
def extract_tier1_checkpoint(experience, autonomous_steps):
    """Purely mechanical extraction of checkpoint data from the experience list.

    No LLM calls. Returns a dict with: checkpoint_type, session_id, step_count,
    timestamps, prompt_hash, and a snapshot of the last N tool calls (name +
    200-char truncated output).
    """
    # Map tool_call_id -> tool name from assistant messages
    tool_call_names = {}
    for entry in experience:
        if entry.get("role") == "assistant" and entry.get("tool_calls"):
            for tc in entry["tool_calls"]:
                if isinstance(tc, dict):
                    tool_call_names[tc.get("id")] = tc.get("function", {}).get("name", "?")

    # Collect last N tool-output entries
    tool_entries = [e for e in experience if e.get("role") == "tool"]
    recent_tools = tool_entries[-CHECKPOINT_TOOL_SNAPSHOT:]

    snapshot = []
    for entry in recent_tools:
        tc_id = entry.get("tool_call_id", "?")
        name = tool_call_names.get(tc_id, "?")
        content = entry.get("content", "")
        truncated = content[:CHECKPOINT_OUTPUT_CHARS]
        snapshot.append({
            "tool_call_id": tc_id,
            "tool_name": name,
            "output_truncated": truncated,
        })

    # Prompt hash for provenance
    try:
        prompt_text = Path("prompt.txt").read_text(encoding="utf-8", errors="replace")
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]
    except Exception:
        prompt_hash = "unknown"

    return {
        "checkpoint_type": "tier1_mechanical",
        "session_id": SESSION_ID,
        "step_count": autonomous_steps,
        "timestamp": get_current_time(),
        "timestamp_iso": datetime.datetime.now().isoformat(),
        "prompt_hash": prompt_hash,
        "tool_snapshot": snapshot,
    }

# --- M1 Step 1.2: Atomic checkpoint file write (temp+rename) ---
def write_checkpoint_file(checkpoint_data):
    """Atomically write checkpoint JSON to checkpoints/<session>/<ts>.json.

    Uses temp-file + os.replace for atomicity. Returns the Path on success,
    or None on failure (never raises — file write failure must not crash the loop).
    Per v4 write-ordering: file is written BEFORE any send attempt.
    """
    try:
        session_dir = CHECKPOINT_DIR / checkpoint_data.get("session_id", "unknown")
        session_dir.mkdir(parents=True, exist_ok=True)
        # Filename-safe timestamp: 20260904T215400
        ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        dest = session_dir / f"{ts}.json"
        # Avoid collision if two checkpoints land in the same second
        if dest.exists():
            dest = session_dir / f"{ts}_{uuid.uuid4().hex[:4]}.json"
        tmp = session_dir / f"{ts}.json.tmp"
        tmp.write_text(json.dumps(checkpoint_data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(dest))
        return dest
    except Exception as error:
        print(f"CHECKPOINT_FILE_WRITE_FAILED: {type(error).__name__}: {error}")
        # Clean up temp file if it exists
        try:
            if 'tmp' in dir() and tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return None

# --- M1 Step 1.3: Human-readable checkpoint via normal send path ---
def format_checkpoint_message(checkpoint_data, checkpoint_path):
    """Format a human-readable checkpoint summary from Tier-1 data.

    Returns a concise string suitable for sending through the channel.
    """
    lines = [
        f"[CHECKPOINT] Turn budget exhausted after {checkpoint_data.get('step_count', '?')} autonomous steps without a send.",
    ]
    snapshot = checkpoint_data.get("tool_snapshot", [])
    if snapshot:
        lines.append(f"Last {len(snapshot)} tool calls:")
        for i, entry in enumerate(snapshot, 1):
            name = entry.get("tool_name", "?")
            output = entry.get("output_truncated", "")
            lines.append(f"  {i}. {name}: {output}")
    else:
        lines.append("(no tool calls in snapshot)")
    if checkpoint_path:
        lines.append(f"Checkpoint file: {checkpoint_path}")
    else:
        lines.append("(checkpoint file write failed — this is the human-readable fallback)")
    lines.append(f"Session: {checkpoint_data.get('session_id', '?')}")
    return "\n".join(lines)

def send_checkpoint_message(checkpoint_data, checkpoint_path):
    """Send a human-readable checkpoint summary via the normal send tool.

    Best-effort: never raises. Returns True on success, False on failure.
    Per v4 write-ordering this is called AFTER the file write.
    """
    try:
        message = format_checkpoint_message(checkpoint_data, checkpoint_path)
        result = invoke_dynamic(Path("tools/send.py"), "run",
                                channel=CHECKPOINT_CHANNEL, content=message)
        if not result["ok"]:
            print(f"CHECKPOINT_SEND_FAILED: {result['error']}")
            return False
        send_result = result["result"]
        if send_result != "SUCCESS":
            print(f"CHECKPOINT_SEND_NONSUCCESS: {send_result}")
            return False
        print(f"CHECKPOINT_SENT via channel={CHECKPOINT_CHANNEL}")
        return True
    except Exception as error:
        print(f"CHECKPOINT_SEND_EXCEPTION: {type(error).__name__}: {error}")
        return False

# --- M2 Step 2.1: Threaded LLM call wrapper with deadline T ---
# Background branch state (populated when ITER_CONCURRENCY_ENABLED)
_branch_lock = threading.Lock()
_active_branch = None  # holds BranchState or None

class BranchState:
    """State for a promoted background LLM call branch (R11: deep copy, R12: separate client)."""
    def __init__(self, branch_id, branch_client, branch_messages, thread, result_container):
        self.branch_id = branch_id
        self.branch_client = branch_client
        self.branch_messages = branch_messages  # deep copy per R11
        self.thread = thread
        self.result_container = result_container
        self.created_at = time.time()
        self.completed = False

def _bg_llm_thread_target(llm_client, model, messages, tools, tool_choice, max_tokens, extra_body, result_container):
    """Thread target for background LLM call; stores result in result_container.

    On exception (R14): if the call was promoted to a background branch
    (branch_id available in result_container), pushes an error marker
    (type + bounded message) onto _merge_queue and frees the branch slot.
    The main loop's drain_merge_queue() surfaces the error as a normal
    experience entry (R6 single-writer: only the main thread appends to
    experience, so the marker goes through the queue, not directly).
    """
    try:
        response = llm_client.chat.completions.create(
            model=model, messages=messages, tools=tools,
            tool_choice=tool_choice, max_tokens=max_tokens, extra_body=extra_body,
        )
        result_container["ok"] = True
        result_container["response"] = response
        # M3 Step 3.5: if promoted, run the branch mini-loop (R20: step budget + checkpoint queuing)
        branch_id = result_container.get("branch_id")
        if branch_id:
            branch_client = result_container.get("branch_client")
            branch_messages = result_container.get("branch_messages")
            if branch_client is not None and branch_messages is not None:
                _bg_branch_mini_loop(branch_id, branch_client, branch_messages, response, result_container)
    except Exception as e:
        result_container["ok"] = False
        result_container["error"] = f"{type(e).__name__}: {e}"
        # R14: push error marker to merge queue and free branch slot
        branch_id = result_container.get("branch_id")
        if branch_id:
            error_marker = {
                "role": "system",
                "content": (
                    f"[BACKGROUND_BRANCH_ERROR] branch_id={branch_id} "
                    f"error={type(e).__name__}: {str(e)[:500]}"
                ),
                "branch": branch_id,
                "error": True,
                "error_type": type(e).__name__,
                "error_message": str(e)[:500],
            }
            _merge_queue.put(error_marker)
            # Free the branch slot if we're still the active branch
            global _active_branch
            with _branch_lock:
                if _active_branch is not None and _active_branch.branch_id == branch_id:
                    _active_branch = None
            print(f"BACKGROUND_ERROR: branch_id={branch_id} error={type(e).__name__}: {e}")

# --- M3 Step 3.5: Background branch mini-loop (R20: branch step budget + checkpoint queuing) ---
def _bg_branch_mini_loop(branch_id, branch_client, branch_messages, initial_response, result_container):
    """Background branch mini-loop after promotion (R20: branch step budget + checkpoint queuing).

    Runs up to BRANCH_STEP_BUDGET follow-up steps in the background thread:
    - Pushes assistant + tool entries to _merge_queue (tagged with branch id).
    - Makes follow-up LLM calls with branch_client on branch_messages (deep copy, R11).
    - On step-budget exhaustion: queues Tier-1 checkpoint data to _merge_queue
      (R20: never writes files directly — the main thread handles file write + send).
    - On exception in follow-up LLM call: pushes error marker (R14) and frees slot.
    - On normal completion (no more tool calls): frees slot.

    Flag-off: never called; threaded_llm_call is behind ITER_CONCURRENCY_ENABLED.
    """
    global _active_branch
    response = initial_response
    branch_steps = 0

    # Load tools once at the start (stateless subprocesses; coherence model: snapshot)
    inops, _omitted, _tool_errors = load_tools()
    tools = native_tools(inops)

    while branch_steps < BRANCH_STEP_BUDGET:
        message = response.choices[0].message

        # Build assistant entry for merge queue (tagged) and branch_messages (untagged)
        assistant_entry = {key: value for key, value in message.model_dump(exclude_none=True).items()
                          if KEEP_REASONING_IN_EPISODE or key not in ("reasoning", "reasoning_details", "reasoning_content")}
        _merge_queue.put({**assistant_entry, "branch": branch_id})
        branch_messages.append(assistant_entry)

        if not message.tool_calls:
            break  # No more tool calls — branch is done

        # Execute tool calls (stateless subprocesses)
        for tool_call in message.tool_calls[:MAX_TOOL_CALLS]:
            tool_name = tool_call.function.name
            try:
                tool_arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as error:
                tool_arguments = tool_call.function.arguments
                ret = f"Invalid tool arguments from model: {error}"
            else:
                try:
                    if tool_name not in inops:
                        ret = f"Unknown tool: {tool_name!r}"
                    elif not isinstance(tool_arguments, dict):
                        ret = "Tool arguments must be a JSON object"
                    else:
                        result = invoke_dynamic(inops[tool_name][0], "run", **tool_arguments)
                        ret = result["result"] if result["ok"] else f"Tool execution failed: {result['error']}"
                except Exception as error:
                    ret = f"Tool execution failed: {type(error).__name__}: {error}"
            ret = str(ret)
            if len(ret) > MAX_TOOL_OUTPUT_CHARS:
                ret = ret[:MAX_TOOL_OUTPUT_CHARS] + " [TRUNCATED]"
            tool_content = "Step " + get_current_time() + ": " + ret
            _merge_queue.put({"role": "tool", "tool_call_id": tool_call.id, "content": tool_content, "branch": branch_id})
            branch_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_content})

        branch_steps += 1
        if branch_steps >= BRANCH_STEP_BUDGET:
            break

        # Make follow-up LLM call with branch_client (R12: separate client)
        try:
            response = branch_client.chat.completions.create(
                model=MODEL, messages=branch_messages, tools=tools,
                tool_choice="required", max_tokens=MAX_TOKENS,
                extra_body={"enable_thinking": True},
            )
        except Exception as e:
            # R14: push error marker and free slot
            error_marker = {
                "role": "system",
                "content": (
                    f"[BACKGROUND_BRANCH_ERROR] branch_id={branch_id} "
                    f"error={type(e).__name__}: {str(e)[:500]}"
                ),
                "branch": branch_id,
                "error": True,
                "error_type": type(e).__name__,
                "error_message": str(e)[:500],
            }
            _merge_queue.put(error_marker)
            with _branch_lock:
                if _active_branch is not None and _active_branch.branch_id == branch_id:
                    _active_branch = None
            print(f"BACKGROUND_ERROR: branch_id={branch_id} error={type(e).__name__}: {e}")
            return

    # Check if we exited due to step budget exhaustion
    if branch_steps >= BRANCH_STEP_BUDGET:
        # R20: Queue Tier-1 checkpoint data to main thread (never write files directly)
        checkpoint_data = extract_tier1_checkpoint(branch_messages, branch_steps)
        checkpoint_data["branch"] = branch_id
        checkpoint_data["_checkpoint_payload"] = True
        _merge_queue.put(checkpoint_data)
        print(f"BRANCH_CHECKPOINT_QUEUED: branch_id={branch_id} steps={branch_steps}")

    # Free the branch slot (compare-and-swap to avoid racing with deadline check)
    with _branch_lock:
        if _active_branch is not None and _active_branch.branch_id == branch_id:
            _active_branch = None
    print(f"BRANCH_COMPLETE: branch_id={branch_id} steps={branch_steps}")


def threaded_llm_call(llm_client, model, messages, tools, tool_choice, max_tokens, extra_body):
    """LLM call with deadline ITER_PROMOTE_SECONDS.

    Starts the call in a foreground daemon thread with join timeout T.
    - If the call completes within T: returns (response, None) — identical to direct call.
    - If T expires: promotes to a background branch with a deep copy of messages (R11),
      a separate OpenAI client (R12), and branch id bg-<uuid8>. Returns (None, BranchState).

    The original thread continues running (R9: no token waste). The branch's
    result_container is populated when the thread completes; _active_branch
    holds the branch for merge-queue integration (step 2.2).

    Flag-off: not called; the existing direct client.chat.completions.create path is used.
    """
    result_container = {}
    thread = threading.Thread(
        target=_bg_llm_thread_target,
        args=(llm_client, model, messages, tools, tool_choice, max_tokens, extra_body, result_container),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=ITER_PROMOTE_SECONDS)

    if thread.is_alive():
        # Deadline expired — promote to background branch
        branch_id = f"bg-{uuid.uuid4().hex[:8]}"
        result_container["branch_id"] = branch_id  # R14: thread reads this on error to push marker
        bg_messages = copy.deepcopy(messages)
        bg_client = openai.OpenAI(
            api_key=API_KEY, base_url=BASE_URL,
            timeout=LLM_TIMEOUT, max_retries=0,
            default_headers={"X-APC-Tenant": "iter-bg", "x-session-id": SESSION_ID, "x-branch-id": branch_id},
        )
        # M3 Step 3.5: store branch client + messages for mini-loop access (R20)
        result_container["branch_client"] = bg_client
        result_container["branch_messages"] = bg_messages
        branch = BranchState(
            branch_id=branch_id,
            branch_client=bg_client,
            branch_messages=bg_messages,
            thread=thread,
            result_container=result_container,
        )
        with _branch_lock:
            global _active_branch
            _active_branch = branch
        print(f"LLM_PROMOTED: branch_id={branch_id} deadline={ITER_PROMOTE_SECONDS}s")
        return None, branch

    # Call completed within deadline
    if result_container.get("ok"):
        return result_container["response"], None
    else:
        raise Exception(f"Background LLM call failed: {result_container.get('error', 'unknown')}")

# --- M2 Step 2.2: Merge queue + double drain (R15) + single-writer + tagged entries (R16) ---
_merge_queue = queue.Queue()  # background→main merge queue (R15)

def _build_tool_call_map(messages):
    """Build a map from tool_call_id → (tool_name, arguments) from assistant messages.

    Used by drain_merge_queue for R16 supersede detection.
    """
    lookup = {}
    for entry in messages:
        if entry.get("role") == "assistant" and entry.get("tool_calls"):
            for tc in entry["tool_calls"]:
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    lookup[tc.get("id")] = (fn.get("name", ""), fn.get("arguments", ""))
    return lookup

def drain_merge_queue():
    """Drain all pending entries from the merge queue into experience (R15).

    Pops all entries non-blocking, ensures each has a "branch" tag (R16),
    annotates duplicate tool calls with "superseded_by" (R16), extends
    experience, and saves. Single-writer: only called from the main loop
    thread (R6 single-writer discipline).

    Returns the number of entries merged. When the queue is empty (flag off
    or no active branch), returns 0 and is a pure no-op.
    """
    # Collect all pending entries, separating checkpoint payloads (R20) from regular entries
    merged_entries = []
    checkpoint_payloads = []
    while True:
        try:
            entry = _merge_queue.get_nowait()
        except queue.Empty:
            break
        if not isinstance(entry, dict):
            continue
        # R20: detect checkpoint payloads queued by background branch — handle separately
        if entry.get("_checkpoint_payload"):
            checkpoint_payloads.append(entry)
            continue
        # Ensure branch tag is present (R16)
        if "branch" not in entry:
            entry["branch"] = "unknown"
        merged_entries.append(entry)

    # R20: Main thread handles checkpoint file write + send (single-writer discipline)
    for cp in checkpoint_payloads:
        cp_data = {k: v for k, v in cp.items() if k not in ("branch", "_checkpoint_payload")}
        cp_path = write_checkpoint_file(cp_data)
        if cp_path:
            print(f"BRANCH_CHECKPOINT_FILE_WRITTEN: {cp_path}")
        else:
            print("BRANCH_CHECKPOINT_FILE_WRITE_FAILED — will still attempt send")
        send_checkpoint_message(cp_data, cp_path)
        # Add a system marker to experience so the LLM sees the branch checkpoint
        experience.append({
            "role": "system",
            "content": f"[BACKGROUND_BRANCH_CHECKPOINT] branch={cp.get('branch', '?')} steps={cp_data.get('step_count', '?')} file={cp_path}",
            "branch": cp.get("branch", "unknown"),
        })

    if not merged_entries:
        save_experience(experience) if checkpoint_payloads else None
        return len(checkpoint_payloads)

    # R16: supersede annotation for duplicate tool calls
    # Build tool_call_id → (tool_name, arguments) from merged assistant entries
    merged_call_lookup = _build_tool_call_map(merged_entries)

    # Build (tool_name, arguments) → first tool-entry index from existing experience
    existing_call_lookup = _build_tool_call_map(experience)
    existing_tool_index = {}  # (tool_name, arguments) → index in experience
    for i, entry in enumerate(experience):
        if entry.get("role") != "tool":
            continue
        tc_id = entry.get("tool_call_id")
        if tc_id and tc_id in existing_call_lookup:
            key = existing_call_lookup[tc_id]
            if key not in existing_tool_index:
                existing_tool_index[key] = i  # first occurrence only

    # Annotate duplicate tool entries with superseded_by (R16)
    for entry in merged_entries:
        if entry.get("role") != "tool":
            continue
        tc_id = entry.get("tool_call_id")
        if tc_id and tc_id in merged_call_lookup:
            key = merged_call_lookup[tc_id]
            if key in existing_tool_index:
                entry["superseded_by"] = str(existing_tool_index[key])

    # Append all entries to experience (R6: single-writer — only main thread)
    for entry in merged_entries:
        experience.append(entry)
    merged = len(merged_entries)
    save_experience(experience)
    print(f"MERGE_DRAINED: {merged} entries from background branch(es)")
    return merged

# --- M3 Step 3.1: BACKGROUND_DEADLINE — abandon + marker + slot frees (R13) ---
def check_background_deadline():
    """Check if the active background branch has exceeded BACKGROUND_DEADLINE (R13).

    If the branch has been running longer than BACKGROUND_DEADLINE seconds:
    - its results are discarded (the daemon thread continues but we ignore it);
    - an abandon marker is queued to _merge_queue with branch id and timing;
    - the branch slot is freed (_active_branch = None), allowing a new promotion.

    Returns True if a branch was abandoned, False otherwise.
    Flag-off: never called; _active_branch is always None when flag is off.
    """
    global _active_branch
    with _branch_lock:
        branch = _active_branch
        if branch is None:
            return False
        elapsed = time.time() - branch.created_at
        if elapsed <= BACKGROUND_DEADLINE:
            return False
        # Branch has exceeded the deadline — abandon it
        branch_id = branch.branch_id
        has_result = bool(branch.result_container.get("ok", False))
        _active_branch = None  # free the slot (R13)
    # Queue abandon marker (R13: "an abandon marker is queued")
    abandon_marker = {
        "role": "system",
        "content": (
            f"[BACKGROUND_BRANCH_ABANDONED] branch_id={branch_id} "
            f"elapsed={elapsed:.1f}s deadline={BACKGROUND_DEADLINE}s. "
            f"LLM call completed: {has_result}. Results discarded."
        ),
        "branch": branch_id,
        "abandoned": True,
    }
    _merge_queue.put(abandon_marker)
    print(f"BACKGROUND_ABANDONED: branch_id={branch_id} elapsed={elapsed:.1f}s deadline={BACKGROUND_DEADLINE}s llm_completed={has_result}")
    return True

# --- M3 Step 3.3: Shutdown protocol (R17: SIGTERM/SIGINT stop event, 5s grace, drain, save, exit) ---
SHUTDOWN_GRACE = int(os.getenv("ITER_SHUTDOWN_GRACE", "5"))
_shutdown_event = threading.Event()

def _iter_signal_handler(signum, frame):
    """Signal handler for SIGTERM/SIGINT: set the shutdown event (R17).

    Best-effort: only sets the event; the main loop performs the actual
    graceful shutdown in graceful_shutdown().
    """
    try:
        sig_name = signal.Signals(signum).name
    except (AttributeError, ValueError):
        sig_name = str(signum)
    print(f"SHUTDOWN_SIGNAL: {sig_name} received, setting shutdown event")
    _shutdown_event.set()

def _install_signal_handlers():
    """Install SIGTERM/SIGINT handlers for graceful shutdown (R17).

    Best-effort: if signal installation fails (e.g. not in main thread),
    logs the error and continues — the loop still checks _shutdown_event
    which can be set by other means.
    """
    try:
        signal.signal(signal.SIGTERM, _iter_signal_handler)
        signal.signal(signal.SIGINT, _iter_signal_handler)
        print("SIGNAL_HANDLERS_INSTALLED: SIGTERM, SIGINT")
    except (ValueError, OSError) as e:
        print(f"SIGNAL_HANDLER_INSTALL_FAILED: {type(e).__name__}: {e}")

def graceful_shutdown():
    """Perform graceful shutdown: wait grace, drain, save, exit (R17).

    Called from the main loop when _shutdown_event is set.
    - Wait up to SHUTDOWN_GRACE seconds for any active branch to push results.
    - Drain the merge queue (R15).
    - Save experience (R6: single-writer — only main thread calls save).
    - Exit cleanly. Branch threads are daemon threads so they cannot block exit.
    """
    print(f"SHUTDOWN: grace={SHUTDOWN_GRACE}s")
    global _active_branch
    deadline = time.time() + SHUTDOWN_GRACE
    while time.time() < deadline:
        with _branch_lock:
            branch = _active_branch
        if branch is None:
            break
        # Check if branch thread has completed (ok key present = success or error)
        if branch.result_container.get("ok") is not None:
            break
        time.sleep(0.1)
    drained = drain_merge_queue()
    save_experience(experience)
    print(f"SHUTDOWN_COMPLETE: drained={drained} experience_len={len(experience)}")
    sys.exit(0)

# --------------------------------------------------------------------
# 3. Dynamic components:
# --------------------------------------------------------------------
def load_tools():
    inops = {}
    errors = []
    paths = [path for path in sorted(Path("tools").glob("*.py")) if not path.name.startswith("_")]
    for path in paths[:MAX_TOOLS]:
        try:
            result = invoke_dynamic(path, "__tool_metadata__")
            if not result["ok"]:
                raise RuntimeError(result["error"])
            metadata = result["result"]
            inops[path.stem] = (path, metadata["description"], metadata["parameters"])
        except Exception as error:
            errors.append(f"[TOOL ERROR in {path}: {type(error).__name__}: {error}. Repair {path} if needed.]")
    return inops, len(paths) - MAX_TOOLS, "\n".join(errors)

def native_tools(inops):
    tools = []
    for name, (path, description, parameters) in inops.items():
        tools.append({"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": { parameter: { "type": "string" } for parameter in parameters }, "required": [parameter for parameter in parameters], "additionalProperties": False}}})
    return tools

def load_transformation_descriptions():
    entries = []
    for path in sorted(Path("transformations").glob("*.py")):
        if path.name.startswith("_"):
            continue
        result = invoke_dynamic(path, "__description__")
        if result["ok"]:
            entries.append(f"{path.stem}: {result['result']}")
        else:
            entries.append(f"{path.stem}: [DESCRIPTION MISSING]")
    return "\n".join(entries)

def apply_transformation(messages, tools):
    errors = []
    paths = sorted(path for path in Path("transformations").glob("*.py") if not path.name.startswith("_"))
    for path in paths:
        try:
            result = invoke_dynamic(path, "transform", messages, tools)
            if not result["ok"]:
                raise RuntimeError(result["error"])
            messages, tools = result["result"]
        except Exception as error:
            errors.append(f"[RUNTIME ERROR in {path}: {type(error).__name__}: {error}. Repair {path} if needed.]")
    return messages, tools, "\n".join(errors)

# --------------------------------------------------------------------
# 4. Main loop
# --------------------------------------------------------------------
try:
    with open("experience.json", "r", encoding="utf-8") as file:
        experience = json.load(file)
except FileNotFoundError:
    experience = []
SESSION_ID = str(uuid.uuid4())
client = openai.OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=LLM_TIMEOUT, max_retries=0, default_headers={"X-APC-Tenant": "iter", "x-session-id": SESSION_ID})
time.sleep(INIT_WAIT)
Path("memory").mkdir(exist_ok=True)
Path("transformations").mkdir(exist_ok=True)
post_task_mode, autonomous_steps, new_burst = False, 0, True
send_since_checkpoint = False
pending_event_append = resume_claimed()
cleanup_interval = MAX_EXPERIENCE_SIZE - RETAIN_EXPERIENCE_SIZE
cleanup_bucket = len(experience) // cleanup_interval
if ITER_CONCURRENCY_ENABLED:
    _install_signal_handlers()
while True:
    # M3 Step 3.3: shutdown check (R17: SIGTERM/SIGINT → stop event → grace → drain → save → exit)
    if ITER_CONCURRENCY_ENABLED and _shutdown_event.is_set():
        graceful_shutdown()
    current_bucket = len(experience) // cleanup_interval
    if current_bucket > cleanup_bucket:
        for i, old_message in enumerate(experience):
            if i < len(experience) - RETURN_VALUE_PRESERVE_MESSAGES:
                if old_message.get("role") == "tool" and len(old_message.get("content", "")) > RETURN_VALUE_PRESERVE:
                    old_message["content"] = old_message.get("content", "")[:RETURN_VALUE_PRESERVE] + " [TRUNCATED]"
                for key in ("reasoning", "reasoning_details", "reasoning_content"):
                    old_message.pop(key, None)
        cleanup_bucket = current_bucket
    if len(experience) >= MAX_EXPERIENCE_SIZE:
        experience = experience[-RETAIN_EXPERIENCE_SIZE:]
        cleanup_bucket = len(experience) // cleanup_interval
    while experience and experience[0].get("role") == "tool":
        experience = experience[1:]
    # M3 Step 3.1: check background deadline before drain (R13)
    if ITER_CONCURRENCY_ENABLED:
        check_background_deadline()
    # M2 Step 2.2: double drain — (a) top of loop before receive() (R15)
    if ITER_CONCURRENCY_ENABLED:
        drain_merge_queue()
    history_checkpoint = len(experience) #before user input
    try:
        time.sleep(DEFAULT_DELAY)
        print("BEFORE RECEIVE")
        event_append = pending_event_append or receive()
        print("AFTER RECEIVE")
        if event_append:
            autonomous_steps, new_burst, post_task_mode = 0, False, False
            send_since_checkpoint = False
            print("IN FROM CHANNEL " + event_append)
            experience += [{"role": "user", "content": "Step " + get_current_time() + ": " + event_append}]
            save_experience(experience)
            pending_event_append = ""
            base_temporary_message = []
        elif new_burst:
            post_task_mode, new_burst = True, False
            base_temporary_message = [{"role": "user", "content": "Step " + get_current_time() + ": [TASK COMPLETED. DO NOT RE-SEND THE COMPLETED RESPONSE BUT SEND IN CASE YOU FORGOT. NOW QUERY FOR AND PICK A TASK BASED ON YOUR GOALS, PREFERABLY MEMORY CONSOLIDATION: FINDING EPISODES WHICH SUPPORT / CONTRADICT LTM ITEMS, LINKING EPISODES, PROMOTING USEFUL MEMORIES]"}]
        elif post_task_mode:
            base_temporary_message = [{"role": "user", "content": "Step " + get_current_time() + ": [NO NEW USER INPUT. CONTINUE AUTONOMOUS WORK. DO NOT REPEAT THE PREVIOUS RESPONSE. ONLY USE send FOR GENUINELY NEW INFORMATION OR WHEN USER INPUT IS NEEDED.]"}]
        else:
            base_temporary_message = [{"role": "user", "content": "Step " + get_current_time() + ": [NO ADDITIONAL USER INPUT. CONTINUE THE CURRENT USER TASK.]"}]
        history_checkpoint = len(experience) #as we want not to loose user input even when exception
        retry_message = None
        _promoted = False
        while True:
            temporary_message = list(base_temporary_message)
            if retry_message:
                temporary_message += retry_message
            INOPS, omitted_tools, tool_load_error = load_tools()
            if tool_load_error:
                temporary_message += [{"role": "user", "content": tool_load_error}]
            if omitted_tools > 0:
                temporary_message += [{"role": "user", "content": f"[TOOL LIMIT REACHED: {omitted_tools} tools are currently omitted. Consolidate or remove tools if they are needed.]"}]
            TOOLS = native_tools(INOPS)
            TRANSFORMATIONS = load_transformation_descriptions()
            memory_paths = [path for path in sorted(Path("memory").rglob("*")) if path.is_file() and not any(part.startswith("_") for part in path.relative_to("memory").parts)]
            memory_contents = [(path, path.read_text(encoding="utf-8", errors="replace").strip()) for path in memory_paths]
            memory_len = sum(len(content) for _, content in memory_contents)
            if memory_len <= MAX_MEMORY_CHARS:
                MARGIN = MAX_MEMORY_CHARS - memory_len
                MEMORY = f"[{MARGIN} CHARACTERS BELOW MAXIMUM]\n./memory/:\n"
                MEMORY += "\n\n".join(f"{path}:\n{content}" for path, content in memory_contents)
            else:
                DIFF = memory_len - MAX_MEMORY_CHARS
                MEMORY = "./memory/:\n" + "\n".join(str(path) for path in memory_paths)
                temporary_message += [{"role": "user", "content": f"[MEMORY FOLDER TOTAL CHARACTER CAPACITY BY FILES NOT BEGINNING WITH _ EXCEEDED BY {DIFF} CHARS. FIX THIS FIRST.]"}]
            # M2 Step 2.2: double drain — (b) immediately before building messages (R15)
            if ITER_CONCURRENCY_ENABLED:
                drain_merge_queue()
            request_messages = [{"role": "system", "content": "prompt.txt:\n" + open("prompt.txt", encoding="utf-8", errors="replace").read().strip() + "\n\n./transformations/:\n" + TRANSFORMATIONS + "\n\n" + MEMORY}] + experience + temporary_message
            request_messages, request_tools, transformation_error = apply_transformation(request_messages, TOOLS)
            if transformation_error:
                request_messages += [{"role": "user", "content": transformation_error}]
            print("BEFORE LLM")
            if ITER_CONCURRENCY_ENABLED:
                response, _branch = threaded_llm_call(client, MODEL, request_messages, request_tools, "required", MAX_TOKENS, {"enable_thinking": True})
                if response is None:
                    _promoted = True
                    break
            else:
                response = client.chat.completions.create(model=MODEL, messages=request_messages, tools=request_tools, tool_choice="required", max_tokens=MAX_TOKENS, extra_body={ "enable_thinking": True})
            print("AFTER LLM", response)
            message = response.choices[0].message
            if message.content:
                message.content += "\n[NOT DELIVERED TO ANY CHANNEL. IF THIS WAS INTENDED AS COMMUNICATION, USE send.]"
            if message.tool_calls:
                message.tool_calls = message.tool_calls[:MAX_TOOL_CALLS]
                break
            try:
                if response.choices[0].finish_reason == "length":
                    retry_message = [{"role": "user", "content": "[OUTPUT TOKEN LIMIT REACHED. CALL THE REQUIRED TOOL CONCISELY.]"}]
                else:
                    retry_message = [{"role": "user", "content": f"[YOUR PREVIOUS RESPONSE CONTAINED NO TOOL CALL AND WAS NOT DELIVERED. CALL AT LEAST ONE TOOL NOW. IF YOU INTENDED THIS CONTENT AS COMMUNICATION, USE send: {message.content!r}]"}]
            except:
                retry_message = [{"role": "user", "content": f"[YOUR PREVIOUS RESPONSE CONTAINED NO TOOL CALL AND WAS NOT DELIVERED. CALL AT LEAST ONE TOOL NOW. IF YOU INTENDED THIS CONTENT AS COMMUNICATION, USE send: {message.content!r}]"}]
        if _promoted:
            continue
        print(f"RESPONSE {response}\nFINISH_REASON {response.choices[0].finish_reason}\nUSAGE {response.usage}")
        experience += [{key: value for key, value in message.model_dump(exclude_none=True).items() if KEEP_REASONING_IN_EPISODE or key not in ("reasoning", "reasoning_details", "reasoning_content")}]
        tool_outputs = []
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as error:
                tool_arguments = tool_call.function.arguments
                ret = f"Invalid tool arguments from model: {error}"
            else:
                try: #unless tool unknown/args formatting issue, we use the tool's INOPS function return value:
                    if tool_name not in INOPS:
                        ret = f"Unknown tool: {tool_name!r}"
                    elif not isinstance(tool_arguments, dict):
                        ret = "Tool arguments must be a JSON object"
                    else:
                        result = invoke_dynamic(INOPS[tool_name][0], "run", **tool_arguments)
                        ret = result["result"] if result["ok"] else f"Tool execution failed: {result['error']}"
                except Exception as error:
                    ret = f"Tool execution failed: {type(error).__name__}: {error}"
            ret = str(ret)
            if len(ret) > MAX_TOOL_OUTPUT_CHARS:
                ret = ret[:MAX_TOOL_OUTPUT_CHARS] + " [TRUNCATED]"
            experience += [{"role": "tool", "tool_call_id": tool_call.id, "content": "Step " + get_current_time() + ": " + ret}]
            tool_outputs += ["tool call: " + tool_name + " " + str(tool_arguments) + "\n" "tool return: " + ret]
        history_checkpoint = len(experience) #tool calls succeeded, even on later exception we won't unroll them
        save_experience(experience)
        print("Output> " + "\n".join(tool_outputs))
        autonomous_steps = 0 if event_append else autonomous_steps + 1
        called_send = any(call.function.name == "send" for call in message.tool_calls)
        called_nop = any(call.function.name == "nop" for call in message.tool_calls)
        if called_send:
            send_since_checkpoint = True
        if (not called_send
                and autonomous_steps == TURN_WATCHDOG_THRESHOLD
                and not event_append):
            # Turn-budget watchdog: the agent is close to exhausting its step
            # budget without having sent a reply. Inject a checkpoint reminder
            # so it emits a progress summary via send before the limit.
            experience += [{"role": "user", "content": (
                f"[TURN BUDGET WARNING: You are at step {autonomous_steps} of {MAX_FAST_STEPS} "
                f"without calling send. Call send NOW with a concise progress summary: "
                f"what you accomplished, what remains, and the current state. "
                f"Do not wait until the task is fully complete.")}]
            save_experience(experience)
        if called_nop:
            new_burst, autonomous_steps = True, 0
            pending_event_append = slow_wait_for_input()
        elif autonomous_steps >= MAX_FAST_STEPS:
            # M1 Step 1.1: Tier-1 mechanical checkpoint extraction (flag-guarded)
            if ITER_CHECKPOINT_ENABLED and not send_since_checkpoint:
                _checkpoint_data = extract_tier1_checkpoint(experience, autonomous_steps)
                _checkpoint_path = write_checkpoint_file(_checkpoint_data)
                if _checkpoint_path:
                    print(f"CHECKPOINT_FILE_WRITTEN: {_checkpoint_path}")
                else:
                    print("CHECKPOINT_FILE_WRITE_FAILED — will still attempt send")
                # M1 Step 1.3: human-readable send via normal tool path
                send_checkpoint_message(_checkpoint_data, _checkpoint_path)
            else:
                _checkpoint_data = None
                _checkpoint_path = None
            autonomous_steps = 0
            pending_event_append = slow_wait_for_input()
    except Exception as error:
        print(f"Output> {type(error).__name__}: {error}")
        experience = experience[:history_checkpoint]
        time.sleep(ERROR_RECOVERY_TIME)
