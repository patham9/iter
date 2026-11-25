import subprocess
import tempfile
import os
import glob
from pathlib import Path

DESCRIPTION = "Evaluate MeTTa code using ~/PeTTa/run.sh. Pass multi-line MeTTa code as a string."

RUN_SH = str(Path.home() / "PeTTa" / "run.sh")
PETTA_DIR = str(Path.home() / "PeTTa")

# Path to the metta/ directory in the Iter working dir
METTA_DIR = str(Path(__file__).parent.parent / "metta")

# Default imports prepended to every eval - NAL and PLN inference libraries
DEFAULT_IMPORTS = """!(import! &self lib_nal)
!(import! &self lib_pln)
"""

def build_metta_imports():
    """Build import statements for all .metta files in the metta/ directory.
    Each file (e.g., kb.metta) is loaded into a space of the same name (e.g., &kb)."""
    imports = DEFAULT_IMPORTS
    if os.path.isdir(METTA_DIR):
        for metta_file in sorted(glob.glob(os.path.join(METTA_DIR, "*.metta"))):
            name = Path(metta_file).stem  # e.g., "kb" from "kb.metta"
            imports += f'!(import! &{name} "{metta_file}")\n'
    return imports

def run(code):
    """
    code: str - multi-line MeTTa code to evaluate
    returns: str - output from run.sh
    """
    code = code.strip()
    if not code:
        return "No MeTTa code provided"
    
    full_code = build_metta_imports() + code
    
    # Write temp file to ~/PeTTa/ so working_dir resolves correctly for imports
    with tempfile.NamedTemporaryFile(mode="w", suffix=".metta", delete=False, dir=PETTA_DIR, prefix="tmp_metta_") as f:
        f.write(full_code)
        f.flush()
        temp_path = f.name
    
    try:
        result = subprocess.run(
            ["bash", RUN_SH, temp_path, "-s"],
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout
        if result.stderr:
            output += "\n[STDERR]\n" + result.stderr
        if not output.strip():
            output = "(no output)"
        return output
    except subprocess.TimeoutExpired:
        return "Timeout: MeTTa evaluation took longer than 30 seconds"
    except Exception as e:
        return f"Error: {e}"
    finally:
        os.unlink(temp_path)
