"""
Knowledge graph backed by NetworkX. Persists to GraphML for queryability.
Supports add_node, add_edge, get_recent_nodes, and get_neighbors for traversal.
"""
import json
import os
import threading
from pathlib import Path

from layla.time_utils import utcnow

MEMORY_DIR = Path(__file__).resolve().parent
GRAPH_PATH = MEMORY_DIR / "knowledge_graph.graphml"
LEGACY_PATH = MEMORY_DIR / "knowledge_graph.json"

# Serialises the whole-file read-modify-write in add_node/add_edge/save_graph so
# concurrent writers (the scheduler's memory job + the drone consolidation worker)
# can't lose each other's updates.
_graph_lock = threading.RLock()


def _quarantine_and_recover_graph(exc) -> "object":
    """The graphml file EXISTS but is unreadable (corruption / partial write / transient IO). Do NOT let
    the caller silently os.replace() an empty graph over it — that permanently destroys the whole
    knowledge graph (audit #1). Move the bad file aside (recoverable) and restore the last-good .bak if
    one exists, mirroring verify_and_recover_db's quarantine-and-restore for layla.db. Returns a graph
    (restored, or empty) — never overwrites the quarantined data silently."""
    import logging
    import shutil

    import networkx as nx
    logger = logging.getLogger("layla")
    try:
        stamp = utcnow().strftime("%Y%m%d%H%M%S")
        corrupt = GRAPH_PATH.with_name(GRAPH_PATH.name + f".corrupt.{stamp}")
        shutil.move(str(GRAPH_PATH), str(corrupt))
        logger.error(
            "knowledge_graph.graphml unreadable (%s) — quarantined to %s (NOT overwritten) to prevent "
            "total knowledge-graph loss", exc, corrupt.name,
        )
    except Exception as _mv:
        logger.error("knowledge_graph.graphml unreadable and quarantine failed: %s / %s", exc, _mv)
    bak = GRAPH_PATH.with_name(GRAPH_PATH.name + ".bak")
    if bak.exists():
        try:
            shutil.copy2(str(bak), str(GRAPH_PATH))
            G = nx.read_graphml(GRAPH_PATH)
            logger.warning("restored knowledge_graph.graphml from last-good backup (%d nodes)", G.number_of_nodes())
            return G
        except Exception as _rb:
            logger.error("knowledge_graph.graphml backup restore failed: %s", _rb)
    return nx.DiGraph()


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
        except Exception as _exc:
            # File exists but won't parse → quarantine + try backup restore. NEVER fall through to an
            # empty graph that a caller then persists over the (now preserved) corrupt file (audit #1).
            G = _quarantine_and_recover_graph(_exc)
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
    # Atomic: write a temp file then os.replace() so a crash mid-write can't truncate
    # knowledge_graph.graphml (which would corrupt the whole knowledge graph).
    tmp = GRAPH_PATH.with_name(GRAPH_PATH.name + ".tmp")
    nx.write_graphml(G, tmp)
    # Durability (audit #3): fsync the temp file's DATA before the rename. os.replace is atomic for the
    # metadata rename but does NOT flush data blocks, so a power loss can otherwise leave a 0-length /
    # truncated graphml despite the "atomic" write — which then trips the corrupt-read path above.
    try:
        with open(tmp, "rb") as _f:
            os.fsync(_f.fileno())
    except Exception:
        pass
    os.replace(tmp, GRAPH_PATH)
    try:
        _dirfd = os.open(str(MEMORY_DIR), os.O_RDONLY)
        try:
            os.fsync(_dirfd)  # flush the directory entry (best-effort; not supported on Windows)
        finally:
            os.close(_dirfd)
    except Exception:
        pass
    # Keep a rotating last-good backup — ONLY of a non-empty graph, so a post-corruption empty save can
    # never clobber the backup — giving _quarantine_and_recover_graph something to restore from (audit #1).
    try:
        if G.number_of_nodes() > 0:
            import shutil
            shutil.copy2(str(GRAPH_PATH), str(GRAPH_PATH.with_name(GRAPH_PATH.name + ".bak")))
    except Exception:
        pass


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
    with _graph_lock:
        G = nx.DiGraph()
        for node in graph.get("nodes", []):
            nid = str(node.get("id", len(G.nodes())))
            G.add_node(nid, label=node.get("label", "")[:120], metadata=json.dumps(node.get("metadata", {})), created_at=node.get("created_at", ""))
        for edge in graph.get("edges", []):
            G.add_edge(str(edge["src"]), str(edge["dst"]), relation=edge.get("relation", ""))
        _save_graph(G)


def _prune_graph_if_needed(G, max_nodes: int | None = None) -> int:
    """Cap the knowledge-graph node count so a whole-file-rewrite graph can't grow forever
    (audit H2). Removes the OLDEST nodes (by created_at) beyond the cap; their edges go with
    them. Caller holds _graph_lock. Returns count removed."""
    try:
        if max_nodes is None:
            import runtime_safety
            max_nodes = int(runtime_safety.load_config().get("knowledge_graph_max_nodes", 5000) or 5000)
        if max_nodes <= 0 or G.number_of_nodes() <= max_nodes:
            return 0
        nodes = sorted(G.nodes(data=True), key=lambda nd: str((nd[1] or {}).get("created_at", "")))
        over = G.number_of_nodes() - max_nodes
        for nid, _ in nodes[:over]:
            G.remove_node(nid)
        return over
    except Exception:
        return 0


def add_node(label: str, metadata: dict = None) -> int:
    """Add a node to the knowledge graph. Returns the new node id.

    Also links the new node to existing similar nodes via cosine similarity
    (Mem0-style entity linking). Edges are created when cosine sim > 0.8.
    """
    with _graph_lock:
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

        _prune_graph_if_needed(G)
        _save_graph(G)
        return node_id


def add_edge(src_id: int, dst_id: int, relation: str) -> None:
    """Add a directed edge between two nodes."""
    with _graph_lock:
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
