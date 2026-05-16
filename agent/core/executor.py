"""
agent/core/executor.py — Phase 4: Execute

Wraps every tool call with:
- sandbox boundary check (path-based, not thread-local)
- per-tool timeout (concurrent.futures.ThreadPoolExecutor)
- output size cap
- structured ToolResult

Used by agent_loop.py for the generic tool dispatch path.
Inline tool handlers (write_file, shell, etc.) may call this directly
or continue to use TOOLS[name]["fn"](**args) — both paths are valid.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


@contextmanager
def db_session():
    """Get a DB connection for explicit lifecycle management."""
    from layla.memory.db_connection import _conn, close_thread_connection
    conn = _conn()
    try:
        yield conn
    finally:
        # Don't close thread-local connections on every use — they're pooled
        pass


# Maximum bytes allowed in tool result before truncation
_MAX_OUTPUT_BYTES = 256 * 1024  # 256 KB
_TRUNCATION_SUFFIX = "\n[OUTPUT TRUNCATED — exceeded 256 KB]"

# Executor pool: one thread per tool call; auto-scaled
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="layla_tool")


def run_tool(
    tool_name: str,
    args: dict,
    timeout_s: float = 60.0,
    sandbox_root: str | None = None,
    *,
    allow_run: bool = False,
    conversation_id: str = "",
) -> dict[str, Any]:
    """
    Execute a single tool call from the TOOLS registry with timeout and output cap.

    Returns a ToolResult dict:
      {ok, result, error, tool_name, duration_ms, output_bytes, timed_out}

    Never raises — all exceptions become ok=False results.
    """
    from layla.tools.registry import TOOLS

    start = time.monotonic()

    if tool_name not in TOOLS:
        return {
            "ok": False,
            "tool_name": tool_name,
            "error": f"Unknown tool: {tool_name!r}",
            "duration_ms": 0,
            "output_bytes": 0,
            "timed_out": False,
        }

    fn = TOOLS[tool_name]["fn"]

    # Strip 'goal' key — it's loop-internal, not a tool argument
    clean_args = {k: v for k, v in (args or {}).items() if k != "goal"}

    def _call() -> Any:
        # Ensure thread-local sandbox is set for this tool thread.
        try:
            from layla.tools.registry import set_effective_sandbox

            if _ws:
                set_effective_sandbox(_ws)
        except Exception as e:
            logger.error("sandbox setup failed: %s", e, exc_info=True)
        try:
            return fn(**clean_args)
        finally:
            try:
                from layla.tools.registry import set_effective_sandbox

                set_effective_sandbox(None)
            except Exception as e:
                logger.error("sandbox teardown failed: %s", e, exc_info=True)

    _ws = sandbox_root or ""
    try:
        from services.agent_hooks import run_agent_hooks

        run_agent_hooks(
            "pre_tool",
            tool_name=tool_name,
            allow_run=allow_run,
            conversation_id=conversation_id,
            workspace_root=_ws,
        )
    except Exception as e:
        logger.debug("pre_tool hook failed: %s", e, exc_info=True)

    timed_out = False
    result_raw: Any = None
    error: str | None = None

    future = _executor.submit(_call)
    try:
        result_raw = future.result(timeout=timeout_s)
    except FuturesTimeout:
        future.cancel()
        timed_out = True
        error = f"Tool timed out after {timeout_s:.0f}s"
        logger.warning("executor: tool=%s timed_out after %.0fs", tool_name, timeout_s)
    except Exception as exc:
        error = str(exc)
        logger.error("executor: tool=%s raised %s: %s", tool_name, type(exc).__name__, exc)

    duration_ms = int((time.monotonic() - start) * 1000)

    if timed_out or error:
        try:
            from services.agent_hooks import run_agent_hooks

            run_agent_hooks(
                "post_tool",
                tool_name=tool_name,
                allow_run=allow_run,
                conversation_id=conversation_id,
                workspace_root=_ws,
                tool_ok=False,
            )
        except Exception as e:
            logger.debug("post_tool hook (error path) failed: %s", e, exc_info=True)
        err_code = "timeout" if timed_out else (error or "unknown")[:80]
        _trace_tool_call(
            tool_name=tool_name,
            args=args,
            result=None,
            duration_ms=duration_ms,
            run_id=conversation_id,
            error_code=err_code,
        )
        # Phase 3: Prometheus metrics for failed tool calls
        try:
            from services.metrics import record_tool_call as _record_tool_metric
            _record_tool_metric(tool_name, False, duration_ms / 1000.0)
        except Exception as e:
            logger.debug("metrics recording (error path) failed: %s", e, exc_info=True)
        return {
            "ok": False,
            "tool_name": tool_name,
            "error": error or "unknown",
            "duration_ms": duration_ms,
            "output_bytes": 0,
            "timed_out": timed_out,
        }

    # Normalise result to dict
    if not isinstance(result_raw, dict):
        result_raw = {"ok": True, "result": result_raw}

    # Enforce output size cap
    try:
        serialised = json.dumps(result_raw, default=str)
        output_bytes = len(serialised.encode("utf-8"))
        if output_bytes > _MAX_OUTPUT_BYTES:
            # Truncate the innermost string values until it fits
            truncated = _truncate_result(result_raw)
            logger.info(
                "executor: tool=%s output truncated %d→%d bytes",
                tool_name,
                output_bytes,
                len(json.dumps(truncated, default=str).encode("utf-8")),
            )
            result_raw = truncated
            output_bytes = len(json.dumps(result_raw, default=str).encode("utf-8"))
    except Exception as e:
        logger.warning("output size calculation failed: %s", e)
        output_bytes = 0

    result_raw["_meta"] = {
        "tool_name": tool_name,
        "duration_ms": duration_ms,
        "output_bytes": output_bytes,
        "timed_out": False,
    }
    try:
        from services.llm_gateway import record_tool_call

        record_tool_call()
    except Exception as e:
        logger.debug("llm_gateway record_tool_call failed: %s", e, exc_info=True)
    try:
        from services.request_tracer import record_trace_tool_call

        record_trace_tool_call()
    except Exception as e:
        logger.debug("request_tracer record_trace_tool_call failed: %s", e, exc_info=True)
    try:
        from services.agent_hooks import run_agent_hooks

        _ok = True
        if isinstance(result_raw, dict):
            _ok = bool(result_raw.get("ok", True))
        run_agent_hooks(
            "post_tool",
            tool_name=tool_name,
            allow_run=allow_run,
            conversation_id=conversation_id,
            workspace_root=_ws,
            tool_ok=_ok,
        )
    except Exception as e:
        logger.debug("post_tool hook (success path) failed: %s", e, exc_info=True)

    # Phase 0.2: structured tool call trace (fire-and-forget, never blocks execution)
    _trace_tool_call(
        tool_name=tool_name,
        args=args,
        result=result_raw,
        duration_ms=duration_ms,
        run_id=conversation_id,
        error_code=None,
    )

    # Phase 3: Prometheus metrics (fire-and-forget)
    try:
        from services.metrics import record_tool_call as _record_tool_metric
        _ok = bool(result_raw.get("ok", True)) if isinstance(result_raw, dict) else True
        _record_tool_metric(tool_name, _ok, duration_ms / 1000.0)
    except Exception as e:
        logger.debug("metrics recording (success path) failed: %s", e, exc_info=True)

    return result_raw


def _trace_tool_call(
    tool_name: str,
    args: dict | None,
    result: dict | None,
    duration_ms: int,
    run_id: str = "",
    error_code: str | None = None,
    cost_usd: float = 0.0,
    provider: str = "",
    model_used: str = "",
) -> None:
    """Persist a compact tool-call trace record to the tool_calls table (Phase 0.2).

    Phase 3 additions: *cost_usd*, *provider*, *model_used* capture LLM cost
    when the tool call was routed through litellm.

    NOTE: migrate() is NOT called here — migration runs once at startup
    (main.py lifespan). Calling it on every tool trace was unnecessary overhead.
    """
    try:
        args_hash = hashlib.sha256(
            json.dumps(args or {}, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        result_ok = 1 if (result is not None and isinstance(result, dict) and result.get("ok", True)) else 0
        from layla.memory.db_connection import _conn
        from layla.time_utils import utcnow

        with _conn() as db:
            db.execute(
                "INSERT INTO tool_calls (run_id, tool_name, args_hash, result_ok, error_code, duration_ms, created_at, cost_usd, provider, model_used)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    (run_id or "")[:64],
                    tool_name,
                    args_hash,
                    result_ok,
                    (error_code or "")[:80],
                    duration_ms,
                    utcnow().isoformat(),
                    float(cost_usd or 0.0),
                    (provider or "")[:80],
                    (model_used or "")[:120],
                ),
            )
            db.commit()
    except Exception as _e:
        logger.debug("tool_trace write failed: %s", _e)


def _truncate_result(result: dict, max_bytes: int = _MAX_OUTPUT_BYTES) -> dict:
    """Truncate the largest string field in a result dict until total size fits."""
    import copy
    r = copy.deepcopy(result)
    for key in ("output", "content", "text", "result", "stdout", "stderr"):
        val = r.get(key)
        if isinstance(val, str) and len(val) > 1000:
            r[key] = val[: max_bytes // 2] + _TRUNCATION_SUFFIX
            break
    return r
