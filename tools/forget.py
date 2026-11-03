import sys
TOOLS_DIR = "/work/iter/tools"
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import _petta_db as petta_db

DESCRIPTION = "Delete a memory from the PeTTa chroma_db. Item_id must be a UUID from chroma_query results. Returns success or error message."

def run(item_id):
    chroma_client = petta_db.PersistentClient()
    collection = chroma_client.get_or_create_collection(name="memories")

    res = collection.get(ids=[item_id], include=["metadatas"])
    if not res.get("ids"):
        return f"ERROR: memory not found: {item_id}"

    collection.delete(ids=[item_id])
    return f"FORGET-SUCCESS: item {item_id} deleted from chroma_db"
