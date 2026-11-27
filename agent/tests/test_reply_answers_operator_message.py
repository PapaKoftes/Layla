"""The reply must answer the operator's message, never the model's revised_objective.

Live on jinx-20b the decision emitted revised_objective "I have enough context to answer."; decision_loop
rebinds `goal` to it, and that became the reply prompt's "User:" line — so "What sentence did I ask you to
remember?" was answered with a quoted prompt line, and "Say hello" with "Probe_token.txt exists.".
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_stream_and_nonstream_reply_use_the_original_goal(monkeypatch):
    import agent_loop as al
    import orchestrator
    from services.agent import reasoning_handler as rh
    from services.prompts import system_head_builder as shb

    seen = {}

    def _std(message, aspect, context, head, convo_block):
        seen["message"] = message
        return "PROMPT"

    monkeypatch.setattr(orchestrator, "build_standard_prompt", _std)
    monkeypatch.setattr(orchestrator, "should_deliberate", lambda *a, **k: False)
    monkeypatch.setattr(shb, "build_system_head", lambda *a, **k: "HEAD")
    monkeypatch.setattr(al, "run_completion", lambda *a, **k: {"choices": [{"text": "fine"}]})

    run_params = {"active_aspect": {"id": "morrigan", "name": "Morrigan"}, "cfg": {"deliberation_mode": "solo"},
                  "workspace": "", "_precomputed_recall": None, "_dignity_boundary_prompt": "", "temperature": 0.2}
    base = {"original_goal": "What sentence did I ask you to remember?", "steps": [], "reasoning_mode": "light"}

    state = dict(base)
    rh.handle_reasoning_intent(state, run_params, "I have enough context to answer.", "", [], False, True, None, "")
    assert state.get("goal_for_stream") == base["original_goal"], "streamed reply must answer the operator"

    state = dict(base)
    try:
        rh.handle_reasoning_intent(state, run_params, "I have enough context to answer.", "", [], False, False, None, "")
    except Exception:
        pass  # downstream post-processing isn't under test; the prompt was already built
    assert seen.get("message") == base["original_goal"], f"reply prompt answered {seen.get('message')!r}"


def test_reframe_does_not_queue_the_direction_question():
    src = (AGENT_DIR / "services" / "agent" / "decision_loop.py").read_text(encoding="utf-8")
    block = src[src.index("if revised_objective and isinstance"):src.index("if consecutive >= 2 and not objective_complete")]
    code = "\n".join(ln for ln in block.splitlines() if not ln.strip().startswith("#"))
    assert "reflection_pending" not in code
