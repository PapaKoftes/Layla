"""Guard: maturity phase gates must use valid PhaseId names, never hand-typed typos.

Three features (proactive initiative, observation mode, voice-evolution) silently died
because runtime gates compared `ms.phase` against strings that are NOT valid phases
(`nascent`, `adept`, `veteran`, `transcendent`). The engine phases are
awakening/attunement/resonance/sovereignty/transcendence. This test fails if anyone
reintroduces an invalid phase literal at a gate site, and pins the predicate behavior.
"""
import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_predicates_match_engine_phases():
    from services.personality import maturity_engine as me
    assert me.VALID_PHASES == {"awakening", "attunement", "resonance", "sovereignty", "transcendence"}
    # early = first-contact/observation; high-trust = initiative unlocked; disjoint + covering-ish
    assert me.is_early_phase("awakening") and me.is_early_phase("attunement")
    assert not me.is_early_phase("resonance")
    assert me.is_high_trust_phase("resonance") and me.is_high_trust_phase("transcendence")
    assert not me.is_high_trust_phase("awakening")
    # the dead typo'd names must be rejected by every predicate
    for bad in ("nascent", "apprentice", "adept", "veteran", "transcendent"):
        assert not me.is_valid_phase(bad)
        assert not me.is_early_phase(bad)
        assert not me.is_high_trust_phase(bad)


def test_no_invalid_phase_literals_at_gate_sites():
    # Scan the runtime gate files for the known-bad phase literals used in string compares.
    # (voice_evolution keys in personalities/*.json are intentionally the OLD names — they're
    #  translated via orchestrator._PHASE_TO_VOICE — so JSON is excluded here.)
    bad_names = ("nascent", "apprentice", "adept", "veteran", "transcendent")
    gate_files = [
        AGENT_DIR / "services" / "agent" / "reasoning_handler.py",
        AGENT_DIR / "services" / "agent" / "llm_decision.py",
    ]
    # match a bad name only when it appears as a quoted string literal (i.e. a comparison value)
    quoted = re.compile(r"""['"](%s)['"]""" % "|".join(bad_names))
    offenders = []
    for f in gate_files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]  # ignore explanatory comments — guard the CODE only
            if quoted.search(code):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, "invalid phase-name literals at gate sites:\n" + "\n".join(offenders)


def test_phase_to_voice_map_covers_all_phases():
    # H10 was a false-positive: voice_evolution IS wired via this translation. Pin it so the
    # map can't silently drift out of sync with the engine phases.
    import orchestrator
    from services.personality import maturity_engine as me
    assert set(orchestrator._PHASE_TO_VOICE) == me.VALID_PHASES
