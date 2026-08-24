DESCRIPTION = "Graph search over space.metta atom space. Finds shortest path distance between two concepts, showing connecting atoms and statements. Supports fuzzy matching for concept names. Pass source and target concept names (case-insensitive, fuzzy-matched)."
import os, re, difflib
from collections import defaultdict, deque

SPACE_PATH = os.path.expanduser('~/iter/transformations/.runtime/space.metta')
OPS = {'-->', '==>', '\u00d7', '[]', 'stv'}

def _load_graph():
    with open(SPACE_PATH) as f:
        content = f.read()
    lines = [l.strip() for l in content.splitlines()
             if l.strip() and not l.strip().startswith('#') and not l.strip().startswith(';')]
    adj = defaultdict(list)
    all_atoms = set()
    for line in lines:
        core = re.sub(r'\s*\(stv\s+[\d.eE+-]+\s+[\d.eE+-]+\)\s*$', '', line).strip()
        while core.startswith('(') and core.endswith(')'):
            core = core[1:-1].strip()
        atoms = set()
        for token in re.findall(r'[A-Za-z][A-Za-z0-9_]*(?:[-_][A-Za-z0-9_]*)*', core):
            if token not in OPS:
                atoms.add(token)
        all_atoms |= atoms
        atom_list = list(atoms)
        for i in range(len(atom_list)):
            for j in range(i+1, len(atom_list)):
                adj[atom_list[i]].append((atom_list[j], line))
                adj[atom_list[j]].append((atom_list[i], line))
    return adj, all_atoms

def _fuzzy_match(query, all_atoms, cutoff=0.4):
    all_list = sorted(all_atoms)
    for atom in all_list:
        if atom.lower() == query.lower():
            return atom, 1.0
    matches = difflib.get_close_matches(query, all_list, n=1, cutoff=cutoff)
    if matches:
        ratio = difflib.SequenceMatcher(None, query.lower(), matches[0].lower()).ratio()
        return matches[0], ratio
    return None, 0.0

def _bfs(adj, start, goal):
    if start == goal:
        return 0, [start], []
    visited = {start}
    queue = deque([(start, [start], [])])
    while queue:
        node, path, stmts = queue.popleft()
        for neighbor, statement in adj[node]:
            if neighbor in visited:
                continue
            new_path = path + [neighbor]
            new_stmts = stmts + [statement]
            if neighbor == goal:
                return len(new_path) - 1, new_path, new_stmts
            visited.add(neighbor)
            queue.append((neighbor, new_path, new_stmts))
    return None, None, None

def run(source='', target=''):
    if not source or not target:
        return "Usage: graph_search(source='ConceptA', target='ConceptB')"
    adj, all_atoms = _load_graph()
    src_match, src_conf = _fuzzy_match(source, all_atoms)
    tgt_match, tgt_conf = _fuzzy_match(target, all_atoms)
    if not src_match:
        return f"Source '{source}' not found in space.metta ({len(all_atoms)} atoms). Try a different spelling."
    if not tgt_match:
        return f"Target '{target}' not found in space.metta ({len(all_atoms)} atoms). Try a different spelling."
    result = []
    result.append(f"Graph Search: '{source}' -> '{target}'")
    result.append(f"Matched: '{src_match}' (conf={src_conf:.2f}) -> '{tgt_match}' (conf={tgt_conf:.2f})")
    result.append(f"Atomspace: {len(all_atoms)} atoms")
    dist, path, stmts = _bfs(adj, src_match, tgt_match)
    if dist is None:
        result.append(f"No path found between '{src_match}' and '{tgt_match}'.")
        return '\n'.join(result)
    result.append(f"Distance: {dist}")
    result.append(f"Path: {' -> '.join(path)}")
    result.append(f"")
    result.append(f"Connecting atoms ({len(stmts)}):")
    for i, s in enumerate(stmts):
        result.append(f"  [{i+1}] {s}")
    return '\n'.join(result)
