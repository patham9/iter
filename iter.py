import json
import os
import sys
import time
import bridge

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
SLOW_STEP_DELAY = 10
ERROR_RECOVERY_TIME = 1 #after how long to retry when exception occurs
RETURN_VALUE_PRESERVE = 0
RETURN_VALUE_PRESERVE_MESSAGES = 10
DEFAULT_DELAY = 0 #default delay added irregard of whether in slow mode
MAX_TOKENS = 5000
INIT_WAIT = 10
MAX_TOOLS = 30
MAX_TOOL_DESCRIPTION_CHARS = 500
DYNAMIC_TIMEOUT = 5
CONFIG = json.loads(str(bridge.config()))
MODEL = CONFIG.get("model") or "z-ai/glm-5.2"
BASE_URL = (CONFIG.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")
API_KEY = CONFIG.get("api_key") or "dummy"

# --------------------------------------------------------------------
# 1. Dynamic execution:
# --------------------------------------------------------------------
def dynamic_worker(path, function, *args, **kwargs):
    try:
        with open(path, "r", encoding="utf-8") as file:
            source = file.read()
        module = {"__name__": "_dynamic_" + path.rsplit("/", 1)[-1].rsplit(".", 1)[0], "__file__": path}
        exec(source, module)
        if function == "__description__":
            result = str(module["DESCRIPTION"])
        elif function == "__tool_metadata__":
            marker = "async def run(" if "async def run(" in source else "def run("
            start = source.find(marker) + len(marker)
            end = source.find(")", start)
            parameters = []
            if start >= len(marker) and end >= start:
                for parameter in source[start:end].split(","):
                    parameter = parameter.strip()
                    if parameter and not parameter.startswith("*"):
                        parameter = parameter.split("=", 1)[0].split(":", 1)[0].strip()
                        if parameter and parameter not in ("self", "cls"):
                            parameters.append(parameter)
            description = str(module["DESCRIPTION"])
            if len(description) > MAX_TOOL_DESCRIPTION_CHARS:
                description = description[:MAX_TOOL_DESCRIPTION_CHARS] + " [DESCRIPTION TRUNCATED]"
            result = {"description": description, "parameters": parameters}
        else:
            result = module[function](*args, **kwargs)
            if function != "transform" and result is not None:
                result = str(result)
        return {"ok": True, "result": result}
    except BaseException as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}

def invoke_dynamic(path, function, *args, **kwargs):
    return dynamic_worker(path, function, *args, **kwargs)

# --------------------------------------------------------------------
# 2. Runtime helpers:
# --------------------------------------------------------------------
def get_current_time():
    current = time.localtime()
    return "%04d-%02d-%02d %02d:%02d:%02d" % (current[0], current[1], current[2], current[3], current[4], current[5])

def receive():
    events = []
    paths = ["channels/" + name for name in sorted(os.listdir("channels")) if name.endswith(".py") and not name.startswith("_")]
    for path in paths:
        try:
            result = invoke_dynamic(path, "receive")
            if not result["ok"]:
                raise RuntimeError(result["error"])
            event = result["result"]
            if event:
                events.append("[" + path.rsplit("/", 1)[-1].rsplit(".", 1)[0] + "] " + str(event))
        except Exception as error:
            events.append(f"[CHANNEL ERROR in {path}: {type(error).__name__}: {error}. Repair {path} if needed.]")
    return "\n".join(events)

async def slow_wait_for_input():
    for second in range(SLOW_STEP_DELAY):
        await bridge.sleep(1000)
        event_append = receive()
        if event_append:
            return event_append
    return ""

def save_experience(experience):
    with open("experience.tmp", "w", encoding="utf-8") as file:
        file.write(json.dumps(experience))
    try:
        os.remove("experience.json")
    except OSError:
        pass
    os.rename("experience.tmp", "experience.json")
    bridge.persist()

