"""Maturity rank does not gate features — and removing the gate granted nothing.

DESIGN CORRECTION, NOT A BUG FIX. `runtime_safety._apply_maturity_gates` ran inside
`load_config()` over the MERGED config, forcing six capability flags False below a rank. Because
it ran inside the loader, no operator action could defeat it: not the settings API, not the setup
wizard, not hand-editing runtime_config.json. Rank was only ever meant to be a visual indicator of
how much Layla has learned about the operator, so the overlay is deleted and the six keys are
ordinary settings.

THE SAFETY PROPERTY IS THE POINT OF THIS FILE. Deleting a gate must not enable anything. The
argument is structural: every one of these keys defaults to False in `load_config`'s `defaults`,
and the overlay only ever WROTE False (never True), so its removal cannot flip a key on for a
config that did not ask — it can only stop overriding a config that did. `test_removing_the_gate_
granted_nothing` drives that end to end rather than trusting the argument, by diffing the full
effective config of a never-asked config against an explicit all-False baseline.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]

# The random leaf `tempfile.TemporaryDirectory(prefix="layla-gate-")` appends (lowercase letters,
# digits, underscore — never a path separator). Normalising it to a constant makes two scenarios'
# temp-derived paths compare equal regardless of how load_config spelled them (resolve/slash/case).
_GATE_TOKEN = re.compile(r"layla-gate-[0-9A-Za-z_]+")

# The six keys the overlay owned. Listed literally, on purpose: the registry that used to hold
# them is deleted, and a test that reads its subject from the code under test cannot notice the
# subject going missing.
FORMERLY_GATED = (
    "inline_initiative_enabled",
    "initiative_engine_enabled",
    "autonomous_research_mode",
    "autonomous_mode",
    "initiative_project_proposals_enabled",
    "autonomy_optimizer_enabled",
)

# Of those six, the ones that a code path outside runtime_safety/config_schema actually READS.
# `autonomous_research_mode` is excluded and that exclusion is load-bearing — see
# `test_the_inert_key_did_not_get_a_fake_switch`.
LIVE_KEYS = (
    "inline_initiative_enabled",
    "initiative_engine_enabled",
    "autonomous_mode",
    "initiative_project_proposals_enabled",
    "autonomy_optimizer_enabled",
)

# Runs load_config() in a child process against an isolated LAYLA_DATA_DIR, so the operator's real
# runtime_config.json is never read or written and module-level config caching cannot leak between
# scenarios.
_CHILD = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
import runtime_safety as rs
rs._config_cache = None
rs._config_mtime = None
cfg = rs.load_config()
out = {}
for k, v in cfg.items():
    try:
        json.dumps(v)
        out[k] = v
    except Exception:
        out[k] = "<UNSERIALIZABLE>"
print("@@@" + json.dumps(out))
"""


def _effective_config(seed: dict) -> dict:
    """The full effective config load_config() produces for `seed`, in a throwaway data dir."""
    with tempfile.TemporaryDirectory(prefix="layla-gate-") as td:
        d = Path(td)
        (d / "runtime_config.json").write_text(json.dumps(seed), encoding="utf-8")
        child = d / "child.py"
        child.write_text(_CHILD, encoding="utf-8")
        env = dict(os.environ)
        env["LAYLA_DATA_DIR"] = str(d)
        env["LAYLA_TEST_MODE"] = "1"
        p = subprocess.run(
            [sys.executable, str(child), str(AGENT_DIR)],
            env=env, cwd=str(AGENT_DIR), capture_output=True, text=True, timeout=300,
        )
        hits = [ln for ln in p.stdout.splitlines() if ln.startswith("@@@")]
        if not hits:
            pytest.fail("load_config() child failed:\n%s\n%s" % (p.stdout[-2000:], p.stderr[-2000:]))
        cfg = json.loads(hits[-1][3:])
        # Values derived from the throwaway data dir are harness artifacts, not config differences,
        # and the two scenarios use DIFFERENT throwaway dirs — so any path under one is a false diff
        # against the other. The old `str(d) in v` substring drop MISSED models_dir in CI: load_config
        # stores it in a resolved / forward-slash form that is not a literal substring of str(d) (the
        # classic Windows resolve()/separator mismatch), so the false diff survived and reddened the
        # suite. The two dirs differ ONLY in their random `layla-gate-XXXX` leaf, so normalising that
        # one token to a constant neutralises every temp-derived path at once, immune to how the path
        # was spelled — while a genuine grant landing on a non-path key still shows in the diff.
        return {k: (_GATE_TOKEN.sub("layla-gate-X", v) if isinstance(v, str) else v)
                for k, v in cfg.items()}


