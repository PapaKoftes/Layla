"""BL-338 + BL-376: a real streamed turn must teach, and it must teach the RIGHT thing.

These are DB-observation tests, not source-greps. Each one drives the actual HTTP surface (or
the actual extractor) and then reads `learnings` out of an isolated SQLite file. A test that
greps for a call site cannot fail when the wiring breaks — only when the source string moves —
and four of the worst vacuous tests in this repo were written that way.

Each test proves ONE thing and fails for its OWN distinct reason. None certifies another's path.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ── the operator's REAL junk corpus ─────────────────────────────────────────────────────
# Verbatim from the operator's learnings table (ids 26..101). 28/28 rows pass every gate in
# the store — filter_learning, is_memory_junk, passes_learning_quality_gate. This is a
# golden-file regression corpus of known-bad OUTPUTS, not a hand-maintained list of call
# sites: the failure mode that sank an earlier attempt was a curated list of places to check
# that missed the very instance it was built to catch. A corpus of outputs cannot miss an
# instance, because the guard is the SOURCE (test D), not corpus membership.
REAL_JUNK_CORPUS = [
    "Paris serves as the political, cultural, and economic center of France.",
    "n (int): The position in the Fibonacci sequence to return. Must be a non-negative integer.",
    '[1] "Python Sets". Real Python. Retrieved 2023-04-15.',
    "bool: True if n is prime, False otherwise.",
    "Aim for clear variable names and concise logic.",
    "ValueError: Ensure inputs are non-negative integers.",
    "The capital of France is Paris, located in the north-central part of the country.",
    "Tokyo is the capital and most populous city of Japan.",
    'raise ValueError("n must be a non-negative integer.")',
    "Sets in Python are unordered collections of unique elements.",
]


def _join_learn_threads(timeout: float = 5.0) -> None:
    """Join the daemon threads commit_turn/_auto_extract_learnings spawn.

    The extraction runs off-thread so it never adds latency to the reply; without joining,
    reading the DB is a race and the test would pass or fail on timing.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = [t for t in threading.enumerate() if t.name in ("auto-learn", "conv-entity", "title-synth")]
        if not alive:
            return
        for t in alive:
            t.join(timeout=max(0.05, deadline - time.time()))


def _learning_rows() -> list[dict]:
    from layla.memory.db import get_recent_learnings

    return list(get_recent_learnings(n=50) or [])


@pytest.fixture
def hermetic_cfg(monkeypatch):
    """Deterministic detectors only — no model is loaded in a unit test.

    Turning the LLM path OFF does not weaken these tests: the deterministic detectors are the
    PRIMARY path (that is the point of finding 2.1), and tests E/F drive the LLM path directly.
    """
    import runtime_safety

    base = dict(runtime_safety.load_config() or {})
    base.update(
        {
            "operator_memory_llm_enabled": False,
            "conversation_title_synthesis_enabled": False,
            "identity_capture_enabled": False,
            "emotional_presence_enabled": False,
        }
    )
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: base)
    return base


def _reset_fingerprints():
    import collections

    import services.infrastructure.outcome_writer as ow

    ow._recent_learning_fingerprints = collections.OrderedDict()