# --------------------------------------------------------------------
# 3. Dynamic components:
# --------------------------------------------------------------------
def load_tools():
    inops = {}
    errors = []
    paths = ["tools/" + name for name in sorted(os.listdir("tools")) if name.endswith(".py") and not name.startswith("_")]
    for path in paths[:MAX_TOOLS]:
        try:
            result = invoke_dynamic(path, "__tool_metadata__")
            if not result["ok"]:
                raise RuntimeError(result["error"])
            metadata = result["result"]
            inops[path.rsplit("/", 1)[-1].rsplit(".", 1)[0]] = (path, metadata["description"], metadata["parameters"])
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
    paths = ["transformations/" + name for name in sorted(os.listdir("transformations")) if name.endswith(".py") and not name.startswith("_")]
    for path in paths:
        result = invoke_dynamic(path, "__description__")
        if result["ok"]:
            entries.append(f"{path.rsplit('/', 1)[-1].rsplit('.', 1)[0]}: {result['result']}")
        else:
            entries.append(f"{path.rsplit('/', 1)[-1].rsplit('.', 1)[0]}: [DESCRIPTION MISSING]")
    return "\n".join(entries)

def apply_transformation(messages, tools):
    errors = []
    paths = ["transformations/" + name for name in sorted(os.listdir("transformations")) if name.endswith(".py") and not name.startswith("_")]
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
        experience = json.loads(file.read())
except OSError:
    experience = []
SESSION_ID = str(bridge.session_id())
await bridge.sleep(INIT_WAIT * 1000)
try:
    os.mkdir("memory")
except OSError:
    pass
try:
    os.mkdir("transformations")
except OSError:
    pass
