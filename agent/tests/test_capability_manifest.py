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
    # The true positives the W6 object-gate must not cost: bare verb, her as the object, and the
    # faculty named directly.
    "can you hear me",
    "can you speak out loud",
    "can you search the web",
    "can you access the internet",
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
    # W6: the `can you <sense-verb>` list gated the VERB and not the OBJECT, so every one of these
    # ordinary requests was billed as a capability turn. Measured against the 848-token baseline:
    # "can you see the error in line 4" +730 tok, "can you browse to the file and fix it" +721 —
    # the same cost as the true positive "can you speak" (+715).
    "can you see the error in line 4",
    "can you browse to the file and fix it",
    "can you listen to this audio file",
    "can you talk to the api",
    "can you see why this fails",
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
        #
        # "Custom aspects" and "frozen" were pinned here until 2026-07-19 — REMOVED, and this is the
        # sharpest example yet of why this guard must assert SEMANTICS and not substrings. Both features
        # were FIXED (custom aspect selection in 4bd41b5, capability practice wiring in the same commit)
        # and neither fix touched the manifest. So this test was GREEN *because the manifest was WRONG*:
        # it actively enforced two lies, and would have failed the moment someone corrected them. A guard
        # that punishes telling the truth is worse than no guard.
        #   - custom aspects: DRIVEN 2026-07-19 — select_aspect(force_aspect=<custom id>) returns the
        #     custom id/name/prompt-hint (a bogus id still falls back to Morrigan with a miss flag). The
        #     residual limit is real and the manifest states it: exactly one entry point ("talk as this"
        #     in the Ctrl+K overlay); the aspect bar and @mention list only the 6 built-ins.
        #   - capability scores: DRIVEN 2026-07-19 through commit_turn itself (the seam, not the helper) —
        #     a coding turn moved coding 0.50/0 -> 0.51/1 with a fresh last_practiced_at; "hi" and a
        #     refused turn recorded nothing.
        # The Study "Quick picks" disclosure was never pinned here, but it was stale for the same reason
        # and was corrected in the same pass (driven in a live browser: a real click adds the plan).
        ("Encryption-at-rest never fires", "nothing marks a memory sensitive"),
        ("approval gate is the real protection", "the sandbox filters do not hold"),
        # Added 2026-07-19, each re-verified by driving the real path before pinning:
        #   - LAN offload: `submit_task` and `run_completion_with_fallback` both still have ZERO callers
        #     outside comments, so clustering moves no inference work.
        #   - Python net: python_runner installs _NET_SPEEDBUMP, explicitly labelled "trivially bypassable
        #     — NOT a boundary" (BL-295 kept it as a speed-bump rather than pretending to a jail).
        ("LAN peer offload moves no work", "clustering has no inference entry point"),
        ("does NOT block the network", "the python sandbox net-jail is a speed-bump, not a boundary"),
    ]
    for needle, why in required:
        assert needle in core, f"manifest must disclose: {why}"


def test_manifest_does_not_reintroduce_the_fixed_lies():
    """The other half of honesty, and the half that was missing.

    `test_manifest_is_honest_about_what_is_broken` only ever asserted PRESENCE, so it could not notice that
    three of the phrases it was guarding had become false — it enforced them instead. This is the negative
    guard: these features were each DRIVEN working on 2026-07-19, so the manifest must never again describe
    them as dead. If one genuinely regresses, fix the FEATURE; only then change this list, and say here how
    you drove it.
    """
    core = " ".join(_capability_manifest_core(ROOT).split())
    forbidden = [
        ("Quick picks\" preset buttons do nothing", "the presets work — a real click adds the study plan"),
        ("can be created but never selected", "custom aspects resolve via select_aspect"),
        ("scores are frozen", "commit_turn records practice: coding moved 0.50/0 -> 0.51/1"),
        ("blocklist is bypassable", "the .exe / trailing-dot bypass is closed; 17/17 variants blocked"),
    ]
    for needle, why in forbidden:
        assert needle not in core, (
            f"manifest has re-introduced a FIXED defect as broken ({needle!r}) — {why}. Telling her a "
            f"working feature is dead is the same failure as inventing one."
        )


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


# ── the manifest must actually REACH the model ─────────────────────────────────────────────────────
# Everything above this line tests the manifest's CONTENT. Everything below tests its DELIVERY, which
# for a long time was zero: the manifest was correct, injected, and then thrown away twice over.
#
# The test directly above (`..._survives_tail_truncation`) is kept for its list-ordering signal but it does
# NOT prove its own name, and it is worth being precise about why, because it was green through the entire
# outage:
#   - it passes repo_root=ROOT, a root the TEST computes — so it never touched the two production constants
#     that were both wrong (prompt_builder.REPO_ROOT resolved to agent/, system_head_builder.REPO_ROOT to
#     agent/services/, and .identity/ is at neither). In production the manifest was "" on every call.
#   - it passes identity="IDENTITY", one token — so the manifest could not possibly be pushed past a cap by
#     the 751-token identity file that actually sits there.
#   - it asserts a LIST INDEX. It never joins the parts, never truncates, never counts a token. "Front half
#     of the list" says nothing about surviving a token budget: the list is 17 items and the item at index 3
#     already starts at token offset ~1030, inside a section capped at 800 (417 effective on a 2048-ctx box).
#
# The tests below use the PRODUCTION constants, the REAL identity file, the real join, the real budget
# assembler and the real truncation, and they count tokens.


def _production_roots():
    from services.prompts import prompt_builder as _pb
    from services.prompts import system_head_builder as _shb
    return {"prompt_builder.REPO_ROOT": _pb.REPO_ROOT, "system_head_builder.REPO_ROOT": _shb.REPO_ROOT}


def test_production_repo_root_constants_actually_locate_the_manifest():
    """D1. Both constants were hand-rolled `__file__.parent...` chains and both were off by a level.

    Asserting on the FILESYSTEM rather than on the literal expression, so any future refactor is free to
    compute the root however it likes as long as the manifest is still there when it does.
    """
    for name, root in _production_roots().items():
        assert (root / ".identity" / "capabilities.md").is_file(), (
            f"{name} = {root} — no .identity/capabilities.md under it. Every capability question will be "
            f"answered from invention, silently, because _capability_manifest_core returns '' on a miss."
        )
        assert _capability_manifest_core(root), f"{name} = {root} resolves no PROMPT-CORE block"


