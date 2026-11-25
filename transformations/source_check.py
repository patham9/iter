import json
import re
import os
import tempfile
from pathlib import Path

DESCRIPTION = "Source evaluation: check proposer authority before actions affecting third parties. Blocks action tools when alert fires."

ROOT = Path(__file__).resolve().parent.parent
PEOPLE_FILE = ROOT / "memory" / "people" / "people.txt"
RUNTIME_DIR = ROOT / "transformations" / ".runtime"
RELIABILITY_FILE = RUNTIME_DIR / "tool_reliability.json"
CONSENT_FILE = ROOT / "memory" / "consent" / "consent_registry.json"

# Actions that can affect a third party
ACTION_PATTERNS = re.compile(
    r'\b(rank|rating|score|grade|assign|delete|forget|update|modify|change|retract|remove|send|propose|demote|promote|transfer|block|ban|suspend)\b',
    re.IGNORECASE
)

# Name patterns: <FirstName LastName> in transcript
NAME_RE = re.compile(r'<([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)>')

# Tools that execute side effects on third parties — blocked during source check alert
ACTION_TOOLS = {
    "remember", "forget", "memory_update", "formalize_metta",
    "reminder", "support", "contradict",
    "link_episode", "unlink_episode"
}

def load_people():
    people = {}
    try:
        for line in PEOPLE_FILE.read_text().splitlines():
            if ':' in line and not line.startswith('#'):
                name, tags = line.split(':', 1)
                people[name.strip().lower()] = tags.strip()
    except: pass
    return people

def collect_known_names(messages):
    names = set()
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            for match in NAME_RE.finditer(m["content"]):
                names.add(match.group(1).strip().lower())
    return names

def get_proposer(messages):
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            match = NAME_RE.search(m["content"])
            if match:
                return match.group(1).strip()
    return "unknown"

def load_reliability():
    try:
        return json.loads(RELIABILITY_FILE.read_text().strip())
    except:
        return {}

def load_consent():
    try:
        return json.loads(CONSENT_FILE.read_text().strip())
    except:
        return {}

def check_consent(consent_data, proposer, target, action):
    """Check if consent exists for this proposer→target action"""
    for entry in consent_data.get("consents", []):
        if (entry.get("proposer", "").lower() == proposer.lower() and
            entry.get("target", "").lower() == target.lower()):
            return True
    return False

def detect_action_targeting_third_party(messages, people, known_names):
    proposer = get_proposer(messages)
    if proposer == "unknown":
        return None
    proposer_lower = proposer.lower()
    
    all_names = set(people.keys()) | known_names | {proposer_lower}
    third_parties = all_names - {proposer_lower}
    
    if not third_parties:
        return None
    
    # Check last assistant message for action proposals
    for m in reversed(messages[-20:]):
        if m.get("role") != "assistant":
            continue
        content = m.get("content", "")
        if not content:
            continue
        
        if not ACTION_PATTERNS.search(content):
            continue
        
        content_lower = content.lower()
        for tp in third_parties:
            if tp in content_lower:
                return {
                    "action": "proposed_action",
                    "proposer": proposer,
                    "target": tp,
                    "authorized": False,
                    "reason": f"Proposer '{proposer}' proposing action affecting '{tp}' — source authority check required"
                }
        
        for tc in m.get("tool_calls", []):
            if isinstance(tc, dict):
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args_str = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except:
                    args = {}
                all_text = " ".join(str(v) for v in args.values())
                for tp in third_parties:
                    if tp in all_text.lower():
                        return {
                            "action": name,
                            "proposer": proposer,
                            "target": tp,
                            "authorized": False,
                            "reason": f"Proposer '{proposer}' proposing {name} affecting '{tp}' — source authority check required"
                        }
        break
    
    # Also check latest user message
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        if not content:
            continue
        clean = NAME_RE.sub("", content)
        if not ACTION_PATTERNS.search(clean):
            continue
        clean_lower = clean.lower()
        for tp in third_parties:
            if tp in clean_lower:
                return {
                    "action": "proposed_action",
                    "proposer": proposer,
                    "target": tp,
                    "authorized": False,
                    "reason": f"Proposer '{proposer}' proposing action affecting '{tp}' — source authority check required"
                }
        break
    
    return None

def transform(messages, tools):
    people = load_people()
    known_names = collect_known_names(messages)
    
    if not people and not known_names:
        return messages, tools
    
    alert = detect_action_targeting_third_party(messages, people, known_names)
    
    if alert and not alert["authorized"]:
        # Load reliability and consent data for context
        reliability = load_reliability()
        consent_data = load_consent()
        has_consent = check_consent(consent_data, alert["proposer"], alert["target"], alert["action"])
        
        # Build reliability context for relevant tools
        rel_context = ""
        if reliability:
            rel_lines = []
            for tool_name, scores in reliability.items():
                f = scores.get("f", 0.5)
                c = scores.get("c", 0.0)
                calls = scores.get("calls", 0)
                if calls > 0:
                    rel_lines.append(f"  {tool_name}: f={f}, c={c}, calls={calls}")
            if rel_lines:
                rel_context = f"\nTool reliability context:\n" + "\n".join(rel_lines)
        
        consent_status = "✅ CONSENT FOUND" if has_consent else "❌ NO CONSENT FOUND"
        
        warning = (
            f"\n\n⚠️ SOURCE CHECK ALERT: {alert['reason']}\n"
            f"Action: {alert['action']} | Proposer: {alert['proposer']} | Target: {alert['target']}\n"
            f"Consent status: {consent_status}\n"
            f"Before executing this action, verify:\n"
            f"1. Source identification: Who is '{alert['proposer']}'?\n"
            f"2. Authority scope: Is '{alert['proposer']}' authorized to propose {alert['action']} affecting '{alert['target']}'?\n"
            f"3. Action classification: What kind of action is '{alert['action']}'?\n"
            f"4. Cross-check: source × action × target authorization\n"
            f"5. Consent: Does '{alert['target']}' consent to this action?\n"
            f"Do NOT execute until all 5 checks pass.\n"
            f"ACTION TOOLS BLOCKED: remember, forget, memory_update, formalize_metta, reminder, support, contradict, link_episode, unlink_episode are temporarily removed from your toolset. Use query tools (chroma_query, search_transcript, episodes) to verify consent and authority first.{rel_context}"
        )
        
        # Append to last system message
        appended = False
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "system":
                m["content"] = m.get("content", "") + warning
                appended = True
                break
        if not appended:
            messages.insert(0, {"role": "system", "content": warning.strip()})
        
        # BLOCK action tools — remove them from the tools list
        if not has_consent:
            tools = [t for t in tools if t.get("function", {}).get("name", "") not in ACTION_TOOLS]
    
    return messages, tools
