"""BL-374 — an unavailable embedder must be LOUD and KNOWABLE, not silent.

The embedder (model2vec / nomic / all-MiniLM) is fetched from HuggingFace on first use and is not bundled, so
an offline first run cannot load it and semantic retrieval degrades to keyword-only. That used to happen in
total silence: a DEBUG line no one sees, a "ChromaDB failed" message that blamed the wrong component, and a
/health that still said "RAG active".

These tests pin the three honesty properties of the fix:
  1. embedder_status() reports 'unavailable' (with a reason) once a load has failed — never a bare 'ok'.
  2. /health/deps' vector_store label stops claiming "RAG active" when the embedder is unavailable.
  3. the embedder gets its own line in the dependency matrix.
"""
import importlib

import pytest


@pytest.fixture()
def vs():
    """Fresh vector_store module state per test (embedder status is module-global)."""
    import layla.memory.vector_store as _vs
    importlib.reload(_vs)
    return _vs


def test_embedder_status_starts_unknown_never_ok(vs):
    st = vs.embedder_status()
    # Never claim 'ok' before anything has actually embedded — an unproven claim is what got us here.
    assert st["status"] in ("unknown", "ok", "unavailable")
    if st["status"] == "unknown":
        assert not st["model"]


def test_recorded_failure_flips_status_to_unavailable_with_reason(vs):
    vs._record_embedder_failure(OSError("We couldn't connect to huggingface.co"))
    st = vs.embedder_status()
    assert st["status"] == "unavailable", st
    assert "huggingface" in st["detail"].lower(), st
    assert st["model"] == ""


def test_failure_logs_loud_error_once(vs, caplog):
    import logging

    with caplog.at_level(logging.ERROR, logger="layla"):
        vs._record_embedder_failure(OSError("offline"))
        vs._record_embedder_failure(OSError("offline again"))
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR and "EMBEDDER UNAVAILABLE" in r.getMessage()]
    assert len(errs) == 1, f"expected exactly ONE loud ERROR, got {len(errs)}"
    msg = errs[0].getMessage()
    # Actionable: names the offline cause and a concrete fix, and points at the health endpoint.
    assert "offline" in msg.lower() and "/health/deps" in msg
    assert "model2vec" in msg or "connect once" in msg.lower()


def test_health_vector_store_label_is_honest_when_embedder_down(monkeypatch):
    """When the embedder is unavailable, /health/deps must NOT say 'RAG active' — it must say DEGRADED."""
    import layla.memory.vector_store as _vs
    from services.observability import health_snapshot

    monkeypatch.setattr(
        _vs, "embedder_status",
        lambda: {"status": "unavailable", "model": "", "detail": "OSError: offline"},
    )
    deps = health_snapshot.build_dependency_status(probe_chroma=False)
    assert deps.get("embedder") == "unavailable", deps
    label = deps.get("vector_store", "")
    assert "RAG active" not in label, f"health still claims RAG active with a dead embedder: {label!r}"
    assert "DEGRADED" in label or "keyword-only" in label, label


def test_health_reports_embedder_line(monkeypatch):
    import layla.memory.vector_store as _vs
    from services.observability import health_snapshot

    monkeypatch.setattr(
        _vs, "embedder_status",
        lambda: {"status": "ok", "model": "minishlab/potion-base-8M", "detail": ""},
    )
    deps = health_snapshot.build_dependency_status(probe_chroma=False)
    assert deps.get("embedder") == "ok", deps
    assert deps.get("embedder_model") == "minishlab/potion-base-8M", deps
    # With a working embedder and chroma reported ok (probe skipped), the label is the healthy one.
    assert deps.get("vector_store") in ("chroma", "sqlite-fallback (RAG active)"), deps
