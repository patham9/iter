"""
Confidence Boost Tool
Scans chroma_db for formalized LTM items with low confidence (c < threshold),
searches episode history near each item's creation time for a supporting episode,
and applies NAL truth revision with positive evidence to boost confidence.

This automates what was previously a manual process of:
1. Finding low-confidence formalized items
2. Searching episodes near the item's timestamp
3. Calling support() to link the episode and revise truth values
"""

DESCRIPTION = "Find and boost low-confidence formalized LTM items by linking supporting episodes from transcript history. Optional params: threshold (default 0.6), max_items (default 50)."

import os
import json
import chromadb
from pathlib import Path
from datetime import datetime, timedelta

# --- NAL Truth Revision (matching support.py) ---
def c2w(c):
    return c / (1.0 - c) if c < 1.0 else 999999.0

def w2c(w):
    return w / (w + 1.0)

def truth_revision(s1, c1, s2, c2):
    w1 = c2w(c1)
    w2 = c2w(c2)
    w = w1 + w2
    f = (w1 * s1 + w2 * s2) / w if w > 0 else 0.0
    c = w2c(w)
    f = min(1.00, f)
    c = min(0.99, max(max(c, c1), c2))
    return round(f, 6), round(c, 6)

# --- Episode search (lightweight version of episodes.py) ---
HISTORY_PATH = os.path.expanduser("~/PeTTa/repos/mettaclaw/memory/history.metta")

def _parse_timestamp(line):
    idx = line.find('"')
    if idx < 0:
        return None
    end = line.find('"', idx + 1)
    if end < 0:
        return None
    ts_str = line[idx + 1:end]
    try:
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

def find_episode_near(time_str, search_range_minutes=30):
    """Find an episode timestamp near the given time string, within search_range_minutes."""
    if not os.path.isfile(HISTORY_PATH):
        return None

    try:
        target = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    file_size = os.path.getsize(HISTORY_PATH)
    if file_size == 0:
        return None

    with open(HISTORY_PATH, 'rb') as f:
        lo = 0
        hi = file_size
        best_ts = None
        best_diff = None

        while lo < hi:
            mid = (lo + hi) // 2
            if mid == lo:
                break
            f.seek(mid)
            if mid > 0:
                f.readline()  # skip partial
            raw = f.readline()
            if not raw:
                lo = mid + 1
                continue
            line = raw.decode('utf-8', errors='replace').strip()
            ts = _parse_timestamp(line)
            if ts is None:
                lo = mid + 1
                continue
            diff = abs((ts - target).total_seconds())
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_ts = ts
            if ts < target:
                lo = f.tell()
            elif ts > target:
                hi = mid
            else:
                best_ts = ts
                break

    if best_ts is None:
        return None

    # Only return if within range
    if best_diff is not None and best_diff <= search_range_minutes * 60:
        return best_ts.strftime("%Y-%m-%d %H:%M:%S")
    return None


def run(threshold=0.6, max_items=50):
    """
    threshold: float - confidence below this triggers a boost attempt
    max_items: int - maximum number of items to process
    returns: str - summary of boosts applied
    """
    threshold = float(threshold)
    max_items = int(max_items)

    db_path = str(Path.home() / "PeTTa" / "chroma_db")
    chroma_client = chromadb.PersistentClient(path=db_path)
    collection = chroma_client.get_or_create_collection(
        name="memories",
        embedding_function=None
    )

    results = collection.get(include=["metadatas", "documents"])
    if not results.get("ids"):
        return "No memories found in chroma_db."

    low_conf_items = []
    for i, meta in enumerate(results["metadatas"]):
        has_form = bool(meta.get("formalization", ""))
        if not has_form:
            continue
        conf = meta.get("confidence", 0.5)
        try:
            conf = float(conf)
        except (ValueError, TypeError):
            conf = 0.5
        if conf < threshold:
            linked = meta.get("linkedEpisodes", [])
            if isinstance(linked, str):
                try:
                    linked = json.loads(linked)
                except:
                    linked = []
            time_str = meta.get("time", "")
            doc = results["documents"][i] if results["documents"] else ""
            low_conf_items.append({
                "id": results["ids"][i],
                "confidence": conf,
                "linked_episodes": linked,
                "time": time_str,
                "doc": doc[:80] if doc else "",
            })

    if not low_conf_items:
        return f"All formalized items already have confidence >= {threshold}. Nothing to boost."

    boosted = 0
    skipped = 0
    failed = 0
    details = []

    for item in low_conf_items[:max_items]:
        item_id = item["id"]
        existing_eps = item["linked_episodes"]

        # Try to find a supporting episode near the item's creation time
        episode_time = find_episode_near(item["time"])

        if episode_time is None:
            # Try a wider search: ±2 hours
            episode_time = find_episode_near(item["time"], search_range_minutes=120)

        if episode_time is None:
            skipped += 1
            details.append(f"  SKIP {item_id[:8]} c={item['confidence']:.2f} | no episode found near {item['time']}")
            continue

        if episode_time in existing_eps:
            skipped += 1
            details.append(f"  SKIP {item_id[:8]} c={item['confidence']:.2f} | episode {episode_time} already linked")
            continue

        # Apply support: link episode + truth revision with positive evidence
        meta = dict(collection.get(ids=[item_id], include=["metadatas"])["metadatas"][0] or {})
        linked_episodes = meta.get("linkedEpisodes", [])
        linked_episodes.append(episode_time)
        meta["linkedEpisodes"] = linked_episodes

        s1 = float(meta.get("strength", 1.0))
        c1 = float(meta.get("confidence", 0.5))
        s2, c2 = 1.0, 0.5  # positive evidence
        new_s, new_c = truth_revision(s1, c1, s2, c2)

        meta["strength"] = new_s
        meta["confidence"] = new_c
        collection.update(ids=[item_id], metadatas=[meta])

        boosted += 1
        details.append(f"  BOOST {item_id[:8]} c={c1:.2f}->{new_c:.2f} | ep={episode_time} | {item['doc'][:50]}")

    summary = f"CONFIDENCE BOOST SUMMARY:\n"
    summary += f"  Scanned: {len(low_conf_items)} low-confidence formalized items\n"
    summary += f"  Boosted: {boosted}\n"
    summary += f"  Skipped: {skipped}\n"
    summary += f"  Failed:  {failed}\n"
    if details:
        summary += "\nDetails:\n" + "\n".join(details)
    return summary
