import bridge
import json

DESCRIPTION = "Capture the current browser page/viewport for visual inspection."

async def run():
    result = str(await bridge.screenshot())
    error = "__ITER_SCREENSHOT_ERROR__\n"
    if result.startswith(error):
        raise RuntimeError(result[len(error):])
    metadata = json.loads(result)
    return "__ITER_SCREENSHOT__ " + metadata["path"]
