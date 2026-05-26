"""Thread-local allowlist: non-empty step.tools on file-plan execution hard-gates tool names in agent_loop."""

from __future__ import annotations

import threading

_tls = threading.local()


def set_plan_step_tool_allowlist(names: frozenset[str] | None) -> None:
    if names is None or len(names) == 0:
        clear_plan_step_tool_allowlist()
        return
    _tls.plan_step_tools = names


def clear_plan_step_tool_allowlist() -> None:
    if hasattr(_tls, "plan_step_tools"):
        delattr(_tls, "plan_step_tools")


def get_plan_step_tool_allowlist() -> frozenset[str] | None:
    return getattr(_tls, "plan_step_tools", None)