# ── the safety property ─────────────────────────────────────────────────────────

def test_removing_the_gate_granted_nothing():
    """A config that never asked for these capabilities must not acquire one.

    THE FULL effective dict is diffed, not just the six keys, because a silent grant that landed
    on some seventh key an autonomy flag feeds would pass a six-key assertion.
    """
    never_asked = _effective_config({})
    explicitly_off = _effective_config({k: False for k in FORMERLY_GATED})

    diff = {k: (explicitly_off.get(k, "<ABSENT>"), never_asked.get(k, "<ABSENT>"))
            for k in set(never_asked) | set(explicitly_off)
            if never_asked.get(k, "<ABSENT>") != explicitly_off.get(k, "<ABSENT>")}
    assert not diff, (
        "a config that never mentioned these keys differs from one that set them all False:\n"
        + "\n".join(f"  {k}: explicitly-off={o!r} never-asked={n!r}" for k, (o, n) in diff.items())
    )
    for key in FORMERLY_GATED:
        assert never_asked.get(key) is False, (
            f"'{key}' is {never_asked.get(key)!r} on a config that never asked for it. Removing "
            "the rank gate has silently granted a capability — that is the one outcome this "
            "change was not allowed to have."
        )


def test_a_config_that_asks_is_no_longer_overridden():
    """The positive half. Without this, "nothing changed" would pass by doing nothing at all."""
    asked = _effective_config({k: True for k in LIVE_KEYS})
    for key in LIVE_KEYS:
        assert asked.get(key) is True, (
            f"'{key}' was set True in runtime_config.json and load_config() returned "
            f"{asked.get(key)!r}. Something is still overriding the operator."
        )


def test_the_gate_is_gone_by_name():
    """Behavioural tests alone would pass against a gate reintroduced at a rank the box exceeds."""
    import runtime_safety as rs

    for gone in ("MATURITY_GATED_KEYS", "_apply_maturity_gates", "current_maturity_rank"):
        assert not hasattr(rs, gone), f"runtime_safety.{gone} is back"

    # A source scan too, so a gate rebuilt under a new name is still caught. Scoped to the SHAPES
    # a rank gate needs — reading the rank, or importing the engine that knows it — because the
    # bare word "maturity" legitimately appears here: `maturity_enabled` is the XP system's own
    # on/off switch, which is not a gate over anything and stays.
    src = (AGENT_DIR / "runtime_safety.py").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#") and '"""' not in ln)
    for shape in ("maturity_engine", "get_state(", ".rank", "_RANK_UNLOCKS"):
        assert shape not in body, (
            f"runtime_safety has live code using {shape!r}. Config loading must not consult the "
            "maturity rank at all — rank is a familiarity display, not a capability gate."
        )


# ── the gate did not simply move one file over ──────────────────────────────────
# THE ABOVE TEST SCANS ONE FILE, AND THAT WAS THE HOLE. When `_apply_maturity_gates` was deleted
# from runtime_safety.py, `maturity_engine.get_trust_tier` still ended in `rank >= 6 -> tier 2`
# and three live consumers still demanded a tier, so 151 tests passed while this file's headline
# claim ("Maturity rank does not gate features") was false. A scan that only ever looks where the
# gate used to be cannot notice it being rebuilt next door.

def test_the_trust_tier_does_not_read_rank():
    """`get_trust_tier` is the place the gate moved to. It must not consult rank/XP/phase."""
    import inspect

    from services.personality import maturity_engine as me

    body = "\n".join(
        ln for ln in inspect.getsource(me.get_trust_tier).splitlines()
        if not ln.lstrip().startswith("#")
    )
    body = body.split('"""')[0] + body.split('"""')[-1]  # drop the docstring, which discusses rank
    for shape in ("get_state(", ".rank", ".phase", ".xp", "phase_for_rank"):
        assert shape not in body, (
            f"get_trust_tier has live code using {shape!r}. The autonomy ceiling must come from "
            "the operator's own setting, never from an activity counter."
        )


