"""Tests for audit/log payload redaction (REQ-42/43).

`services.secret_filter.redact_payload` masks secrets/PII and caps oversized
content; `runtime_safety.log_execution` applies it at the single chokepoint that
every tool_dispatch call funnels through (so e.g. mcp_tools_call's arbitrary args
can't leak into .governance/execution_log.json). Pure-stdlib; runs anywhere.
"""
import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.secret_filter import REDACTED, redact_payload  # noqa: E402

# --- key-based redaction --------------------------------------------------

def test_top_level_secret_keys_redacted():
    out = redact_payload({"api_key": "sk-123", "bot_token": "xoxb-9", "path": "x.py"})
    assert out["api_key"] == REDACTED
    assert out["bot_token"] == REDACTED
    assert out["path"] == "x.py"  # diagnostic key preserved


def test_nested_secret_keys_redacted():
    payload = {"args": {"headers": {"authorization": "Bearer abc", "cookie": "sid=1"},
                        "password": "hunter2", "limit": 10}}
    out = redact_payload(payload)
    assert out["args"]["headers"]["authorization"] == REDACTED
    assert out["args"]["headers"]["cookie"] == REDACTED
    assert out["args"]["password"] == REDACTED
    assert out["args"]["limit"] == 10


def test_email_pii_redacted_but_count_preserved():
    out = redact_payload({"email": "a@b.com", "user_email": "c@d.com", "email_count": 3})
    assert out["email"] == REDACTED
    assert out["user_email"] == REDACTED
    assert out["email_count"] == 3  # not a PII value


def test_diagnostic_keys_not_redacted():
    # Conservative: must not eat *_max_tokens / n_ctx / token_ttl (see secret_filter).
    out = redact_payload({"completion_max_tokens": 256, "n_ctx": 2048,
                          "tunnel_token_ttl_hours": 12})
    assert out["completion_max_tokens"] == 256
    assert out["n_ctx"] == 2048
    assert out["tunnel_token_ttl_hours"] == 12


def test_empty_secret_value_left_alone():
    # Don't replace a blank with the marker (nothing to hide).
    out = redact_payload({"api_key": "", "password": None})
    assert out["api_key"] == ""
    assert out["password"] is None


# --- size capping ---------------------------------------------------------

def test_oversized_string_truncated():
    big = "x" * 5000
    out = redact_payload({"content": big})
    assert out["content"].endswith("***truncated***")
    assert len(out["content"]) < 5000


def test_long_list_capped():
    out = redact_payload({"items": list(range(500))})
    assert len(out["items"]) <= 101
    assert "truncated" in str(out["items"][-1])


def test_list_of_dicts_each_redacted():
    out = redact_payload([{"api_key": "a"}, {"api_key": "b", "ok": 1}])
    assert out[0]["api_key"] == REDACTED
    assert out[1]["api_key"] == REDACTED
    assert out[1]["ok"] == 1


def test_deeply_nested_depth_capped():
    # Build a 20-deep nest; must not recurse forever / must collapse.
    node = inner = {}
    for _ in range(20):
        nxt = {}
        node["n"] = nxt
        node = nxt
    out = redact_payload(inner)
    assert out is not None  # returned without error


def test_input_not_mutated():
    payload = {"api_key": "secret", "nested": {"password": "p"}}
    redact_payload(payload)
    assert payload["api_key"] == "secret"
    assert payload["nested"]["password"] == "p"


# --- chokepoint integration ----------------------------------------------

def test_log_execution_writes_redacted(tmp_path, monkeypatch):
    import runtime_safety as rs

    gov = tmp_path / ".governance"
    monkeypatch.setattr(rs, "GOV_PATH", gov)
    monkeypatch.setattr(rs, "EXEC_LOG_FILE", gov / "execution_log.json")

    rs.log_execution("mcp_tools_call", {"name": "x", "args": {"api_key": "sk-LEAK",
                                                              "q": "hello"}})
    data = json.loads((gov / "execution_log.json").read_text(encoding="utf-8"))
    entry = data[-1]
    assert entry["tool"] == "mcp_tools_call"
    assert entry["payload"]["args"]["api_key"] == REDACTED
    assert entry["payload"]["args"]["q"] == "hello"
    # the raw secret must not appear anywhere in the persisted file
    assert "sk-LEAK" not in (gov / "execution_log.json").read_text(encoding="utf-8")