def test_persona_edits_invalidate_the_static_prompt_cache(tmp_path, monkeypatch):
    """D1's quiet side effect: _personality_file_mtime looks under REPO_ROOT/personalities/, so the wrong
    root made it return 0.0 for every aspect, forever. The static prompt cache keys on that mtime — a
    constant 0.0 means editing a persona file never invalidated the cache and the operator kept getting the
    voice they had already replaced, until a restart.
    """
    import json
    import os

    from services.prompts import prompt_builder as PB

    # Real root first: a real aspect must produce a real mtime, a bogus one must not.
    assert PB._personality_file_mtime("morrigan") > 0.0, (
        "personalities/morrigan.json is not being found under the production REPO_ROOT — the static "
        "prompt cache can never invalidate"
    )
    assert PB._personality_file_mtime("no_such_aspect_xyz") == 0.0

    # Then prove the invalidation itself against a temp root, so the repo's own files are never written to.
    (tmp_path / "personalities").mkdir()
    f = tmp_path / "personalities" / "morrigan.json"
    f.write_text(json.dumps({"id": "morrigan", "voice": "v1"}), encoding="utf-8")
    monkeypatch.setattr(PB, "REPO_ROOT", tmp_path)

    cfg = {"prompt_static_cache_enabled": True}
    before = PB._static_cache_key("morrigan", cfg)
    f.write_text(json.dumps({"id": "morrigan", "voice": "v2"}), encoding="utf-8")
    # Advance the mtime explicitly. Two writes inside one filesystem timestamp tick are indistinguishable,
    # which would make this test flaky rather than wrong — an editor's save is minutes apart, not microseconds.
    _st = f.stat()
    os.utime(f, (_st.st_atime, _st.st_mtime + 2))
    after = PB._static_cache_key("morrigan", cfg)
    assert before != after, (
        "editing a persona file did not change the static cache key — the cached prompt is now stale "
        "until the process restarts"
    )


def _drive_head(goal, monkeypatch, _hist=None, _aspect=None, **cfg_over):
    """Drive the REAL build_system_head on a pinned low-tier config.

    n_ctx 2048 / head ratio 0.22 is this project's floor tier and the configuration the injection defect was
    measured on — pinned here rather than read from the operator's config so the assertion means the same
    thing on every machine.
    """
    import runtime_safety as rs
    from services.context.context_manager import record_prompt_metrics
    from services.prompts import system_head_builder as SHB

    # Clear the module-global prompt metrics first. build_system_prompt feeds the PREVIOUS call's
    # section sizes into rebalance_budget, so without this a drive inherits pressure from whatever ran
    # before it — these tests went order-dependent under pytest-randomly for exactly that reason, and an
    # assertion that depends on test order is not measuring the code.
    record_prompt_metrics({}, 2048)
    _orig = rs.load_config()
    monkeypatch.setattr(
        rs, "load_config",
        lambda: {**_orig, "n_ctx": 2048, "system_head_budget_ratio": 0.22, **cfg_over},
    )
    return SHB.build_system_head(
        goal=goal,
        aspect=_aspect or {"id": "morrigan", "name": "Morrigan"},
        conversation_history=_hist or [],
    )


# Needles from the manifest's first line, its middle, and its LAST line. The last one is the load-bearing
# assertion: truncation is from the tail, so a manifest that is merely *present* proves nothing — a block cut
# at 60% still contains "CANNOT speak" while having lost every disclosure after it.
_MANIFEST_HEAD = "My real capabilities"
_MANIFEST_MIDDLE = "I CANNOT speak or listen"
_MANIFEST_TAIL = "Do not recite this list"


def test_manifest_survives_the_real_budget_and_the_real_truncation(monkeypatch):
    """D2. The end-to-end proof, in tokens, through the production assembler.

    Goes RED if either production REPO_ROOT regresses (manifest resolves to "" and nothing is injected) or
    if the insert index regresses (manifest lands behind the 751-token identity file and is truncated away).
    Both were verified by breaking them, one at a time, and watching this fail.
    """
    from services.context.context_manager import token_estimate

    head = _drive_head("what can you do?", monkeypatch)

    assert _MANIFEST_HEAD in head, (
        "the capability manifest never reached the assembled prompt. Check the two REPO_ROOT constants "
        "(a wrong root yields '' with no error) and the insert index in build_core_sys_parts."
    )
    assert _MANIFEST_MIDDLE in head, "manifest reached the prompt but was cut before its BROKEN section"
    assert _MANIFEST_TAIL in head, (
        "manifest was truncated before its final line — it is being injected behind something large enough "
        "to push its tail past the system_instructions cap, or the head budget is not being widened to fit it"
    )

    # And it must be EARLY, measured in tokens against the real 751-token identity file — not by list index.
    offset = token_estimate(head[: head.index(_MANIFEST_HEAD)])
    manifest_tok = token_estimate(_capability_manifest_core(ROOT))
    assert offset < manifest_tok, (
        f"manifest starts at token offset {offset} — more than its own size ({manifest_tok} tok) is sitting "
        f"in front of it. That is the shape of the original defect (measured offset ~1030, cap 417)."
    )


def test_identity_manifesto_is_the_one_that_gets_truncated_not_the_manifest(monkeypatch):
    """The ordering pin, stated as the trade it actually is.

    Both the manifesto and the manifest cannot fit on a 2048-ctx box. Truncation is from the tail, so
    whichever goes second is the one that loses its end. On a turn whose entire subject is "what can you do",
    the capability facts must win and the identity prose must be the one cut. This assertion is independent
    of any budget arithmetic, so it still bites if the head budget is later widened enough to hide it.

    The precondition "identity is present" was dropped on 2026-07-19. It was only ever satisfiable because
    `_drive_head` defaults to a stub aspect with no voice contract; driven with the REAL Morrigan aspect the
    identity manifesto was already fully truncated on a capability turn, before any of this phase's changes.
    Requiring it to be present therefore asserted an artefact of the stub, not a property of the product.
    What IS a property: the manifest must arrive COMPLETE, and the identity prose must be the loser — which
    is now checked whether the prose is partly cut (present, and behind the manifest) or entirely cut.
    """
    for aspect in (None, _real_morrigan()):
        head = _drive_head("what can you do?", monkeypatch, _aspect=aspect)
        identity_marker = "a bounded AI companion and engineering agent"

        assert _MANIFEST_HEAD in head and _MANIFEST_TAIL in head, (
            "the capability manifest is not intact on a capability turn — the trade this test describes "
            "(identity prose yields to capability facts) is not being made"
        )
        if identity_marker in head:
            assert head.index(_MANIFEST_HEAD) < head.index(identity_marker), (
                "the capability manifest is behind the identity manifesto again. That is exactly the "
                "~1030-token offset that made it unreachable: it is found, injected, and then truncated "
                "away every time."
            )


