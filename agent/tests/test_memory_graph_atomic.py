"""Knowledge-graph writes are lock-serialised and atomic: concurrent add_node calls
don't lose updates, and a save leaves no truncated file / temp leftover."""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import layla.memory.memory_graph as mg


def _isolated(tmp_path: Path):
    return (
        patch.object(mg, "GRAPH_PATH", tmp_path / "kg.graphml"),
        patch.object(mg, "LEGACY_PATH", tmp_path / "kg.json"),
        patch.object(mg, "MEMORY_DIR", tmp_path),
        # Skip the auto-link vector search (irrelevant to the write-atomicity contract).
        patch("layla.memory.vector_store.search_similar", lambda *a, **k: []),
    )


def test_concurrent_add_node_no_lost_updates(tmp_path):
    p_graph, p_legacy, p_dir, p_vs = _isolated(tmp_path)
    with p_graph, p_legacy, p_dir, p_vs:
        def worker(i):
            for j in range(5):
                mg.add_node(f"node-{i}-{j}")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        nodes = mg.load_graph()["nodes"]
        assert len(nodes) == 20                              # 4 threads x 5 — none lost
        assert not (tmp_path / "kg.graphml.tmp").exists()     # atomic: no temp leftover
        assert (tmp_path / "kg.graphml").exists()


def test_add_edge_persists_atomically(tmp_path):
    p_graph, p_legacy, p_dir, p_vs = _isolated(tmp_path)
    with p_graph, p_legacy, p_dir, p_vs:
        a = mg.add_node("alpha")
        b = mg.add_node("beta")
        mg.add_edge(a, b, "relates_to")
        edges = mg.load_graph()["edges"]
        assert any(e["relation"] == "relates_to" for e in edges)
        assert not (tmp_path / "kg.graphml.tmp").exists()