def _client(monkeypatch, reply: str, *, refused: bool = False):
    """A /agent app with the LLM boundary stubbed and NOTHING else stubbed.

    commit_turn and _auto_extract_learnings are deliberately real — they are what is under test.
    """
    from routers import agent as ag

    def _sr(*a, **k):
        for chunk in reply.split(" "):
            yield chunk + " "

    monkeypatch.setattr(ag, "get_touch_activity", lambda: (lambda: None), raising=False)
    monkeypatch.setattr(ag, "get_append_history", lambda: (lambda *a, **k: None), raising=False)
    monkeypatch.setattr(ag, "get_conv_history", lambda cid: [], raising=False)
    monkeypatch.setattr(ag, "stream_reason", _sr, raising=False)
    monkeypatch.setattr("services.safety.auth.is_direct_local", lambda h, host: True)
    # The test config has no model_filename; this gate 503s before any reply path runs. It is
    # not what these tests are about — the LLM boundary itself is stubbed via stream_reason.
    monkeypatch.setattr(ag, "_model_ready_message", lambda: None, raising=False)

    app = FastAPI()
    app.include_router(ag.router)
    return TestClient(app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST A — the liveness guard. A REAL streamed turn, driven over HTTP, must teach.
# Fails if: reasoning_handler's stream_pending early-return once again means no learning runs
# (i.e. if commit_turn is unwired from the streamed done-frame).
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_streamed_turn_writes_operator_learning_to_db(monkeypatch, isolated_db, hermetic_cfg):
    _reset_fingerprints()
    assert _learning_rows() == [], "fixture must start empty"

    tc = _client(monkeypatch, "Noted — tea it is from now on.")
    r = tc.post(
        "/agent",
        json={
            "message": "I prefer tea over coffee, always",
            "stream": True,
            "conversation_id": "conv-stream-A",
        },
    )
    assert r.status_code == 200, r.text
    _join_learn_threads()

    rows = _learning_rows()
    contents = [str(x.get("content") or "") for x in rows]
    assert any("Operator preference" in c and "tea" in c for c in contents), (
        "a STREAMED turn must write a learning ABOUT THE USER. Got rows: " + repr(contents)
    )
    hit = next(x for x in rows if "Operator preference" in str(x.get("content") or ""))
    assert hit.get("learning_type") == "preference", hit


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST B — the safety guard. Independent of A: A passes with the gate deleted; B does not.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_refused_turn_writes_no_learning(monkeypatch, isolated_db, hermetic_cfg):
    from services.agent.turn_commit import commit_turn

    _reset_fingerprints()
    assert _learning_rows() == []

    # `refused=True` is the signal the real done-frames pass (`refused=bool(result.get("refused"))`
    # at routers/agent.py and routers/openai_compat.py) — not a status string. Exercise the
    # reachable one: a test that drives a signal no call site sends proves nothing.
    commit_turn(
        "conv-refused",
        "I prefer tea over coffee, always",
        "I won't help with that.",
        aspect_id="morrigan",
        refused=True,
    )
    _join_learn_threads()

    assert _learning_rows() == [], "a refused turn must not teach — the request was refused"


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST B2 — the other reachable safety branch. Distinct from B: B passes with "blocked"
# removed from _NO_LEARN_STATUSES; B2 passes with the `refused` check removed. Each fails
# for its own reason.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_blocked_turn_writes_no_learning(isolated_db, hermetic_cfg):
    from services.agent.turn_commit import commit_turn

    _reset_fingerprints()
    assert _learning_rows() == []

    commit_turn(
        "conv-blocked",
        "I prefer tea over coffee, always",
        "[content removed]",
        aspect_id="morrigan",
        status="blocked",
    )
    _join_learn_threads()

    assert _learning_rows() == [], "a content-guard-blocked turn must not teach"


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST C — the double-fire guard. Asserts the OBSERVABLE message count, not the call sites.
# Fails at 4 if any done-frame kept its inline persist alongside commit_turn.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_streamed_turn_persists_exactly_once(monkeypatch, isolated_db, hermetic_cfg):
    from layla.memory.db import get_conversation

    _reset_fingerprints()
    tc = _client(monkeypatch, "Noted — tea it is from now on.")
    r = tc.post(
        "/agent",
        json={"message": "I prefer tea over coffee, always", "stream": True, "conversation_id": "conv-once"},
    )
    assert r.status_code == 200
    _join_learn_threads()

    conv = get_conversation("conv-once") or {}
    assert int(conv.get("message_count") or 0) == 2, (
        f"exactly one user + one assistant message per turn; got {conv.get('message_count')} "
        "(4 means a call site kept its inline persist — append_conversation_message has no upsert)"
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST D — the SOURCE guard. THE core of BL-376.
# Fails if anyone re-points the extractor at the assistant's `response`.
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("junk", REAL_JUNK_CORPUS)
def test_assistant_reply_junk_yields_no_learning(junk, isolated_db, hermetic_cfg):
    from services.infrastructure.outcome_writer import _auto_extract_learnings

    _reset_fingerprints()
    # A real request + a real reply that CONTAINS the exact junk row the old extractor stored.
    _auto_extract_learnings("write a fibonacci function in python", junk, "morrigan")
    _join_learn_threads()

    rows = [str(x.get("content") or "") for x in _learning_rows()]
    assert rows == [], (
        "the extractor must read the OPERATOR's turn, never the assistant's reply. "
        f"Stored: {rows!r}"
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST E — the hard reject. subject != "user" must never be stored.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_world_subject_is_hard_rejected(monkeypatch, isolated_db):
    import runtime_safety
    import services.infrastructure.outcome_writer as ow

    base = dict(runtime_safety.load_config() or {})
    base.update({"operator_memory_llm_enabled": True, "llama_server_url": "",
                 "identity_capture_enabled": False})
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: base)
    monkeypatch.setattr("services.llm.llm_gateway._get_llm", lambda *a, **k: object())
    monkeypatch.setattr(
        "services.llm.gbnf_grammar.run_gbnf_memory_extraction",
        lambda *a, **k: {"subject": "world", "type": "preference",
                         "fact": "Paris is the capital of France", "durable": True},
    )
    _reset_fingerprints()

    # First-person so the pre-filter passes and the LLM path is genuinely reached; no
    # deterministic trigger, so the ONLY thing that could store a row is the LLM path.
    ow._auto_extract_learnings("my question is about the capital of France", "Paris.", "morrigan")
    _join_learn_threads()

    assert _learning_rows() == [], "subject='world' must be hard-rejected"


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST F — malformed model output stores NOTHING (never "store the raw text").
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_malformed_llm_output_stores_nothing(monkeypatch, isolated_db):
    import runtime_safety
    import services.infrastructure.outcome_writer as ow

    base = dict(runtime_safety.load_config() or {})
    base.update({"operator_memory_llm_enabled": True, "llama_server_url": "",
                 "identity_capture_enabled": False})
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: base)
    monkeypatch.setattr("services.llm.llm_gateway._get_llm", lambda *a, **k: object())
    monkeypatch.setattr(
        "services.llm.gbnf_grammar.run_gbnf_memory_extraction",
        lambda *a, **k: None,  # what the runner returns for unparseable output
    )
    _reset_fingerprints()

    # No deterministic trigger in this message, so nothing else can save a row.
    ow._auto_extract_learnings("my name is Mina and I work on backend systems", "Nice to meet you.", "morrigan")
    _join_learn_threads()

    assert _learning_rows() == [], "unvalidated model output must never be stored"


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST F2 — the LLM extraction must hold the process-wide inference lock.
#
# NOT a hypothetical. The first end-to-end run of this feature against the real app ABORTED the
# server process on the very first streamed turn:
#     GGML_ASSERT(src1_ptr + src1_col_stride*nrows <= params->wdata + params->wsize) failed
#     Fatal Python error: Aborted
#     Thread A: run_gbnf_memory_extraction  <- the auto-learn background thread
#     Thread B: llama_cpp ... decode        <- the turn's own generation, still streaming
# llama_cpp is not thread-safe; two threads decoding on one Llama handle corrupt the shared
# scratch buffer and kill the PROCESS (not an exception — no try/except can catch it). Every unit
# test here stubs the LLM boundary, so none of them can see this: only driving the running app
# could. This test pins the invariant so a refactor cannot quietly drop the lock again.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_llm_extraction_holds_the_inference_lock(monkeypatch, isolated_db):
    import runtime_safety
    import services.infrastructure.outcome_writer as ow
    from services.llm import llm_gateway

    base = dict(runtime_safety.load_config() or {})
    base.update({"operator_memory_llm_enabled": True, "llama_server_url": "",
                 "llm_serialize_per_workspace": False, "identity_capture_enabled": False})
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: base)
    monkeypatch.setattr("services.llm.llm_gateway._get_llm", lambda *a, **k: object())

    seen = {"held": None}

    def _probe(*a, **k):
        # llm_serialize_lock is an RLock; acquire(blocking=False) from THIS thread would succeed
        # re-entrantly, so assert on the owner count instead — non-zero means it is held.
        seen["held"] = llm_gateway.llm_serialize_lock._is_owned()
        return None

    monkeypatch.setattr("services.llm.gbnf_grammar.run_gbnf_memory_extraction", _probe)
    ow._auto_extract_learnings("my name is Mina and I work on backend systems", "Hi.", "morrigan")

    assert seen["held"] is True, (
        "run_gbnf_memory_extraction must be called while holding the gateway's inference lock — "
        "an unserialized decode aborts the whole process (GGML_ASSERT)"
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST G — the detectors are PRIMARY, not downstream of `if not extracted: return`.
# This is the direct encoding of the bug the repo's own test comment admitted to dodging
# ("The response needs extractable bullet points so the function doesn't early-return").
# Distinct from A: A drives HTTP and can pass while the detectors are still LLM-coupled.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_preference_saved_when_llm_returns_nothing(isolated_db, hermetic_cfg):
    from services.infrastructure.outcome_writer import _auto_extract_learnings

    _reset_fingerprints()
    # A TERSE reply — 2 words. The old code required >=20 words and an LLM/regex extraction
    # before the preference detectors could run at all.
    _auto_extract_learnings("I prefer tabs over spaces", "Got it.", "echo")
    _join_learn_threads()

    rows = _learning_rows()
    assert any(r.get("learning_type") == "preference" for r in rows), (
        "an operator preference must be recorded even when the assistant said almost nothing. "
        f"Got: {[(r.get('learning_type'), r.get('content')) for r in rows]}"
    )


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST H — the choke point must not eat a short operator fact.
# ══════════════════════════════════════════════════════════════════════════════════════════
def test_short_operator_preference_survives_choke_point(isolated_db):
    from services.memory.memory_router import save_learning

    rid_default = save_learning(content="Operator preference: I prefer tea", kind="preference")
    assert rid_default == -1, "baseline: the 40-char floor rejects it (33 chars) — this is the bug"

    rid = save_learning(
        content="Operator preference: I prefer tea",
        kind="preference",
        confidence=0.7,
        source="operator_turn",
        min_length=12,
    )
    assert rid > 0, "min_length must thread through memory_router -> db -> learnings -> filter_learning"


# ══════════════════════════════════════════════════════════════════════════════════════════
# TEST I — `correction` and `episodic` must survive the type tuple, not be coerced to "fact".
# ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("kind", ["correction", "episodic"])
def test_operator_memory_types_are_not_coerced_to_fact(kind, isolated_db):
    from layla.memory.db import get_recent_learnings
    from services.memory.memory_router import save_learning

    rid = save_learning(
        content=f"Operator {kind}: the operator uses tabs for indentation in this project",
        kind=kind,
        confidence=0.8,
        min_length=12,
    )
    assert rid > 0
    row = next(r for r in get_recent_learnings(n=10) if int(r.get("id") or 0) == int(rid))
    assert row.get("learning_type") == kind, (
        f"'{kind}' was silently coerced to '{row.get('learning_type')}' — the type gate is unenforceable"
    )


def test_one_message_never_writes_two_rows_for_the_same_text():
    """A message that is BOTH a correction and a preference must produce ONE row, not two.

    Found by adversarial verification, uncovered by the original suite. `_detect_operator_facts` used two
    independent `if`s, so "Actually I prefer the recursive version" matched both trigger sets and emitted the
    same text twice. Dedup could not save it: the stored rows are prefixed by type ("Operator correction: …"
    vs "Operator preference: …"), so their content_hash differs and both persist.

    These are the verifier's real reproductions, not invented strings.
    """
    from services.infrastructure.outcome_writer import detect_operator_facts

    for msg in (
        "Actually I prefer the recursive version here",
        "No, that's wrong. I prefer PostgreSQL over MySQL",
    ):
        facts = detect_operator_facts(msg)
        assert len(facts) == 1, f"one message wrote {len(facts)} rows for the same text: {facts!r}"
        # Correction is the stronger signal and carries the higher confidence (0.8 vs 0.7).
        assert facts[0][0] == "correction", f"correction must win over preference, got {facts[0][0]!r}"

    # A pure preference (no correction trigger) must still be detected — the elif must not eat it.
    pure = detect_operator_facts("I prefer tea over coffee, always")
    assert len(pure) == 1 and pure[0][0] == "preference", f"pure preference broken: {pure!r}"