@pytest.mark.parametrize("rank", [0, 2, 5, 6, 99])
def test_rank_does_not_change_the_trust_tier(rank, monkeypatch):
    """Driven across the whole ladder, including the rank 2/6 boundary the old branch turned on."""
    import layla.memory.db as db
    from services.personality import maturity_engine as me

    monkeypatch.setattr(me, "get_state", lambda: me.MaturityState(xp=0, rank=rank, phase="awakening"))
    # Patched at its source: get_trust_tier imports it inside the function body.
    monkeypatch.setattr(db, "get_user_identity", lambda *a, **k: None)
    tier = me.get_trust_tier({"autonomy_trust_tiers_enabled": True})
    assert tier == me.MAX_TRUST_TIER, (
        f"rank {rank} produced tier {tier}. Rank is an activity odometer; a capability ceiling "
        "derived from it is the gate this file says does not exist."
    )


def test_a_blank_ceiling_is_unset_not_zero():
    """user_profile stores "" for a cleared row, and "" used to clamp to tier 0 — the most
    restrictive value available — silently pinning every consumer shut."""
    from services.personality import maturity_engine as me

    for blank in ("", "   ", None):
        tier = me.get_trust_tier({"autonomy_trust_tiers_enabled": True, "trust_tier_override": blank})
        assert tier == me.MAX_TRUST_TIER, f"a blank ceiling {blank!r} read as tier {tier}"


def test_the_ceiling_is_reachable():
    """The escape hatch the rank gate never had. Neither key was in ANY writable registry, so no
    sequence of in-app actions could clear the tier — which is what made it a lock."""
    from install.feature_status import writable_config_keys

    writable = writable_config_keys()
    for key in ("trust_tier_override", "autonomy_trust_tiers_enabled"):
        assert key in writable, (
            f"'{key}' cannot be set by any settings schema, wizard flag or theme. A restriction "
            "the operator cannot reach is a lock, however it is spelled."
        )


def test_the_phase_predicates_gate_nothing():
    """`phase` is `phase_for_rank(rank)`, so a phase test IS a rank test wearing a hat.

    Two live sites used these: reasoning_handler suppressed inline initiative below "resonance"
    (rank 6) even with `inline_initiative_enabled` on — which this operator has on — and
    llm_decision keyed observation mode on the early phases. Both are gone; the predicates
    survive only for display/narrative. Scans the tree so a third site cannot appear quietly.
    """
    # PARSE, DO NOT GREP. Two independent reasons, both of which bit this test in its first form:
    #
    # 1. It used `git grep`, which searches TRACKED files only. familiarity.py was untracked when
    #    the gate ran before its own commit, so the scan could not see it, the gate went green,
    #    and the slice shipped. The failure appeared on the next run for reasons unrelated to that
    #    run's diff. A guard whose coverage depends on staging state is not a guard.
    # 2. It filtered prose by `startswith("#")`, which misses DOCSTRINGS. `knows_operator`'s
    #    docstring explains that observation mode used to ask `is_early_phase(maturity.phase)` —
    #    a sentence describing the removed gate was read as the gate. That is the same mistake as
    #    forbidding a guard from naming the defect it prevents: it pushes the reasoning out of the
    #    file.
    #
    # An AST walk answers the real question — is either predicate CALLED? — and prose cannot fake
    # a Call node.
    import ast

    offenders = []
    for path in sorted((AGENT_DIR).rglob("*.py")):
        rel = path.relative_to(AGENT_DIR).as_posix()
        if rel.startswith("tests/") or "maturity_engine.py" in rel:  # the latter defines them
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name in ("is_high_trust_phase", "is_early_phase"):
                offenders.append(f"{rel}:{node.lineno}: calls {name}()")
    assert not offenders, (
        "a capability decision is being derived from maturity phase again:\n  "
        + "\n  ".join(offenders)
        + "\nPhase comes from rank. If the behaviour needs a guard it must be a SETTING; if it "
        "needs to know the operator, read services.personality.familiarity."
    )


# ── R2: the keys are settable, and honestly described ───────────────────────────

