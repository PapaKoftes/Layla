"""Wiring guard: the search_backend selection is HONORED, not a silent config lie.

Two seams were unwired (found in the finish-line review):
  - WRITE: save_learning indexed into Elasticsearch ONLY (a direct elasticsearch_bridge call), so a
    user who selected search_backend=meilisearch indexed nothing there.
  - READ: the /memories keyword tier called sqlite FTS directly, never routing through search_router,
    so even an indexed external backend was never consulted.

These tests pin both seams via mocks (no live Meilisearch/Elasticsearch server required); the actual
server round-trip is covered by test_meilisearch_bridge / test_elasticsearch_bridge.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


def test_save_learning_fans_out_to_every_enabled_backend(isolated_db, monkeypatch):
    """A selected Meilisearch backend must be indexed on save — previously it was Elasticsearch-only."""
    import runtime_safety
    from services.memory.memory_router import save_learning

    cfg = {**runtime_safety.load_config(), "meilisearch_enabled": True, "elasticsearch_enabled": False}
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)

    with patch("services.retrieval.meilisearch_bridge.index_learning") as ms_index:
        save_learning("The falcon roosts on the north tower at dusk", kind="fact", source="t")
        assert ms_index.called, (
            "save_learning must fan out to the selected Meilisearch backend via search_router "
            "(it used to call elasticsearch_bridge directly, so Meilisearch was never indexed)"
        )


def test_memories_search_routes_through_search_router(monkeypatch):
    """The /memories keyword tier must consult the selected backend via search_router."""
    import routers.learn as learn
    from layla.memory import vector_store

    # Force the vector primary to fail so the keyword/fallback tier runs.
    monkeypatch.setattr(learn, "get_touch_activity", lambda: (lambda: None))
    monkeypatch.setattr(
        vector_store, "search_memories_full",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no vector")),
    )
    with patch(
        "services.retrieval.search_router.search",
        return_value={"ok": True, "hits": [{"text": "routed via meili"}], "backend": "meilisearch"},
    ) as srch:
        resp = learn.search_memories(q="falcon", n=5, aspect_id="")
        srch.assert_called_once()

    body = json.loads(resp.body)
    assert body["memories"] == ["routed via meili"], "the endpoint must return the routed backend's hits"
    assert body.get("backend") == "meilisearch", "the endpoint must report which backend answered"


def test_search_router_sqlite_path_returns_real_hits(isolated_db):
    """The ALWAYS-available sqlite tier of search_router must actually work — NOT mocked.

    Regression guard: search_router called search_learnings_fts(query, limit=...) (wrong kwarg → the
    signature is n=) and imported a non-existent get_db, so BOTH sqlite tiers raised and search_router
    returned {"backend":"none"} for every no-external-backend install. The other wiring tests mock
    search_router.search wholesale and could not catch it. This one drives the real sqlite path."""
    from layla.memory.learnings import save_learning
    from services.retrieval import search_router

    save_learning("The zephyr deploy runbook lives at ops/deploy/RUNBOOK-zephyr.md",
                  kind="fact", source="t", bypass_rate_limit=True)

    res = search_router.search("zephyr deploy runbook", limit=5, cfg={"search_backend": "sqlite_fts"})
    assert res.get("ok"), f"sqlite_fts tier must succeed, got {res}"
    assert res.get("backend") in ("sqlite_fts", "sqlite_like"), res
    hits = res.get("hits") or []
    assert any("zephyr" in (h.get("content") or h.get("text") or "").lower() for h in hits), (
        f"the seeded fact must be recalled via the sqlite keyword tier, got {res}"
    )

    # The LIKE fallback (used when FTS5 is unavailable) must also be alive, not raise on a bad import.
    like = search_router._search_sqlite_like({}, "zephyr", 5)
    assert like.get("ok") and (like.get("hits")), f"LIKE fallback must return hits, got {like}"


def test_aspect_scoped_memories_search_keeps_direct_fts(monkeypatch):
    """Aspect-scoped search keeps the direct FTS path (search_router does not thread aspect_id)."""
    import routers.learn as learn
    from layla.memory import vector_store

    monkeypatch.setattr(learn, "get_touch_activity", lambda: (lambda: None))
    monkeypatch.setattr(
        vector_store, "search_memories_full",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no vector")),
    )
    with patch("layla.memory.db.search_learnings_fts", return_value=[{"content": "aspect hit"}]) as fts, \
         patch("services.retrieval.search_router.search") as srch:
        resp = learn.search_memories(q="falcon", n=5, aspect_id="morrigan")
        fts.assert_called_once()
        srch.assert_not_called()

    body = json.loads(resp.body)
    assert body["memories"] == ["aspect hit"]
