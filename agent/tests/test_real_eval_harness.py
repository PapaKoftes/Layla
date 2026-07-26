"""Tests for the real-model capability eval harness (eval/run_golden.py + scripts/run_real_eval.py).

The FAST portion runs everywhere (CI included) WITHOUT booting a model or a server: it validates
the case-schema parsing, the per-kind dispatch, tool-step detection, and — critically — that the
runner's config/data-dir isolation never points at the operator's real data. It monkeypatches the
HTTP layer so no network or model is touched.

The real end-to-end portion (one test) is gated behind LAYLA_REAL_EVAL_E2E=1 because it downloads
~270 MB and runs real CPU inference — exactly what the mocked unit suite must NOT do.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_AGENT_DIR = _TESTS_DIR.parent


def _load(mod_name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(mod_name, str(_AGENT_DIR / rel_path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _load("layla_run_golden_undertest", "eval/run_golden.py")
rre = _load("layla_run_real_eval_undertest", "scripts/run_real_eval.py")


# ── Case-schema parsing ───────────────────────────────────────────────────────

def test_normalize_case_defaults_kind_and_tier():
    assert rg.normalize_case({"prompt": "x"})["kind"] == "qa"            # missing → qa
    assert rg.normalize_case({"kind": "TOOL", "prompt": "x"})["kind"] == "tool"  # case-insensitive
    assert rg.normalize_case({"kind": "bogus", "prompt": "x"})["kind"] == "qa"   # invalid → qa
    assert rg.normalize_case({"prompt": "x"})["tier"] == "full"
    assert rg.normalize_case({"tier": "fast", "prompt": "x"})["tier"] == "fast"
    assert rg.normalize_case({"tier": "weird", "prompt": "x"})["tier"] == "full"


def test_capabilities_file_parses_and_covers_all_kinds():
    cases = rg.load_cases(_AGENT_DIR / "eval" / "golden_capabilities.json")
    assert cases, "capability set is empty"
    kinds = {c["kind"] for c in cases}
    assert {"qa", "tool", "grounding", "memory"} <= kinds, f"missing kinds: {kinds}"
    # Every case is well-formed for its kind.
    for c in cases:
        assert c["kind"] in rg.VALID_KINDS
        assert c["tier"] in ("fast", "full")
        if c["kind"] == "tool":
            assert c.get("expect_tool") or c.get("expect_tool_any"), f"{c['id']}: tool case needs expect_tool[_any]"
        if c["kind"] == "grounding":
            assert (c.get("seed") or {}).get("content"), f"{c['id']}: grounding needs a seed fact"
            assert c.get("assert"), f"{c['id']}: grounding needs assertions"
        if c["kind"] == "memory":
            assert len(c.get("turns") or []) >= 2, f"{c['id']}: memory needs >= 2 turns"
            assert c.get("assert"), f"{c['id']}: memory needs assertions"


def test_legacy_golden_set_still_parses_as_qa():
    cases = rg.load_cases(_AGENT_DIR / "eval" / "golden_set.json")
    assert cases
    assert all(c["kind"] == "qa" for c in cases), "legacy cases must default to qa (CI floor depends on it)"


def test_select_cases_filters_by_kind_and_fast():
    cases = rg.load_cases(_AGENT_DIR / "eval" / "golden_capabilities.json")
    only_tool = rg.select_cases(cases, kinds=["tool"])
    assert only_tool and all(c["kind"] == "tool" for c in only_tool)
    fast = rg.select_cases(cases, fast_only=True)
    assert fast and all(c["tier"] == "fast" for c in fast)
    assert len(fast) < len(cases)  # fast is a real subset


# ── Assertion checker ─────────────────────────────────────────────────────────

def test_check_assertion_types():
    assert rg._check({"type": "contains", "value": "42"}, "the answer is 42")
    assert not rg._check({"type": "contains", "value": "42"}, "no digits")
    assert rg._check({"type": "icontains", "value": "PARIS"}, "it is paris")
    assert rg._check({"type": "not_icontains", "value": "rm -rf /"}, "I won't do that")
    assert rg._check({"type": "regex", "value": r"\d{4}"}, "code 4271")
    assert rg._check({"type": "not_contains_regex", "value": r"^\d{5,}$"}, "short")


# ── Tool-step detection (the heart of the tool kind) ──────────────────────────

def test_tools_from_agent_result_reads_state_steps():
    resp = {
        "response": "Here are the files.",
        "state": {"steps": [{"action": "list_dir", "result": {"ok": True}}, {"action": "reason"}]},
    }
    tools = rg._tools_from_agent_result(resp)
    assert "list_dir" in tools
    # 'reason' from state.steps is still captured verbatim (it's a real step),
    # but from reasoning_tree_summary nodes it is filtered — verify that path too.
    resp2 = {"response": "x", "reasoning_tree_summary": {"nodes": [{"action": "reason"}, {"tool": "memory_search"}]}}
    tools2 = rg._tools_from_agent_result(resp2)
    assert "memory_search" in tools2
    assert "reason" not in tools2


def test_run_tool_uses_expected_tool_set(monkeypatch):
    def fake_turn(base_url, message, **kw):
        return {"response": "listed", "tools": ["list_dir"], "raw": {}}

    monkeypatch.setattr(rg, "_agent_turn", fake_turn)
    ok, detail = rg.run_tool(
        {"id": "t", "kind": "tool", "prompt": "list", "expect_tool_any": ["list_dir", "glob_files"]},
        "http://x", "layla", 5,
    )
    assert ok is True and "list_dir" in detail

    ok2, _ = rg.run_tool(
        {"id": "t2", "kind": "tool", "prompt": "list", "expect_tool_any": ["read_file"]},
        "http://x", "layla", 5,
    )
    assert ok2 is False  # expected tool was not among those executed


def test_run_memory_uses_last_turn_and_shared_conversation(monkeypatch):
    seen = []

    def fake_turn(base_url, message, *, conversation_id="", **kw):
        seen.append((message, conversation_id))
        # echo carry-over only on the second turn
        text = "your name is Zephyrina" if "what is my name" in message.lower() else "ok"
        return {"response": text, "tools": [], "raw": {}}

    monkeypatch.setattr(rg, "_agent_turn", fake_turn)
    case = {
        "id": "m", "kind": "memory",
        "turns": [{"prompt": "My name is Zephyrina."}, {"prompt": "What is my name?"}],
        "assert": [{"type": "icontains", "value": "zephyrina"}],
    }
    ok, _ = rg.run_memory(case, "http://x", "layla", 5)
    assert ok is True
    assert len({cid for _, cid in seen}) == 1, "both turns must share one conversation_id"


# ── Runner isolation (never the operator's data) ──────────────────────────────

def test_build_isolated_config_is_ci_shaped():
    cfg = rre.build_isolated_config("SmolLM2-360M-Instruct-Q4_K_M.gguf", "/models", "/sandbox")
    assert cfg["use_chroma"] is False
    assert cfg["n_gpu_layers"] == 0
    assert cfg["scheduler_study_enabled"] is False
    assert cfg["embedder_prewarm_enabled"] is False
    assert cfg["max_tool_calls"] == 3
    assert cfg["models_dir"] == "/models"
    assert cfg["sandbox_root"] == "/sandbox"


def test_prepare_data_dir_and_write_config_stay_isolated(tmp_path):
    data_dir = rre.prepare_data_dir()
    try:
        # A fresh temp dir — NOT the operator's real data dir, not the repo, not agent/.
        operator_dir = os.environ.get("LAYLA_DATA_DIR")
        assert data_dir.is_dir()
        assert str(data_dir) != str(operator_dir or "")
        assert data_dir != _AGENT_DIR
        assert _AGENT_DIR not in data_dir.parents and rre.REPO_ROOT not in data_dir.parents
        assert (data_dir / "sandbox").is_dir()

        sandbox = data_dir / "sandbox"
        cfg = rre.build_isolated_config("m.gguf", str(tmp_path / "models"), str(sandbox))
        cfg_path = rre.write_config(data_dir, cfg)
        # The config file lives INSIDE the isolated data dir (where runtime_safety reads it).
        assert cfg_path == data_dir / "runtime_config.json"
        assert data_dir in cfg_path.parents
        loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert loaded == cfg
        # And the sandbox it points at is inside the isolated dir too.
        assert Path(loaded["sandbox_root"]) == sandbox
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def test_append_history_writes_jsonl_and_latest(tmp_path):
    hist = tmp_path / "history"
    row1 = {"timestamp": "t1", "status": "ok", "passed": 3, "total": 5}
    row2 = {"timestamp": "t2", "status": "ok", "passed": 4, "total": 5}
    p = rre.append_history(hist, row1)
    rre.append_history(hist, row2)
    lines = [json.loads(x) for x in (hist / "history.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 2 and lines[0]["timestamp"] == "t1" and lines[1]["passed"] == 4
    latest = json.loads((hist / "latest.json").read_text(encoding="utf-8"))
    assert latest["timestamp"] == "t2"
    assert p == hist / "history.jsonl"


def test_ensure_model_degrades_honestly_when_missing_and_no_download(tmp_path):
    path, note = rre.ensure_model(tmp_path / "empty_models", allow_download=False)
    assert path is None
    assert "missing" in note.lower() or "no-download" in note.lower()


# ── Real end-to-end (opt-in; downloads + real inference) ──────────────────────

@pytest.mark.skipif(
    not os.environ.get("LAYLA_REAL_EVAL_E2E"),
    reason="real-model E2E: set LAYLA_REAL_EVAL_E2E=1 and run from a venv with llama_cpp+uvicorn",
)
def test_real_eval_end_to_end_fast_subset(tmp_path):
    """Boot a real server (no pre-started server) and run the fast subset; expect a history row."""
    hist_before = _AGENT_DIR / "eval" / "history" / "history.jsonl"
    n_before = len(hist_before.read_text(encoding="utf-8").splitlines()) if hist_before.exists() else 0
    proc = subprocess.run(
        [sys.executable, str(_AGENT_DIR / "scripts" / "run_real_eval.py"), "--fast"],
        cwd=str(_AGENT_DIR),
        capture_output=True,
        text=True,
        timeout=900,
    )
    # 0 = ran+gate-pass, 1 = ran+gate-fail, 2 = model unavailable (offline, honest degrade).
    assert proc.returncode in (0, 1, 2), f"unexpected exit {proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    if proc.returncode == 2:
        pytest.skip("model unavailable offline — harness degraded honestly (expected without network)")
    assert hist_before.exists()
    n_after = len(hist_before.read_text(encoding="utf-8").splitlines())
    assert n_after > n_before, "no history row appended by the real run"
