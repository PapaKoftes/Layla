"""
Knowledge graph auto-expansion.
When new learnings are stored: extract entities, create edges between them.
Uses load_graph/save_graph from memory_graph (no private API).
"""
import re
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent


def expand_graph_from_learning(content: str) -> None:
    """
    Extract entities from learning text; add nodes and edges to knowledge graph.
    Example: "FAISS is used for vector search" -> FAISS -> vector_search
    """
    if not content or len(content.strip()) < 15:
        return
    entities = _extract_entities(content)
    if len(entities) < 2:
        return
    try:
        from layla.memory.memory_graph import load_graph, save_graph
        from layla.time_utils import utcnow
        data = load_graph()
        nodes = list(data.get("nodes") or [])
        edges = list(data.get("edges") or [])
        label_to_id: dict[str, int] = {}
        max_id = max((n.get("id", 0) for n in nodes), default=-1)
        for lbl in entities:
            lbl_clean = _normalize_label(lbl)
            if not lbl_clean or len(lbl_clean) < 2:
                continue
            key = lbl_clean.lower()
            if key in label_to_id:
                continue
            # Find existing node with same label
            existing = next((n for n in nodes if (n.get("label") or "").strip().lower() == key), None)
            if existing:
                label_to_id[key] = int(existing.get("id", 0))
            else:
                max_id += 1
                nodes.append({"id": max_id, "label": lbl_clean[:120], "metadata": {}, "created_at": utcnow().isoformat()})
                label_to_id[key] = max_id
        vals = list(label_to_id.values())
        existing_pairs = {(e["src"], e["dst"]) for e in edges}
        for i in range(len(vals) - 1):
            if vals[i] != vals[i + 1] and (vals[i], vals[i + 1]) not in existing_pairs:
                edges.append({"src": vals[i], "dst": vals[i + 1], "relation": "related_in_learning"})
                existing_pairs.add((vals[i], vals[i + 1]))
        if len(edges) > len(data.get("edges") or []):
            save_graph({"nodes": nodes, "edges": edges})
    except Exception:
        pass


def _extract_entities(text: str) -> list[str]:
    """Extract candidate entities. Prefer spaCy NER, else regex for CamelCase/ALL_CAPS."""
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
        doc = nlp(text[:2000])
        out = []
        for ent in doc.ents:
            if ent.label_ in ("ORG", "PRODUCT", "GPE", "TECH", "PERSON", "WORK_OF_ART") or len(ent.text) > 3:
                out.append(ent.text.strip())
        if out:
            return list(dict.fromkeys(out))
    except Exception:
        pass
    # Fallback: CamelCase, ALL_CAPS, quoted
    seen = set()
    for m in re.finditer(r"[A-Z][a-z]+(?:[A-Z][a-z]+)+|[A-Z]{2,}|[\"']([^\"']{3,50})[\"']", text):
        s = (m.group(1) if m.lastindex else m.group(0)).strip()
        if s and s.lower() not in ("the", "and", "for", "with", "from"):
            seen.add(s)
    return list(seen)[:10]


def _normalize_label(s: str) -> str:
    """Normalize entity label for graph node."""
    return s.strip()[:80] if s else ""
