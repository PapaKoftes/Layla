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


def _deliberate_predicate(src: str) -> str:
    m = re.search(r"deliberate\s*=\s*(.+)", src)
    assert m, "no `deliberate =` assignment found"
    return m.group(1)


def test_both_reason_paths_gate_deliberation_on_show_thinking():
    from services.agent import reasoning_handler, stream_handler

    rh = _deliberate_predicate(inspect.getsource(reasoning_handler.handle_reasoning_intent))
    sh = inspect.getsource(stream_handler)
    # Both must include show_thinking in the deliberate predicate.
    assert "show_thinking" in rh, f"non-stream deliberate predicate omits show_thinking: {rh}"
    assert re.search(r"deliberate\s*=\s*bool\(show_thinking\)", sh), "stream path lost its show_thinking gate"