post_task_mode, autonomous_steps, new_burst, pending_event_append = False, 0, True, ""
cleanup_interval = MAX_EXPERIENCE_SIZE - RETAIN_EXPERIENCE_SIZE
cleanup_bucket = len(experience) // cleanup_interval
while not bool(bridge.should_stop()):
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
        await bridge.sleep(DEFAULT_DELAY * 1000)
        print("BEFORE RECEIVE")
        event_append = pending_event_append or receive()
        print("AFTER RECEIVE")
        if event_append:
            autonomous_steps, new_burst, post_task_mode = 0, False, False
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
            memory_paths = []
            memory_folders = ["memory"]
            while memory_folders:
                folder = memory_folders.pop()
                for name in sorted(os.listdir(folder)):
                    if name.startswith("_"):
                        continue
                    path = folder + "/" + name
                    try:
                        directory = bool(os.stat(path)[0] & 0x4000)
                    except OSError:
                        directory = False
                    if directory:
                        memory_folders.append(path)
                    else:
                        memory_paths.append(path)
            memory_paths = sorted(memory_paths)
            memory_contents = []
            for path in memory_paths:
                with open(path, "r", encoding="utf-8") as file:
                    memory_contents.append((path, file.read().strip()))
            memory_len = sum(len(content) for _, content in memory_contents)
            if memory_len <= MAX_MEMORY_CHARS:
                MARGIN = MAX_MEMORY_CHARS - memory_len
                MEMORY = f"[{MARGIN} CHARACTERS BELOW MAXIMUM]\n./memory/:\n"
                MEMORY += "\n\n".join(f"{path}:\n{content}" for path, content in memory_contents)
            else:
                DIFF = memory_len - MAX_MEMORY_CHARS
                MEMORY = "./memory/:\n" + "\n".join(str(path) for path in memory_paths)
                temporary_message += [{"role": "user", "content": f"[MEMORY FOLDER TOTAL CHARACTER CAPACITY BY FILES NOT BEGINNING WITH _ EXCEEDED BY {DIFF} CHARS. FIX THIS FIRST.]"}]
            with open("prompt.txt", "r", encoding="utf-8") as file:
                request_messages = [{"role": "system", "content": "prompt.txt:\n" + file.read().strip() + "\n\n./transformations/:\n" + TRANSFORMATIONS + "\n\n" + MEMORY}] + experience + temporary_message
            request_messages, request_tools, transformation_error = apply_transformation(request_messages, TOOLS)
            if transformation_error:
                request_messages += [{"role": "user", "content": transformation_error}]
            print("BEFORE LLM")
            response = json.loads(str(await bridge.llm(BASE_URL + "/chat/completions", API_KEY, json.dumps({"model": MODEL, "messages": request_messages, "tools": request_tools, "tool_choice": "required", "max_tokens": MAX_TOKENS, "enable_thinking": True}), SESSION_ID)))
            print("AFTER LLM", response)
            message = response["choices"][0]["message"]
            if message.get("content"):
                message["content"] += "\n[NOT DELIVERED TO ANY CHANNEL. IF THIS WAS INTENDED AS COMMUNICATION, USE send.]"
            if message.get("tool_calls"):
                message["tool_calls"] = message["tool_calls"][:MAX_TOOL_CALLS]
                break
            try:
                if response["choices"][0]["finish_reason"] == "length":
                    retry_message = [{"role": "user", "content": "[OUTPUT TOKEN LIMIT REACHED. CALL THE REQUIRED TOOL CONCISELY.]"}]
                else:
                    retry_message = [{"role": "user", "content": f"[YOUR PREVIOUS RESPONSE CONTAINED NO TOOL CALL AND WAS NOT DELIVERED. CALL AT LEAST ONE TOOL NOW. IF YOU INTENDED THIS CONTENT AS COMMUNICATION, USE send: {message.get('content')!r}]"}]
            except:
                retry_message = [{"role": "user", "content": f"[YOUR PREVIOUS RESPONSE CONTAINED NO TOOL CALL AND WAS NOT DELIVERED. CALL AT LEAST ONE TOOL NOW. IF YOU INTENDED THIS CONTENT AS COMMUNICATION, USE send: {message.get('content')!r}]"}]
        print(f"RESPONSE {response}\nFINISH_REASON {response['choices'][0].get('finish_reason')}\nUSAGE {response.get('usage')}")
        experience += [{key: value for key, value in message.items() if value is not None and (KEEP_REASONING_IN_EPISODE or key not in ("reasoning", "reasoning_details", "reasoning_content"))}]
        tool_outputs = []
        for tool_call in message["tool_calls"]:
            tool_name = tool_call["function"]["name"]
            try:
                tool_arguments = json.loads(tool_call["function"]["arguments"])
            except Exception as error:
                tool_arguments = tool_call["function"]["arguments"]
                ret = f"Invalid tool arguments from model: {error}"
            else:
                try: #unless tool unknown/args formatting issue, we use the tool's INOPS function return value:
                    if tool_name not in INOPS:
                        ret = f"Unknown tool: {tool_name!r}"
                    elif not isinstance(tool_arguments, dict):
                        ret = "Tool arguments must be a JSON object"
                    else:
                        with open(INOPS[tool_name][0], "r", encoding="utf-8") as file:
                            tool_source = file.read()
                        tool_module = {"__name__": "_dynamic_" + tool_name, "__file__": INOPS[tool_name][0]}
                        exec(tool_source, tool_module)
                        result = tool_module["run"](**tool_arguments)
                        if "async def run(" in tool_source:
                            result = await result
                        ret = "" if result is None else str(result)
                except Exception as error:
                    ret = f"Tool execution failed: {type(error).__name__}: {error}"
            ret = str(ret)
            if len(ret) > MAX_TOOL_OUTPUT_CHARS:
                ret = ret[:MAX_TOOL_OUTPUT_CHARS] + " [TRUNCATED]"
            experience += [{"role": "tool", "tool_call_id": tool_call["id"], "content": "Step " + get_current_time() + ": " + ret}]
            tool_outputs += ["tool call: " + tool_name + " " + str(tool_arguments) + "\n" "tool return: " + ret]
        history_checkpoint = len(experience) #tool calls succeeded, even on later exception we won't unroll them
        save_experience(experience)
        print("Output> " + "\n".join(tool_outputs))
        autonomous_steps = 0 if event_append else autonomous_steps + 1
        called_nop = any(call["function"]["name"] == "nop" for call in message["tool_calls"])
        if called_nop:
            new_burst, autonomous_steps = True, 0
            pending_event_append = await slow_wait_for_input()
        elif autonomous_steps >= MAX_FAST_STEPS:
            autonomous_steps = 0
            pending_event_append = await slow_wait_for_input()
    except Exception as error:
        print(f"Output> {type(error).__name__}: {error}")
        experience = experience[:history_checkpoint]
        await bridge.sleep(ERROR_RECOVERY_TIME * 1000)
