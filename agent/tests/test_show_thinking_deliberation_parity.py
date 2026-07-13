"""audit round-3 #5: show_thinking must gate deliberation IDENTICALLY on the streaming and
non-streaming reason paths (project memory: 'deliberation IS the thinking mode'). Previously the
non-stream reasoning_handler omitted show_thinking, so {show_thinking:true} deliberated when streamed
but returned a plain answer when non-streamed."""
import inspect
import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

_PRED = re.compile(r"deliberate\s*=\s*bool\(show_thinking\)\s*or\s*orchestrator\.should_deliberate")


def test_both_reason_paths_gate_deliberation_on_show_thinking():
    from services.agent import reasoning_handler, stream_handler

    # The real deliberate PREDICATE (not the `deliberate = False/True` set-up lines) must OR-in
    # show_thinking on BOTH paths.
    rh = inspect.getsource(reasoning_handler.handle_reasoning_intent)
    sh = inspect.getsource(stream_handler)
    assert _PRED.search(rh), "non-stream reason path does not gate deliberation on show_thinking"
    assert _PRED.search(sh), "stream reason path lost its show_thinking deliberation gate"
