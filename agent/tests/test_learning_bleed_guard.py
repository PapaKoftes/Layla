"""Layla's own system prompt must never be stored as something she "learned".

Observed live: 4 of 32 rows in the operator's learnings table were verbatim system-prompt text or
internal prompt-context blocks — e.g. a byte-exact copy of a system_head_builder line
("This is a written TEXT chat: you are typing, not speaking…") and the KG block header
("Knowledge graph associations: ValueError; Hello.; …").

Why it mattered beyond noise — the loop was already CLOSED, with physical evidence:
    learning -> knowledge-graph node -> "Knowledge graph associations:" block in the next prompt
    -> the 3B model regurgitates it -> extracted as a new learning -> its tokens spawn new nodes
Graph nodes 'ValueError', 'Hello.', 'TEXT' and 'talking' were harvested from the bleed rows
themselves. Left alone, Layla's memory fills with her own instructions and crowds out real knowledge.

Two layers, tested here:
  1. SOURCE (run_finalizer): the extractor read the RAW `reason` step while the router sanitized only
     the text it SHOWS — so the user saw a clean reply while the extractor ate the bleed. It now
     sanitizes first. This is not symptom-filtering: the extractor was reading the wrong variable.
     (The true source — a 3B failing its output-discipline instruction — is not fixable in code.)
  2. FLOOR (distill.is_memory_junk): the shared chokepoint for the ~10 other writers (distill, tools,
     scheduler jobs, ingestion) that never touch the router.
"""
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from layla.memory.distill import is_memory_junk  # noqa: E402

# Verbatim rows recovered from the operator DB — the regression these guards exist for.
REAL_POISON = [
    "This is a written TEXT chat: you are typing, not speaking — never mention audio, voice, "
    "microphones, or 'talking'. Talk like a real, sharp person messaging: natural and direct.",
    "Knowledge graph associations: ValueError; Hello.; Input must be a non-negative... To add two "
    "and two, you simply count up to four. No need for complex logic here.",
    "**Core**: Implement, debug, architect, ship.",
    "**Voice Contract**: Blunt and surgical — target the problem, not the person.",
]
# Prompt blocks that would close the feedback loop if stored.
PROMPT_BLOCKS = [
    "Things I remember: the user prefers tea.",
    "Relevant memories: the user is called Mina.",
    "Recent learnings: something the model echoed back.",
    "Knowledge graph associations: A; B; C",
]
# Legitimate learnings. A filter that eats these is WORSE than the bug it fixes — it would silently
# destroy real memory. Includes deliberate traps: header-like words used as ordinary content.
LEGIT = [
    "The user prefers concise answers without preamble.",
    "Validate the existence of the key before sorting.",
    "Use enumerate() to iterate with an index in Python.",
    "Focus on readability when reviewing this codebase.",
    "Voice Contract negotiations concluded in 2019.",
    "The user remembers things better when given examples.",
    "Relevant memories were discussed at the meeting.",
]


def test_real_poisoned_rows_are_rejected():
    for content in REAL_POISON:
        assert is_memory_junk(content), f"system-prompt bleed must never be stored: {content[:60]!r}"


def test_prompt_context_blocks_are_rejected():
    # Anchored at content start: storing these closes the learning -> graph -> prompt -> learning loop.
    for content in PROMPT_BLOCKS:
        assert is_memory_junk(content), f"prompt block must never be stored: {content[:60]!r}"


def test_legitimate_learnings_are_not_eaten():
    for content in LEGIT:
        assert not is_memory_junk(content), f"FALSE POSITIVE — real learning rejected: {content!r}"


def test_system_prompt_bleed_in_a_reply_cannot_reach_the_learnings_table(isolated_db, monkeypatch):
    """BEHAVIOURAL replacement for the old source-grep (BL-338/BL-376).

    The previous version of this test regex-grepped run_finalizer.py for
    `target=auto_extract_learnings_fn, args=(..., learn_text, ...)`. That could only fail when the
    source STRING changed — never when the wiring broke — which is exactly the vacuity it was
    supposed to prevent. It also asserted a call site that no longer exists: extraction moved to
    services/agent/turn_commit.commit_turn.

    The layer-1 defence is now STRUCTURAL rather than sanitizing: post-BL-376 the extractor reads the
    OPERATOR's turn and never the assistant's reply, so bleed in the reply has no route into the
    table at all. This test proves that by observation — it feeds the real extractor the real
    recovered poison as the assistant's reply and reads the real DB.
    """
    import collections

    import runtime_safety
    import services.infrastructure.outcome_writer as ow
    from layla.memory.db import get_recent_learnings

    base = dict(runtime_safety.load_config() or {})
    base.update({"operator_memory_llm_enabled": False, "identity_capture_enabled": False})
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: base)

    for poison in REAL_POISON:
        ow._recent_learning_fingerprints = collections.OrderedDict()
        # A perfectly ordinary request; the model bleeds its own system prompt into the reply.
        ow._auto_extract_learnings("how do i add two numbers in python", poison, "morrigan")

    rows = [str(r.get("content") or "") for r in (get_recent_learnings(n=50) or [])]
    assert rows == [], f"system-prompt bleed reached the learnings table via the reply: {rows!r}"
