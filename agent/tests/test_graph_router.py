"""Knowledge-graph HTTP API (routers/graph.py).

The graph store (layla/memory/memory_graph.py) had been writing entities and auto-linked
`similar_to` edges for the whole life of the memory layer with NO reader — no router, no UI.
These tests pin the read path against the schema the store actually persists: GraphML nodes
carrying `label` / `metadata` (a JSON *string*) / `created_at`, and edges carrying `relation`.

Every test writes its own graph into tmp_path. Without that the suite would read (and, on a
missing file, WRITE) the operator's real agent/layla/memory/knowledge_graph.graphml — the store
resolves its path from __file__, not from LAYLA_DATA_DIR, so conftest's data-dir isolation does
not cover it.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _isolate(tmp_path):
    """Point the graph store at tmp_path. Same shape as test_memory_graph_atomic._isolated."""
    import layla.memory.memory_graph as mg

    return (
        patch.object(mg, "GRAPH_PATH", tmp_path / "kg.graphml"),
        patch.object(mg, "LEGACY_PATH", tmp_path / "kg.json"),
        patch.object(mg, "MEMORY_DIR", tmp_path),
    )


def _seed(tmp_path, nodes, edges=()):
    """Write a graph in the store's real on-disk shape and return a client bound to it.

    Written with networkx + _save_graph rather than add_node() so the fixture cannot reach the
    embedder: add_node's auto-linker calls vector_store.embed() before anything is patchable at
    the call site, and a cold HuggingFace download inside a unit test is a CI timeout waiting to
    happen. `test_router_reads_what_the_real_writers_wrote` covers the add_node path explicitly.
    """
    import networkx as nx

    import layla.memory.memory_graph as mg

    G = nx.DiGraph()
    for nid, label, meta, created in nodes:
        G.add_node(str(nid), label=label, metadata=json.dumps(meta), created_at=created)
    for src, dst, relation in edges:
        G.add_edge(str(src), str(dst), relation=relation)
    mg._save_graph(G)


@pytest.fixture
def client():
    import main

    return TestClient(main.app)


# ── empty graph ───────────────────────────────────────────────────────────────

def test_empty_graph_reports_zeros_not_an_error(client, tmp_path):
    """A brand-new install has no entities. That is a valid state, not a failure —
    the panel must be able to say 'nothing yet' rather than render an error."""
    p1, p2, p3 = _isolate(tmp_path)
    with p1, p2, p3:
        stats = client.get("/graph/stats")
        assert stats.status_code == 200
        s = stats.json()
        assert s["ok"] is True
        assert s["entity_count"] == 0
        assert s["relationship_count"] == 0
        assert s["isolated_count"] == 0
        assert s["relation_counts"] == []
        assert s["most_connected"] == []
        assert s["newest"] == []

        listing = client.get("/graph/entities")
        assert listing.status_code == 200
        d = listing.json()
        assert d["ok"] is True
        assert d["entities"] == []
        assert d["total"] == 0
        assert d["matched"] == 0

        missing = client.get("/graph/entity/0")
        assert missing.status_code == 404
        assert "not found" in missing.json()["detail"]


# ── entities listing ──────────────────────────────────────────────────────────

def test_entities_are_listed_newest_first_with_degree(client, tmp_path):
    p1, p2, p3 = _isolate(tmp_path)
    with p1, p2, p3:
        _seed(
            tmp_path,
            nodes=[
                (0, "Ahmed prefers email", {"source": "learning"}, "2026-01-01T00:00:00"),
                (1, "Project Castilla", {"source": "project"}, "2026-02-01T00:00:00"),
                (2, "User ships on Fridays", {"source": "timeline"}, "2026-03-01T00:00:00"),
            ],
            edges=[(0, 1, "similar_to")],
        )
        d = client.get("/graph/entities").json()
        assert d["ok"] is True
        assert d["total"] == 3
        assert d["matched"] == 3
        labels = [e["label"] for e in d["entities"]]
        assert labels == ["User ships on Fridays", "Project Castilla", "Ahmed prefers email"]

        by_label = {e["label"]: e for e in d["entities"]}
        assert by_label["Ahmed prefers email"]["degree"] == 1
        assert by_label["Ahmed prefers email"]["relations"] == ["similar_to"]
        assert by_label["User ships on Fridays"]["degree"] == 0
        # metadata is stored as a JSON string in GraphML — the API must hand back a dict
        assert by_label["Project Castilla"]["metadata"] == {"source": "project"}


def test_entities_search_filters_label_and_metadata(client, tmp_path):
    p1, p2, p3 = _isolate(tmp_path)
    with p1, p2, p3:
        _seed(
            tmp_path,
            nodes=[
                (0, "Ahmed prefers email", {"source": "learning"}, "2026-01-01T00:00:00"),
                (1, "Project Castilla", {"source": "project"}, "2026-02-01T00:00:00"),
            ],
        )
        hit = client.get("/graph/entities", params={"q": "castilla"}).json()
        assert hit["matched"] == 1
        assert hit["total"] == 2  # total is the whole graph, matched is the filtered set
        assert hit["entities"][0]["label"] == "Project Castilla"

        # metadata values are searchable too
        meta_hit = client.get("/graph/entities", params={"q": "learning"}).json()
        assert [e["label"] for e in meta_hit["entities"]] == ["Ahmed prefers email"]

        miss = client.get("/graph/entities", params={"q": "nothing-matches-this"}).json()
        assert miss["matched"] == 0
        assert miss["entities"] == []


def test_entities_paging_walks_the_whole_graph(client, tmp_path):
    p1, p2, p3 = _isolate(tmp_path)
    with p1, p2, p3:
        _seed(tmp_path, nodes=[(i, f"entity-{i:02d}", {}, f"2026-01-{i + 1:02d}T00:00:00") for i in range(7)])
        first = client.get("/graph/entities", params={"limit": 3, "offset": 0}).json()
        second = client.get("/graph/entities", params={"limit": 3, "offset": 3}).json()
        third = client.get("/graph/entities", params={"limit": 3, "offset": 6}).json()
        assert [len(p["entities"]) for p in (first, second, third)] == [3, 3, 1]
        seen = [e["id"] for p in (first, second, third) for e in p["entities"]]
        assert len(set(seen)) == 7          # no page overlap, nothing dropped
        assert all(p["matched"] == 7 for p in (first, second, third))

        # the cap is enforced rather than silently honoured
        assert client.get("/graph/entities", params={"limit": 5000}).status_code == 422


# ── entity detail ─────────────────────────────────────────────────────────────

def test_entity_detail_carries_both_relationship_directions(client, tmp_path):
    p1, p2, p3 = _isolate(tmp_path)
    with p1, p2, p3:
        _seed(
            tmp_path,
            nodes=[
                (0, "Layla", {"kind": "identity"}, "2026-01-01T00:00:00"),
                (1, "Project Castilla", {}, "2026-01-02T00:00:00"),
                (2, "ship the UI", {}, "2026-01-03T00:00:00"),
            ],
            edges=[(0, 1, "works_on"), (2, 0, "assigned_to")],
        )
        r = client.get("/graph/entity/0")
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert d["entity"]["label"] == "Layla"
        assert d["entity"]["metadata"] == {"kind": "identity"}
        assert d["outgoing"] == [{"id": "1", "label": "Project Castilla", "relation": "works_on"}]
        assert d["incoming"] == [{"id": "2", "label": "ship the UI", "relation": "assigned_to"}]
        assert d["relationship_count"] == 2
        assert d["neighbor_count"] == 2

        # an entity with no edges is a valid answer, not a 404
        leaf = client.get("/graph/entity/1").json()
        assert leaf["relationship_count"] == 1
        assert leaf["incoming"][0]["relation"] == "works_on"
        assert leaf["outgoing"] == []


def test_listed_entity_ids_round_trip_to_the_detail_endpoint(client, tmp_path):
    """The id the list hands the UI must be the id the detail route accepts. load_graph()
    coerces ids to ints and falls back to a positional index for non-numeric ones — an id
    that does not round-trip is a dead link in the panel."""
    p1, p2, p3 = _isolate(tmp_path)
    with p1, p2, p3:
        _seed(tmp_path, nodes=[(0, "alpha", {}, "2026-01-01T00:00:00"), (1, "beta", {}, "2026-01-02T00:00:00")])
        for e in client.get("/graph/entities").json()["entities"]:
            got = client.get(f"/graph/entity/{e['id']}")
            assert got.status_code == 200, e
            assert got.json()["entity"]["label"] == e["label"]


def test_unknown_entity_is_404(client, tmp_path):
    p1, p2, p3 = _isolate(tmp_path)
    with p1, p2, p3:
        _seed(tmp_path, nodes=[(0, "alpha", {}, "2026-01-01T00:00:00")])
        assert client.get("/graph/entity/999").status_code == 404


# ── stats ─────────────────────────────────────────────────────────────────────

def test_stats_counts_relations_and_isolated_entities(client, tmp_path):
    p1, p2, p3 = _isolate(tmp_path)
    with p1, p2, p3:
        _seed(
            tmp_path,
            nodes=[
                (0, "hub", {}, "2026-01-01T00:00:00"),
                (1, "spoke-a", {}, "2026-01-02T00:00:00"),
                (2, "spoke-b", {}, "2026-01-03T00:00:00"),
                (3, "spoke-c", {}, "2026-01-04T00:00:00"),
                (4, "orphan", {}, "2026-01-05T00:00:00"),
            ],
            edges=[(0, 1, "similar_to"), (0, 2, "similar_to"), (0, 3, "mentions")],
        )
        s = client.get("/graph/stats").json()
        assert s["entity_count"] == 5
        assert s["relationship_count"] == 3
        assert s["isolated_count"] == 1                       # only "orphan"
        assert s["relation_counts"] == [
            {"relation": "similar_to", "count": 2},
            {"relation": "mentions", "count": 1},
        ]
        assert s["most_connected"][0] == {"id": "0", "label": "hub", "degree": 3}
        assert "orphan" not in [m["label"] for m in s["most_connected"]]
        assert s["newest"][0]["label"] == "orphan"            # newest by created_at
        assert client.get("/graph/stats", params={"top": 1}).json()["newest"] == s["newest"][:1]


def test_unlabelled_edges_are_not_reported_as_a_blank_relation(client, tmp_path):
    """Legacy-JSON migration writes relation="" — the histogram must name that state
    rather than emitting an empty key the UI would render as a blank chip."""
    p1, p2, p3 = _isolate(tmp_path)
    with p1, p2, p3:
        _seed(
            tmp_path,
            nodes=[(0, "a", {}, "2026-01-01T00:00:00"), (1, "b", {}, "2026-01-02T00:00:00")],
            edges=[(0, 1, "")],
        )
        assert client.get("/graph/stats").json()["relation_counts"] == [
            {"relation": "(unlabelled)", "count": 1},
        ]


# ── the store's real writers ──────────────────────────────────────────────────

def test_router_reads_what_the_real_writers_wrote(client, tmp_path):
    """End-to-end against add_node()/add_edge() — the functions the memory pipeline calls.
    Pins that the router reads the LIVE schema, not a shape the tests invented."""
    import layla.memory.memory_graph as mg

    p1, p2, p3 = _isolate(tmp_path)
    with p1, p2, p3, \
            patch("layla.memory.vector_store.embed", lambda *a, **k: [0.0] * 8), \
            patch("layla.memory.vector_store.search_similar", lambda *a, **k: []):
        a = mg.add_node("User builds Layla", {"source": "conversation"})
        b = mg.add_node("Layla runs locally", {"source": "conversation"})
        mg.add_edge(a, b, "relates_to")

        listing = client.get("/graph/entities").json()
        assert listing["total"] == 2
        assert {e["label"] for e in listing["entities"]} == {"User builds Layla", "Layla runs locally"}
        assert all(e["created_at"] for e in listing["entities"])       # add_node stamps created_at

        detail = client.get(f"/graph/entity/{a}").json()
        assert detail["entity"]["metadata"] == {"source": "conversation"}
        assert detail["outgoing"] == [{"id": str(b), "label": "Layla runs locally", "relation": "relates_to"}]


# ── read-only by construction ─────────────────────────────────────────────────

def test_graph_router_exposes_no_mutation_endpoints(client):
    """The viewer must not be able to plant entities. Anything written here re-enters the
    prompt as if Layla had learned it — the 'planted test data' failure mode, with a UI.

    Read through the OpenAPI schema, not app.routes: this FastAPI builds included routers
    lazily (app.routes holds _IncludedRouter placeholders whose .path is None), so walking
    it directly reports an empty, always-passing result.
    """
    spec = client.get("/openapi.json").json()
    graph_paths = {p: ops for p, ops in spec["paths"].items() if p.startswith("/graph")}
    assert graph_paths, "the /graph router is not mounted in main.py"
    assert set(graph_paths) == {"/graph/stats", "/graph/entities", "/graph/entity/{entity_id}"}
    mutating = {
        f"{verb.upper()} {path}"
        for path, ops in graph_paths.items()
        for verb in ops
        if verb.lower() not in ("get", "head")
    }
    assert not mutating, f"/graph exposes mutating endpoint(s): {sorted(mutating)}"
