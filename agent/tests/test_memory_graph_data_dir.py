"""memory_graph resolves its GraphML path PER CALL under LAYLA_DATA_DIR — model-free, pure path/DB.

The defect (plan item 30, data-integrity): the store resolved knowledge_graph.graphml from `__file__`
at import, so it IGNORED LAYLA_DATA_DIR and every test / tool wrote the OPERATOR'S REAL graph at
agent/layla/memory/knowledge_graph.graphml — the exact "module resolves a data path without honouring
LAYLA_DATA_DIR" class the write-tracer hunts.

These tests pin the fix without loading a model or an embedder:
  * with LAYLA_DATA_DIR set, add_node materialises the graph UNDER that dir (not under agent/);
  * the operator's REAL graphml is never touched (byte-for-byte identical, mtime unchanged);
  * the legacy `patch.object(mg, "GRAPH_PATH", ...)` isolation idiom still wins (back-compat).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import layla.memory.memory_graph as mg

# The operator's real graph — must be READ-ONLY for the whole life of this module. Resolved from the
# store's own import-time default so the assertion tracks the true legacy location, not a literal.
REAL_GRAPH = mg._DEFAULT_GRAPH_PATH


def _stat_fingerprint(p: Path):
    """(size, mtime_ns, sha256) — a strong 'this file was not written' fingerprint."""
    st = p.stat()
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    return st.st_size, st.st_mtime_ns, digest


def _no_embedder():
    """Neutralise add_node's auto-linker so the test never reaches the (offline/cold) embedder.
    add_node does `from layla.memory.vector_store import embed, search_similar` at call time, so
    patching the module attributes is what the call actually binds to."""
    return (
        patch("layla.memory.vector_store.embed", lambda *a, **k: [0.0] * 8),
        patch("layla.memory.vector_store.search_similar", lambda *a, **k: []),
    )


def test_add_node_materialises_under_layla_data_dir(monkeypatch, tmp_path):
    """With LAYLA_DATA_DIR=tmp_path and NO module patch, the graphml is created under tmp_path
    (via the canonical data_paths resolver: <LAYLA_DATA_DIR>/.layla/knowledge_graph.graphml)."""
    from services.infrastructure.data_paths import layla_data_file

    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))

    # Capture the operator's real graph BEFORE we touch anything.
    real_before = _stat_fingerprint(REAL_GRAPH) if REAL_GRAPH.exists() else None

    p_embed, p_search = _no_embedder()
    with p_embed, p_search:
        # The resolver must point at tmp_path, resolved per call — never the __file__ location.
        resolved = mg._resolve_graph_path()
        assert tmp_path in resolved.parents, f"{resolved} is not under {tmp_path}"
        assert REAL_GRAPH.parent not in resolved.parents

        node_id = mg.add_node("data-dir-probe-node")
        assert node_id >= 0

    expected = layla_data_file("knowledge_graph.graphml")
    assert expected.exists(), f"graphml not materialised at {expected}"
    assert tmp_path in expected.parents
    # The label we just wrote is present in the on-disk file under tmp_path.
    assert "data-dir-probe-node" in expected.read_text(encoding="utf-8")

    # The operator's real graph was NOT written (the whole point). Migration may READ it (copy2 source)
    # but must never modify it — byte-for-byte identical, same mtime.
    if real_before is not None:
        assert _stat_fingerprint(REAL_GRAPH) == real_before, "operator's real graphml was modified!"
    # And nothing new appeared beside it (no stray .tmp/.bak written into agent/layla/memory/).
    assert not (REAL_GRAPH.with_name(REAL_GRAPH.name + ".tmp")).exists()


def test_load_and_reads_round_trip_under_data_dir(monkeypatch, tmp_path):
    """A full write→read round-trip stays entirely under LAYLA_DATA_DIR."""
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))
    real_before = _stat_fingerprint(REAL_GRAPH) if REAL_GRAPH.exists() else None

    p_embed, p_search = _no_embedder()
    with p_embed, p_search:
        a = mg.add_node("alpha-under-datadir")
        b = mg.add_node("beta-under-datadir")
        mg.add_edge(a, b, "relates_to")
        labels = {n["label"] for n in mg.load_graph()["nodes"]}
        assert {"alpha-under-datadir", "beta-under-datadir"} <= labels
        assert any(e["relation"] == "relates_to" for e in mg.load_graph()["edges"])

    if real_before is not None:
        assert _stat_fingerprint(REAL_GRAPH) == real_before, "operator's real graphml was modified!"


def test_patched_graph_path_still_wins_backcompat(monkeypatch, tmp_path):
    """Back-compat: the historical `patch.object(mg, "GRAPH_PATH", ...)` isolation idiom must still
    take precedence over LAYLA_DATA_DIR, writing verbatim to the patched path — otherwise every
    existing test in test_memory_graph_atomic / test_graph_router would silently break."""
    data_dir = tmp_path / "data"
    patched = tmp_path / "patched" / "kg.graphml"
    patched.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LAYLA_DATA_DIR", str(data_dir))
    real_before = _stat_fingerprint(REAL_GRAPH) if REAL_GRAPH.exists() else None

    p_embed, p_search = _no_embedder()
    with patch.object(mg, "GRAPH_PATH", patched), \
            patch.object(mg, "LEGACY_PATH", tmp_path / "patched" / "kg.json"), \
            patch.object(mg, "MEMORY_DIR", tmp_path / "patched"), \
            p_embed, p_search:
        assert mg._module_overridden() is True
        assert mg._resolve_graph_path() == patched
        mg.add_node("goes-to-patched-path")
        assert patched.exists()
        # LAYLA_DATA_DIR was NOT consulted while patched — nothing under data_dir/.layla.
        assert not (data_dir / ".layla" / "knowledge_graph.graphml").exists()

    if real_before is not None:
        assert _stat_fingerprint(REAL_GRAPH) == real_before, "operator's real graphml was modified!"


def test_legacy_graph_migrated_non_destructively(monkeypatch, tmp_path):
    """When LAYLA_DATA_DIR has no graph yet but a legacy graph exists at the __file__ location, the
    store COPIES it forward once (never moves it). Proven against a synthetic legacy file so the
    assertion does not depend on the operator's real node count — and the operator's real graph is
    still verified untouched."""
    import networkx as nx

    from services.infrastructure.data_paths import layla_data_file

    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))
    real_before = _stat_fingerprint(REAL_GRAPH) if REAL_GRAPH.exists() else None

    # Build a synthetic "legacy" graph and point the migration source at it (NOT the operator's file).
    legacy = tmp_path / "legacy" / "knowledge_graph.graphml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    G = nx.DiGraph()
    G.add_node("0", label="legacy-entity", metadata="{}", created_at="2026-01-01T00:00:00")
    nx.write_graphml(G, legacy)
    legacy_fp = _stat_fingerprint(legacy)

    target = layla_data_file("knowledge_graph.graphml")
    assert not target.exists()

    # Make `legacy` the module's DEFAULT graph location with NO override in effect: both the live
    # constant and its import-time snapshot point at `legacy`, so _module_overridden() stays False and
    # the migration source is `legacy`. (Patching only _DEFAULT_GRAPH_PATH would read as an override.)
    with patch.object(mg, "GRAPH_PATH", legacy), patch.object(mg, "_DEFAULT_GRAPH_PATH", legacy):
        assert mg._module_overridden() is False
        mg._migrate_legacy_graph_if_needed(target)

    # Copied forward…
    assert target.exists()
    assert "legacy-entity" in target.read_text(encoding="utf-8")
    # …and the source legacy file is byte-for-byte unchanged (copy, not move).
    assert _stat_fingerprint(legacy) == legacy_fp

    if real_before is not None:
        assert _stat_fingerprint(REAL_GRAPH) == real_before, "operator's real graphml was modified!"
