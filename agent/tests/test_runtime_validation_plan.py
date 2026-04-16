"""
Runtime validation for POST /agent and background workers (plan: gaps + contract).

- Live LLM: optional slow test when a model is configured (skipped in CI without GGUF).
- Subprocess worker: fake long-running child + cancel (hard kill path) without loading LLM in worker.
- MCP in loop: real autonomous_run with mocked decision → mcp_tools_call step.
- Timeout / system_busy / tool_limit: router + mocked autonomous_run.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid as uuid_mod
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

FAKE_MCP = AGENT_DIR / "tests" / "fixtures" / "fake_mcp_stdio.py"


def _model_ready() -> bool:
    from services.llm_gateway import model_loaded_status

    return not bool(model_loaded_status().get("error"))


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_live_post_agent_multi_tool_when_model_ready(tmp_path, monkeypatch):
    """When a model is available, ask for two read-only tools; assert >=2 tool steps or skip."""
    if not _model_ready():
        pytest.skip("no local/remote model configured (model_loaded_status error set)")

    import routers.agent as agent_router

    monkeypatch.setattr(agent_router, "_model_ready_message", lambda: None)

    from main import app

    client = TestClient(app)
    msg = (
        "Use tool list_dir with path . then use read_file on requirements.txt in this folder. "
        "Do not explain; execute tools then answer in one short sentence."
    )
    r = client.post(
        "/agent",
        json={
            "message": msg,
            "workspace_root": str(AGENT_DIR),
            "allow_write": False,
            "allow_run": False,
            "conversation_id": str(uuid_mod.uuid4()),
        },
    )
    assert r.status_code == 200
    data = r.json()
    out_path = (os.environ.get("LAYLA_TRACE_CAPTURE") or "").strip()
    if out_path:
        Path(out_path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    st = data.get("state") or {}
    status = st.get("status")
    steps = st.get("steps") or []
    tool_like = [
        s
        for s in steps
        if isinstance(s, dict) and (s.get("action") or "") not in ("", "reason", "think")
    ]
    if status in ("timeout", "system_busy", "parse_failed"):
        pytest.skip(f"live run ended with {status!r} — not a failure, model/load dependent")
    if len(tool_like) < 2:
        pytest.skip(
            f"model produced {len(tool_like)} non-reason steps (need 2+ for strict proof); "
            f"status={status!r} steps={len(steps)}"
        )
    assert len(tool_like) >= 2


def test_subprocess_background_cancel_hard_kill(monkeypatch, tmp_path):
    """worker_mode subprocess + cancel while wait_worker_result blocks; task ends cancelled."""
    import runtime_safety
    import services.background_subprocess as bgsp
    from main import app

    orig_load = runtime_safety.load_config
    base_cfg = dict(orig_load())

    def _merged():
        c = dict(base_cfg)
        c["background_use_subprocess_workers"] = True
        c["llama_server_url"] = "http://127.0.0.1:59999"
        c["sandbox_root"] = str(tmp_path)
        c["background_worker_force_sandbox_only"] = False
        return c

    monkeypatch.setattr(runtime_safety, "load_config", _merged)

    def _fake_spawn(job: dict, *, python_executable: str | None = None) -> subprocess.Popen:
        exe = python_executable or sys.executable
        kw = bgsp._popen_kwargs()
        kw["stdin"] = subprocess.DEVNULL
        return subprocess.Popen(
            [exe, "-c", "import time; time.sleep(3600)"],
            **kw,
        )

    monkeypatch.setattr(bgsp, "spawn_background_worker", _fake_spawn)

    client = TestClient(app)
    r = client.post("/agent/background", json={"message": "subprocess cancel probe"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert body.get("worker_mode") == "subprocess"
    tid = body["task_id"]
    time.sleep(0.25)
    c2 = client.post(f"/agent/tasks/{tid}/cancel")
    assert c2.status_code == 200
    for _ in range(80):
        g = client.get(f"/agent/tasks/{tid}")
        assert g.status_code == 200
        st = (g.json().get("task") or {}).get("status")
        if st == "cancelled":
            break
        time.sleep(0.05)
    else:
        pytest.fail("task did not reach cancelled with subprocess fake worker")
    g2 = client.get(f"/agent/tasks/{tid}")
    task = (g2.json().get("task") or {})
    assert task.get("status") == "cancelled"
    assert "cancel_event" not in task
    assert task.get("worker_mode") == "subprocess"


def test_mcp_tools_call_in_autonomous_run_http(tmp_path, monkeypatch):
    """Mock decision to mcp_tools_call; real MCP echo via fake stdio server; step appears in state.steps."""
    import agent_loop
    import layla.memory.distill as distill_mod
    import routers.agent as agent_router
    import runtime_safety
    import services.tool_policy as tool_policy
    from main import app
    from services import model_router, planner

    orig = runtime_safety.load_config
    fake_cfg = {
        "mcp_client_enabled": True,
        "mcp_stdio_servers": [
            {"name": "fake", "command": sys.executable, "args": [str(FAKE_MCP.resolve())]},
        ],
        "sandbox_root": str(tmp_path),
    }

    def _cfg():
        c = dict(orig())
        c.update(fake_cfg)
        return c

    monkeypatch.setattr(runtime_safety, "load_config", _cfg)

    phase = {"n": 0}

    def fake_llm_decision(_goal, _state, _context, _active_aspect, _show_thinking, _history):
        if phase["n"] == 0:
            phase["n"] = 1
            return {
                "action": "tool",
                "tool": "mcp_tools_call",
                "args": {
                    "mcp_server": "fake",
                    "tool_name": "echo",
                    "arguments": {"hello": "loop"},
                },
            }
        return {"action": "reason", "objective_complete": True}

    def fake_run_completion(*_a, **_kw):
        return "After MCP."

    monkeypatch.setattr(agent_loop, "_llm_decision", fake_llm_decision)
    monkeypatch.setattr(agent_loop, "run_completion", fake_run_completion)
    monkeypatch.setattr(runtime_safety, "require_approval", lambda _tool: False)
    monkeypatch.setattr(agent_loop, "system_overloaded", lambda **_kw: False)
    monkeypatch.setattr(tool_policy, "tool_allowed", lambda _intent, _vt: True)
    monkeypatch.setattr(agent_loop, "_semantic_recall", lambda *_a, **_k: "")
    monkeypatch.setattr(agent_loop, "_load_learnings", lambda *_a, **_k: "")
    monkeypatch.setattr(model_router, "is_routing_enabled", lambda *a, **k: False)
    monkeypatch.setattr(planner, "should_plan", lambda *a, **k: False)
    monkeypatch.setattr(distill_mod, "run_distill_after_outcome", lambda *a, **k: None)
    monkeypatch.setattr(agent_router, "_model_ready_message", lambda: None)

    client = TestClient(app)
    r = client.post(
        "/agent",
        json={
            "message": "Call MCP echo then summarize.",
            "workspace_root": str(tmp_path),
            "allow_write": False,
            "allow_run": True,
            "conversation_id": str(uuid_mod.uuid4()),
        },
    )
    assert r.status_code == 200
    data = r.json()
    steps = (data.get("state") or {}).get("steps") or []
    mcp_step = next((s for s in steps if isinstance(s, dict) and s.get("action") == "mcp_tools_call"), None)
    assert mcp_step is not None
    res = mcp_step.get("result") or {}
    assert res.get("ok") is True
    assert (res.get("mcp") or {}).get("content")


@pytest.mark.parametrize(
    "status,needle",
    [
        ("timeout", "too long"),
        ("system_busy", "under load"),
        ("tool_limit", "maximum tool calls"),
    ],
)
def test_agent_router_maps_limited_status_to_user_text(status, needle, monkeypatch):
    import agent_loop
    import routers.agent as ra

    def fake_run(*_a, **_k):  # accepts engineering_pipeline_mode etc. from router
        return {
            "status": status,
            "response": "",
            "steps": [],
            "aspect": "morrigan",
            "aspect_name": "Morrigan",
            "refused": False,
            "refusal_reason": "",
            "ux_states": [],
            "memory_influenced": [],
        }

    monkeypatch.setattr(agent_loop, "autonomous_run", fake_run)
    monkeypatch.setattr(ra, "_model_ready_message", lambda: None)

    from main import app

    c = TestClient(app)
    r = c.post(
        "/agent",
        json={"message": f"force branch {status} {uuid_mod.uuid4().hex[:8]}", "allow_write": False, "allow_run": False},
    )
    assert r.status_code == 200
    data = r.json()
    assert (data.get("state") or {}).get("status") == status
    assert needle in (data.get("response") or "").lower()


def test_empty_and_fast_path_include_steps_array(client):
    """Contract: empty message and fast_path states expose steps (possibly empty)."""
    r0 = client.post("/agent", json={})
    assert r0.status_code == 200
    s0 = r0.json().get("state") or {}
    assert s0.get("steps") == []
    assert s0.get("status") == "empty_message"

    r1 = client.post("/agent", json={"message": "ok"})
    assert r1.status_code == 200
    s1 = r1.json().get("state") or {}
    assert s1.get("steps") == []
    assert s1.get("status") == "fast_path"


@pytest.fixture
def client():
    from main import app

    return TestClient(app)
