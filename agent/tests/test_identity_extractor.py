"""Phase 3b: deterministic durable-fact capture — high precision, no false positives.

Powers the "About you" memory panel + the "memory updated" receipt. Must capture explicit
self-statements and never fire on ambiguous phrasing.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_captures_explicit_facts():
    from services.memory.identity_extractor import extract_identity_facts as ex
    assert dict(ex("call me Mina")).get("name") == "Mina"
    assert dict(ex("my name is Sarah")).get("name") == "Sarah"
    assert dict(ex("my timezone is UTC+2")).get("timezone") == "UTC+2"
    assert dict(ex("btw i use neovim for everything")).get("editor") == "Neovim"
    assert dict(ex("i use VSCode")).get("editor") == "VS Code"
    assert dict(ex("my pronouns are she/her")).get("pronouns") == "she/her"
    assert dict(ex("I am on Windows now")).get("os") == "Windows"


def test_no_false_positives_on_ambiguous_phrasing():
    from services.memory.identity_extractor import extract_identity_facts as ex
    for neg in ("im tired", "i am so done with this", "i am working on it",
                "i use it daily", "call me maybe", "my name is too long to remember honestly"):
        assert not ex(neg), f"false positive on: {neg!r} -> {ex(neg)}"


def test_capture_writes_and_returns_receipt(tmp_path, monkeypatch):
    import layla.memory.db as db
    saved = {}
    monkeypatch.setattr(db, "get_all_user_identity", lambda: {})
    monkeypatch.setattr(db, "set_user_identity", lambda k, v: saved.__setitem__(k, v))
    from services.memory.identity_extractor import capture_identity_from_turn
    receipt = capture_identity_from_turn("call me Mina and i use neovim")
    assert saved.get("name") == "Mina" and saved.get("editor") == "Neovim"
    assert "what i know about you" in receipt.lower()
    # nothing new → empty receipt (idempotent, no redundant writes)
    monkeypatch.setattr(db, "get_all_user_identity", lambda: {"name": "Mina"})
    assert capture_identity_from_turn("call me Mina") == ""


def test_flag_default_on():
    import runtime_safety
    assert runtime_safety.load_config().get("identity_capture_enabled") is True
