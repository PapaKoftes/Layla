"""Every event name the observability layer emits is a registered event type.

The hand-kept list had drifted to 9 of the 26 names emitted, so every live turn logged ~15
"Unknown event_type ... recording anyway" warnings, burying real warnings in the server log.
"""
import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

EMITTER = AGENT_DIR / "services" / "observability" / "_legacy_observability.py"


def _emitted_names() -> set[str]:
    tree = ast.parse(EMITTER.read_text(encoding="utf-8"))
    return {
        n.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_log_event"
        and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
    }


def test_every_emitted_event_type_is_registered():
    from services.observability.event_logger import _VALID_EVENT_TYPES

    names = _emitted_names()
    assert len(names) >= 20, f"PROBE BROKEN: found only {sorted(names)} in {EMITTER}"
    assert names <= _VALID_EVENT_TYPES, sorted(names - _VALID_EVENT_TYPES)


def test_a_registered_event_does_not_warn(caplog):
    from services.observability.event_logger import log_event

    with caplog.at_level("WARNING", logger="layla.observability.events"):
        log_event("agent_decision", {"duration": 1})
        log_event("surely_not_a_real_event_type", {})
    warned = [r.getMessage() for r in caplog.records if "Unknown event_type" in r.getMessage()]
    assert warned == ["Unknown event_type 'surely_not_a_real_event_type' -- recording anyway"], warned
