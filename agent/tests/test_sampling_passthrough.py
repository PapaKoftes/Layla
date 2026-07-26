"""Plan #18: honour request sampling (temperature / top_p / top_k / max_tokens / seed) on the
FINAL user-visible generation only, in /v1 and the Ollama surface.

Covers three things:
  (a) `_extract_sampling` CLAMPS to safe ranges and drops garbage.
  (b) an override reaches the FINAL generation call and NOT the tool-DECISION call.
  (c) requests WITHOUT sampling behave exactly as before (no override).

The model is mocked throughout — these assert the PARAM plumbing, not model output.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from routers import openai_compat as oc


# ---------------------------------------------------------------------------
# (a) _extract_sampling clamps + drops garbage
# ---------------------------------------------------------------------------
def test_extract_sampling_clamps_temperature():
    assert oc._extract_sampling({"temperature": 50})["temperature"] == 2.0    # high → 2
    assert oc._extract_sampling({"temperature": -5})["temperature"] == 0.0    # low  → 0
    assert oc._extract_sampling({"temperature": 0})["temperature"] == 0.0     # 0 (determinism) survives


def test_extract_sampling_clamps_top_p():
    assert oc._extract_sampling({"top_p": -1})["top_p"] == 0.0
    assert oc._extract_sampling({"top_p": 5})["top_p"] == 1.0
    assert oc._extract_sampling({"top_p": 0.9})["top_p"] == 0.9


def test_extract_sampling_clamps_top_k_nonnegative():
    assert oc._extract_sampling({"top_k": -3})["top_k"] == 0
    assert oc._extract_sampling({"top_k": 40})["top_k"] == 40


def test_extract_sampling_caps_max_tokens():
    assert oc._extract_sampling({"max_tokens": 10_000_000})["max_tokens"] == oc._MAX_SAMPLING_TOKENS
    assert oc._extract_sampling({"max_tokens": 0})["max_tokens"] == 1   # floor at 1
    assert oc._extract_sampling({"max_tokens": 512})["max_tokens"] == 512


def test_extract_sampling_drops_garbage():
    s = oc._extract_sampling({
        "temperature": "hot",       # non-numeric
        "top_p": [],                # wrong type
        "max_tokens": True,         # bool is not a token count
        "top_k": "lots",            # non-numeric
        "seed": "x",                # non-int seed dropped
    })
    assert s["temperature"] is None
    assert s["top_p"] is None
    assert s["max_tokens"] is None
    assert s["top_k"] is None
    assert s["seed"] is None


def test_extract_sampling_ignores_unknown_keys_and_passes_valid_seed():
    s = oc._extract_sampling({"frequency_penalty": 1, "banana": 2, "seed": 7})
    assert s["seed"] == 7
    assert s["temperature"] is None and s["max_tokens"] is None   # nothing invented from junk


# ---------------------------------------------------------------------------
# (b) override reaches the FINAL streaming generation
# ---------------------------------------------------------------------------
def _record_stream_call(monkeypatch, goal, **stream_kwargs) -> dict:
    """Drive stream_reason with the gateway completion mocked; return the params it SAW."""
    import services.agent.stream_handler as sh
    import services.llm.llm_gateway as gw
    seen: dict = {}

    def _fake(prompt, **kw):
        seen["temperature"] = kw.get("temperature")
        seen["max_tokens"] = kw.get("max_tokens")
        yield "ok."

    monkeypatch.setattr(gw, "run_completion", _fake)
    list(sh.stream_reason(goal, reasoning_mode_override="light", aspect_id="morrigan", **stream_kwargs))
    return seen


def test_sampling_reaches_final_stream_generation(monkeypatch):
    seen = _record_stream_call(
        monkeypatch, "who are you?",
        sampling={"temperature": 0.0, "max_tokens": 32},
    )
    assert seen["temperature"] == 0.0    # temperature=0 (determinism) reaches the FINAL stream
    assert seen["max_tokens"] == 32


def test_stream_without_sampling_uses_config_default(monkeypatch):
    import runtime_safety
    default_t = float(runtime_safety.load_config().get("temperature", 0.2))
    seen = _record_stream_call(monkeypatch, "who are you?")   # no sampling
    assert seen["temperature"] == default_t                  # unchanged from server default
    assert seen["max_tokens"] is not None and seen["max_tokens"] > 80   # full substantive budget


# ---------------------------------------------------------------------------
# (b') FINAL-generation seam applies the override; the DECISION seam (gateway-direct) does NOT
# ---------------------------------------------------------------------------
def test_final_seam_applies_override_but_gateway_direct_does_not(monkeypatch):
    import agent_loop
    from services.llm import llm_gateway

    # Structural proof: the agent-loop FINAL-gen seam is a DIFFERENT callable than the gateway's
    # run_completion — the one services.agent.llm_decision imports directly — so a tool-decision
    # call can never be routed through the sampling override.
    assert agent_loop.run_completion is not llm_gateway.run_completion

    seen: list[dict] = []

    def _spy(prompt, max_tokens=256, temperature=0.2, stream=False, stop=None, **kw):
        seen.append({"temperature": temperature, "max_tokens": max_tokens})
        return {"choices": [{"message": {"content": "x"}}]}

    # The wrapper delegates to agent_loop._gateway_run_completion; a decision call hits
    # llm_gateway.run_completion. Point both at one spy so we can read what each call SAW.
    monkeypatch.setattr(agent_loop, "_gateway_run_completion", _spy)
    monkeypatch.setattr(llm_gateway, "run_completion", _spy)

    tok = agent_loop._final_sampling_var.set({"temperature": 0.0, "max_tokens": 16})
    try:
        # FINAL generation (reasoning_handler + the parse_failed fallback route through this seam)
        agent_loop.run_completion("p", max_tokens=256, temperature=0.7, stream=False)
        assert seen[-1] == {"temperature": 0.0, "max_tokens": 16}   # override applied

        # DECISION call (llm_decision imports run_completion from the gateway directly) — the
        # override MUST NOT touch it, or tool-decision JSON stops being deterministic.
        llm_gateway.run_completion("p", max_tokens=200, temperature=0.1, stream=False)
        assert seen[-1] == {"temperature": 0.1, "max_tokens": 200}  # untouched
    finally:
        agent_loop._final_sampling_var.reset(tok)


def test_final_seam_passthrough_when_no_override(monkeypatch):
    import agent_loop
    seen: list[dict] = []

    def _spy(prompt, max_tokens=256, temperature=0.2, stream=False, stop=None, **kw):
        seen.append({"temperature": temperature, "max_tokens": max_tokens})
        return {"choices": [{"message": {"content": "x"}}]}

    monkeypatch.setattr(agent_loop, "_gateway_run_completion", _spy)
    # No contextvar set → the caller's own args pass through verbatim.
    agent_loop.run_completion("p", max_tokens=256, temperature=0.7, stream=False)
    assert seen[-1] == {"temperature": 0.7, "max_tokens": 256}


# ---------------------------------------------------------------------------
# (c) /v1 threads the clamped override into autonomous_run; absence stays absence
# ---------------------------------------------------------------------------
def _v1_client(monkeypatch, capture: dict):
    monkeypatch.setattr(oc, "_quick_reply_for_trivial_turn", lambda goal: None)  # force autonomous_run
    monkeypatch.setattr(oc, "get_append_history", lambda: (lambda role, content: None))

    def _fake_run(goal, **kw):
        capture["sampling"] = kw.get("sampling")
        return {"response": "ok", "aspect": "morrigan", "aspect_name": "Morrigan",
                "status": "finished", "steps": []}

    monkeypatch.setattr(oc, "autonomous_run", _fake_run)
    app = FastAPI()
    app.include_router(oc.router)
    return TestClient(app)


def test_v1_passes_clamped_sampling_to_autonomous_run(monkeypatch):
    cap: dict = {}
    client = _v1_client(monkeypatch, cap)
    r = client.post("/v1/chat/completions", json={
        "model": "layla", "stream": False, "temperature": 0, "max_tokens": 99,
        "messages": [{"role": "user", "content": "do a real thing"}],
    })
    assert r.status_code == 200
    assert cap["sampling"]["temperature"] == 0.0    # temperature=0 reaches the FINAL answer path
    assert cap["sampling"]["max_tokens"] == 99


def test_v1_without_sampling_leaves_override_absent(monkeypatch):
    cap: dict = {}
    client = _v1_client(monkeypatch, cap)
    r = client.post("/v1/chat/completions", json={
        "model": "layla", "stream": False,
        "messages": [{"role": "user", "content": "do a real thing"}],
    })
    assert r.status_code == 200
    # Every sampling field absent → no override (behaves exactly as before).
    assert cap["sampling"]["temperature"] is None
    assert cap["sampling"]["max_tokens"] is None


# ---------------------------------------------------------------------------
# (c') Ollama nests sampling under `options`; it must map onto the v1 body
# ---------------------------------------------------------------------------
def _ollama_client(monkeypatch, capture: dict):
    from routers import ollama_compat as olc

    async def _fake_v1(oai, request):
        capture["oai"] = oai
        return JSONResponse({
            "object": "chat.completion", "model": "layla-morrigan",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        })

    monkeypatch.setattr("routers.openai_compat.v1_chat_completions", _fake_v1)
    app = FastAPI()
    app.include_router(olc.router)
    return TestClient(app)


def test_ollama_options_map_to_v1_sampling(monkeypatch):
    cap: dict = {}
    client = _ollama_client(monkeypatch, cap)
    r = client.post("/api/chat", json={
        "model": "layla",
        "messages": [{"role": "user", "content": "hi"}],
        "options": {"temperature": 0, "top_p": 0.5, "top_k": 10, "seed": 3, "num_predict": 64, "stop": ["X"]},
    })
    assert r.status_code == 200
    oai = cap["oai"]
    assert oai["temperature"] == 0
    assert oai["max_tokens"] == 64          # Ollama num_predict → OpenAI max_tokens
    assert oai["top_p"] == 0.5 and oai["top_k"] == 10 and oai["seed"] == 3
    assert oai["stop"] == ["X"]


def test_ollama_without_options_adds_no_sampling_keys(monkeypatch):
    cap: dict = {}
    client = _ollama_client(monkeypatch, cap)
    r = client.post("/api/chat", json={"model": "layla", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    for k in ("temperature", "max_tokens", "top_p", "top_k", "seed"):
        assert k not in cap["oai"]          # absence preserved → no override
