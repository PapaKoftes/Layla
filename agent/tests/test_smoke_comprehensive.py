# -*- coding: utf-8 -*-
"""
test_smoke_comprehensive.py -- Dynamic startup, endpoint, and regression smoke tests.

Catches the class of bug "it loads, it doesn't crash, the endpoint responds"
before a single message is sent. All tests use FastAPI TestClient (no real
LLM required). Hardware probe is dynamic so tests adapt to any machine.

Run:
    cd agent/ && python -m pytest tests/test_smoke_comprehensive.py -v

Exit 0 = clean. Exit 1 = something exploded before production sees it.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Critical imports
# ---------------------------------------------------------------------------

def test_import_main():
    from main import app
    assert app is not None


def test_import_agent_loop():
    from agent_loop import autonomous_run, stream_reason, strip_junk_from_reply
    assert all(callable(f) for f in [autonomous_run, stream_reason, strip_junk_from_reply])


def test_import_context_manager():
    from services.context_manager import DEFAULT_BUDGETS, build_system_prompt
    assert callable(build_system_prompt)
    assert "system_instructions" in DEFAULT_BUDGETS


def test_import_hardware_detect():
    from services.hardware_detect import (
        apply_to_config,
        detect_hardware,
        get_capability_summary,
        get_recommended_settings,
    )
    assert all(callable(f) for f in [
        detect_hardware, get_recommended_settings,
        get_capability_summary, apply_to_config,
    ])


def test_import_llm_gateway():
    from services.llm_gateway import get_stop_sequences, run_completion
    assert callable(run_completion) and callable(get_stop_sequences)


def test_import_runtime_safety():
    import runtime_safety
    assert isinstance(runtime_safety.load_config(), dict)


def test_import_memory_db():
    from layla.memory.db import add_conversation_summary
    assert callable(add_conversation_summary)


# ---------------------------------------------------------------------------
# 2. Hardware probe -- dynamic, adapts to any machine
# ---------------------------------------------------------------------------

def test_hardware_probe_returns_dict():
    from services.hardware_detect import detect_hardware
    hw = detect_hardware()
    assert isinstance(hw, dict)
    assert "machine_tier" in hw


def test_hardware_recommended_settings_complete():
    from services.hardware_detect import get_recommended_settings
    recs = get_recommended_settings()
    required = {
        "n_ctx", "n_batch", "n_threads", "n_gpu_layers",
        "speculative_decoding_enabled", "context_auto_compact_ratio",
    }
    missing = required - set(recs.keys())
    assert not missing, f"get_recommended_settings() missing keys: {missing}"


def test_hardware_n_ctx_sane():
    from services.hardware_detect import get_recommended_settings
    n_ctx = get_recommended_settings()["n_ctx"]
    assert 512 <= n_ctx <= 131072, f"n_ctx={n_ctx} out of range"
    assert n_ctx % 512 == 0, f"n_ctx={n_ctx} must be multiple of 512"


def test_hardware_speculative_decoding_always_false():
    from services.hardware_detect import get_recommended_settings
    assert get_recommended_settings().get("speculative_decoding_enabled") is False, (
        "speculative_decoding_enabled must always be False -- "
        "llama-cpp <=0.3.16 scores shape crash on prompts > n_batch tokens"
    )


def test_hardware_capability_summary_nonempty():
    from services.hardware_detect import get_capability_summary
    s = get_capability_summary()
    assert isinstance(s, str) and len(s) > 20
    assert "tier" in s.lower() or "hardware" in s.lower()


def test_hardware_apply_fills_gaps():
    from services.hardware_detect import apply_to_config
    merged = apply_to_config({})
    assert "n_ctx" in merged and merged["n_ctx"] >= 512


def test_hardware_apply_respects_explicit():
    from services.hardware_detect import apply_to_config
    merged = apply_to_config({"n_ctx": 99999, "n_batch": 7})
    assert merged["n_ctx"] == 99999 and merged["n_batch"] == 7


def test_hardware_tier_valid():
    from services.hardware_detect import detect_hardware, hardware_class
    cls = hardware_class(detect_hardware())
    assert cls in ("potato", "mid", "strong", "workstation"), f"Bad tier: {cls!r}"


def test_hardware_threads_reasonable():
    from services.hardware_detect import get_recommended_settings
    recs = get_recommended_settings()
    assert 1 <= recs["n_threads"] <= 256
    assert 1 <= recs["n_threads_batch"] <= 512


# ---------------------------------------------------------------------------
# 3. Stop sequences -- echo and multi-speaker regression
# ---------------------------------------------------------------------------

def test_stop_sequences_cover_section_headers():
    # Read the source directly -- most reliable, avoids module cache issues
    src = (AGENT_DIR / "services" / "llm_gateway.py").read_text(encoding="utf-8", errors="replace")
    assert "## CONTEXT" in src and "endoftext" in src, (
        "llm_gateway.py stop sequences missing ## CONTEXT -- small models echo section headers"
    )
def test_stop_sequences_cover_endoftext():
    src = (AGENT_DIR / "services" / "llm_gateway.py").read_text(encoding="utf-8", errors="replace")
    assert "endoftext" in src, "Missing <|endoftext|> in stop sequences"
def test_stop_sequences_cover_aspect_names():
    src = (AGENT_DIR / "services" / "llm_gateway.py").read_text(encoding="utf-8", errors="replace")
    for name in ("Morrigan", "Nyx", "Echo", "Eris", "Cassandra", "Lilith"):
        assert name in src, f"Missing aspect stop sequence: {name}"
def test_stop_sequences_no_config_override():
    import json as _json
    cfg_path = AGENT_DIR / "runtime_config.json"
    if not cfg_path.exists():
        pytest.skip("runtime_config.json not found")
    cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
    overrides = cfg.get("stop_sequences")
    assert not overrides, (
        f"stop_sequences config override active ({overrides!r}) -- "
        "bypasses full echo-prevention list"
    )


# ---------------------------------------------------------------------------
# 4. Context budget enforcement
# ---------------------------------------------------------------------------

def test_prompt_no_overflow_2048():
    from services.context_manager import build_system_prompt
    sections = {
        "system_instructions": "You are Layla. " * 50,
        "memory": "fact " * 200,
        "knowledge_graph": "node " * 200,
        "knowledge": "doc " * 200,
        "agent_state": "step " * 200,
        "current_goal": "Do something.",
        "conversation": "User: hi\nAssistant: hello\n" * 10,
    }
    _, metrics = build_system_prompt(sections, n_ctx=2048)
    assert metrics["total_tokens"] <= 2048, (
        f"Prompt {metrics['total_tokens']} tokens > n_ctx=2048"
    )


def test_prompt_no_overflow_4096():
    from services.context_manager import build_system_prompt
    sections = {
        "system_instructions": "You are Layla. " * 50,
        "current_goal": "Write a function.",
        "memory": "User likes directness. " * 20,
        "conversation": "User: hello\nAssistant: hi\n" * 10,
        "current_task": "Fix the bug.",
        "agent_state": "Thinking...",
        "knowledge_graph": "fact: Python uses indent",
        "knowledge": "Reference: PEP8 " * 10,
    }
    _, metrics = build_system_prompt(sections, n_ctx=4096)
    assert metrics["total_tokens"] <= 4096


def test_strip_junk_cleans_headers():
    from agent_loop import strip_junk_from_reply
    for h in ("## CONTEXT\nstuff", "## TASK\ndo this", "## SCRATCHPAD\nnotes"):
        r = strip_junk_from_reply(h)
        assert "## CONTEXT" not in r and "## TASK" not in r and "## SCRATCHPAD" not in r


def test_strip_junk_cleans_aspect_prefixes():
    from agent_loop import strip_junk_from_reply
    for text in ("Morrigan: hello", "Echo: hi there", "Nyx: analysing"):
        r = strip_junk_from_reply(text)
        assert not any(
            r.strip().startswith(n + ":") for n in
            ("Morrigan", "Echo", "Nyx", "Eris", "Cassandra", "Lilith")
        ), f"Aspect prefix leaked: {r!r}"


def test_strip_junk_cleans_completion_gate():
    from agent_loop import strip_junk_from_reply
    r = strip_junk_from_reply("[System: Your last response was incomplete] Try again.")
    assert "[System:" not in r


def test_strip_junk_cleans_earned_title():
    from agent_loop import strip_junk_from_reply
    r = strip_junk_from_reply("[EARNED_TITLE: Debugger] Here is my answer.")
    assert "[EARNED_TITLE" not in r


def test_strip_junk_preserves_clean_response():
    from agent_loop import strip_junk_from_reply
    clean = "Here is the refactored function:\n\n```python\ndef foo(): pass\n```"
    assert strip_junk_from_reply(clean) == clean


# ---------------------------------------------------------------------------
# 5. HTTP endpoints
# ---------------------------------------------------------------------------

def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_agent_endpoint_exists(client):
    r = client.post("/agent", json={})
    assert r.status_code != 404, "/agent endpoint missing"


def test_chat_endpoint_exists(client):
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "model": "layla"})
    assert r.status_code != 404, "/v1/chat/completions endpoint missing"


def test_config_endpoint_readable(client):
    r = client.get("/settings")
    assert r.status_code in (200, 401, 403, 422), f"/settings returned {r.status_code}"


# ---------------------------------------------------------------------------
# 6. DB schema
# ---------------------------------------------------------------------------

def test_db_tables_exist():
    db_candidates = [
        AGENT_DIR.parent / "layla.db",
        AGENT_DIR / "layla.db",
    ]
    db_path = next((p for p in db_candidates if p.exists()), None)
    if db_path is None:
        pytest.skip("layla.db not found")
    con = sqlite3.connect(str(db_path))
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    con.close()
    missing = {"learnings", "timeline_events", "relationship_memory"} - tables
    assert not missing, f"layla.db missing tables: {missing}"


# ---------------------------------------------------------------------------
# 7. Scanners must pass
# ---------------------------------------------------------------------------

def test_pattern_scanner_clean():
    result = subprocess.run(
        [sys.executable, str(AGENT_DIR / "scripts" / "check_patterns.py")],
        capture_output=True, text=True, timeout=60,
        cwd=str(AGENT_DIR),
    )
    assert result.returncode == 0, (
        f"check_patterns.py issues:\n{result.stdout}\n{result.stderr}"
    )


def test_config_checker_clean():
    result = subprocess.run(
        [sys.executable, str(AGENT_DIR / "scripts" / "check_config.py")],
        capture_output=True, text=True, timeout=10,
        cwd=str(AGENT_DIR),
    )
    if result.returncode == 2:
        pytest.skip("runtime_config.json not found")
    assert result.returncode == 0, (
        f"check_config.py issues:\n{result.stdout}\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 8. Regression tests -- one named test per previously fixed bug
# ---------------------------------------------------------------------------

def test_reg001_no_reset_kwarg():
    """REG-001: create_completion must not receive reset=True."""
    path = AGENT_DIR / "services" / "inference_router.py"
    if not path.exists():
        pytest.skip("inference_router.py not found")
    src = path.read_text(encoding="utf-8", errors="replace")
    assert not re.search(r"create_completion\s*\([^)]*reset\s*=\s*True", src), (
        "reset=True kwarg found -- invalid in llama-cpp 0.3.x, causes silent empty responses"
    )


def test_reg002_fts5_escaped():
    """REG-002: FTS5 queries must be quote-escaped."""
    for fname in ("routers/search.py", "layla/memory/learnings.py"):
        path = AGENT_DIR / fname
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        if "MATCH ?" in src:
            assert "_fts_q" in src or "replace" in src, (
                f"{fname}: FTS5 MATCH found but no escape pattern"
            )


def test_reg003_speculative_decoding_off():
    """REG-003: speculative_decoding_enabled=false in config."""
    import runtime_safety
    assert not runtime_safety.load_config().get("speculative_decoding_enabled", False)


def test_reg004_completion_gate_off():
    """REG-004: completion_gate_enabled=false in config."""
    # Read config directly to bypass module cache
    import json
    cfg_path = AGENT_DIR / "runtime_config.json"
    if not cfg_path.exists():
        pytest.skip("runtime_config.json not found")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert not cfg.get("completion_gate_enabled", False), (
        "completion_gate_enabled=True -- retry text leaks to user responses"
    )


def test_reg005_hardware_probe_in_gateway():
    """REG-005: llm_gateway calls apply_to_config for dynamic hardware settings."""
    src = (AGENT_DIR / "services" / "llm_gateway.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "apply_to_config" in src or "hardware_detect" in src


def test_reg006_capability_summary_in_agent_loop():
    """REG-006: agent_loop injects hardware capability summary into system prompt."""
    src = (AGENT_DIR / "agent_loop.py").read_text(encoding="utf-8", errors="replace")
    assert "get_capability_summary" in src


def test_reg007_no_duplicate_config_keys():
    """REG-007: runtime_config.json must have no duplicate JSON keys."""
    path = AGENT_DIR / "runtime_config.json"
    if not path.exists():
        pytest.skip("runtime_config.json not found")
    raw = path.read_text(encoding="utf-8", errors="replace")
    # Only check top-level keys (nested objects like knowledge_sources can repeat url/slug)
    top_level_pattern = re.compile(r'^  "(\w+)"\s*:', re.MULTILINE)
    keys = top_level_pattern.findall(raw)
    seen: set = set()
    dupes = [k for k in keys if k in seen or seen.add(k)]  # type: ignore[func-returns-value]
    assert not dupes, f"Duplicate top-level config keys: {dupes}"

