"""Visible status tool for the internal _petta_db memory backend."""

import sys
import json

TOOLS_DIR = "/work/iter/tools"
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import _petta_db

DESCRIPTION = "Report long-term-memory database status, path, embedding model, dimensions, and whether its vector index is current."


def run():
    return json.dumps(_petta_db.status())
