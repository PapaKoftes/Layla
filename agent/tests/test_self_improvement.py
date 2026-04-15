from __future__ import annotations


def test_self_improvement_generate_and_approve(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYLA_DB_PATH", str(tmp_path / "layla.db"))

    from services.self_improvement import approve_batch, generate_proposals, list_proposals

    r = generate_proposals(session_summary="performance note", capability_levels={}, recent_failures=["x"])
    assert r["ok"] is True
    assert r["count_created"] >= 1

    pending = list_proposals(status="pending", limit=50)["proposals"]
    assert pending
    ids = [p["id"] for p in pending[:2]]
    rr = approve_batch(ids)
    assert rr["ok"] is True

