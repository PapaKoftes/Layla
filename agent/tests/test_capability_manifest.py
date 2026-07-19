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


def test_manifest_is_actually_tracked_in_git():
    """`.identity/` is blanket-gitignored — the manifest was silently EXCLUDED from its first commit and would
    never have reached a fresh clone. "Preloaded self-knowledge" then degrades to "no self-knowledge" and she
    goes back to inventing capabilities, with nothing failing to warn anyone. A negation
    (`!.identity/capabilities.md`) fixes it; this test makes sure the negation is never lost."""
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".identity/capabilities.md"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, (
        "the capability manifest is NOT tracked in git, so it will not ship on clone. "
        "`.identity/` is ignored — .gitignore needs `!.identity/capabilities.md`."
    )


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
        # math_eval was here until 2026-07-16 — fixed (ast.Mul -> ast.Mult), so claiming it is broken would
        # now be its own kind of lie. The manifest must track reality in BOTH directions.
        #
        # search_codebase was here until 2026-07-17 — same story. It was wired to the uninstalled
        # tree-sitter backend and returned ok:true with 0 matches for symbols that existed; it now runs on
        # the ast-based repo_indexer (tests/test_search_codebase_wiring.py proves it finds them, and that
        # an empty index can no longer masquerade as "absent"). Keeping the disclosure would make the
        # manifest lie in the OTHER direction — telling her a working tool is broken, so she would refuse
        # to use it and reach for grep_code forever.
        #
        # The "Ingest button" disclosure was here until 2026-07-17 — REMOVED for the same reason. It was
        # written when the button read #ingest-path (a non-existent element); an earlier slice rewired it to
        # #km-source + POST /intelligence/kb/build/directory, and this phase DROVE it against a real
        # two-file folder on a live instance: {"ok":true,"articles":2}, both articles retrievable via
        # /intelligence/kb/articles. It works. Keeping "it does nothing" would be the manifest lying that a
        # working feature is broken — so she would never offer it. (See test_first_run_tour.py's sibling
        # note on proving-by-execution rather than by reading.)
        ("Custom aspects", "creatable but never selectable — silently falls back to Morrigan"),
        ("frozen", "capability scores never move from use"),
        ("Encryption-at-rest never fires", "nothing marks a memory sensitive"),
        ("approval gate is the real protection", "the sandbox filters do not hold"),
    ]
    for needle, why in required:
        assert needle in core, f"manifest must disclose: {why}"


# ── tool count ─────────────────────────────────────────────────────────────────────────────────────
# Tools proven BROKEN by execution, not by reading. Remove an entry when it is actually fixed; the expected
# count then rises and the manifest must be updated to match. That is the point.
KNOWN_BROKEN_TOOLS: set[str] = set()
# (was {"math_eval"} — `_ast.Mul` does not exist; it is `ast.Mult`, and the tuple was built BEFORE parsing so
#  every input raised AttributeError. Fixed 2026-07-16 along with the missing @functools.wraps that hid it:
#  the wrapper replaced every signature with (*args, **kwargs) and nulled every __doc__, so the tool-count
#  test counted registrations and never invoked one. This guard caught the repair and demanded the manifest be
#  updated — which is what a guard is for. The registry held 198 tools then and holds 200 now; that is why
#  the count below is derived, never written down.)


def test_manifest_tool_count_tracks_reality():
    """The manifest's tool count must be DERIVED from the registry, never a frozen literal.

    The first version of this test asserted `"197" in core`. That meant FIXING math_eval would make the working
    count 198, the manifest would have to say 198, and this test would FAIL — it punished repairing the defect
    and encoded the bug as expected behaviour. That is the same disease this file exists to fight, committed by
    the guard itself.

    Now: expected = registered - known-broken, computed at test time.
    """
    from layla.tools.registry import TOOLS

    expected = len(TOOLS) - len(KNOWN_BROKEN_TOOLS)
    core = _capability_manifest_core(ROOT)
    assert str(expected) in core, (
        f"manifest must state the WORKING tool count ({expected} = {len(TOOLS)} registered - "
        f"{len(KNOWN_BROKEN_TOOLS)} known-broken {sorted(KNOWN_BROKEN_TOOLS)}). If you fixed one, remove it "
        f"from KNOWN_BROKEN_TOOLS and update the manifest."
    )


def test_known_broken_tools_are_still_actually_broken():
    """Executes each known-broken tool. If one starts working, this FAILS and tells you to update the manifest.

    A registry entry proves only that a name maps to a callable: before the @functools.wraps repair every
    tool was wrapped into (*args, **kwargs) by _wrap_tool_with_metrics and the registry carried NO parameter
    schema — so a `len(TOOLS)` assertion passed while a tool raised on every input. Most registered tools are
    still invoked by no test at all. This executes the ones we know about instead of trusting a count.
    """
    from layla.tools.registry import TOOLS

    for name in sorted(KNOWN_BROKEN_TOOLS):
        assert name in TOOLS, f"{name} is no longer registered — update KNOWN_BROKEN_TOOLS"
        try:
            TOOLS[name]["fn"]("2+2")
        except Exception:
            continue  # still broken, as documented
        pytest.fail(
            f"{name} now WORKS — remove it from KNOWN_BROKEN_TOOLS, bump the manifest's tool count, and drop "
            f"its 'never call it' line from the manifest."
        )


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
