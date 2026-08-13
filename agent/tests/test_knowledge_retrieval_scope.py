"""v1.7.5: knowledge retrieval breadth + preset scoping.

Locks in the fix that lets practical domain questions reach the knowledge base (not just
"research …" queries), and that preset config resolves to the right pack set.
"""
from pathlib import Path

from layla.memory.knowledge_packs import is_doc_enabled, pack_of, resolve_enabled_packs
from services.prompts.system_head_builder import needs_knowledge_rag


def test_substantive_questions_trigger_knowledge():
    for goal in [
        "what feeds should I use for MDF?",
        "which router bit for aluminium",
        "how do I wire an I2C sensor",
        "design a drawer box",
        "help me debug this python error",
        "explain anchoring bias",
    ]:
        assert needs_knowledge_rag(goal) is True, goal


def test_phatic_turns_do_not_trigger_knowledge():
    for goal in ["hi", "hello", "thanks", "thank you", "ok", "good morning", "gn", ""]:
        assert needs_knowledge_rag(goal) is False, goal


def test_preset_resolution_default_is_all():
    assert resolve_enabled_packs({}) is None  # nothing configured -> all packs


def test_explicit_packs_win_and_core_always_on():
    enabled = resolve_enabled_packs({"knowledge_packs": ["fabrication"]})
    assert enabled == {"fabrication", "core"}


def test_named_preset_expands():
    enabled = resolve_enabled_packs({"knowledge_preset": "maker"})
    assert enabled is not None
    assert "core" in enabled and "fabrication" in enabled


def test_loose_docs_always_enabled_but_packs_scoped():
    fab = Path("knowledge/packs/fabrication/feeds-and-speeds.md")
    emb = Path("knowledge/packs/embedded/arduino-patterns.md")
    loose = Path("knowledge/operator-shop-notes.md")
    enabled = {"fabrication", "core"}
    assert is_doc_enabled(fab, enabled) is True
    assert is_doc_enabled(emb, enabled) is False      # not in enabled set
    assert is_doc_enabled(loose, enabled) is True     # loose docs never filtered out
    assert is_doc_enabled(emb, None) is True          # None = everything on
    assert pack_of(fab) == "fabrication" and pack_of(loose) is None
