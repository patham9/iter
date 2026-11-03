import json
import os

DESCRIPTION = "Attach screenshot tool results as one-shot multimodal input."
MARKER = "__ITER_SCREENSHOT__ "

def transform(messages, tools):
    transformed = []
    for message in messages:
        content = message.get("content")
        if message.get("role") != "tool" or not isinstance(content, str) or MARKER not in content:
            transformed.append(message)
            continue

        index = content.find(MARKER)
        path = content[index + len(MARKER):].strip()
        copied = dict(message)
        record = None
        try:
            with open(path, "r") as file:
                record = json.loads(file.read())
        except Exception:
            pass

        copied["content"] = content[:index].rstrip() + ("\n" if content[:index].rstrip() else "") + "[SCREENSHOT CAPTURED" + (": " + str(record.get("width")) + "x" + str(record.get("height")) if record else "") + "]"
        transformed.append(copied)

        if record and record.get("data_url"):
            transformed.append({"role": "user", "content": [
                {"type": "text", "text": "Visual context for the immediately preceding screenshot tool result. This is the current browser page/viewport."},
                {"type": "image_url", "image_url": {"url": record["data_url"]}}
            ]})
            try:
                os.remove(path)
            except OSError:
                pass

    return transformed, tools
