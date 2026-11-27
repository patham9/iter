import datetime
import inspect
import json
import os
import sys
import openai
import time
import importlib.util
import signal
import subprocess
import tempfile
import uuid
import re
import tui
import utils
from pathlib import Path

# --------------------------------------------------------------------
# 0. Configuration:
# --------------------------------------------------------------------
MAX_MEMORY_CHARS = int(os.getenv("MAX_MEMORY_CHARS", "3000"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "600"))
KEEP_REASONING_IN_EPISODE = os.getenv("KEEP_REASONING_IN_EPISODE", "True") == "True"
PRINT_CALLS = os.getenv("PRINT_CALLS", "False") == "True"
MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", "10"))
MAX_TOOL_OUTPUT_CHARS = int(os.getenv("MAX_TOOL_OUTPUT_CHARS", "5000"))
MAX_EXPERIENCE_SIZE = int(os.getenv("MAX_EXPERIENCE_SIZE", "100"))
RETAIN_EXPERIENCE_SIZE = int(os.getenv("RETAIN_EXPERIENCE_SIZE", "30"))
MAX_FAST_STEPS = int(os.getenv("MAX_FAST_STEPS", "20"))
SLOW_STEP_DELAY = int(os.getenv("SLOW_STEP_DELAY", "1"))
ERROR_RECOVERY_TIME = float(os.getenv("ERROR_RECOVERY_TIME", "1"))
RETURN_VALUE_PRESERVE = int(os.getenv("RETURN_VALUE_PRESERVE", "0"))
RETURN_VALUE_PRESERVE_MESSAGES = int(os.getenv("RETURN_VALUE_PRESERVE_MESSAGES", "10"))
DEFAULT_DELAY = float(os.getenv("DEFAULT_DELAY", "0"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "5000"))
INIT_WAIT = float(os.getenv("INIT_WAIT", "10"))
MAX_TOOLS = int(os.getenv("MAX_TOOLS", "30"))
MAX_CONTEXT_TRANSFORMATIONS = int(os.getenv("MAX_CONTEXT_TRANSFORMATIONS", "30"))
MAX_TOOL_DESCRIPTION_CHARS = int(os.getenv("MAX_TOOL_DESCRIPTION_CHARS", "500"))
DYNAMIC_TIMEOUT = float(os.getenv("DYNAMIC_TIMEOUT", "5"))
MODEL = os.getenv("LLM_MODEL", "mlx-community/gemma-4-26b-a4b-it-4bit")
BACKUP_MODEL = os.getenv("LLM_BACKUP_MODEL", "")
BASE_URL = os.getenv("BASE_URL", "http://192.168.64.1:2277/v1")
API_KEY = os.getenv("AI_API_KEY", "dummy")
TOOL_CHOICE = os.getenv("TOOL_CHOICE", "auto")


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


def invoke_dynamic(path, function, /, *args, **kwargs):
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
    # The fullscreen TUI owns stdin; collect its completed input lines.
    if tui.terminal_ui_active():
        while True:
            line = tui.poll_input()
            if not line:
                break
            events.append("[terminal] " + line)
    paths = [path for path in sorted(Path("channels").glob("*.py")) if not path.name.startswith("_")]
    for path in paths:
        if tui.terminal_ui_active() and path.stem == "terminal":
            continue  # Avoid a competing stdin reader.
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


def slow_wait_for_input():
    tui.wait(SLOW_STEP_DELAY)
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
    paths = sorted(path for path in Path("transformations").glob("*.py") if not path.name.startswith("_"))
    active_paths = paths[:MAX_CONTEXT_TRANSFORMATIONS]
    entries = []
    for path in active_paths:
        result = invoke_dynamic(path, "__description__")
        if result["ok"]:
            entries.append(f"{path.stem}: {result['result']}")
        else:
            entries.append(f"{path.stem}: [DESCRIPTION MISSING]")
    return "\n".join(entries), active_paths, max(0, len(paths) - MAX_CONTEXT_TRANSFORMATIONS)


def apply_transformation(messages, tools, paths):
    errors = []
    for path in paths:
        try:
            result = invoke_dynamic(path, "transform", messages, tools)
            if not result["ok"]:
                raise RuntimeError(result["error"])
            messages, tools = result["result"]
        except Exception as error:
            errors.append(f"[RUNTIME ERROR in {path}: {type(error).__name__}: {error}. Repair {path} if needed.]")
    return messages, tools, "\n".join(errors)


