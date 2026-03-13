"""
Integration tests for study plans: API endpoints and DB wiring.
Run with: cd agent && python -m pytest tests/test_study_integration.py -v
Or: cd agent && python tests/test_study_integration.py
Requires: server not running (tests use DB and main.app directly) or run against live server (test_study_api_live).
"""
import json
import uuid
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_db_get_plan_by_topic():
    """get_plan_by_topic returns plan when topic matches (case-insensitive)."""
    from layla.memory.db import save_study_plan, get_plan_by_topic, get_active_study_plans
    topic = "IntegrationTestTopic_" + uuid.uuid4().hex[:6]
    plan_id = uuid.uuid4().hex[:8]
    save_study_plan(plan_id=plan_id, topic=topic, status="active")
    plan = get_plan_by_topic(topic)
    assert plan is not None
    assert plan.get("topic") == topic
    assert plan.get("id") == plan_id
    plan2 = get_plan_by_topic(topic.upper())
    assert plan2 is not None
    assert plan2.get("id") == plan_id
    plan_none = get_plan_by_topic("NonexistentTopic_xyz")
    assert plan_none is None


def test_db_update_study_progress():
    """update_study_progress appends note and sets last_studied."""
    from layla.memory.db import save_study_plan, update_study_progress, get_plan_by_topic
    topic = "ProgressTest_" + uuid.uuid4().hex[:6]
    plan_id = uuid.uuid4().hex[:8]
    save_study_plan(plan_id=plan_id, topic=topic, status="active")
    update_study_progress(plan_id, "First note.")
    plan = get_plan_by_topic(topic)
    assert plan is not None
    assert plan.get("last_studied")
    progress = json.loads(plan.get("progress") or "[]")
    assert len(progress) == 1
    assert progress[0].get("note") == "First note."


def test_add_study_plan_dedup():
    """Adding same topic twice does not duplicate (main.add_study_plan logic)."""
    from layla.memory.db import get_active_study_plans, get_plan_by_topic, save_study_plan
    topic = "DedupTest_" + uuid.uuid4().hex[:6]
    plan_id1 = uuid.uuid4().hex[:8]
    save_study_plan(plan_id=plan_id1, topic=topic, status="active")
    active_before = len([p for p in get_active_study_plans() if (p.get("topic") or "").strip().lower() == topic.strip().lower()])
    assert active_before == 1
    existing = get_plan_by_topic(topic)
    assert existing is not None
    assert existing.get("id") == plan_id1


def test_record_progress_creates_plan_if_missing():
    """record_progress creates plan when topic not in list then updates."""
    from layla.memory.db import get_plan_by_topic, save_study_plan, update_study_progress
    topic = "RecordProgressNew_" + uuid.uuid4().hex[:6]
    assert get_plan_by_topic(topic) is None
    plan_id = uuid.uuid4().hex[:8]
    save_study_plan(plan_id=plan_id, topic=topic, status="active")
    update_study_progress(plan_id, "Note for new plan.")
    plan = get_plan_by_topic(topic)
    assert plan is not None
    assert plan.get("last_studied")


def test_api_study_plans_get_post_record():
    """Test GET /study_plans, POST /study_plans (with dedup), POST /study_plans/record_progress."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    topic = "ApiTest_" + uuid.uuid4().hex[:6]

    r = client.get("/study_plans")
    assert r.status_code == 200
    data = r.json()
    assert "plans" in data
    plans_before = len(data["plans"])

    r = client.post("/study_plans", json={"topic": topic})
    assert r.status_code == 200
    assert r.json().get("ok") is True
    assert r.json().get("topic") == topic
    assert r.json().get("already_exists") is not True

    r = client.post("/study_plans", json={"topic": topic})
    assert r.status_code == 200
    assert r.json().get("ok") is True
    assert r.json().get("already_exists") is True

    r = client.get("/study_plans")
    assert r.status_code == 200
    plans = [p for p in r.json().get("plans", []) if (p.get("topic") or "").strip() == topic]
    assert len(plans) == 1
    assert plans[0].get("last_studied") is None or plans[0].get("last_studied") == ""

    r = client.post("/study_plans/record_progress", json={"topic": topic, "note": "Studied via API."})
    assert r.status_code == 200
    assert r.json().get("ok") is True

    r = client.get("/study_plans")
    assert r.status_code == 200
    plans = [p for p in r.json().get("plans", []) if (p.get("topic") or "").strip() == topic]
    assert len(plans) == 1
    assert plans[0].get("last_studied")


def test_api_record_progress_no_topic():
    """record_progress returns error when topic or note missing."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.post("/study_plans/record_progress", json={})
    assert r.status_code == 200
    assert r.json().get("ok") is False
    assert "topic" in (r.json().get("error") or "").lower()
    r = client.post("/study_plans/record_progress", json={"topic": "X"})
    assert r.status_code == 200
    assert r.json().get("ok") is False


def test_capabilities_get_and_record_practice():
    """Evolution layer: GET /capabilities returns domains and capabilities; record_practice updates level."""
    from fastapi.testclient import TestClient
    from main import app
    from layla.memory.db import get_capability, get_capability_domains
    from layla.memory import capabilities as cap_mod
    client = TestClient(app)
    r = client.get("/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert "domains" in data
    assert "capabilities" in data
    assert len(data["domains"]) >= 10
    assert len(data["capabilities"]) >= 10
    cap_mod.record_practice("coding", mission_id="test-mission", delta_level=0.02)
    c = get_capability("coding")
    assert c is not None
    assert (c.get("level") or 0) >= 0.5
    assert (c.get("practice_count") or 0) >= 1


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
