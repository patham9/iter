"""
Python Tool — execute arbitrary Python with all other tools available as callables.

The LLM writes a Python snippet. This tool loads all other tools in the tools/
directory and exposes their run() functions as callable names (e.g. shell, send,
screenshot).

The snippet can call any tool, process results, branch, loop, and chain calls
without the LLM mediating between steps.

Browser tools may be asynchronous, so await them when needed:
    x = await shell("ls -la")
    print(x)
"""

import os
import sys
import json
import re

DESCRIPTION = "Execute arbitrary Python code with all other tools available as callable functions. Pass Python code as a string."

TOOLS_DIR = __file__.rsplit("/", 1)[0] if "/" in __file__ else "tools"

class _Capture:
    def __init__(self):
        self.parts = []

    def write(self, value):
        value = str(value)
        self.parts.append(value)
        return len(value)

    def flush(self):
        pass

    def getvalue(self):
        return "".join(self.parts)

async def run(code: str) -> str:
    captured = _Capture()

    def captured_print(*args, **kwargs):
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        captured.write(sep.join(str(value) for value in args) + end)

    namespace = {
        "os": os,
        "sys": sys,
        "json": json,
        "re": re,
        "print": captured_print,
    }

    for fname in os.listdir(TOOLS_DIR):
        if not fname.endswith(".py") or fname.startswith("_") or fname == "python.py":
            continue
        mod_name = fname[:-3]
        path = TOOLS_DIR + "/" + fname
        try:
            with open(path, "r", encoding="utf-8") as file:
                source = file.read()
            module = {
                "__name__": "_python_tool_" + mod_name,
                "__file__": path,
                "print": captured_print,
            }
            exec(source, module)
            if "run" in module:
                namespace[mod_name] = module["run"]
        except Exception:
            pass

    body = "\n".join("    " + line for line in str(code).splitlines())
    if not body.strip():
        body = "    pass"
    source = "async def __iter_python_main__():\n" + body + "\n    return locals()\n"

    try:
        exec(source, namespace)
        values = await namespace["__iter_python_main__"]()
        output = captured.getvalue()
        if not output:
            if isinstance(values, dict) and "result" in values:
                output = str(values["result"])
            else:
                output = "[python: no output]"
        return output
    except Exception as error:
        try:
            sys.print_exception(error, captured)
            detail = captured.getvalue()
        except Exception:
            detail = type(error).__name__ + ": " + str(error)
        return "[python ERROR]\n" + detail
