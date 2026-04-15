from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


def test_completion_gate_rejects_empty() -> None:
    from services.output_quality import passes_completion_gate

    ok, reasons = passes_completion_gate(goal="do x", text="", state={"tool_calls": 0, "steps": []}, cfg={})
    assert ok is False
    assert "empty_response" in reasons


def test_completion_gate_requires_ok_tool_when_tool_calls() -> None:
    from services.output_quality import passes_completion_gate

    ok, reasons = passes_completion_gate(
        goal="edit file",
        text="done",
        state={"tool_calls": 1, "steps": [{"action": "write_file", "result": {"ok": False}}]},
        cfg={},
    )
    assert ok is False
    assert "no_successful_tool_steps" in reasons