def test_ordinary_turns_do_not_pay_for_the_manifest(monkeypatch):
    """The widened head budget is goal-gated. If it leaks onto ordinary turns, a 3B loses its context window.

    The relative half of this assertion (`ordinary < cap`) is kept for readability but is NOT the guard —
    it cannot fail while both operands move together, which is exactly what happened: the widening fired on
    every turn, ordinary went 829 -> 1480 and capability went 1463 -> 1718, and this test stayed green
    through a 79% inflation of every ordinary prompt. The real guard is the absolute ceiling in
    test_ordinary_turn_head_stays_under_an_absolute_ceiling.
    """
    from services.context.context_manager import token_estimate

    cap = _drive_head("what can you do?", monkeypatch)
    ordinary = _drive_head("fix this bug in my python code", monkeypatch)

    assert _MANIFEST_HEAD not in ordinary, "manifest injected on an ordinary turn — ~750 tok for nothing"
    assert token_estimate(ordinary) < token_estimate(cap), (
        "an ordinary turn now costs as much as a capability turn — the head widening is not goal-gated"
    )


# The ordinary-turn head budget, as an ABSOLUTE number of tokens.
#
# Written down deliberately. Every existing size assertion in this file is relative — one head compared
# against another head built by the same code — and `grep -rn "assert.*token_estimate.*< [0-9]"` over
# agent/tests returned nothing at all before this constant existed. That is how a 79% inflation of every
# ordinary prompt passed a green suite: there was no fixed point anywhere for it to be measured against.
#
# Calibrated on the config _drive_head pins (n_ctx 2048, head ratio 0.22) with the REAL Morrigan aspect,
# whose 590-token voice contract is what makes this tier tight. Measured ordinary heads sit at 825-845
# tokens; the structural floor is ~830 (a 512-token section budget plus the ~320-token output-discipline
# footer appended after assembly). 1000 leaves ~160 tokens of headroom for prompt edits while still
# failing decisively on the regression it exists to catch, which was 1480-1575.
_ORDINARY_HEAD_CEILING_TOK = 1000


def _real_morrigan():
    """The aspect the product actually uses, not the hand-built stub `_drive_head` defaults to.

    `{"id": "morrigan", "name": "Morrigan"}` carries no `systemPromptAddition`; the real one loaded from
    personalities/morrigan.json carries a 590-token voice contract. That single difference is what decides
    every budget question in this file — driven with the stub, an ordinary head is ~830 tokens and the
    regression these ceilings exist to catch is invisible on half its rows.
    """
    import orchestrator

    aspect = orchestrator.select_aspect("hello", force_aspect="morrigan")
    assert (aspect.get("systemPromptAddition") or "").strip(), (
        "the real Morrigan persona has no systemPromptAddition — these budget tests are no longer "
        "exercising the large-persona case they exist for"
    )
    return aspect

# The capability turn is allowed more — it is carrying the manifest, which is the entire point. Measured
# 1576 (English) / 1625 (with a language directive), and that total is accounted for rather than observed:
#
#   core line 23 + per-turn directives ~184 (aspect behaviour 23, rank gate 29, language 73, hardware 59)
#   + manifest 889 + current_goal ~11 + output-discipline footer ~320 + memory ~68  ->  ~1625
#
# 1700 leaves ~75 tokens of headroom. It still fails on the pre-reorder head (1718), which is the
# regression it exists to catch — and that head had ALSO lost the manifest's last line, so this ceiling
# and the _MANIFEST_TAIL assertion in the same test guard it from two directions: what it cost, and what
# the cost bought. If the manifest grows enough to breach this, the right response is to tighten the
# manifest, not to raise the number: it is injected into a 2048-token window.
_CAPABILITY_HEAD_CEILING_TOK = 1700


@pytest.mark.parametrize("goal", [
    "fix this bug in my python code",
    "explain decorators",
    "refactor this function to use a dataclass",
    "write a test for the parser",
    "hi",
])
@pytest.mark.parametrize("language", [None, "spanish"])
def test_ordinary_turn_head_stays_under_an_absolute_ceiling(goal, language, monkeypatch):
    """An ordinary turn must cost a fixed, small number of tokens — asserted against a NUMBER, not a sibling.

    This is the test that catches R1. The widening was gated on `if _protected_prefix_tokens:`, and that
    value is core line + persona + per-turn directives, which is truthy on literally every turn — so
    `reserve_for_response` went 512 -> 0 always, doubling build_system_prompt's total_budget from
    (window - 512) to the full window. Nothing about the resulting prompt was better; the extra ~650 tokens
    were identity-manifesto prose, and the manifest was not even on those turns.

    Parametrised over a language because the naive fix for R1 — gating the widening on the capability
    question alone — restores the token numbers while silently dropping the BL-160 language directive,
    which is half of what this slice promised. A green row here with `language="spanish"` and a green
    test_response_language_directive_reaches_the_prompt are what make that fix distinguishable from the
    real one.
    """
    from services.context.context_manager import token_estimate

    over = {"response_language": language} if language else {}
    head = _drive_head(goal, monkeypatch, _aspect=_real_morrigan(), **over)
    tok = token_estimate(head)

    assert tok <= _ORDINARY_HEAD_CEILING_TOK, (
        f"ordinary turn {goal!r} (language={language}) built a {tok}-token head, over the "
        f"{_ORDINARY_HEAD_CEILING_TOK}-token ceiling. On a 2048-token window that is spent on the hottest "
        f"path there is: it is CPU-prefill latency on every turn and it is the head crowding out the "
        f"conversation. Check that the head widening is still gated on the protected prefix genuinely not "
        f"fitting the ordinary budget, and that the protected prefix still excludes the persona."
    )


