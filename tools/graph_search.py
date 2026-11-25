"""Graph search over space.metta + inferred.metta atom space. Finds shortest path distance between two concepts, showing connecting atoms and statements. Supports fuzzy matching for concept names. Pass source and target concept names (case-insensitive, fuzzy-matched)."""

DESCRIPTION = "Graph search over space.metta + inferred.metta atom space. Finds shortest path distance between two concepts, showing connecting atoms and statements. Supports fuzzy matching for concept names. Pass source and target concept names (case-insensitive, fuzzy-matched)."
import os, re, difflib
from collections import defaultdict, deque

SPACE_PATH = os.path.expanduser('~/iter/metta/space.metta')
INFERRED_PATH = os.path.expanduser('~/iter/metta/inferred.metta')
OPS = {'-->', '==>', '\u00d7', '[]', 'stv'}

def _load_graph():
    adj = defaultdict(list)
    all_atoms = set()
    for path in [SPACE_PATH, INFERRED_PATH]:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            content = f.read()
        lines = [l.strip() for l in content.splitlines()
                 if l.strip() and not l.strip().startswith('#') and not l.strip().startswith(';')]
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

def _fuzzy_match(query, all_atoms, adj=None, cutoff=0.6):
    all_list = sorted(all_atoms)
    ql = query.lower()
    exact_matches = [atom for atom in all_list if atom.lower() == ql]
    if exact_matches:
        if len(exact_matches) == 1:
            return exact_matches[0], 1.0
        # Prefer the variant with more edges (better connected for pathfinding)
        best = max(exact_matches, key=lambda a: len(adj.get(a, [])))
        return best, 1.0
    # Prefer exact substring matches (query IS the atom, not part of a longer one)
    substring_matches = [a for a in all_list if ql in a.lower() or a.lower() in ql]
    if substring_matches:
        # Prefer atoms closest in length to the query
        best = min(substring_matches, key=lambda a: abs(len(a) - len(query)))
        return best, difflib.SequenceMatcher(None, ql, best.lower()).ratio()
    matches = difflib.get_close_matches(query, all_list, n=1, cutoff=cutoff)
    if matches:
        ratio = difflib.SequenceMatcher(None, ql, matches[0].lower()).ratio()
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
    src_match, src_conf = _fuzzy_match(source, all_atoms, adj)
    tgt_match, tgt_conf = _fuzzy_match(target, all_atoms, adj)
    if not src_match:
        return f"Source '{source}' not found in atom space ({len(all_atoms)} atoms). Try a different spelling."
    if not tgt_match:
        return f"Target '{target}' not found in atom space ({len(all_atoms)} atoms). Try a different spelling."
    result = []
    result.append(f"Graph Search: '{source}' -> '{target}'")
    result.append(f"Matched: '{src_match}' (conf={src_conf:.2f}) -> '{tgt_match}' (conf={tgt_conf:.2f})")
    result.append(f"Atomspace: {len(all_atoms)} atoms (space.metta + inferred.metta)")
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
