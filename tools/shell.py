import os
import sys
import json
import bridge

DESCRIPTION = "Run a command with just-bash in the shared browser filesystem."

async def run(command):
    result = str(await bridge.shell(str(command)))
    err = "__ITER_SHELL_ERROR__\n"
    if result.startswith(err):
        raise RuntimeError(result[len(err):])

    marker = "__ITER_PYTHON__\n"
    if result.startswith(marker):
        payload = json.loads(result[len(marker):])
        old_cwd = os.getcwd()
        had_argv = hasattr(sys, "argv")
        old_argv = getattr(sys, "argv", None)
        try:
            os.chdir(payload.get("cwd") or old_cwd)
            try:
                sys.argv = payload.get("argv") or []
            except Exception:
                pass
            exec(payload["code"], {
                "__name__": "__main__",
                "__file__": payload.get("filename", "<string>")
            })
        finally:
            if had_argv:
                try:
                    sys.argv = old_argv
                except Exception:
                    pass
            else:
                try:
                    delattr(sys, "argv")
                except Exception:
                    pass
            os.chdir(old_cwd)
        return "python executed"
    return result