def test_capability_turn_head_stays_under_an_absolute_ceiling(monkeypatch):
    """The manifest turn is allowed to cost more, but not without limit."""
    from services.context.context_manager import token_estimate

    for language in (None, "spanish"):
        over = {"response_language": language} if language else {}
        head = _drive_head("what can you do?", monkeypatch, _aspect=_real_morrigan(), **over)
        tok = token_estimate(head)
        assert tok <= _CAPABILITY_HEAD_CEILING_TOK, (
            f"capability turn (language={language}) built a {tok}-token head, over the "
            f"{_CAPABILITY_HEAD_CEILING_TOK}-token ceiling"
        )
        assert _MANIFEST_TAIL in head, (
            "the capability head is within budget but the manifest lost its tail — the budget is being "
            "spent on something other than the thing it was widened for"
        )


def test_head_plus_conversation_plus_reply_is_measured_against_n_ctx(monkeypatch):
    """The overflow test the previous one only claimed to be.

    `test_widened_head_backs_off_instead_of_overflowing_the_window` named overflow as its failure mode and
    then never added the three terms up: it compared the head against `ordinary + 64`, where `ordinary` was
    itself built by the widened code and inflated by the same ~650 tokens. A comparator that moves with the
    regression cannot detect the regression.

    So: add up what the model is actually handed — assembled head + the conversation block the CALLER
    appends + the reply the model must have room to generate — and compare THAT against n_ctx.

    Asserted at the depths where fitting is achievable. At 24 turns of long messages it is not: the capped
    conversation block alone is ~1780 tokens, which with the reply leaves less than the head's structural
    floor. That floor is pre-existing and is not what this test guards, so the deep-history rows assert the
    head has backed off to its floor instead — which is the part the head controls.
    """
    from services.context.context_manager import token_estimate
    from services.prompts import system_head_builder as SHB

    prose = (
        "I have been working through the retrieval layer this morning and the ranking still looks wrong "
        "for short queries, so I want to walk through how the scores are combined. "
    ) * 6
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": prose} for i in range(40)]
    n_ctx, reply = 2048, 320

    for turns in (0, 6, 12, 24):
        head = _drive_head("fix this bug in my python code", monkeypatch, convo_turns=turns,
                           completion_max_tokens=reply, _hist=history, _aspect=_real_morrigan())
        head_tok = token_estimate(head)
        convo_tok = SHB._convo_block_tokens({"convo_turns": turns}, history)
        total = head_tok + convo_tok + reply

        # The head's own contribution is bounded at every depth. This is the assertion with teeth at 24.
        assert head_tok <= _ORDINARY_HEAD_CEILING_TOK, (
            f"at {turns} conversation turns the ordinary head is {head_tok} tok, over the "
            f"{_ORDINARY_HEAD_CEILING_TOK}-token ceiling — the head is making a tight window tighter"
        )
        if turns <= 6:
            assert total <= n_ctx, (
                f"at {turns} conversation turns the model is handed {total} tokens against an n_ctx of "
                f"{n_ctx} (head {head_tok} + conversation {convo_tok} + reply {reply}). This overflows: "
                f"llama.cpp will drop the oldest tokens, and the oldest tokens are the system head — "
                f"identity, directives and all."
            )


def test_every_per_turn_directive_survives_an_ordinary_turn(monkeypatch):
    """The other half of R1: cheap the right way, not cheap by dropping what matters.

    Gating the widening on the capability question alone gets the token numbers right and quietly costs the
    language directive (~73 tok) and the aspect-behaviour block (~23 tok) on every ordinary turn. The
    directives are what a per-turn instruction IS; they belong in the protected prefix and the persona does
    not. Each needle below is a block that was measured being appended after the join and truncated away.
    """
    head = _drive_head("fix this bug in my python code", monkeypatch,
                       _aspect=_real_morrigan(), response_language="spanish")

    for label, needle in (
        ("core identity line", "You are Layla. Use the identity and rules below"),
        ("aspect behaviour", "Tool bias for this aspect"),
        ("BL-160 language directive", "## Language"),
        ("hardware summary", "[Hardware:"),
        ("the user's actual question", "Current goal:"),
    ):
        assert needle in head, (
            f"{label} is missing from an ordinary head. It is a per-turn directive: it must sit in the "
            f"protected prefix, ahead of the persona, not on the tail where truncation reaches it first."
        )


def test_familiarity_directive_is_not_persona_prose(monkeypatch):
    """Same budget guard, new occupant. This used to pin the rank<1 "early growth phase" directive,
    which had been appended to `personality` — the tail of a 590-token voice contract that is itself
    truncated from the tail, so it was the first thing cut on every ordinary turn.

    That directive is gone: it was keyed on maturity rank, which is an activity counter, so it
    arrived and left for reasons unrelated to whether she actually knew the operator. What sits in
    that slot now is familiarity_line(), which measures the same thing directly and also replaced
    the "Your current capabilities: ..." string. Both branches are driven, because on a fresh box
    the roster is empty and only the knows-nothing branch would ever be seen.

    It must reach the prompt intact — i.e. live in `_directives`, not on the persona tail.
    """
    from services.personality.familiarity import familiarity_line

    head = _drive_head("fix this bug in my python code", monkeypatch, _aspect=_real_morrigan())
    line = familiarity_line()
    assert line, "familiarity_line() produced nothing"
    # Match on a distinctive fragment: the head is assembled, so the sentence may be adjacent to others.
    needle = "preferences on file" if "preferences on file" in line else "do not know this operator"
    assert needle in head, (
        f"the familiarity directive ({needle!r}) is being truncated away — it is a directive, so it "
        "belongs in `_directives`, not appended to the persona string"
    )

    # And the capability claim it replaced must not have come back with it.
    assert "Your current capabilities" not in head, (
        "the rank-derived capability string is back in the assembled head, contradicting the manifest"
    )


def test_response_language_directive_reaches_the_prompt(monkeypatch):
    """D3, and the user-visible one: seven blocks were appended to system_instructions AFTER the join, onto
    the tail of a ~3100-token string capped at 800. Every one was built and then discarded on every turn.

    The BL-160 language directive is the proof, because its failure is visible without reading any code: set
    Spanish, still get English. Asserted for two languages so a hardcoded needle cannot fake it.
    """
    es = _drive_head("fix this bug in my python code", monkeypatch, response_language="spanish")
    assert "Español" in es or "Spanish" in es, (
        "the response-language directive did not reach the prompt — setting a language does nothing"
    )

    ja = _drive_head("fix this bug in my python code", monkeypatch, response_language="japanese")
    assert "日本語" in ja or "Japanese" in ja
    assert "Spanish" not in ja, "language directive is not actually tracking the configured language"


