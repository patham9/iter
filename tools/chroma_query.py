import sys
TOOLS_DIR = "/work/iter/tools"
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import _petta_db as petta_db

DESCRIPTION = "Query the PeTTa chroma_db for similar memories by text. Returns matching entries with their content and metadata."

async def run(query, k=5):
    chroma_client = petta_db.PersistentClient()
    collection = chroma_client.get_or_create_collection(name="memories")

    if not collection.get(include=["metadatas"]).get("ids"):
        return "No results found."

    query_embedding = await petta_db.get_embedding(query, "search_query")

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=int(k),
        include=["documents", "metadatas", "distances"]
    )

    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if not documents:
        return "No results found."

    output_lines = ["Found " + str(len(documents)) + ' results for query: "' + query + '"\n']
    for i in range(len(documents)):
        id_val = ids[i] if i < len(ids) else "unknown"
        doc = documents[i] if i < len(documents) else ""
        meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        dist = distances[i] if i < len(distances) else 0.0

        if meta is None:
            meta = {}

        time_val = meta.get("time", "unknown")
        linked = meta.get("linkedEpisodes", [])
        strength = meta.get("strength", 1.0)
        confidence = meta.get("confidence", 0.5)
        formalization = meta.get("formalization", None)
        prov = meta.get("provenance_type", "unknown")

        output_lines.append("--- Result " + str(i+1) + " (distance: " + str(round(dist, 4)) + ") ---")
        output_lines.append("ID: " + str(id_val))
        output_lines.append("Time: " + str(time_val))
        output_lines.append("Provenance: " + str(prov))
        output_lines.append("STV: (" + str(strength) + ", " + str(confidence) + ")")
        if linked:
            output_lines.append("Linked Episodes: " + str(linked))
        if formalization:
            output_lines.append("Formalization: " + str(formalization))
        output_lines.append("Content: " + str(doc))
        output_lines.append("")

    return "\n".join(output_lines)
