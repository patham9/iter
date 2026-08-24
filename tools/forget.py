import chromadb
from pathlib import Path

DESCRIPTION = "Delete a memory from the PeTTa chroma_db. Item_id must be a UUID from chroma_query results. Returns success or error message."

def run(item_id):
    """
    item_id: str - UUID of the memory item to forget/delete
    returns: str - success or error message
    """
    db_path = str(Path.home() / "PeTTa" / "chroma_db")
    chroma_client = chromadb.PersistentClient(path=db_path)
    collection = chroma_client.get_or_create_collection(
        name="memories",
        embedding_function=None
    )

    # Verify item exists before deleting
    res = collection.get(ids=[item_id], include=["metadatas"])
    if not res.get("ids"):
        return f"ERROR: memory not found: {item_id}"

    collection.delete(ids=[item_id])

    return f"FORGET-SUCCESS: item {item_id} deleted from chroma_db"