def test_every_live_key_has_a_writer():
    from install.feature_status import writable_config_keys

    writable = writable_config_keys()
    missing = [k for k in LIVE_KEYS if k not in writable]
    assert not missing, (
        f"{missing} cannot be set by any settings schema, wizard flag or theme. A feature the "
        "operator cannot ask for is not gated, it is absent."
    )


def test_the_inert_key_did_not_get_a_fake_switch():
    """`autonomous_research_mode` has a default and had a rank-3 gate, and NOTHING reads it.

    Giving it a settings switch would replace a fake gate with a fake control. maturity_engine
    already dropped its matching unlock row for the same reason. This test fails in BOTH
    directions: if a reader is ever wired up, it will start demanding the switch.
    """
    from config_schema import EDITABLE_SCHEMA

    key = "autonomous_research_mode"
    readers = subprocess.run(
        ["git", "grep", "-l", key, "--", "*.py", "*.js", "*.html"],
        cwd=str(AGENT_DIR.parent), capture_output=True, text=True,
    ).stdout.split()
    real = [f for f in readers
            if "/tests/" not in f and not f.endswith(("runtime_safety.py", "config_schema.py",
                                                     "feature_status.py", "maturity_engine.py"))]
    in_schema = key in {e["key"] for e in EDITABLE_SCHEMA}
    if real:
        assert in_schema, (
            f"'{key}' is now read by {real} — it does something, so it needs a switch in "
            "EDITABLE_SCHEMA."
        )
    else:
        assert not in_schema, (
            f"'{key}' has a settings switch but nothing in the repo reads it. A control that "
            "changes nothing is the same defect as a gate that cannot be cleared."
        )


@pytest.mark.parametrize("key,must_say", [
    ("autonomous_mode", "POWERFUL"),
    ("autonomy_optimizer_enabled", "POWERFUL"),
])
def test_the_powerful_keys_state_the_risk_plainly(key, must_say):
    """The operator owns this machine and asked for the choice — so label it, do not hide it."""
    from config_schema import EDITABLE_SCHEMA

    entry = next((e for e in EDITABLE_SCHEMA if e["key"] == key), None)
    assert entry, f"'{key}' is not in EDITABLE_SCHEMA"
    assert entry["default"] is False, f"'{key}' must ship off"
    assert must_say in entry["hint"], (
        f"'{key}' is a genuinely powerful capability and its description does not say so:\n"
        f"  {entry['hint']}"
    )


def test_no_settings_hint_promises_a_rank_unlock():
    """Sweeps the whole schema: no leftover copy may tell an operator to go level up."""
    from config_schema import EDITABLE_SCHEMA

    guilty = [e["key"] for e in EDITABLE_SCHEMA
              if any(p in (e.get("hint") or "").lower()
                     for p in ("maturity rank", "unlocks at rank", "level up", "rank 5", "rank 10"))]
    assert not guilty, f"these settings still describe rank as gating them: {guilty}"


# ── the switch does the thing, at every rank ────────────────────────────────────
# ASSERTING ON RETURN VALUES IS NOT ENOUGH HERE: generate_project_proposals returns [] both when
# the tier blocks it and when the LLM call fails, which is always in a test. So a SENTINEL
# replaces load_project_memory and "the body ran" is recorded by the body itself.

@pytest.fixture()
def _reached(monkeypatch):
    import services.memory.project_memory as pm

    seen: list[str] = []
    monkeypatch.setattr(pm, "load_project_memory", lambda ws: seen.append(str(ws)) or {})
    return seen


@pytest.mark.parametrize("rank", [0, 2, 6, 99])
def test_project_proposals_run_at_every_rank_when_asked(rank, _reached, monkeypatch):
    """The operator's switch, honoured. At rank 2 this returned before touching anything."""
    from services.infrastructure import initiative_engine as ie
    from services.personality import maturity_engine as me

    monkeypatch.setattr(me, "get_state", lambda: me.MaturityState(xp=0, rank=rank, phase="awakening"))
    ie.generate_project_proposals(cfg={"initiative_project_proposals_enabled": True})
    assert _reached, (
        f"rank {rank}: the switch is on and the capability never ran. A setting the operator can "
        "turn on must not be held shut by an activity counter."
    )


