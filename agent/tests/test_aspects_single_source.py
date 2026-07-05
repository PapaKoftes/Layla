"""BL-122: the frontend aspect roster and the backend aspect roster must not diverge.

main.js derives its palette aspect-switch commands from `aspect.ASPECTS` (one frontend
source), which must stay in lock-step with the backend `orchestrator._load_aspects()`.
This guard fails the moment someone adds/renames/removes an aspect on only one side.
"""
from __future__ import annotations

import re
from pathlib import Path

_AGENT = Path(__file__).resolve().parent.parent
_ASPECT_JS = _AGENT / "ui" / "components" / "aspect.js"


def _frontend_aspect_ids() -> set[str]:
    text = _ASPECT_JS.read_text(encoding="utf-8")
    m = re.search(r"export const ASPECTS\s*=\s*\[(.*?)\]", text, re.S)
    assert m, "could not find `export const ASPECTS = [...]` in aspect.js"
    return set(re.findall(r"id:\s*'([a-z0-9_]+)'", m.group(1)))


def _backend_aspect_ids() -> set[str]:
    import orchestrator
    return {str(a.get("id")) for a in orchestrator._load_aspects() if a.get("id")}


def test_frontend_and_backend_aspects_match():
    frontend = _frontend_aspect_ids()
    backend = _backend_aspect_ids()
    assert frontend, "no aspect ids parsed from aspect.js"
    assert frontend == backend, (
        f"aspect roster drift — frontend {sorted(frontend)} != backend {sorted(backend)}. "
        "Update components/aspect.js and the backend aspect source together."
    )
