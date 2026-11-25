"""
Metta Space Info: append metta file/space name info to the first system message.
Scans ./metta/*.metta, derives space names from filenames (strip .metta → &name),
and appends as e.g. "kb.metta / &kb\nquery.metta / &query" to the first system message.
"""
import os
import glob

DESCRIPTION = "Append metta file/space name info to first system message."

BASE = os.path.expanduser("~/iter")
METTA_DIR = os.path.join(BASE, "metta")

def transform(messages, tools):
    try:
        if not messages:
            return messages, tools

        # Gather metta files and their space names
        entries = []
        for fpath in sorted(glob.glob(os.path.join(METTA_DIR, "*.metta"))):
            fname = os.path.basename(fpath)
            space_name = "&" + fname.replace(".metta", "")
            entries.append(f"{fname} / {space_name}")

        if not entries:
            return messages, tools

        info_block = "\n".join(entries)
        appendix = "\n\n=== METTA SPACES ===\n" + info_block

        first_msg = messages[0]
        if isinstance(first_msg, dict):
            content = first_msg.get("content", "")
            if isinstance(content, str):
                first_msg["content"] = content.rstrip() + appendix
            elif isinstance(content, list):
                first_msg["content"] = content + [{"type": "text", "text": appendix}]
    except Exception:
        pass

    return messages, tools
