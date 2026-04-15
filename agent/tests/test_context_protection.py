from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


def test_steps_summary_deterministic() -> None:
    from agent_loop import _summarize_steps_deterministic

    steps = [{"action": "read_file", "result": {"ok": True, "path": "a.py"}}] * 12
    s = _summarize_steps_deterministic(steps, keep_last=5, max_lines=5)
    assert "Steps completed so far" in s
