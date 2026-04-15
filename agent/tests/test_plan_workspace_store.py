"""plan_workspace_store: manifest + prior digest."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture()
def fake_ws(monkeypatch):
    import services.plan_workspace_store as pws

    root = Path(tempfile.mkdtemp(prefix="layla_plan_ws_"))
    # Must patch the binding used by plan_workspace_store (not only registry).
    monkeypatch.setattr(pws, "inside_sandbox", lambda p: True)
    return root


def test_mirror_and_prior_digest(fake_ws, monkeypatch):
    from services import plan_workspace_store as pws

    plan = {
        "id": "p1",
        "workspace_root": str(fake_ws),
        "goal": "Refactor auth",
        "context": "",
        "steps": [{"id": 1, "description": "step"}],
        "status": "draft",
        "conversation_id": "",
        "created_at": "t0",
        "updated_at": "t1",
    }
    pws.mirror_sqlite_plan(plan)
    snap = fake_ws / ".layla" / "plan_store" / "plans" / "p1.json"
    assert snap.is_file()
    data = json.loads(snap.read_text(encoding="utf-8"))
    assert data["id"] == "p1"
    assert data["source"] == "sqlite"
    d = pws.prior_plans_digest(str(fake_ws), limit=5)
    assert "Refactor" in d or "p1" in d


def test_coerce_tool_result():
    from services.plan_step_result_models import coerce_tool_result

    assert coerce_tool_result("write_file", {"ok": True, "path": "/x"})["path"] == "/x"
    assert coerce_tool_result("run_tests", {"ok": True, "returncode": 0, "passed": 2})["passed"] == 2
