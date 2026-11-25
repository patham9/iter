"""Appends a queued image (from view_image tool) as a user image message once, then deletes the queue file.
GIFs/large images are converted to a <=1024px PNG (GIF: contact sheet of up to 9 frames)."""
import json, base64, io
from pathlib import Path

DESCRIPTION = "Image view: appends image queued by view_image tool as one image message, then consumes it."
Q = Path(".runtime/pending_image.json")

def _encode(path):
    from PIL import Image, ImageSequence
    im = Image.open(path)
    note = ""
    n = getattr(im, "n_frames", 1)
    if n > 1:
        frames = [f.convert("RGB") for f in ImageSequence.Iterator(im)]
        k = min(9, len(frames))
        idx = [round(i * (len(frames) - 1) / max(1, k - 1)) for i in range(k)]
        w, h = frames[0].size
        cols = 3 if k > 4 else k
        rows = (k + cols - 1) // cols
        sheet = Image.new("RGB", (w * cols, h * rows), "white")
        for j, i in enumerate(idx):
            sheet.paste(frames[i], ((j % cols) * w, (j // cols) * h))
        im = sheet
        note = f" (animated, {n} frames; contact sheet of frames {idx}, left-to-right, top-to-bottom)"
    im = im.convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode(), im.size, note

def _log(msg):
    import datetime
    with open(".runtime/image_view.log","a") as f:
        f.write(datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S ")+msg+"\n")

def transform(messages, tools):
    if not Q.exists():
        return messages, tools
    try:
        path = json.loads(Q.read_text())["path"]
    finally:
        Q.unlink(missing_ok=True)  # consume once, even on error
    try:
        b64, size, note = _encode(path)
        messages.append({"role": "user", "content": [
            {"type": "text", "text": f"[IMAGE VIEW: {path}, shown {size[0]}x{size[1]}{note}. Shown once only; describe now what you see if needed.]"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]})
        _log(f"appended {path} {size} b64len={len(b64)}")
    except Exception as e:
        _log(f"FAILED {path}: {e}")
        messages.append({"role": "user", "content": f"[IMAGE VIEW FAILED for {path}: {type(e).__name__}: {e}]"})
    return messages, tools
