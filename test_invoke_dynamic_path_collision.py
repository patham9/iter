"""Test that invoke_dynamic doesn't collide when tool kwargs contain 'path'.

This tests the fix for the parameter name collision bug where
invoke_dynamic(path, function, *args, **kwargs) would raise
TypeError: invoke_dynamic() got multiple values for argument 'path'
when a tool's run() function has a parameter named 'path' and the
caller splats **kwargs containing that key.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def test_invoke_dynamic_accepts_path_kwarg():
    """invoke_dynamic should not collide when kwargs contains 'path'."""
    # Write a minimal tool module that has a 'path' parameter in run()
    tool_code = (
        "DESCRIPTION = 'test tool with path param'\n"
        "def run(path, caption=''):\n"
        "    return f'path={path} caption={caption}'\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, dir="."
    ) as f:
        f.write(tool_code)
        tool_path = f.name

    try:
        # Import invoke_dynamic from iter.py
        # We need to import it without running the main loop.
        # iter.py has a guard: if len(sys.argv) > 1 and sys.argv[1] == "--invoke"
        # We run in the same process but we need to import the function.
        # Since iter.py runs an infinite loop at module level, we extract
        # just the function by exec-ing the relevant portion.

        # Instead, let's test the function signature directly:
        import inspect

        # Read iter.py and find the invoke_dynamic definition
        iter_src = Path("iter.py").read_text()
        # Check that the signature uses positional-only parameter
        sig_match = "def invoke_dynamic(path, /, function, *args, **kwargs):"
        assert sig_match in iter_src, (
            f"Expected positional-only signature not found in iter.py.\n"
            f"Looking for: {sig_match}\n"
            f"Found instead: {next(l for l in iter_src.splitlines() if 'def invoke_dynamic' in l)}"
        )

        # Functional test: call invoke_dynamic with path in kwargs
        # We use the --invoke subprocess path that iter.py provides
        result_fd, result_file = tempfile.mkstemp(prefix="test-result-", suffix=".json")
        payload_fd, payload_file = tempfile.mkstemp(prefix="test-payload-", suffix=".json")
        os.close(result_fd)
        os.close(payload_fd)

        Path(payload_file).write_text(
            json.dumps({"args": [], "kwargs": {"path": "/some/test/file", "caption": "hello"}})
        )

        proc = subprocess.Popen(
            [sys.executable, str(Path("iter.py").resolve()), "--invoke",
             str(Path(tool_path).resolve()), "run", result_file, payload_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(timeout=10)

        result_data = json.loads(Path(result_file).read_text())
        assert result_data["ok"], f"Tool execution failed: {result_data.get('error')}\nstderr: {stderr.decode()}"
        assert "/some/test/file" in result_data["result"], (
            f"Expected path in result, got: {result_data['result']}"
        )
        assert "hello" in result_data["result"], (
            f"Expected caption in result, got: {result_data['result']}"
        )

        os.unlink(result_file)
        os.unlink(payload_file)
    finally:
        os.unlink(tool_path)


def test_invoke_dynamic_no_path_kwarg_still_works():
    """invoke_dynamic should still work normally without path in kwargs."""
    tool_code = (
        "DESCRIPTION = 'test tool without path param'\n"
        "def run(message):\n"
        "    return f'message={message}'\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, dir="."
    ) as f:
        f.write(tool_code)
        tool_path = f.name

    try:
        result_fd, result_file = tempfile.mkstemp(prefix="test-result-", suffix=".json")
        payload_fd, payload_file = tempfile.mkstemp(prefix="test-payload-", suffix=".json")
        os.close(result_fd)
        os.close(payload_fd)

        Path(payload_file).write_text(
            json.dumps({"args": [], "kwargs": {"message": "world"}})
        )

        proc = subprocess.Popen(
            [sys.executable, str(Path("iter.py").resolve()), "--invoke",
             str(Path(tool_path).resolve()), "run", result_file, payload_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(timeout=10)

        result_data = json.loads(Path(result_file).read_text())
        assert result_data["ok"], f"Tool execution failed: {result_data.get('error')}\nstderr: {stderr.decode()}"
        assert "world" in result_data["result"], (
            f"Expected message in result, got: {result_data['result']}"
        )

        os.unlink(result_file)
        os.unlink(payload_file)
    finally:
        os.unlink(tool_path)


if __name__ == "__main__":
    test_invoke_dynamic_accepts_path_kwarg()
    print("test_invoke_dynamic_accepts_path_kwarg: PASS")
    test_invoke_dynamic_no_path_kwarg_still_works()
    print("test_invoke_dynamic_no_path_kwarg_still_works: PASS")
    print("All tests passed.")
