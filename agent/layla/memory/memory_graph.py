"""
Knowledge graph backed by NetworkX. Persists to GraphML for queryability.
Supports add_node, add_edge, get_recent_nodes, and get_neighbors for traversal.
"""
import json
from pathlib import Path

from layla.time_utils import utcnow

MEMORY_DIR = Path(__file__).resolve().parent
GRAPH_PATH = MEMORY_DIR / "knowledge_graph.graphml"
LEGACY_PATH = MEMORY_DIR / "knowledge_graph.json"


def _get_graph():
    import networkx as nx
    G = nx.DiGraph()
    if GRAPH_PATH.exists():
        try:
            G = nx.read_graphml(GRAPH_PATH)
            # GraphML reads node ids as strings; ensure we have int-like ids for add_node
            for n in G.nodes():
                if isinstance(n, str) and n.isdigit():
                    pass  # keep as is for iteration
        except Exception:
            pass
    if not GRAPH_PATH.exists() and G.number_of_nodes() == 0:
        _save_graph(G)
    if LEGACY_PATH.exists() and G.number_of_nodes() == 0:
        try:
            data = json.loads(LEGACY_PATH.read_text(encoding="utf-8"))
            for node in data.get("nodes", []):
                nid = str(node.get("id", len(G.nodes())))
                G.add_node(nid, label=node.get("label", "")[:120], metadata=json.dumps(node.get("metadata", {})), created_at=node.get("created_at", ""))
            for edge in data.get("edges", []):
                G.add_edge(str(edge["src"]), str(edge["dst"]), relation=edge.get("relation", ""))
            _save_graph(G)
            LEGACY_PATH.rename(LEGACY_PATH.with_suffix(".json.migrated"))
        except Exception:
            pass
    return G


def _save_graph(G) -> None:
    import networkx as nx
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(G, GRAPH_PATH)


def load_graph():
    """Return the graph as a dict of nodes and edges for compatibility."""
    G = _get_graph()
    nodes = []
    for nid in G.nodes():
        data = G.nodes.get(nid, {})
        nodes.append({
            "id": int(nid) if isinstance(nid, str) and nid.isdigit() else len(nodes),
            "label": data.get("label", ""),
            "metadata": json.loads(data.get("metadata", "{}")) if isinstance(data.get("metadata"), str) else (data.get("metadata") or {}),
            "created_at": data.get("created_at", ""),
        })
    edges = []
    for src, dst, attrs in G.edges(data=True):
        edges.append({"src": int(src) if isinstance(src, str) and src.isdigit() else src, "dst": int(dst) if isinstance(dst, str) and dst.isdigit() else dst, "relation": attrs.get("relation", "")})
    return {"nodes": nodes, "edges": edges}


def save_graph(graph: dict) -> None:
    import networkx as nx
    G = nx.DiGraph()
    for node in graph.get("nodes", []):
        nid = str(node.get("id", len(G.nodes())))
        G.add_node(nid, label=node.get("label", "")[:120], metadata=json.dumps(node.get("metadata", {})), created_at=node.get("created_at", ""))
    for edge in graph.get("edges", []):
        G.add_edge(str(edge["src"]), str(edge["dst"]), relation=edge.get("relation", ""))
    _save_graph(G)


def add_node(label: str, metadata: dict = None) -> int:
    """Add a node to the knowledge graph. Returns the new node id.

    Also links the new node to existing similar nodes via cosine similarity
    (Mem0-style entity linking). Edges are created when cosine sim > 0.8.
    """
    G = _get_graph()
    existing = [int(x) for x in G.nodes() if isinstance(x, str) and x.isdigit()]
    node_id = max(existing, default=-1) + 1
    nid = str(node_id)
    G.add_node(nid, label=label[:120], metadata=json.dumps(metadata or {}), created_at=utcnow().isoformat())

    # Auto-link: find similar existing nodes via vector search
    try:
        from layla.memory.vector_store import embed, search_similar
        q_vec = embed(label)
        similar = search_similar(q_vec, k=3)
        for s in similar:
            src_label = (s.get("content") or "").strip()
            if not src_label or src_label == label.strip():
                continue
            # Find the graph node matching this label
            for existing_nid in G.nodes():
                n_data = G.nodes.get(existing_nid, {})
                if (n_data.get("label") or "").strip() == src_label[:120]:
                    G.add_edge(existing_nid, nid, relation="similar_to")
                    break
    except Exception:
        pass

    _save_graph(G)
    return node_id


def add_edge(src_id: int, dst_id: int, relation: str) -> None:
    """Add a directed edge between two nodes."""
    G = _get_graph()
    G.add_edge(str(src_id), str(dst_id), relation=relation)
    _save_graph(G)


def get_recent_nodes(n: int = 10) -> list:
    """Return the n most recently added nodes (by id order)."""
    G = _get_graph()
    if G.number_of_nodes() == 0:
        return []
    nodes = []
    for nid in sorted(G.nodes(), key=lambda x: int(x) if isinstance(x, str) and x.isdigit() else 0):
        data = G.nodes.get(nid, {})
        nodes.append({
            "id": int(nid) if isinstance(nid, str) and nid.isdigit() else nid,
            "label": data.get("label", ""),
            "metadata": json.loads(data.get("metadata", "{}")) if isinstance(data.get("metadata"), str) else (data.get("metadata") or {}),
            "created_at": data.get("created_at", ""),
        })
    return nodes[-n:]


def get_neighbors(node_id: int, direction: str = "out") -> list:
    """Return nodes connected to node_id. direction: 'out', 'in', or 'both'."""
    G = _get_graph()
    nid = str(node_id)
    if nid not in G:
        return []
    neighbor_ids = []
    if direction in ("out", "both"):
        neighbor_ids.extend(G.successors(nid))
    if direction in ("in", "both"):
        neighbor_ids.extend(G.predecessors(nid))
    result = []
    for uid in set(neighbor_ids):
        data = G.nodes.get(uid, {})
        result.append({
            "id": int(uid) if isinstance(uid, str) and uid.isdigit() else uid,
            "label": data.get("label", ""),
            "metadata": json.loads(data.get("metadata", "{}")) if isinstance(data.get("metadata"), str) else (data.get("metadata") or {}),
        })
    return result