@pytest.mark.parametrize("rank", [0, 2, 6, 99])
def test_project_proposals_stay_off_when_not_asked(rank, _reached, monkeypatch):
    """The safety half: removing a gate must not enable anything."""
    from services.infrastructure import initiative_engine as ie
    from services.personality import maturity_engine as me

    monkeypatch.setattr(me, "get_state", lambda: me.MaturityState(xp=0, rank=rank, phase="awakening"))
    ie.generate_project_proposals(cfg={})
    assert not _reached, f"rank {rank}: a capability ran for a config that never asked for it"


def test_the_scheduled_path_actually_reaches_the_engine(_reached, monkeypatch):
    """_bg_initiative called generate_project_proposals() with NO cfg, and the callee reads a
    missing cfg as {} — so its own flag check saw False and it returned before doing anything,
    every single run. The background half of this setting was inert regardless of the gate."""
    import runtime_safety as rs
    from layla.scheduler import jobs

    monkeypatch.setattr(rs, "load_config", lambda *a, **k: {"initiative_project_proposals_enabled": True})
    jobs._bg_initiative()
    assert _reached, (
        "the scheduled job did not reach the engine. This setting's hint promises scheduled "
        "maintenance drafts proposals; if the job cannot, the hint is false."
    )


def test_the_scheduled_path_respects_the_switch(_reached, monkeypatch):
    import runtime_safety as rs
    from layla.scheduler import jobs

    monkeypatch.setattr(rs, "load_config", lambda *a, **k: {"initiative_project_proposals_enabled": False})
    jobs._bg_initiative()
    assert not _reached, "the scheduled job ran with the setting off"


def test_the_ceiling_still_restricts_when_the_operator_sets_one(_reached, monkeypatch):
    """`trust_tier_override` is a real control, not decoration — the thing that made the rank
    gate unacceptable was that the operator could not set OR clear it, not that it existed."""
    from services.infrastructure import initiative_engine as ie
    from services.personality import maturity_engine as me

    monkeypatch.setattr(me, "get_state", lambda: me.MaturityState(xp=0, rank=99, phase="transcendence"))
    ie.generate_project_proposals(cfg={
        "initiative_project_proposals_enabled": True,
        "autonomy_trust_tiers_enabled": True,
        "trust_tier_override": 1,
    })
    assert not _reached, "an explicit operator ceiling of 1 did not hold back a tier-2 capability"


@pytest.mark.parametrize("rank,phase", [(0, "awakening"), (2, "awakening"), (5, "attunement"),
                                        (6, "resonance"), (99, "transcendence")])
def test_inline_initiative_is_not_phase_gated(rank, phase, monkeypatch):
    """The operator has `inline_initiative_enabled: True` in their live config and sits at rank 2.

    `is_high_trust_phase` starts at "resonance" = rank 6, so their switch was on and the
    suggestion was never appended — ~19,500 XP of unrelated activity away from the feature they
    had already asked for. Driven through the real handler with a sentinel.
    """
    import runtime_safety as rs
    import services.infrastructure.initiative_inline as ii
    from services.agent import reasoning_handler as rh
    from services.personality import maturity_engine as me

    seen: list[str] = []
    monkeypatch.setattr(ii, "maybe_append_inline_suggestion",
                        lambda text, state=None, cfg=None: seen.append("hit") or text)
    monkeypatch.setattr(me, "get_state", lambda: me.MaturityState(xp=0, rank=rank, phase=phase))
    monkeypatch.setattr(rs, "load_config", lambda *a, **k: {"inline_initiative_enabled": True})

    try:
        rh.handle_reasoning_intent
    except AttributeError:  # pragma: no cover - the handler was renamed
        pytest.skip("handle_reasoning_intent is gone; update this test's entry point")

    src = (AGENT_DIR / "services" / "agent" / "reasoning_handler.py").read_text(encoding="utf-8")
    block = src[src.index("inline_initiative_enabled"):src.index("agent_loop:inline_initiative")]
    code = "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))
    assert "is_high_trust_phase" not in code and "get_state" not in code, (
        f"the inline-initiative block still consults maturity at rank {rank}:\n{code}"
    )