def test_language_directive_survives_alongside_the_manifest(monkeypatch):
    """The two fixes must not cannibalise each other: the manifest is ~750 tok and the directives are small,
    so a naive ordering that puts the directives after the manifest loses them on exactly the turn where the
    most is being asked of the budget."""
    head = _drive_head("what can you do?", monkeypatch, response_language="spanish")
    assert _MANIFEST_TAIL in head, "manifest lost when a language directive was also present"
    assert "Español" in head or "Spanish" in head, "language directive lost when the manifest was present"


def test_widened_head_backs_off_instead_of_overflowing_the_window(monkeypatch):
    """The widening's safety property, and the one worth a test because it is invisible until it bites.

    Making room for a 757-token manifest inside a 2048-token window only works while there is room. Under a
    real conversation there is not, and the head must then shrink back — a truncated manifest costs a
    disclosure, an overflowed context costs the whole turn. The head window is therefore bounded by what
    n_ctx can SPARE (minus the reply, minus the conversation block the caller appends), not by a fraction.

    Driven at four history depths. Two measurements are behind this: a fixed 0.75 fraction was both too
    small (CI's config carries two more directive blocks than this box, and those ~40 tokens pushed the
    manifest's last line out — the CI gate caught it, this box did not) and too large (1536 tokens of head
    plus a full backscroll overruns 2048).

    The comparator was rewritten on 2026-07-19. It was `max(spare, ordinary + 64)`, where `ordinary` was an
    ordinary-turn head built by the SAME code under test — and while the widening was firing on every turn,
    that comparator was inflated by the same ~650 tokens as the thing it was measuring. It could not fail.
    It is now measured against the window and against a written-down ceiling, neither of which moves when
    the code under test regresses.
    """
    from services.context.context_manager import token_estimate
    from services.prompts import system_head_builder as SHB

    prose = (
        "I have been working through the retrieval layer this morning and the ranking still looks wrong "
        "for short queries, so I want to walk through how the scores are combined. "
    ) * 6
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": prose} for i in range(40)]

    heads = {}
    for turns in (0, 6, 12, 24):
        heads[turns] = token_estimate(
            _drive_head("what can you do?", monkeypatch, convo_turns=turns, _aspect=_real_morrigan(),
                        completion_max_tokens=320, _hist=history)
        )
        # Fixed ceiling, not a sibling measurement. Catches the pre-reorder 1718-token capability head.
        assert heads[turns] <= _CAPABILITY_HEAD_CEILING_TOK, (
            f"capability head is {heads[turns]} tok with {turns} conversation turns, over the "
            f"{_CAPABILITY_HEAD_CEILING_TOK}-token ceiling"
        )
        cfg = {"convo_turns": turns, "completion_max_tokens": 320}
        spare = 2048 - SHB._reply_reserve_tokens(cfg) - SHB._convo_block_tokens(cfg, history)
        if spare >= _CAPABILITY_HEAD_CEILING_TOK:
            # Only assert against the window where the window can actually accommodate a manifest turn.
            # It cannot at every depth, and that is a MEASURED STRUCTURAL LIMIT rather than something this
            # test should pretend away: the head has a hard floor of ~1340 tokens on a capability turn
            # (a 1024-token minimum window plus the ~320-token output-discipline footer appended after
            # assembly), so once the capped conversation block passes ~380 tokens — about 6 turns of long
            # messages — a capability question on a 2048-token context does not fit and llama.cpp drops
            # the oldest tokens. build_system_head logs this at debug. Fixing it means either raising
            # n_ctx or shrinking the footer; neither belongs in this test, and asserting a bound the code
            # cannot meet would only make this test lie in the other direction.
            assert heads[turns] <= spare, (
                f"capability head is {heads[turns]} tok with {turns} conversation turns — past the "
                f"{spare} tokens the window can spare, even though it had room. The head is not backing off."
            )

    assert heads[0] > heads[12], (
        "the head did not shrink as the conversation grew — the widening is unconditional, which is the "
        "shape of a context overflow waiting for a long enough chat"
    )


def test_every_broken_disclosure_survives_with_the_REAL_aspect(monkeypatch):
    """The guard for the failure that every other test in this file was blind to.

    `_drive_head` passes `aspect={"id": "morrigan", "name": "Morrigan"}` — a hand-built dict with no
    `systemPromptAddition`. The real one, loaded from personalities/morrigan.json by select_aspect, carries a
    590-token voice contract. That is the difference between a persona that costs ~50 tokens and one that
    costs ~640, and it decided whether the manifest fit.

    Driven with the real aspect, the manifest was cut after "200 working tools": every positive capability
    claim survived and the ENTIRE "BROKEN — never offer these" section was gone. That is the one outcome
    worse than injecting nothing — she would list her capabilities with total confidence and not one of the
    caveats, which is precisely the authoritative lying this whole file exists to prevent.

    So this test asserts on the disclosures specifically, and uses the aspect the product actually uses.
    """
    import orchestrator

    goal = "what can you do?"
    aspect = orchestrator.select_aspect(goal, force_aspect="morrigan")
    assert (aspect.get("systemPromptAddition") or "").strip(), (
        "the real Morrigan persona has no systemPromptAddition — this test is no longer exercising the "
        "large-persona case it exists for"
    )

    for language in (None, "spanish"):
        head = _drive_head(goal, monkeypatch, _aspect=aspect,
                           **({"response_language": language} if language else {}))
        for needle in (
            "BROKEN — never offer these",
            "I CANNOT speak or listen",
            "Encryption-at-rest never fires",
            "LAN peer offload moves no work",
            "does NOT block the network",
            "approval gate is the real protection",
        ):
            assert needle in head, (
                f"disclosure {needle!r} did not survive with the real persona (language={language}). The "
                f"manifest is being truncated into its positive claims only — worse than not injecting it."
            )
        # …and the user's actual question must still be there, whole. It is ~11 tokens and it is the
        # single most important thing in the prompt; the manifest yields its tail before the goal yields.
        assert goal in head, "the user's question was truncated to make room for the manifest"


