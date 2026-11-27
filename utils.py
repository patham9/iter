import inspect
import json
import re
import os
import sys
import openai
import importlib.util
import uuid
import time
import tui
from pathlib import Path

# --------------------------------------------------------------------
# 1. Dynamic execution (worker side, started by invoke_dynamic of utils.metta):
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
            result = {"description": str(module.DESCRIPTION), "parameters": [parameter.name for parameter in parameters]}
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

if len(sys.argv) > 1 and sys.argv[1] == "--invoke":
    dynamic_worker()
    sys.exit(0)

# --------------------------------------------------------------------
# 2. Python API access for utils.metta (imported via pyimport)
# --------------------------------------------------------------------
CLIENT = None

def init_client(base_url, api_key, timeout):
    global CLIENT
    CLIENT = openai.OpenAI(api_key=str(api_key), base_url=str(base_url), timeout=timeout, max_retries=0, default_headers={"X-APC-Tenant": "iter", "x-session-id": str(uuid.uuid4())})
    return True

def exception_text(error):
    return f"{type(error).__name__}: {error}"

# LLM call with refusal fallback: always tries the primary model first. If no usable
# message is returned (refusal, empty message, content filter, or API error), the same
# request is retried once with backup_model (BACKUP_MODEL from iter.metta, if set).

def is_refusal(response):
    """True if the response did not return a usable LLM message."""
    try:
        choice = response.choices[0]
        message = choice.message
    except (AttributeError, IndexError, TypeError):
        return True
    if message is None:
        return True
    if str(getattr(choice, "finish_reason", "") or "").lower() in ("refusal", "content_filter"):
        return True
    if getattr(message, "refusal", None):
        return True
    return not (getattr(message, "content", None) or getattr(message, "tool_calls", None))

def create_with_backup(client, model, backup_model, **kwargs):
    """Returns (response, used_model). Primary first, backup if no message returned."""
    use_backup = bool(backup_model) and backup_model != model
    try:
        response = client.chat.completions.create(model=model, **kwargs)
        if not use_backup or not is_refusal(response):
            return response, model
    except Exception as error:
        if not use_backup:
            raise
        try:
            return client.chat.completions.create(model=backup_model, **kwargs), backup_model
        except Exception:
            raise error
    return client.chat.completions.create(model=backup_model, **kwargs), backup_model

def chat_completion(messages, tools, model, backup_model, tool_choice, max_tokens): #messages and tools as JSON text, returns message_json finish_reason response usage
    response, used_model = create_with_backup(CLIENT, str(model), str(backup_model), messages=json.loads(str(messages)), tools=json.loads(str(tools)), tool_choice=str(tool_choice), max_tokens=int(max_tokens), extra_body={ "enable_thinking": True})
    if used_model != str(model):
        tui.warning("BACKUP !", f"{model} returned no usable message; used LLM_BACKUP_MODEL {used_model}")
    global LAST_RESPONSE
    LAST_RESPONSE = response
    choice = response.choices[0]
    return [json.dumps(choice.message.model_dump(exclude_none=True), ensure_ascii=False), str(choice.finish_reason), str(response), str(response.usage)]

# --------------------------------------------------------------------
# Colored terminal output (tui.py), called from iter.metta
# --------------------------------------------------------------------
LAST_RESPONSE = None
LLM_STARTED = 0.0

def tui_header(model, history_count):
    tui.header(str(model), str(uuid.uuid4()), int(history_count))
    return True

def tui_incoming(message):
    tui.incoming(str(message)); return True

def tui_status(message):
    tui.status(str(message)); return True

def tui_warning(label, message):
    tui.warning(str(label), str(message)); return True

def tui_error(label, message):
    tui.error(str(label), str(message)); return True

def tui_retry(message):
    tui.retry(str(message)); return True

def tui_failure(message):
    tui.failure(str(message)); return True

def tui_wait(seconds):
    tui.wait(int(seconds)); return True

def tui_llm_start():
    global LLM_STARTED
    LLM_STARTED = time.monotonic()
    tui.llm_start(); return True

def tui_llm_complete():
    tui.llm_complete(time.monotonic() - LLM_STARTED, LAST_RESPONSE); return True

def tui_tool_call(name, arguments, ret, failed):
    try:
        args = json.loads(str(arguments))
    except Exception:
        args = str(arguments)
    tui.tool_call(str(name), args, str(ret), str(failed) == "true"); return True

def ui_input():
    """Completed input lines of the fullscreen TUI (which owns stdin), as one event string."""
    lines = []
    while tui.terminal_ui_active():
        line = tui.poll_input()
        if not line:
            break
        lines.append("[terminal] " + line)
    return "\n".join(lines)

def ui_skip_channel(stem):
    """'yes' if the channel must be skipped to avoid a competing stdin reader."""
    return "yes" if tui.terminal_ui_active() and str(stem) == "terminal" else "no"
