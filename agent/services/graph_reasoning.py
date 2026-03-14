"""
Knowledge graph reasoning. Entity extraction (spaCy) + graph expansion (networkx).
Expands query context via graph relationships.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")

_nlp = None
_nlp_failed = False


def _get_nlp():
    """Lazy-load spaCy model. Returns None if unavailable."""
    global _nlp, _nlp_failed
    if _nlp_failed:
        return None
    if _nlp is not None:
        return _nlp
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
    except Exception as e:
        logger.debug("spaCy unavailable for graph_reasoning: %s", e)
        _nlp_failed = True
    return _nlp


def extract_entities(text: str) -> list[dict[str, Any]]:
    """
    Extract named entities from text using spaCy.
    Returns list of {text, label, start, end}.
    Falls back to empty list when spaCy unavailable.
    """
    nlp = _get_nlp()
    if nlp is None or not (text or "").strip():
        return []
    try:
        doc = nlp(text.strip()[:5000])
        out = []
        for ent in doc.ents:
            out.append({
                "text": ent.text.strip(),
                "label": ent.label_,
                "start": ent.start_char,
                "end": ent.end_char,
            })
        return out
    except Exception as e:
        logger.debug("entity extraction failed: %s", e)
        return []


def expand_query_via_graph(query: str, max_hops: int = 2, max_nodes: int = 15) -> list[dict[str, Any]]:
    """
    Expand query context via knowledge graph relationships.
    1. Extract entities from query (spaCy)
    2. Find matching graph nodes by label
    3. Traverse graph (BFS) up to max_hops
    4. Return expanded node labels for context
    """
    try:
        from layla.memory.memory_graph import _get_graph, get_recent_nodes, get_neighbors
    except ImportError:
        return []

    G = _get_graph()
    if G.number_of_nodes() == 0:
        return []

    # Entity extraction or fallback: use significant query words
    entities = extract_entities(query)
    seed_labels = [e["text"] for e in entities if len(e["text"]) > 2]
    if not seed_labels:
        # Fallback: words longer than 3 chars
        seed_labels = [w for w in query.split() if len(w) > 3][:5]

    # Map label -> node id
    label_to_nid: dict[str, str] = {}
    for nid in G.nodes():
        data = G.nodes.get(nid, {})
        lbl = (data.get("label") or "").strip()
        if lbl:
            label_to_nid[lbl.lower()] = nid

    # Find seed nodes
    visited: set[str] = set()
    frontier: list[tuple[str, int]] = []  # (nid, hop)
    for lbl in seed_labels:
        key = lbl.lower()
        if key in label_to_nid:
            nid = label_to_nid[key]
            if nid not in visited:
                visited.add(nid)
                frontier.append((nid, 0))
        else:
            # Fuzzy: check if label is substring of any node label
            for node_lbl, nid in label_to_nid.items():
                if key in node_lbl and nid not in visited:
                    visited.add(nid)
                    frontier.append((nid, 0))
                    break

    # If no seeds, use recent nodes as entry points
    if not frontier:
        recent = get_recent_nodes(n=5)
        for n in recent:
            nid = str(n.get("id", ""))
            if nid in G.nodes() and nid not in visited:
                visited.add(nid)
                frontier.append((nid, 0))

    # BFS expansion
    result: list[dict[str, Any]] = []
    while frontier and len(result) < max_nodes:
        nid, hop = frontier.pop(0)
        data = G.nodes.get(nid, {})
        lbl = data.get("label", "")
        if lbl:
            result.append({"label": lbl, "hop": hop, "id": nid})

        if hop >= max_hops:
            continue

        neighbor_id = int(nid) if isinstance(nid, str) and nid.isdigit() else nid
        for neighbor in get_neighbors(neighbor_id, direction="both"):
            uid = str(neighbor.get("id", ""))
            if uid in G.nodes() and uid not in visited:
                visited.add(uid)
                frontier.append((uid, hop + 1))

    return result[:max_nodes]


def get_expanded_context(query: str, max_hops: int = 2, max_nodes: int = 15) -> str:
    """
    Return a string of expanded graph context for prompt injection.
    Format: "Knowledge graph associations: entity1; entity2; ..."
    """
    if not (query or "").strip():
        return ""
    nodes = expand_query_via_graph(query, max_hops=max_hops, max_nodes=max_nodes)
    if not nodes:
        return ""
    labels = [n["label"] for n in nodes if n.get("label")]
    if not labels:
        return ""
    return "Knowledge graph associations: " + "; ".join(labels[:12])