def test_aspect_behaviour_directive_reaches_the_prompt(monkeypatch):
    """Another of the seven. test_system_head_builder's pressure-branch test proves these survive a REBUILD,
    but it disables the budget assembler outright — so it never proved they survive the BUDGET, which is
    what was actually eating them."""
    head = _drive_head("explain python decorators in detail", monkeypatch)
    assert "Tool bias for this aspect" in head, (
        "the aspect-behaviour block is still being appended to the tail and truncated away"
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


# --- R5: the two halves must COMPOSE ---------------------------------------------------------------
# The language directive and the capability manifest were built in the same phase and never tested
# together across languages. `_CAP_Q_RE` was ASCII/English-only, so setting Spanish and asking
# "¿qué puedes hacer?" produced the worst available outcome: she answers a question about herself,
# fluently, in the operator's own language, entirely from invention — while holding a verified answer
# she was never shown.
CAPABILITY_QUESTIONS_I18N = [
    ("spanish", "¿qué puedes hacer?"),
    ("spanish", "cuáles son tus capacidades"),
    ("portuguese", "o que você pode fazer?"),
    ("french", "que peux-tu faire ?"),
    ("french", "quelles sont tes capacités"),
    ("german", "was kannst du tun?"),
    ("german", "deine Fähigkeiten"),
    ("italian", "cosa puoi fare?"),
    ("dutch", "wat kun je doen?"),
    ("japanese", "何ができますか"),
    ("mandarin", "你能做什么"),
    ("arabic", "ماذا يمكنك أن تفعل"),
]

# English phrasings measured as MISSED on 2026-07-19 — each one a real way a user asks this.
CAPABILITY_QUESTIONS_MISSED = [
    "what can you help me with?",
    "what can u do",
    "do you have voice?",
    "do you have internet access",
    "what tools do you have",
    "what tools can you use",
    "how do i use your memory",
    "how do i enable voice",
]

# IDENTITY questions. These were in the list above until it was measured what that cost: "who are you?"
# took the capability path, which trims the persona to anchor+voice, so the turn went 828 -> 1551 tokens
# AND dropped the "## Core" block ("You are Morrigan — Layla's blade...") that is the actual answer.
# They are a separate intent now, answered from the persona. See _IDENTITY_Q_RE in prompt_builder.
IDENTITY_QUESTIONS = [
    "who are you?",
    "who are you",
    "tell me about yourself",
    "what are you?",
    "introduce yourself",
]

# Near-misses that share a PREFIX with a capability question but are ordinary work. Each of these was a
# false positive when the new phrasings were first added unanchored — and a false positive here is not
# cosmetic, it bills an ordinary turn ~705 tokens on a 2048-token window.
CAPABILITY_NEAR_MISSES = [
    "who are you going to assign this to",
    "tell me about yourself-hosted deployment",
    "what can you help me with this regex for",
    "cosa puoi fare per questo bug",
    "do you have a minute",
    "do you have any thoughts on this",
    # Measured 2026-07-19: these fired on ORDINARY work and were free before the manifest existed
    # (it resolved to ""), so nothing caught them. Each measured ~1553-1559 tok against an 848 baseline.
    "how do i use argparse",
    "how do i use pytest fixtures",
    "how do i find the config file",
    "what tools did the previous run use",
    "what tools does this repo need",
    "what can you do about the memory leak in worker.py",
    "what can you do with this stack trace",
    "what can you do to speed up the build",
]


@pytest.mark.parametrize("language,question", CAPABILITY_QUESTIONS_I18N)
def test_capability_question_is_detected_in_every_supported_language(language, question):
    assert _is_capability_question(question.lower()), (
        f"{language}: {question!r} is a capability question and was not detected. The operator can set "
        f"this language in Settings, so asking what she can do IN it is the expected path, not an edge case."
    )


@pytest.mark.parametrize("question", CAPABILITY_QUESTIONS_MISSED)
def test_capability_question_covers_the_phrasings_people_actually_use(question):
    assert _is_capability_question(question.lower()), f"{question!r} must reach the manifest"


@pytest.mark.parametrize("question", CAPABILITY_NEAR_MISSES)
def test_capability_detection_does_not_fire_on_prefix_lookalikes(question):
    assert not _is_capability_question(question.lower()), (
        f"{question!r} is ordinary work that merely STARTS like a capability question. Matching it bills "
        f"~705 tokens of manifest to a turn that has no use for it."
    )


# ------------------------------------------------------------------------------------------------
# Identity is a SEPARATE intent from capability
# ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("question", IDENTITY_QUESTIONS)
def test_identity_questions_are_not_routed_down_the_capability_path(question):
    """The routing decision, asserted at the predicate."""
    from services.prompts.prompt_builder import _is_identity_question

    assert _is_identity_question(question.lower()), f"{question!r} must be recognised as an identity question"
    assert not _is_capability_question(question.lower()), (
        f"{question!r} is being treated as a capability question. That path trims the persona to "
        f"anchor+voice to make room for the manifest — so the turn most about who she is loses her "
        f"self-description and pays ~700 tokens to lose it."
    )


@pytest.mark.parametrize("question", ["who are you?", "what are you", "tell me about yourself"])
def test_the_identity_lock_survives_a_re_broadened_capability_regex(question, monkeypatch):
    """The defence-in-depth lock, driven against the regression it exists for.

    The primary fix is the identity/capability split in the patterns (asserted directly above). The
    lock is the backstop: if someone re-broadens `_CAP_Q_RE` until it swallows identity questions
    again, the persona must still survive.

    This test exists because the backstop did NOT work and nothing noticed. It was written as
    `and not _is_identity_question(...)` on the PERSONA TRIM (system_head_builder ~line 630), while the
    ~700-token manifest was injected further down gated on `_is_capability_question` ALONE. Simulating
    the regression and diffing showed lock-present and lock-removed producing BYTE-IDENTICAL heads with
    "## Core" absent from both: the manifest injection is what evicts the persona, so guarding only the
    trim guarded nothing. Seven tests passed with the lock deleted.

    So the lock now also gates the manifest injection, and this drives it end to end: with
    `_is_capability_question` forced True (the regression, exactly), an identity question must still
    keep its "## Core" block. Delete either half of the lock and this goes red.
    """
    import services.prompts.prompt_builder as PB
    from services.context.context_manager import token_estimate

    # THE REGRESSION: capability detection re-broadened to swallow identity questions.
    monkeypatch.setattr(PB, "_is_capability_question", lambda g: True)

    head = _drive_head(question, monkeypatch, _aspect=_real_morrigan())
    # Control: a REAL capability question, driven in the same process state and config. Everything
    # here is relative to it deliberately. An earlier draft asserted `"## Core" in head` absolutely;
    # that passed on the operator's config and FAILED in the gate under CI's stub config, where the
    # tighter budget can evict the persona for reasons that have nothing to do with this lock. What
    # the lock controls is whether the ~700-token manifest is injected, so that is what is measured.
    control = _drive_head("can you speak", monkeypatch, _aspect=_real_morrigan())

    assert _MANIFEST_HEAD not in head, (
        f"{question!r}: the manifest was injected on an identity turn despite the lock. This is the "
        f"~700-token block whose insertion is what evicts the persona from the budget. The lock must "
        f"gate the MANIFEST INJECTION, not only the persona trim — guarding the trim alone is "
        f"measurably a no-op (lock-present and lock-removed produced byte-identical heads)."
    )
    assert _MANIFEST_HEAD in control, (
        "the control turn did not get the manifest, so this test is not measuring the lock"
    )
    assert token_estimate(head) < token_estimate(control) - 300, (
        f"{question!r} ({token_estimate(head)} tok) costs about as much as a real capability turn "
        f"({token_estimate(control)} tok), so the manifest is still being paid for on an identity turn."
    )


@pytest.mark.parametrize("question", ["who are you?", "tell me about yourself"])
def test_identity_turn_is_budgeted_like_an_ordinary_turn_not_a_capability_turn(question, monkeypatch):
    """The consequence, measured through the real assembler with the real persona.

    RED before the split: 1551 tok, `_MANIFEST_HEAD` present, and the "## Core" block absent.

    Every assertion here is RELATIVE to controls driven in the same process state, deliberately.
    An earlier draft asserted the absolute string "Layla's blade" was present, which passed in
    isolation and FAILED in the full gate run: by then the session DB has accumulated content from
    3500 earlier tests, the memory/knowledge sections are no longer empty, and the persona prose is
    truncated on EVERY turn — ordinary ones included. That made the assertion a statement about how
    much unrelated state the suite had built up, not about routing. Comparing against controls built
    under the same pressure is what makes it measure the thing it is named after.
    """
    from services.context.context_manager import token_estimate

    aspect = _real_morrigan()
    head = _drive_head(question, monkeypatch, _aspect=aspect)
    ordinary = _drive_head("fix this bug in my python code", monkeypatch, _aspect=aspect)
    capability = _drive_head("what can you do?", monkeypatch, _aspect=aspect)
    core_marker = "Layla's blade"

    # 1. The routing fact.
    assert _MANIFEST_HEAD not in head, (
        f"{question!r} pulled the ~700-token capability manifest. Identity questions are answered from "
        f"the persona; the manifest exists for questions that invite a capability CLAIM."
    )
    assert _MANIFEST_HEAD in capability, "control failed: a real capability turn is not pulling the manifest"

    # 2. The persona is treated exactly as it is on an ordinary turn — no special trim.
    assert (core_marker in head) == (core_marker in ordinary), (
        f"{question!r} and an ordinary turn disagree about whether the persona's self-description "
        f"survives ({core_marker in head} vs {core_marker in ordinary}). An identity turn must not be "
        f"trimmed differently from any other non-capability turn."
    )

    # 3. And it costs like an ordinary turn, not like a capability turn. This is the assertion that
    #    encodes the defect: 828 -> 1551 tokens for asking her who she is.
    t_head, t_ord, t_cap = token_estimate(head), token_estimate(ordinary), token_estimate(capability)
    assert abs(t_head - t_ord) < 150, (
        f"{question!r} cost {t_head} tok against an ordinary turn's {t_ord} — it is still paying for "
        f"something it does not use."
    )
    assert t_cap - t_head > 300, (
        f"{question!r} ({t_head} tok) costs about the same as a real capability turn ({t_cap} tok), so "
        f"it is still taking the manifest path."
    )


@pytest.mark.parametrize("question", ["can you speak", "do you have internet access", "what can you do?"])
def test_real_capability_questions_still_pull_the_manifest(question, monkeypatch):
    """The other half of the split: narrowing must not have broken what the manifest is FOR."""
    head = _drive_head(question, monkeypatch, _aspect=_real_morrigan())
    assert _MANIFEST_HEAD in head, f"{question!r} no longer reaches the manifest"
    assert _MANIFEST_TAIL in head, f"{question!r} reached the manifest but it was cut before its last line"


def test_spanish_capability_question_gets_both_the_manifest_and_the_language_directive(monkeypatch):
    """The composition test, end to end through the real assembler.

    This is the exact turn R5 describes: response_language=spanish AND a Spanish capability question. It
    must produce BOTH — the directive telling her to answer in Spanish, and the verified facts to answer
    FROM. Before the i18n patterns it produced only the first, which is how you get a fluent lie.
    """
    head = _drive_head("¿qué puedes hacer?", monkeypatch, _aspect=_real_morrigan(),
                       response_language="spanish")

    assert "## Language" in head, "language directive missing on a Spanish capability turn"
    assert _MANIFEST_HEAD in head, (
        "the Spanish capability question did not trigger the manifest — she will answer a question about "
        "herself, in Spanish, from invention"
    )
    assert _MANIFEST_MIDDLE in head, "manifest present but cut before its BROKEN disclosures"
    assert _MANIFEST_TAIL in head, "manifest present but cut before its anti-recitation instruction"


def test_capability_detection_does_not_backtrack_pathologically():
    r"""The goal string is whatever the user typed, and this regex runs on EVERY turn.

    The end-anchors added for the new phrasings were first written as `\s*[?!.]*\s*$` — three adjacent
    quantifiers over classes the engine must try splitting every possible way, each split backtracking to
    a failing `$`. Measured 67 ms on "who are you" + 3000 spaces + "x". Not exponential, but quadratic on
    a hot path, and free to fix: one possessive character class (`[\s?!.]*+`, Python 3.11+) takes the run
    and never gives it back. Same measurement after: 0.6 ms.

    This test measures SCALING, not a wall clock.

    It used to assert `elapsed_ms < 50` against a 4-6 ms nominal. That is a 10x margin, and it still
    failed unprompted — 50.7 ms on an idle box, again on a cold import after a `__pycache__` purge, and
    2 of 7 runs for another operator. A wall clock on a shared CI runner measures the scheduler as much
    as the code, and a flake in a merge gate is worse than no test: it trains people to re-run until
    green, which is exactly how a real regression gets waved through.

    Catastrophic backtracking is a SCALING property — super-linear time in the input length — so that is
    what is asserted. Quadratic behaviour (the measured defect: 67 ms at 3k, growing with the square)
    shows up as a 16x jump when the input quadruples; linear shows up as 4x. The threshold sits between
    them, and each timing is a best-of-N so a scheduler hiccup inflates a sample rather than the verdict.
    """
    import time

    # (label, builder) — builder(n) produces an input whose backtracking-relevant run is n chars.
    cases = [
        ("what can <n spaces> you do", lambda n: "what can" + " " * n + "you do"),
        ("who are you <n spaces> x", lambda n: "who are you" + " " * n + "x"),
        ("what can you help me with <n ?>", lambda n: "what can you help me with" + "?" * n),
        ("cosa puoi fare <n ' ?'>", lambda n: "cosa puoi fare" + " ?" * n),
        ("'do you have a ' * n", lambda n: "do you have a " * n),
        ("¿qué puedes hacer <n spaces>?", lambda n: "¿qué puedes hacer" + " " * n + "?"),
    ]

    SMALL, LARGE = 5_000, 20_000          # 4x the input
    GROWTH_LIMIT = 8.0                    # linear=4x, quadratic=16x -> threshold between them
    ABSOLUTE_CEILING_S = 2.0              # ~300x the nominal: catches exponential without flaking

    def best_of(fn, rounds=5):
        """Minimum of N runs. The minimum is the sample least contaminated by preemption — a mean or a
        single sample is what made the old assertion a coin flip on a loaded runner."""
        best = float("inf")
        for _ in range(rounds):
            t0 = time.perf_counter()
            fn()
            best = min(best, time.perf_counter() - t0)
        return best

    for label, build in cases:
        small = build(SMALL).lower()
        large = build(LARGE).lower()

        t_small = best_of(lambda s=small: _is_capability_question(s))
        t_large = best_of(lambda s=large: _is_capability_question(s))

        assert t_large < ABSOLUTE_CEILING_S, (
            f"{label}: capability detection took {t_large*1000:.0f} ms on a {len(large)}-char input. "
            f"That is not a slow machine, that is a runaway pattern."
        )

        # Floor the denominator: at a few microseconds the ratio measures timer granularity, not the
        # regex. Below the floor the absolute ceiling above is the only meaningful check, and it passed.
        if t_small < 200e-6:
            continue

        growth = t_large / t_small
        assert growth < GROWTH_LIMIT, (
            f"{label}: 4x the input cost {growth:.1f}x the time "
            f"({t_small*1000:.2f} ms -> {t_large*1000:.2f} ms). Linear is ~4x; this is super-linear, "
            f"which means the anchors are backtracking. Keep the tail as a single possessive class "
            f"(`[\\s?!.]*+`), never `\\s*[?!.]*\\s*$`."
        )


def test_capability_anchors_are_written_possessively():
    r"""The FORM of the anchors, asserted directly.

    `test_capability_detection_does_not_backtrack_pathologically` above cannot catch the regression it
    is named for, and this is not a tuning problem — it is blind BY CONSTRUCTION. Reverting all 8 sites
    from `[\s?!.]*+$` to `\s*[?!.]*\s*$` produces a ~9x CONSTANT-FACTOR slowdown that still scales
    LINEARLY on these inputs. A growth-ratio assertion divides the constant factor out: 4x the input
    still costs ~4x the time, so the ratio test stays green while the hot path got 9x slower. Measured:
    all 8 sites reverted -> that test passes, and the only thing standing between the regression and a
    merge is the 2.0 s absolute ceiling against a ~2042 ms worst case. A 2% margin is not a guard.

    So this pins the property directly rather than a proxy for it. A possessive quantifier is a
    STRUCTURAL fact about the pattern; it does not need a stopwatch, cannot flake, and does not care
    how fast the machine is.

    Kept alongside the scaling test rather than replacing it: this one catches the known regression
    shape, that one catches a NEW pattern whose blow-up nobody predicted.
    """
    import re as _re

    from services.prompts.prompt_builder import (
        _CAP_Q_I18N_RE,
        _CAP_Q_RE,
        _IDENTITY_Q_RE,
    )

    patterns = {
        "_CAP_Q_RE": _CAP_Q_RE.pattern,
        "_IDENTITY_Q_RE": _IDENTITY_Q_RE.pattern,
        "_CAP_Q_I18N_RE": _CAP_Q_I18N_RE.pattern,
    }

    anchors_seen = 0
    for name, pat in patterns.items():
        assert r"\s*[?!.]*\s*$" not in pat, (
            f"{name} contains the exact reverted tail `\\s*[?!.]*\\s*$` — three adjacent quantifiers "
            f"the engine must try splitting every way, each split backtracking to a failing `$`."
        )

        # Every end-anchor must be taken possessively. `[\s?!.]*+$` -> the two characters before `$`
        # are `*+`; any greedy/lazy quantifier there is a backtracking invitation.
        for m in _re.finditer(r"\$", pat):
            anchors_seen += 1
            preceding = pat[max(0, m.start() - 2):m.start()]
            assert preceding == "*+", (
                f"{name}: the `$` at offset {m.start()} is preceded by {preceding!r}, not a possessive "
                f"quantifier. Context: ...{pat[max(0, m.start() - 30):m.start() + 1]!r}\n"
                f"End-anchored alternations must take their tail as ONE possessive class "
                f"(`[\\s?!.]*+$`). Greedy quantifiers before `$` are what made this quadratic."
            )

    # Guard the guard: if the anchors are ever deleted wholesale the loop above passes vacuously.
    assert anchors_seen >= 8, (
        f"expected at least 8 end-anchored capability/identity alternations, found {anchors_seen}. "
        f"Either the anchors were removed (which un-narrows the patterns — see the tests about "
        f"'what can you help me with this regex for') or this guard is looking at the wrong module."
    )
