import os
from openai import OpenAI
import chromadb
from pathlib import Path

DESCRIPTION = "Update the text content and embedding of a specific memory in chroma_db. All metadata (creation time, linked episodes, stv values) is preserved. Item_id must be a UUID from chroma_query results."

def run(item_id, text):
    """
    item_id: str - UUID of the memory item to update
    text: str - new text content for the memory
    returns: str - success or error message
    """
    db_path = str(Path.home() / "PeTTa" / "chroma_db")
    chroma_client = chromadb.PersistentClient(path=db_path)
    collection = chroma_client.get_or_create_collection(
        name="memories",
        embedding_function=None
    )

    # Get existing item to verify it exists and preserve metadata
    res = collection.get(ids=[item_id], include=["metadatas"])
    if not res.get("ids"):
        return f"ERROR: memory not found: {item_id}"

    metadata = dict(res["metadatas"][0] or {})

    # Generate new embedding (same model as remember.py)
    client = OpenAI()
    embedding_response = client.embeddings.create(
        input=text,
        model="text-embedding-3-large"
    )
    embedding = embedding_response.data[0].embedding

    # Update document and embedding, keep metadata as-is
    collection.update(
        ids=[item_id],
        documents=[text],
        embeddings=[embedding],
        metadatas=[metadata]
    )

    return f"MEMORY-UPDATE-SUCCESS: item {item_id} content updated, embedding refreshed, metadata preserved"
