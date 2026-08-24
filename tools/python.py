"""
Python Tool — execute arbitrary Python with all other tools available as callables.

The LLM writes a Python snippet. This tool imports all other tools in the tools/
directory and exposes their run() functions as callable names (e.g. shell, websearch,
lean_check, confab_check, metta, chroma_query, episodes, send, remember).

The snippet can call any tool, process results, branch, loop, and chain calls
without the LLM mediating between steps.

Usage:
    run('x = shell("ls -la"); print(x)')
    run('results = websearch("lean theorem prover", 5); print(results)')
    run('proof = "example (p: Prop) (h: p): p := by exact h"; print(lean_check(proof))')
"""

import os
import sys
import importlib
import traceback
import io
import contextlib

DESCRIPTION = "Execute arbitrary Python code with all other tools available as callable functions. Pass Python code as a string."

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_tools():
    """Import all tool modules in the tools directory and expose their run() functions."""
    namespace = {}
    for fname in os.listdir(TOOLS_DIR):
        if not fname.endswith('.py') or fname.startswith('_') or fname == 'python.py':
            continue
        mod_name = fname[:-3]
        try:
            # Add tools dir to path for imports
            if TOOLS_DIR not in sys.path:
                sys.path.insert(0, TOOLS_DIR)
            mod = importlib.import_module(mod_name)
            if hasattr(mod, 'run'):
                namespace[mod_name] = mod.run
        except Exception as e:
            # Silently skip tools that fail to import
            pass
    return namespace

def run(code: str) -> str:
    """
    Execute arbitrary Python code with all tools available as callable functions.
    
    Args:
        code: Python code string to execute. All tool run() functions are available
              as variables named after their module (e.g. shell, websearch, lean_check).
    
    Returns:
        Captured stdout + any exception traceback if one occurs.
    """
    # Load all tool functions
    tools = _load_tools()
    
    # Prepare execution namespace with tools + builtins
    exec_namespace = {}
    exec_namespace.update(tools)
    exec_namespace.update({
        '__builtins__': __builtins__,
        'os': os,
        'sys': sys,
        'json': __import__('json'),
        're': __import__('re'),
        'subprocess': __import__('subprocess'),
        'print': print,
    })
    
    # Capture stdout
    captured = io.StringIO()
    
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            exec(compile(code, '<python>', 'exec'), exec_namespace)
        output = captured.getvalue()
        if not output:
            # Check for a result variable
            if 'result' in exec_namespace:
                output = str(exec_namespace['result'])
            else:
                output = "[python: no output]"
        return output
    except Exception as e:
        tb = traceback.format_exc()
        return f"[python ERROR]\n{tb}\n[captured stdout: {captured.getvalue()}]"

if __name__ == "__main__":
    if len(sys.argv) > 1:
        code = sys.argv[1]
    else:
        code = sys.stdin.read()
    print(run(code))