def test_observation_mode_is_keyed_on_knowledge_not_rank():
    """Observation mode means "I don't know this person yet" — so it must read the profile.

    Keyed on phase it lifted at rank 6, i.e. caution wore off by grinding XP rather than by
    learning anything about the operator.
    """
    src = (AGENT_DIR / "services" / "agent" / "llm_decision.py").read_text(encoding="utf-8")
    block = src[src.index("observation_mode_enabled"):src.index("explicit_action")]
    code = "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))
    assert "is_early_phase" not in code and "maturity_engine" not in code, (
        f"observation mode still derives restraint from maturity:\n{code}"
    )
    assert "knows_operator" in code, "observation mode no longer reads familiarity"


def test_an_active_ceiling_is_reported_as_the_owner():
    """`key_off_reason` step 3 says "nothing is holding it and no rank or level is required".
    With a ceiling set that sentence is false, so the ceiling must be found as an owner FIRST."""
    from install.feature_status import key_off_reason

    cfg = {
        "initiative_project_proposals_enabled": False,
        "autonomy_trust_tiers_enabled": True,
        "trust_tier_override": 0,
    }
    on, owner, reason, _missing = key_off_reason("initiative_project_proposals_enabled", cfg)
    assert on is False
    assert owner == "trust_tier", f"an active ceiling was reported as {owner!r}: {reason}"
    assert "trust_tier_override" in reason, "the reason must name the control that clears it"


def test_with_no_ceiling_the_plain_setting_explanation_is_true():
    """And the converse — the default case must NOT invent an owner."""
    from install.feature_status import key_off_reason

    cfg = {"initiative_project_proposals_enabled": False, "autonomy_trust_tiers_enabled": True}
    on, owner, reason, _missing = key_off_reason("initiative_project_proposals_enabled", cfg)
    assert on is False
    assert owner == "setting", f"no ceiling is set, yet the reason claims owner {owner!r}: {reason}"
    assert "no rank or level is required" in reason


# ── the gate that must NOT have been weakened ───────────────────────────────────

def test_autonomous_mode_does_not_touch_tool_approval():
    """R2's explicit carve-out: the dangerous TOOL approval gate is separate and stays put.

    Driven, not asserted from source: `_is_approval_bypassed` is called with the exact config the
    change newly makes reachable (every autonomy flag on) and must still refuse to skip approval
    for a destructive tool while safe_mode holds.
    """
    from runtime_safety import DANGEROUS_TOOLS
    from services.tools.tool_dispatch_base import _is_approval_bypassed

    class _Ctx:
        def __init__(self, cfg):
            self.cfg = cfg

    autonomy_on = {k: True for k in LIVE_KEYS}
    tool = sorted(DANGEROUS_TOOLS)[0]

    # safe_mode is the hard floor: even with the bypass on, a destructive tool needs approval.
    cfg = {**autonomy_on, "safe_mode": True, "tool_approval_bypass": True}
    assert _is_approval_bypassed(_Ctx(cfg), tool) is False, (
        f"'{tool}' would run unapproved with autonomy flags on — the safe_mode floor was weakened"
    )
    # …and with no bypass at all, autonomy flags must not conjure one.
    cfg = {**autonomy_on, "safe_mode": True, "tool_approval_bypass": False}
    assert _is_approval_bypassed(_Ctx(cfg), tool) is False


