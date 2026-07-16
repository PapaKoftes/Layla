"""Layla must answer "what can you do?" from verified fact, not imagination.

Asked to report her capabilities in a table, she produced entirely invented ones — "User management",
"Encryption support", "Security auditing". None are real. That was not a formatting bug: she had NO ground
truth to answer from. Three self-knowledge surfaces existed and not one carried a capability list:
  - .identity/self_model.md  — 51 lines of philosophy, and gated to the Lilith aspect only
  - docs/CAPABILITIES.md     — about the implementation registry; no runtime code reads it
  - operating_manual.manual_for_prompt() — named "for_prompt", called only by an API endpoint

.identity/capabilities.md is the fix: a verified manifest, git-tracked (so it ships on clone — genuinely
preloaded, no ingestion step), injected for ALL aspects when the question is about capabilities.

These tests pin the three properties that make it safe:
  1. It reaches the prompt on a capability question, EARLY (system_instructions truncates from the TAIL on
     low tiers, so an appended block is exactly what gets cut).
  2. It costs nothing on ordinary turns — a 3B cannot afford ~600 tok every turn.
  3. It stays HONEST. A manifest that overstates is worse than no manifest: it converts hallucination into
     authoritative lying. The broken-feature disclosures are asserted explicitly.
"""
import sys
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parent.parent
ROOT = AGENT.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from services.prompts.prompt_builder import (  # noqa: E402
    _capability_manifest_core,
    _is_capability_question,
    build_core_sys_parts,
)

# Real phrasings a user would actually type, including the operator's own verbatim message that produced
# the hallucinated table.
CAPABILITY_QUESTIONS = [
    "what can you do",
    "what can you do?",
    "tell me what you can do",
    "list your capabilities",
    "what are your capabilities",
    "what tools do you have",
    "what features do you have",
    "what are you capable of",
    "can you speak",
    "how do i use the memory panel",
    "you are to fully and completely check every capability that you have and report it to me in chat in the form of a table",
]
# Ordinary turns. These must NOT pay the token cost. Several are deliberate near-misses: "can you do this
# refactor" is a REQUEST, not a question about capabilities.
ORDINARY_TURNS = [
    "fix this bug in my python code",
    "what is the capital of france",
    "write a function that sorts a list",
    "hey",
    "can you do this refactor for me",
    "could you do that again",
    "can you do it faster",
    "what do you think about this design",
    "what can you tell me about this repo",
    "list the files in src",
]


def test_manifest_file_ships_and_has_a_prompt_core():
    p = ROOT / ".identity" / "capabilities.md"
    assert p.exists(), "the capability manifest must exist"
    core = _capability_manifest_core(ROOT)
    assert core, "PROMPT-CORE-START/END block must be present and non-empty"
    # Small enough to survive a low-tier budget. ~600 tok is already a lot for a 3B; 4000 chars is the ceiling
    # before it starts crowding out the persona and the actual question.
    assert len(core) < 4000, f"prompt core is {len(core)} chars — too big for the low-tier budget"


def test_manifest_is_honest_about_what_is_broken():
    """The whole point. If these disclosures are dropped, Layla starts lying with authority."""
    # Collapse whitespace: the manifest is wrapped markdown, so a phrase can straddle a newline.
    core = " ".join(_capability_manifest_core(ROOT).split())
    required = [
        ("CANNOT speak", "TTS/STT are dead — every engine is missing from the venv"),
        ("search_codebase", "returns ok:true with 0 matches; a zero result must not be trusted"),
        ("math_eval", "raises AttributeError on every input"),
        ("Ingest button", "reads a non-existent element; knowledge cannot be added via the UI"),
        ("Custom aspects", "creatable but never selectable — silently falls back to Morrigan"),
        ("frozen", "capability scores never move from use"),
        ("Encryption-at-rest never fires", "nothing marks a memory sensitive"),
        ("approval gate is the real protection", "the sandbox filters do not hold"),
    ]
    for needle, why in required:
        assert needle in core, f"manifest must disclose: {why}"


def test_manifest_does_not_overstate_the_tool_count():
    # math_eval raises on every input (ast.Mul does not exist), so 198 registered != 198 working.
    core = _capability_manifest_core(ROOT)
    assert "197" in core, "tool count must be the WORKING count (197), not the registered count (198)"


@pytest.mark.parametrize("goal", CAPABILITY_QUESTIONS)
def test_gate_fires_on_capability_questions(goal):
    assert _is_capability_question(goal.lower()), f"must inject self-knowledge for: {goal!r}"


@pytest.mark.parametrize("goal", ORDINARY_TURNS)
def test_gate_stays_quiet_on_ordinary_turns(goal):
    assert not _is_capability_question(goal.lower()), (
        f"must NOT spend ~600 tok on: {goal!r} — a 3B cannot afford it every turn"
    )


def _parts(goal, aspect_id="morrigan"):
    return build_core_sys_parts(
        cfg={"prompt_static_cache_enabled": False},
        aspect={"id": aspect_id},
        identity="IDENTITY",
        personality="PERSONA",
        goal=goal,
        reasoning_mode="",
        repo_root=ROOT,
    )


def test_manifest_reaches_the_prompt_and_survives_tail_truncation():
    parts = _parts("what can you do?")
    idx = next((i for i, s in enumerate(parts) if "CANNOT speak" in s), -1)
    assert idx >= 0, "manifest must be injected on a capability question"
    # Must be in the FRONT half: system_instructions is budget-truncated from the tail on low tiers, so an
    # appended block is precisely the thing that gets cut (same lesson as the persona insert).
    assert idx < len(parts) / 2, (
        f"manifest at index {idx}/{len(parts)} — too near the tail; low tiers would truncate it away"
    )


def test_manifest_absent_on_an_ordinary_turn():
    assert not any("CANNOT speak" in s for s in _parts("fix this bug in my python code"))


def test_manifest_is_not_lilith_gated():
    """self_model.md is Lilith-only (prompt_builder gates on aspect id) — that is exactly why the hallucinated
    table happened on a Lilith turn with no capability data. Every aspect must get the manifest."""
    for aspect_id in ("morrigan", "nyx", "echo", "eris", "cassandra", "lilith"):
        parts = _parts("what can you do?", aspect_id=aspect_id)
        assert any("CANNOT speak" in s for s in parts), f"{aspect_id} must receive the capability manifest"


def test_missing_manifest_degrades_quietly(tmp_path):
    """A missing/unreadable manifest must not break a turn — it should fall back to today's behavior."""
    _capability_manifest_core.cache_clear()
    try:
        assert _capability_manifest_core(tmp_path) == ""
    finally:
        _capability_manifest_core.cache_clear()
