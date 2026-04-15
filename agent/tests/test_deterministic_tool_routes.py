from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


def test_deterministic_route_tools_disabled_returns_none() -> None:
    from layla.tools.registry import TOOLS
    from services.tool_policy import deterministic_route_tools

    cfg = {"deterministic_tool_routes_enabled": False}
    assert deterministic_route_tools(cfg, "edit this code", TOOLS) is None


def test_deterministic_route_tools_enabled_returns_subset(monkeypatch) -> None:
    from layla.tools.registry import TOOLS
    from services import tool_policy

    monkeypatch.setattr(tool_policy, "_DEFAULT_DETERMINISTIC_TOOL_ROUTES", {"coding": ("read_file", "write_file")})

    # Force classify_task -> coding
    from services import model_router

    monkeypatch.setattr(model_router, "classify_task", lambda *_args, **_kw: "coding")

    cfg = {"deterministic_tool_routes_enabled": True}
    s = tool_policy.deterministic_route_tools(cfg, "edit this code", TOOLS)
    assert s is not None
    assert "read_file" in s
