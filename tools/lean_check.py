DESCRIPTION = "Check a Lean 4 proof. Pass Lean code as a string, or a file path. Returns compilation output and exit status."
import subprocess
import tempfile
import os
import shutil

LEAN_BIN = os.path.expanduser("~/.elan/bin/lean")

def run(code: str) -> str:
    """
    Check Lean 4 code.
    - If `code` is a path to an existing .lean file, check that file.
    - Otherwise, treat `code` as Lean 4 source code, write to temp file, and check.
    
    For multi-file Lean projects (e.g. PettaClaw in /tmp/pettaclaw-formal/),
    set LEAN_PATH env var or the file path will trigger LEAN_PATH detection.
    
    Returns: compilation output (stdout+stderr) and exit status.
    """
    if not shutil.which("lean") and not os.path.exists(LEAN_BIN):
        return "ERROR: lean not found. Install elan from https://github.com/leanprover/elan"
    
    lean_cmd = LEAN_BIN if os.path.exists(LEAN_BIN) else "lean"
    
    # If it's a file path, check directly
    if os.path.isfile(code) and code.endswith('.lean'):
        # Auto-detect LEAN_PATH: if .olean files exist alongside, use that dir
        env = os.environ.copy()
        file_dir = os.path.dirname(code)
        if any(f.endswith('.olean') for f in os.listdir(file_dir)):
            env['LEAN_PATH'] = file_dir
        result = subprocess.run(
            [lean_cmd, code],
            capture_output=True, text=True, timeout=30, env=env
        )
        output = result.stdout + result.stderr
        if result.returncode == 0:
            output += f"\n[exit: 0] ✓ Proof verified successfully"
        else:
            output += f"\n[exit: {result.returncode}] ✗ Proof failed"
        return output.strip()
    
    # Otherwise treat as inline code
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lean', delete=False, dir='/tmp') as f:
        f.write(code)
        f.flush()
        temp_path = f.name
    
    try:
        result = subprocess.run(
            [lean_cmd, temp_path],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout + result.stderr
        if result.returncode == 0:
            output += f"\n[exit: 0] ✓ Proof verified successfully"
        else:
            output += f"\n[exit: {result.returncode}] ✗ Proof failed"
        return output.strip()
    except subprocess.TimeoutExpired:
        return "ERROR: Lean compilation timed out (30s limit)"
    finally:
        os.unlink(temp_path)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        code = sys.argv[1]
    else:
        code = sys.stdin.read()
    print(run(code))
