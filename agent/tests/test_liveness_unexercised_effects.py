"""F2 — the liveness effects the FAST real-eval never exercised are LIVE, not dead.

The 4-case real-eval snapshot showed grounding_recall_fired + conversation_summary_recalled
at 0 fires. That is a COVERAGE artifact, not a severed path: a 4-short-turn eval never (a)
recalls a stored fact into a turn, nor (b) has a durable summary reach the prompt.
(conversation_compacted is already proven live by test_long_conversation_memory.) These drive
each fire CONDITION model-free and assert the effect fires — so if either ever reads 0 under a
real long conversation, it means a genuinely broken path, not missing coverage.
"""
from __future__ import annotations


def _liveness_count(effect: str) -> int:
    from services.observability import liveness
    return int(liveness.snapshot().get(effect, {}).get("count") or 0)


def test_grounding_recall_fired_when_a_learning_is_recalled(isolated_db):
    from services.memory.memory_router import save_learning
    from services.retrieval import retrieve_relevant_memory

    # A distinctive fact so keyword (FTS/BM25) recall is deterministic even with no embedder.
    save_learning("The zephyr deploy runbook lives at ops/deploy/RUNBOOK-zephyr.md", kind="fact", source="f2")
    before = _liveness_count("grounding_recall_fired")

    hits = retrieve_relevant_memory("where is the zephyr deploy runbook", k=5)
    assert hits, "the seeded learning must be recalled (keyword match)"
    assert _liveness_count("grounding_recall_fired") == before + 1, (
        "grounding_recall_fired must fire when a stored learning is recalled into a turn"
    )


def test_conversation_summary_recalled_when_a_summary_reaches_the_prompt(isolated_db, monkeypatch):
    import runtime_safety
    from layla.memory.conversations import add_conversation_summary
    from services.prompts import system_head_builder as shb

    add_conversation_summary("[Earlier conversation summary]\n- earlier we designed the payment retry flow")
    before = _liveness_count("conversation_summary_recalled")

    # n_ctx > 4096 => not a "small model" (expensive head sections run); reasoning_mode not in
    # {none,light} => not a lightweight chat turn => the summary-recall section is reached.
    cfg = {**runtime_safety.load_config(), "n_ctx": 8192, "use_chroma": False}
    monkeypatch.setattr(runtime_safety, "load_config", lambda: cfg)

    head = shb.build_system_head(
        goal="explain in detail how the payment retry flow was designed",
        reasoning_mode="deep",
    )
    assert isinstance(head, str) and head
    assert _liveness_count("conversation_summary_recalled") == before + 1, (
        "conversation_summary_recalled must fire when a durable summary reaches the prompt"
    )