def load_memory():
    memory_paths = [path for path in sorted(Path("memory").rglob("*")) if path.is_file() and not any(part.startswith("_") for part in path.relative_to("memory").parts)]
    memory_contents = [(path, path.read_text(encoding="utf-8", errors="replace").strip()) for path in memory_paths]
    memory_len = sum(len(content) for _, content in memory_contents)
    if memory_len <= MAX_MEMORY_CHARS:
        MARGIN = MAX_MEMORY_CHARS - memory_len
        MEMORY = f"[{MARGIN} CHARACTERS BELOW MAXIMUM]\n./memory/:\n"
        MEMORY += "\n\n".join(f"{path}:\n{content}" for path, content in memory_contents)
    else:
        MEMORY = "./memory/:\n" + "\n".join(str(path) for path in memory_paths)
    return MEMORY, memory_len - MAX_MEMORY_CHARS

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
post_task_mode, autonomous_steps, new_burst, pending_event_append = False, 0, True, ""
cleanup_interval = MAX_EXPERIENCE_SIZE - RETAIN_EXPERIENCE_SIZE
cleanup_bucket = -1  # clean once after a restart; the loop then records the bucket from the loaded length
tui.header(MODEL, SESSION_ID, len(experience)) # Starts Terminal UI
while True:
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
    history_checkpoint = len(experience) #before user input
    try:
        time.sleep(DEFAULT_DELAY)
        event_append = pending_event_append or receive()
        if event_append:
            autonomous_steps, new_burst, post_task_mode = 0, False, False
            tui.incoming(event_append)
            experience += [{"role": "user", "content": "Step " + get_current_time() + ": " + event_append}]
            save_experience(experience)
            pending_event_append = ""
            base_temporary_message = []
        elif new_burst:
            post_task_mode, new_burst = True, False
            tui.status("Autonomous task selection")
            base_temporary_message = [{"role": "user", "content": "Step " + get_current_time() + ": [TASK COMPLETED. DO NOT RE-SEND THE COMPLETED RESPONSE BUT SEND IN CASE YOU FORGOT. NOW QUERY FOR AND PICK A TASK BASED ON YOUR GOALS, PREFERABLY MEMORY CONSOLIDATION: FINDING EPISODES WHICH SUPPORT / CONTRADICT LTM ITEMS, LINKING EPISODES, PROMOTING USEFUL MEMORIES]"}]
        elif post_task_mode:
            base_temporary_message = [{"role": "user", "content": "Step " + get_current_time() + ": [NO NEW USER INPUT. CONTINUE AUTONOMOUS WORK. DO NOT REPEAT THE PREVIOUS RESPONSE. ONLY USE send FOR GENUINELY NEW INFORMATION OR WHEN USER INPUT IS NEEDED.]"}]
        else:
            base_temporary_message = [{"role": "user", "content": "Step " + get_current_time() + ": [NO ADDITIONAL USER INPUT. CONTINUE THE CURRENT USER TASK.]"}]
        history_checkpoint = len(experience) #as we want not to loose user input even when exception
        retry_message = None
        while True:
            temporary_message = list(base_temporary_message)
            if retry_message:
                temporary_message += retry_message
            INOPS, omitted_tools, tool_load_error = load_tools()
            if tool_load_error:
                tui.error("TOOL !", tool_load_error)
                temporary_message += [{"role": "user", "content": tool_load_error}]
            if omitted_tools > 0:
                tui.warning("WARN", f"{omitted_tools} tools excluded (MAX_TOOLS={MAX_TOOLS})")
                temporary_message += [{"role": "user", "content": f"[TOOL LIMIT REACHED: {omitted_tools} tools are currently omitted. Consolidate or remove tools if they are needed.]"}]
            TOOLS = native_tools(INOPS)
            TRANSFORMATIONS, active_transformations, omitted_transformations = load_transformation_descriptions()
            if omitted_transformations > 0:
                tui.warning("XFORM !", f"{omitted_transformations} transformations excluded (MAX_CONTEXT_TRANSFORMATIONS={MAX_CONTEXT_TRANSFORMATIONS})")
                temporary_message += [{"role": "user", "content": f"[CONTEXT TRANSFORMATION LIMIT REACHED: {omitted_transformations} transformations are omitted and will not execute. Consolidate or remove transformations if they are needed.]"}]
            MEMORY, diff = load_memory()
            if diff > 0:
                tui.warning("MEMORY !", f"Capacity exceeded by {diff} characters")
                temporary_message += [{"role": "user", "content": f"[MEMORY FOLDER TOTAL CHARACTER CAPACITY BY FILES NOT BEGINNING WITH _ EXCEEDED BY {diff} CHARS. FIX THIS FIRST.]"}]
            request_messages = [{"role": "system", "content": "prompt.txt:\n" + open("prompt.txt", encoding="utf-8", errors="replace").read().strip() + "\n\n./transformations/:\n" + TRANSFORMATIONS + "\n\n" + MEMORY}] + experience + temporary_message
            request_messages, request_tools, transformation_error = apply_transformation(request_messages, TOOLS, active_transformations)
            if transformation_error:
                tui.error("XFORM !", transformation_error)
                request_messages += [{"role": "user", "content": transformation_error}]
            tui.llm_start()
            started = time.monotonic()
            response, used_model = utils.chat_completion(client, MODEL, BACKUP_MODEL, messages=request_messages, tools=request_tools, tool_choice=TOOL_CHOICE, max_tokens=MAX_TOKENS, extra_body={ "enable_thinking": True})
            if used_model != MODEL:
                tui.warning("BACKUP !", f"{MODEL} refused; used LLM_BACKUP_MODEL {used_model}")
            tui.llm_complete(time.monotonic() - started, response)
            message = response.choices[0].message
            if message.content:
                message.content += "\n[NOT DELIVERED TO ANY CHANNEL. IF THIS WAS INTENDED AS COMMUNICATION, USE send.]"
            if message.tool_calls:
                message.tool_calls = message.tool_calls[:MAX_TOOL_CALLS]
                break
            if response.choices[0].finish_reason == "length":
                tui.retry("Output token limit reached without a tool call")
                retry_message = [{"role": "user", "content": "[OUTPUT TOKEN LIMIT REACHED. CALL THE REQUIRED TOOL CONCISELY.]"}]
            else:
                tui.retry("No tool call returned; requesting one")
                retry_message = [{"role": "user", "content": f"[YOUR PREVIOUS RESPONSE CONTAINED NO TOOL CALL AND WAS NOT DELIVERED. CALL AT LEAST ONE TOOL NOW. IF YOU INTENDED THIS CONTENT AS COMMUNICATION, USE send: {message.content!r}]"}]
        experience += [{key: value for key, value in message.model_dump(exclude_none=True).items() if KEEP_REASONING_IN_EPISODE or key not in ("reasoning", "reasoning_details", "reasoning_content")}]
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            failed = False
            try:
                tool_arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as error:
                tool_arguments = tool_call.function.arguments
                ret = f"Invalid tool arguments from model: {error}"
                failed = True
            else:
                try: #unless tool unknown/args formatting issue, we use the tool's INOPS function return value:
                    if tool_name not in INOPS:
                        ret = f"Unknown tool: {tool_name!r}"
                        failed = True
                    elif not isinstance(tool_arguments, dict):
                        ret = "Tool arguments must be a JSON object"
                        failed = True
                    else:
                        result = invoke_dynamic(INOPS[tool_name][0], "run", **tool_arguments)
                        failed = not result["ok"]
                        ret = result["result"] if result["ok"] else f"Tool execution failed: {result['error']}"
                except Exception as error:
                    ret = f"Tool execution failed: {type(error).__name__}: {error}"
                    failed = True
            ret = str(ret)
            if len(ret) > MAX_TOOL_OUTPUT_CHARS:
                ret = ret[:MAX_TOOL_OUTPUT_CHARS] + " [TRUNCATED]"
            experience += [{"role": "tool", "tool_call_id": tool_call.id, "content": "Step " + get_current_time() + ": " + ret}]
            tui.tool_call(tool_name, tool_arguments, ret, failed)
        history_checkpoint = len(experience) #tool calls succeeded, even on later exception we won't unroll them
        save_experience(experience)
        autonomous_steps = 0 if event_append else autonomous_steps + 1
        called_nop = any(call.function.name == "nop" for call in message.tool_calls)
        if called_nop:
            new_burst, autonomous_steps = True, 0
            pending_event_append = slow_wait_for_input()
        elif autonomous_steps >= MAX_FAST_STEPS:
            autonomous_steps = 0
            pending_event_append = slow_wait_for_input()
    except KeyboardInterrupt:
        tui.stopped()
        break
    except Exception as error:
        tui.failure(f"{type(error).__name__}: {error}")
        experience = experience[:history_checkpoint]
        time.sleep(ERROR_RECOVERY_TIME)
