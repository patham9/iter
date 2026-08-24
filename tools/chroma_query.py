import os
import json
from pathlib import Path
from openai import OpenAI
import chromadb

DESCRIPTION = "Query the PeTTa chroma_db for similar memories by text. Returns matching entries with their content and metadata."

def run(query, k=5):
    # Get embedding
    client = OpenAI()
    embedding_response = client.embeddings.create(
        input=query,
        model="text-embedding-3-large"
    )
    query_embedding = embedding_response.data[0].embedding

    # Query chroma_db
    db_path = str(Path.home() / "PeTTa" / "chroma_db")
    chroma_client = chromadb.PersistentClient(path=db_path)
    collection = chroma_client.get_or_create_collection(
        name="memories",
        embedding_function=None
    )

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=int(k),
        include=["documents", "metadatas", "distances"]
    )

    # Format results
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if not documents:
        return "No results found."

    output_lines = [f"Found {len(documents)} results for query: \"{query}\"\n"]
    for i, (id_val, doc, meta, dist) in enumerate(zip(ids, documents, metadatas, distances)):
        time_val = meta.get("time", "unknown") if meta else "unknown"
        linked = meta.get("linkedEpisodes", []) if meta else []
        strength = meta.get("strength", 1.0) if meta else 1.0
        confidence = meta.get("confidence", 0.5) if meta else 0.5
        formalization = meta.get("formalization", None) if meta else None
        output_lines.append(f"--- Result {i+1} (distance: {dist:.4f}) ---")
        output_lines.append(f"ID: {id_val}")
        output_lines.append(f"Time: {time_val}")
        output_lines.append(f"STV: ({strength}, {confidence})")
        if linked:
            output_lines.append(f"Linked Episodes: {linked}")
        if formalization:
            output_lines.append(f"Formalization: {formalization}")
        output_lines.append(f"Content: {doc}")
        output_lines.append("")

    return "\n".join(output_lines)
