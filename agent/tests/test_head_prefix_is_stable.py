"""The system head stays byte-identical across turns up to the per-turn part, so the KV prompt cache can reuse it.

Measured on jinx-20b: two consecutive "Say hello" reply prompts diverged after 8% (an "(74% of 274
interactions)" counter), then after 38% (the per-turn TASK emitted mid-head) and 41% (sub-objectives repeated
in the scratchpad); every turn re-processed ~3,000 tokens (~20 s). Fixed to 64% shared and the cache on:
~10-13 s.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _common_prefix(a: str, b: str) -> int:
    return next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))


def test_per_turn_task_is_emitted_after_the_stable_sections():
    from services.context.context_manager import build_system_prompt

    base = {
        "system_instructions": "You are Layla. " * 40,
        "durable_facts": "Name: User. Timezone: Europe/Berlin.",
        "agent_state": "Repo structure: a.py, b.py",
        "memory": "Things I remember: the user likes dark mode.",
        "knowledge": "Reference docs:\nREST semantics: GET is safe.",
    }
    a, _ = build_system_prompt({**base, "current_goal": "Sub-objectives: Greet the user; Keep it concise"}, n_ctx=8192)
    b, _ = build_system_prompt({**base, "current_goal": "Sub-objectives: Greet the user; Keep it brief"}, n_ctx=8192)
    assert "Greet the user" in a, "PROBE BROKEN: the goal was not emitted"
    shared = a[:_common_prefix(a, b)]
    for stable in ("Repo structure", "dark mode", "GET is safe"):
        assert stable in shared, f"{stable!r} comes after the per-turn task; shared prefix ends: {shared[-80:]!r}"


def test_scratchpad_does_not_repeat_the_per_turn_sub_objectives():
    src = (AGENT_DIR / "services" / "prompts" / "system_head_builder.py").read_text(encoding="utf-8")
    assert '"Sub-objectives for this run: "' not in src


def test_interaction_pattern_hint_has_no_live_counter(monkeypatch):
    from services.personality import evolution as ev

    cls = next(v for v in vars(ev).values() if isinstance(v, type) and hasattr(v, "get_evolved_hints"))
    obj = cls.__new__(cls)
    out = []
    for total in (274, 275):
        hist = {"total_interactions": total, "type_counts": {"casual": int(total * 0.74), "code_help": 10}}
        monkeypatch.setattr(obj, "_load_drift", lambda a: {}, raising=False)
        monkeypatch.setattr(obj, "_load_communication_prefs", lambda a: {}, raising=False)
        monkeypatch.setattr(obj, "_load_interaction_history", lambda a, h=hist: h, raising=False)
        out.append(obj.get_evolved_hints("morrigan"))
    assert "casual conversation" in out[0], f"PROBE BROKEN: {out[0]!r}"
    assert out[0] == out[1], out
