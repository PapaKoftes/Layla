"""Logic-level guards for the transcript bugs: answer+refuse, tool-limit dead-end, persona recital.

1. [REFUSED:] priming — every aspect ships can_refuse:true, so gating the marker instruction on
   can_refuse injected it on EVERY turn and a small model pattern-completed it (answered, then
   appended "REFUSED: too broad"). Only a will_refuse gatekeeper (Lilith) may see the marker.
2. tool_limit must end with an ANSWER — the loop used to break straight out and the router
   surfaced "Stopped after maximum tool calls" even when gathered context could answer.
3. Persona recital — the full persona prose injected on a phatic turn gets recited back
   ("I am but a voice in the wind…"); phatic turns get anchor + one-line voice only.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ── 1. REFUSED marker only for the will_refuse gatekeeper ────────────────────

def _aspect(aid):
    import orchestrator
    return orchestrator.select_aspect("", force_aspect=aid)


def test_standard_prompt_no_refused_marker_for_non_gatekeepers():
    import orchestrator
    for aid in ("morrigan", "nyx", "echo", "eris", "cassandra"):
        p = orchestrator.build_standard_prompt(message="what is 2+2?", aspect=_aspect(aid))
        assert "[REFUSED" not in p, f"{aid} (can_refuse but not will_refuse) must not be taught the marker"


def test_standard_prompt_refused_marker_for_lilith_only():
    import orchestrator
    p = orchestrator.build_standard_prompt(message="what is 2+2?", aspect=_aspect("lilith"))
    assert "[REFUSED" in p  # the actual gatekeeper keeps her refusal channel


def test_deliberation_conclusion_refusal_gated_on_will_refuse():
    import orchestrator
    p_m = orchestrator.build_deliberation_prompt(message="q", active_aspect=_aspect("morrigan"))
    assert "If you must refuse" not in p_m
    p_l = orchestrator.build_deliberation_prompt(message="q", active_aspect=_aspect("lilith"))
    assert "If you must refuse" in p_l


# ── 2. tool_limit forces a wrap-up answer ────────────────────────────────────

def test_tool_limit_branch_invokes_wrapup_reasoning():
    # Structural guard: the cap branch must call handle_reasoning_intent before breaking,
    # and must instruct a no-more-tools synthesis. (Full loop execution needs a live model;
    # this pins the control flow so the dead-end can't silently come back.)
    src = (AGENT_DIR / "services" / "agent" / "decision_loop.py").read_text(encoding="utf-8")
    cap = src.split('state["status"] = "tool_limit"', 1)[1].split("break", 1)[0]
    assert "handle_reasoning_intent" in cap
    assert "Tool budget exhausted" in cap
    assert 'state.get("response")' in cap  # only when no answer exists yet


# ── 3. Phatic turns don't inject the recitable persona prose ─────────────────

def test_phatic_turn_gets_voice_line_not_persona_prose():
    import orchestrator
    from services.prompts.system_head_builder import build_system_head
    asp = orchestrator.select_aspect("hi", force_aspect="morrigan")
    head = build_system_head(goal="hi", aspect=asp, reasoning_mode="light")
    # the literary material a small model recites must be absent on a greeting …
    for marker in ("Tropes:", "Archetype:", "Speech patterns:"):
        assert marker not in head, marker
    # … but she still knows who she is and how she sounds
    assert "Morrigan" in head
    assert "Voice:" in head


def test_substantive_turn_keeps_persona_anchor_under_budget():
    # THE regression this guards: on the small-window tier the whole SYSTEM section (identity +
    # persona) silently vanished on substantive turns — the assembler reserved downstream
    # sections' full nominal budgets (400 tok for a 25-tok agent_state) leaving SYSTEM ~12
    # tokens, and the truncate retry went negative → empty → skipped uncounted. The model never
    # saw who it was and improvised theatrically. Anchor + goal must ALWAYS survive assembly.
    import orchestrator
    from services.prompts.system_head_builder import build_system_head
    asp = orchestrator.select_aspect("refactor this module for me", force_aspect="morrigan")
    head = build_system_head(goal="refactor this module for me", aspect=asp, reasoning_mode="deep")
    assert "## SYSTEM" in head
    assert "Reply as her only" in head          # the aspect anchor survives
    assert "refactor this module for me" in head  # the goal survives whole


def test_full_persona_present_unbudgeted(monkeypatch):
    # With no budget pressure the full persona (style card) must be in the head.
    import runtime_safety
    _orig = runtime_safety.load_config
    monkeypatch.setattr(runtime_safety, "load_config",
                        lambda: {**_orig(), "prompt_budget_enabled": False})
    import orchestrator
    from services.prompts.system_head_builder import build_system_head
    asp = orchestrator.select_aspect("refactor this module for me", force_aspect="morrigan")
    head = build_system_head(goal="refactor this module for me", aspect=asp, reasoning_mode="deep")
    assert "Traits:" in head or "Archetype:" in head


def test_discipline_forbids_persona_recital():
    from services.prompts import system_head_builder as shb
    head = shb._append_output_discipline("X", {})
    assert "never quote, recite, or perform" in head.lower() or "never \nquote" in head.lower()


# ── 4. Tool-cap misfire: guard REJECTIONS accrue to blocked_calls, not tool_calls ──
#
# THE bug the operator caught ("stopping cause too many tool calls on such a simple request …
# it's hitting on one tool call"): every guard/policy REJECTION did `state["tool_calls"] += 1`
# even though NO tool executed. So a handful of disallowed / looped / duplicate / bad-arg tool
# picks on a trivial turn exhausted the real work budget (cap ~5) and tripped "max tool calls"
# with zero work done. Rejections now accrue to a SEPARATE, generously-bounded counter.

def _reject_once(state):
    """Drive one guard rejection (tool_policy_denied) in full isolation — no model, no config."""
    from services.agent.tool_guards import run_tool_guards
    return run_tool_guards(
        intent="read_file",
        decision={"tool": "read_file", "args": {}},
        state=state,
        cfg={"decision_policy_enabled": False},
        goal=state["original_goal"],
        workspace="",
        context="",
        get_tools_for_goal_fn=lambda *a, **k: frozenset(),   # nothing allowed → policy denies
        log_tool_outcome_fn=lambda *a, **k: None,
        format_steps_fn=lambda steps: "",
        valid_tools=frozenset({"read_file"}),
    )


def test_guard_rejection_increments_blocked_calls_not_tool_calls():
    state = {"original_goal": "what is 2+2?", "steps": [], "tool_calls": 0}
    blocked, _goal = _reject_once(state)
    assert blocked is True
    assert state["tool_calls"] == 0            # real tool-EXECUTION budget untouched
    assert state["blocked_calls"] == 1         # rejection counted on its own ledger
    assert state["steps"][-1]["result"]["reason"] == "tool_policy_denied"


def test_many_rejections_never_exhaust_the_real_tool_budget():
    # 20 rejected decisions in a row: the real budget (cap ~5) must stay pristine so the turn
    # can still do — and finish — actual work instead of dead-ending on "max tool calls".
    state = {"original_goal": "hi", "steps": [], "tool_calls": 0}
    for _ in range(20):
        _reject_once(state)
    assert state["tool_calls"] == 0
    assert state["blocked_calls"] == 20


def test_tool_guards_never_touch_the_real_tool_budget():
    # Every path in tool_guards is a rejection (nothing runs) → it must only ever move
    # blocked_calls. A stray `tool_calls += 1` here is the misfire creeping back.
    src = (AGENT_DIR / "services" / "agent" / "tool_guards.py").read_text(encoding="utf-8")
    assert 'tool_calls"] += 1' not in src
    assert 'blocked_calls"]' in src


def test_blocked_calls_backstop_guards_the_tool_limit_branch():
    # Rejections no longer bound the loop via the tool budget, so a SEPARATE generous backstop
    # must still force the wrap-up answer if the model gets stuck proposing rejected tools.
    # Pin it: the tool_limit branch fires on the real cap OR a blocked_calls overflow.
    src = (AGENT_DIR / "services" / "agent" / "decision_loop.py").read_text(encoding="utf-8")
    seg = src.split("_blocked_cap = ", 1)[1].split('state["status"] = "tool_limit"', 1)[0]
    assert "max_tool_calls_effective" in seg          # condition 1: real budget spent
    assert 'state.get("blocked_calls"' in seg          # condition 2: rejection backstop
