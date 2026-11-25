import json, requests, sys
sys.path.insert(0, "channels")

DESCRIPTION = "Mattermost reactions. react(post_id, emoji) adds emoji (e.g. thumbsup, heart, tada) to a post. Use emoji='?' to list current reactions on that post. post_id is shown as [post_id=...] in incoming messages."

def run(post_id, emoji):
    import mattermost as m
    if emoji.strip() in ("?", "", "list"):
        r = requests.get(f"{m.MM_URL}/api/v4/posts/{post_id}/reactions", headers=m._headers, timeout=15)
        if r.status_code != 200:
            return f"ERROR {r.status_code}: {r.text[:200]}"
        out = []
        for x in (r.json() or []):
            try: name = m._get_display_name(x["user_id"])
            except Exception: name = x["user_id"]
            out.append(f"{name}: :{x['emoji_name']}:")
        return "; ".join(out) or "no reactions"
    me = requests.get(f"{m.MM_URL}/api/v4/users/me", headers=m._headers, timeout=15).json()["id"]
    r = requests.post(f"{m.MM_URL}/api/v4/reactions", headers=m._headers, timeout=15,
                      json={"user_id": me, "post_id": post_id, "emoji_name": emoji.strip(":")})
    return "SUCCESS" if r.status_code in (200, 201) else f"ERROR {r.status_code}: {r.text[:200]}"
