import bridge

DESCRIPTION = "Evaluate MeTTa with PeTTa on SWI-Prolog/WASM. A single bare S-expression is treated as runnable; for example (+ 1 1) returns 2."

async def run(code):
    code = str(code).strip()
    if not code:
        raise ValueError("empty MeTTa code")

    # Tool convenience: a single bare expression is evaluated as a runnable.
    # Full/multiline MeTTa programs retain their syntax unchanged.
    if "\n" not in code and code.startswith("(") and code.endswith(")"):
        code = "!" + code

    result = str(await bridge.metta(code))
    error = "__ITER_METTA_ERROR__\n"
    if result.startswith(error):
        raise RuntimeError(result[len(error):])
    return result
