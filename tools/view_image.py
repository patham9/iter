import json, os
from pathlib import Path

DESCRIPTION = "Show an image file (png/jpg/gif/webp) to you ONLY ONCE: it appears as an image message in your very next step, then it is gone. Afterwards you HAVE seen it, even though it is no longer in your context, so do not claim you did not see it and do not re-queue it; write down what you saw in that same next step. Pass image_path."
Q = Path(".runtime/pending_image.json")

def run(image_path):
    p = Path(os.path.expanduser(image_path.strip()))
    if not p.is_file():
        return f"ERROR: no such file {p}"
    Q.parent.mkdir(exist_ok=True)
    Q.write_text(json.dumps({"path": str(p.resolve())}))
    return f"QUEUED {p.resolve()} ({p.stat().st_size} bytes). You will see it ONLY ONCE, in your next step; describe it right then. In later steps it is gone from context but you DID see it."
