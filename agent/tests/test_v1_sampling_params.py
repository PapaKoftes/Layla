"""BL-151: first-class /v1 params — accept + honour standard OpenAI sampling fields."""
from __future__ import annotations

from routers import openai_compat as oc


def test_extract_sampling_defaults():
    s = oc._extract_sampling({})
    assert s["temperature"] is None and s["max_tokens"] is None
    assert s["stop"] == []


def test_extract_sampling_full():
    s = oc._extract_sampling({
        "temperature": 0.0, "max_tokens": 512, "top_p": 0.9,
        "stop": ["\n\n", "###"], "seed": 7,
    })
    assert s["temperature"] == 0.0 and s["max_tokens"] == 512
    assert s["top_p"] == 0.9 and s["seed"] == 7
    assert s["stop"] == ["\n\n", "###"]


def test_extract_sampling_stop_string_coerced_to_list():
    assert oc._extract_sampling({"stop": "END"})["stop"] == ["END"]


def test_extract_sampling_stop_capped_at_four():
    s = oc._extract_sampling({"stop": ["a", "b", "c", "d", "e"]})
    assert s["stop"] == ["a", "b", "c", "d"]


def test_apply_stop_truncates_at_earliest():
    assert oc._apply_stop("hello world ### tail", ["###"]) == "hello world "
    # earliest of several wins
    assert oc._apply_stop("abcSTOP1def STOP2", ["STOP2", "STOP1"]) == "abc"


def test_apply_stop_noop_when_absent_or_empty():
    assert oc._apply_stop("plain text", ["###"]) == "plain text"
    assert oc._apply_stop("plain text", []) == "plain text"
    assert oc._apply_stop("", ["x"]) == ""


def test_v1_models_lists_aspects():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI(); app.include_router(oc.router)
    data = TestClient(app).get("/v1/models").json()["data"]
    ids = {m["id"] for m in data}
    assert "layla" in ids
    assert any(i.startswith("layla-") for i in ids)   # aspect models discoverable
