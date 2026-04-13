"""
Tool registry: TOOLS dict assembly, validation, and re-exports.

Sandbox helpers live in sandbox_core.py; tool implementations in registry_body.py.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")

from layla.tools.sandbox_core import (  # noqa: F401 — public API
    inside_sandbox,
    set_effective_sandbox,
    shell_command_is_safe_whitelisted,
    shell_command_line,
)


def _build_tools_from_domains(impl: Any) -> dict[str, Any]:
    """Build TOOLS by merging domain modules."""
    from layla.tools.domains import (
        ANALYSIS_TOOLS,
        AUTOMATION_TOOLS,
        CODE_TOOLS,
        DATA_TOOLS,
        FILE_TOOLS,
        GENERAL_TOOLS,
        GEOMETRY_TOOLS,
        GIT_TOOLS,
        MEMORY_TOOLS,
        SYSTEM_TOOLS,
        WEB_TOOLS,
    )

    result: dict[str, Any] = {}
    for domain_tools in (
        FILE_TOOLS,
        GIT_TOOLS,
        WEB_TOOLS,
        MEMORY_TOOLS,
        CODE_TOOLS,
        DATA_TOOLS,
        SYSTEM_TOOLS,
        AUTOMATION_TOOLS,
        ANALYSIS_TOOLS,
        GENERAL_TOOLS,
        GEOMETRY_TOOLS,
    ):
        for name, meta in domain_tools.items():
            meta = dict(meta)
            fn_name = meta.pop("fn_key", name)
            fn = getattr(impl, fn_name, None)
            if fn is None:
                raise ValueError(f"Tool {name}: function {fn_name} not found in registry_body")
            result[name] = {"fn": fn, **meta}
    return result


def __getattr__(name: str) -> Any:
    """Lazy re-export of tool functions and helpers from registry_body (backward compatible)."""
    if name in {"_build_tools_from_domains"}:
        raise AttributeError(name)
    import layla.tools.registry_body as _body

    if hasattr(_body, name):
        return getattr(_body, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    import layla.tools.registry_body as _body

    extra = {n for n in dir(_body) if not n.startswith("_")}
    return sorted(set(globals()) | extra)


import layla.tools.registry_body as _registry_body_impl

TOOLS = _build_tools_from_domains(_registry_body_impl)

# Tool implementations that reference the live TOOLS dict need the same mapping object.
_registry_body_impl.TOOLS = TOOLS
for _impl_name in (
    "analysis",
    "automation",
    "code",
    "data",
    "file_ops",
    "general",
    "geometry",
    "git",
    "memory",
    "system",
    "web",
):
    _sub = __import__(f"layla.tools.impl.{_impl_name}", fromlist=["TOOLS"])
    if hasattr(_sub, "TOOLS"):
        _sub.TOOLS = TOOLS


def _wrap_tool_with_metrics(name: str, fn: Any) -> Any:
    """Wrap tool fn to record execution latency to performance_monitor."""

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        import time

        start = time.perf_counter()
        result = None
        try:
            result = fn(*args, **kwargs)
            return result
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            try:
                from services.observability import log_tool_result

                ok = isinstance(result, dict) and result.get("ok", True) if result is not None else False
                log_tool_result(name, ok=ok, duration_ms=elapsed_ms)
            except Exception:
                pass

    return wrapped


for _tname, _entry in list(TOOLS.items()):
    if isinstance(_entry, dict) and _entry.get("fn"):
        _entry["fn"] = _wrap_tool_with_metrics(_tname, _entry["fn"])

_REQUIRED_META = {"name", "description", "category", "risk_level"}

TOOL_COUNT_THRESHOLD = 50


def validate_tools_registry() -> None:
    """Validate tool registry integrity: count threshold + required metadata. Raise if incomplete."""
    log = logging.getLogger("layla")
    if len(TOOLS) < TOOL_COUNT_THRESHOLD:
        raise RuntimeError(f"Tool registry incomplete: {len(TOOLS)} tools (expected >= {TOOL_COUNT_THRESHOLD})")
    missing = []
    for tool_name, entry in TOOLS.items():
        if not isinstance(entry, dict):
            missing.append((tool_name, "not a dict"))
            continue
        fn = entry.get("fn")
        if not fn:
            missing.append((tool_name, "missing fn"))
            continue
        if not entry.get("name"):
            entry["name"] = tool_name
        if not entry.get("description"):
            doc = (getattr(fn, "__doc__") or "").strip().split("\n")[0][:200]
            if doc:
                entry["description"] = doc
            else:
                entry["description"] = tool_name.replace("_", " ").strip()
        if not entry.get("category"):
            entry["category"] = "general"
            log.debug("tool %s: missing category, defaulting to general", tool_name)
        if not entry.get("risk_level"):
            entry["risk_level"] = "medium" if entry.get("dangerous") else "low"
            log.warning("tool %s: missing risk_level, inferred as %s", tool_name, entry["risk_level"])
    for name, msg in missing:
        log.warning("tool %s: %s", name, msg)