def test_autonomous_run_still_demands_per_request_confirmation():
    """Turning the setting on buys access to the endpoint, not consent for a given run."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import autonomous

    app = FastAPI()
    app.include_router(autonomous.router)
    client = TestClient(app, raise_server_exceptions=False)

    import runtime_safety as rs
    real = rs.load_config

    try:
        rs.load_config = lambda *a, **k: {**real(), "autonomous_mode": True}
        r = client.post("/autonomous/run", json={"goal": "x", "max_steps": 1, "timeout_s": 5})
        assert r.json().get("error") == "confirm_autonomous_required", (
            "confirm_autonomous stopped being required once autonomous_mode became settable"
        )
    finally:
        rs.load_config = real


class TestVoiceEvolutionIsNotRankDriven:
    """The last rank-keyed behaviour: how assertively each aspect speaks.

    orchestrator._load_aspects appended `Voice evolution ({maturity_phase}): {line}` to EVERY
    aspect's systemPromptAddition, and maturity_phase is phase_for_rank(rank). So how decisively
    she spoke was bought with XP — the same construct as the observation-mode restraint, which was
    re-keyed onto familiarity for exactly this reason. Driven at the time: rank 2 produced
    "Short sentences. Cautious." and rank 6 "Confident, surgical." from an otherwise identical
    config.

    It survived the first rank sweep because it never reaches the model — the persona budget cuts
    the tail and this line is appended last. That is not safety, it is luck: dead rank-driven code
    one constant away from being live, which is precisely the shape of the master defect this
    phase opened with (a capability manifest assembled and then truncated away).

    Now keyed on the familiarity roster — things the operator actually told her — so it grows with
    the relationship rather than with background throughput.
    """

    def test_the_voice_tier_tracks_familiarity_not_rank(self):
        from unittest.mock import patch

        import orchestrator as o

        seen = {}
        for known in (0, 6, 12, 18, 23):
            with patch("services.personality.familiarity.get_familiarity",
                       return_value={"known": known, "total": 23}):
                seen[known] = o._voice_key_for_familiarity()

        assert seen[0] == "nascent", (
            "a stranger must get the most cautious voice, got %r" % seen[0])
        assert seen[23] == "transcendent", (
            "a full roster must reach the last tier, got %r" % seen[23])
        assert len(set(seen.values())) > 1, (
            "the tier never changes across the whole familiarity range (%r) — the mapping is "
            "inert and the voice cannot evolve at all" % seen)
        order = ["nascent", "apprentice", "adept", "veteran", "transcendent"]
        idx = [order.index(seen[k]) for k in sorted(seen)]
        assert idx == sorted(idx), (
            "the voice must not become LESS assertive as she learns more about the operator: %r" % seen)

    def test_an_unreadable_roster_does_not_promote_her(self):
        """Failing open here would make an error grant confidence with a stranger."""
        from unittest.mock import patch

        import orchestrator as o

        with patch("services.personality.familiarity.get_familiarity",
                   side_effect=RuntimeError("db gone")):
            assert o._voice_key_for_familiarity() == "nascent"
        with patch("services.personality.familiarity.get_familiarity", return_value={}):
            assert o._voice_key_for_familiarity() == "nascent"

    def test_the_voice_path_reads_no_rank_phase_or_xp(self):
        """THE CLASS GUARD. The previous round's version of this scanned ONE file, so the gate
        living one file over was invisible while 151 tests passed. This one reads the module that
        actually builds the line."""
        import inspect

        import orchestrator as o

        # Scan the CODE, not the prose about it. The first version of this assertion read the raw
        # source and failed on the function's own docstring, which explains why rank was dropped —
        # a guard that forbids naming the defect it prevents would push the reasoning out of the
        # file. Strip comments and the docstring, then scan what actually executes.
        raw = inspect.getsource(o._voice_key_for_familiarity)
        body = re.sub(r'"""[\s\S]*?"""', "", raw)
        body = "\n".join(ln.split("#", 1)[0] for ln in body.splitlines()).lower()
        for banned in ("maturity_phase", "maturity_rank", "phase_for_rank", "get_trust_tier", "_xp"):
            assert banned not in body, (
                "the voice tier is derived from %r in executable code — rank is an indicator, not "
                "a lever on how she speaks" % banned
            )
        # And the caller must not reintroduce it: the rendered label has to name the tier that
        # actually chose the line, not a second input nobody used.
        caller = inspect.getsource(o._load_aspects)
        assert "Voice evolution ({maturity_phase})" not in caller, (
            "the label announces maturity_phase while the content is chosen by familiarity — a "
            "label naming a different input than the one that picked it is how a false lock reads "
            "as true"
        )

    def test_every_aspect_still_gets_a_voice_line(self):
        """Re-keying must not silently drop the feature — the failure mode when a lookup key
        stops matching the data is an empty string and no error."""
        from unittest.mock import patch

        import orchestrator as o

        with patch("services.personality.familiarity.get_familiarity",
                   return_value={"known": 22, "total": 23}):
            aspects = o.reload_aspects()
        assert aspects, "no aspects loaded at all"
        carried = [a for a in aspects if "Voice evolution" in (a.get("systemPromptAddition") or "")]
        assert len(carried) == len(aspects), (
            "%d of %d aspects lost their voice-evolution line — the new key does not match the "
            "voice_evolution blocks in personalities/*.json" % (len(carried), len(aspects))
        )
