"""
Multi-agent delegation — decompose complex tasks into parallel sub-tasks.

When a task involves multiple independent subtasks (e.g., "research X and refactor Y"),
this module decomposes it, dispatches to sub-agents, and aggregates results.

Uses the existing agent_loop infrastructure for each sub-agent.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import re
import time
import uuid
from typing import Any

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_active_tasks: dict[str, dict] = {}
_completed_count: int = 0

# Re-entrancy guard: set while a subtask's own agent run is executing, so a subtask can never
# re-decompose into another multi-agent run (infinite recursion). Checked at the wiring site
# (should_use_multi_agent). A ContextVar so it is isolated per async context / to_thread call.
_in_subtask: contextvars.ContextVar[bool] = contextvars.ContextVar("_in_subtask", default=False)


def in_subtask() -> bool:
    """True when the current execution is already inside a multi-agent subtask."""
    return bool(_in_subtask.get())


def _extract_subtask_reply(state: dict) -> str:
    """Pull the natural-language answer out of an autonomous_run() result dict."""
    if not isinstance(state, dict):
        return ""
    for key in ("response", "reply"):
        v = (state.get(key) or "").strip() if isinstance(state.get(key), str) else ""
        if v:
            return v
    steps = state.get("steps") or []
    if steps:
        last = steps[-1].get("result")
        if isinstance(last, str) and last.strip():
            return last.strip()
    return ""

# ---------------------------------------------------------------------------
# 1. Decomposition heuristic
# ---------------------------------------------------------------------------

# Patterns that suggest a compound / multi-step task
_MULTI_STEP_PATTERNS: list[re.Pattern[str]] = [
    # "do X and Y" where both sides look like clauses (>3 words each)
    re.compile(r"\b\w+(?:\s+\w+){2,}\s+and\s+\w+(?:\s+\w+){2,}", re.IGNORECASE),
    # explicit sequencing
    re.compile(r"\bthen\b", re.IGNORECASE),
    re.compile(r"\balso\b", re.IGNORECASE),
    re.compile(r"\bafterwards?\b", re.IGNORECASE),
    re.compile(r"\bfinally\b", re.IGNORECASE),
    # numbered items  "1. ... 2. ..."
    re.compile(r"(?:^|\n)\s*\d+[.)]\s", re.MULTILINE),
    # bullet lists
    re.compile(r"(?:^|\n)\s*[-*]\s", re.MULTILINE),
    # "first …, second …"
    re.compile(r"\bfirst\b.*\bsecond\b", re.IGNORECASE | re.DOTALL),
]


def is_decomposable(task: str) -> bool:
    """Heuristic check — returns True if the task looks like it contains
    multiple independent sub-tasks that could run in parallel.

    Uses simple regex / keyword matching, not LLM-based.
    """
    if not task or not task.strip():
        return False
    for pat in _MULTI_STEP_PATTERNS:
        if pat.search(task):
            return True
    return False


# ---------------------------------------------------------------------------
# 2. Decompose
# ---------------------------------------------------------------------------

_SPLIT_RE = re.compile(
    r"""
      (?:^|\n)\s*\d+[.)]\s+   |   # numbered list items
      (?:^|\n)\s*[-*]\s+       |   # bullet list items
      \s+and\s+                |   # conjunction
      \s+then\s+              |   # sequencing
      \s+also\s+                   # additive
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SEQUENCE_WORDS = {"then", "afterwards", "after that", "finally", "next"}


def decompose_task(task: str) -> list[dict]:
    """Split a compound task into sub-tasks.

    Returns a list of dicts::

        {"id": str, "description": str, "priority": int, "depends_on": list[str]}

    Falls back to a single-task list if decomposition fails or the task is
    not decomposable.
    """
    if not task or not task.strip():
        return [_single_subtask(task or "")]

    # Try numbered / bullet list first
    numbered = re.split(r"(?:^|\n)\s*\d+[.)]\s+", task)
    numbered = [s.strip() for s in numbered if s.strip()]
    if len(numbered) >= 2:
        return _build_subtask_list(numbered, task)

    bullets = re.split(r"(?:^|\n)\s*[-*]\s+", task)
    bullets = [s.strip() for s in bullets if s.strip()]
    if len(bullets) >= 2:
        return _build_subtask_list(bullets, task)

    # Try conjunction / sequencing split
    parts = re.split(r"\s+(?:and|then|also)\s+", task, flags=re.IGNORECASE)
    parts = [s.strip() for s in parts if s.strip()]
    if len(parts) >= 2:
        return _build_subtask_list(parts, task)

    # Fall back to single task
    return [_single_subtask(task)]


def _single_subtask(description: str) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "description": description.strip() or "(empty)",
        "priority": 0,
        "depends_on": [],
    }


def _build_subtask_list(parts: list[str], original: str) -> list[dict]:
    """Create ordered subtask dicts from extracted parts.

    If the original text contains sequencing words between parts the later
    parts will depend on earlier ones.
    """
    lower = original.lower()
    sequential = any(w in lower for w in _SEQUENCE_WORDS)

    subtasks: list[dict] = []
    for idx, desc in enumerate(parts):
        st: dict[str, Any] = {
            "id": uuid.uuid4().hex[:8],
            "description": desc,
            "priority": idx,
            "depends_on": [],
        }
        if sequential and idx > 0:
            st["depends_on"] = [subtasks[idx - 1]["id"]]
        subtasks.append(st)
    return subtasks


# ---------------------------------------------------------------------------
# 3. Dispatch
# ---------------------------------------------------------------------------

_SUBTASK_TIMEOUT_S = 120


def _run_subtask_sync(description: str, aspect_id: str, cfg: dict | None) -> dict:
    """Run one subtask through the real agent loop (synchronous; holds the LLM lock).

    Executes with the re-entrancy guard set so this subtask cannot itself fan out into
    another multi-agent run. Read-only by default (no write/exec) — a delegated subtask
    should reason and report, not mutate the workspace behind the operator's back.
    """
    import agent_loop as _al
    token = _in_subtask.set(True)
    try:
        return _al.autonomous_run(
            description,
            aspect_id=aspect_id or "",
            allow_write=False,
            allow_run=False,
            stream_final=False,
            skip_engineering_pipeline=True,   # a subtask must not re-enter the engineering pipeline
        )
    finally:
        _in_subtask.reset(token)


async def _run_one_subtask(subtask: dict, cfg: dict | None) -> dict:
    """Execute a single subtask through the agent loop and return its result dict."""
    global _completed_count

    task_id = subtask["id"]
    _active_tasks[task_id] = subtask
    start = time.monotonic()

    try:
        logger.debug("multi_agent: starting subtask %s — %s", task_id, subtask["description"])

        # autonomous_run is synchronous and serializes on the single LLM lock, so run it in a
        # worker thread; the outer dispatch_subtasks already applies _SUBTASK_TIMEOUT_S.
        state = await asyncio.to_thread(
            _run_subtask_sync, subtask["description"], subtask.get("aspect_id", "") or "", cfg,
        )
        result_text = _extract_subtask_reply(state) or f"(subtask {task_id} produced no output)"
        ok = str((state or {}).get("status", "")) not in {"error", "timeout", "parse_failed"}

        duration_ms = (time.monotonic() - start) * 1000
        logger.debug("multi_agent: subtask %s finished in %.1f ms", task_id, duration_ms)

        return {
            "id": task_id,
            "description": subtask["description"],
            "result": result_text,
            "ok": ok,
            "duration_ms": round(duration_ms, 2),
        }
    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        logger.warning("multi_agent: subtask %s failed — %s", task_id, exc)
        return {
            "id": task_id,
            "description": subtask["description"],
            "result": str(exc),
            "ok": False,
            "duration_ms": round(duration_ms, 2),
        }
    finally:
        _active_tasks.pop(task_id, None)
        _completed_count += 1


async def dispatch_subtasks(
    subtasks: list[dict],
    *,
    cfg: dict | None = None,
    max_parallel: int = 3,
) -> list[dict]:
    """Run independent subtasks in parallel, respecting *depends_on* ordering.

    Parameters
    ----------
    subtasks:
        List of subtask dicts as returned by :func:`decompose_task`.
    cfg:
        Optional agent configuration dict forwarded to each sub-agent.
    max_parallel:
        Maximum number of concurrent subtasks.

    Returns
    -------
    list[dict]
        One result dict per subtask with keys
        ``id, description, result, ok, duration_ms``.
    """
    if not subtasks:
        return []

    results: dict[str, dict] = {}
    remaining = list(subtasks)

    sem = asyncio.Semaphore(max_parallel)

    async def _guarded(st: dict) -> dict:
        async with sem:
            return await asyncio.wait_for(
                _run_one_subtask(st, cfg),
                timeout=_SUBTASK_TIMEOUT_S,
            )

    while remaining:
        # Partition into ready (all deps satisfied) vs blocked
        ready: list[dict] = []
        blocked: list[dict] = []
        for st in remaining:
            deps = st.get("depends_on") or []
            if all(d in results for d in deps):
                ready.append(st)
            else:
                blocked.append(st)

        if not ready:
            # All remaining tasks are blocked with unresolvable deps — force-run them
            logger.warning(
                "multi_agent: %d subtasks blocked with unresolvable deps — forcing",
                len(blocked),
            )
            ready = blocked
            blocked = []

        # Dispatch the ready wave
        wave_results = await asyncio.gather(
            *[_guarded(st) for st in ready],
            return_exceptions=True,
        )

        for st, wr in zip(ready, wave_results):
            if isinstance(wr, BaseException):
                results[st["id"]] = {
                    "id": st["id"],
                    "description": st["description"],
                    "result": str(wr),
                    "ok": False,
                    "duration_ms": 0.0,
                }
            else:
                results[st["id"]] = wr

        remaining = blocked

    # Return in original order
    return [results[st["id"]] for st in subtasks if st["id"] in results]


# ---------------------------------------------------------------------------
# 4. Aggregate
# ---------------------------------------------------------------------------


def aggregate_results(results: list[dict]) -> dict:
    """Combine sub-task results into a single coherent response.

    Returns a dict::

        {
            "ok": bool,          # True if *all* subtasks succeeded
            "summary": str,      # human-readable summary
            "subtask_results": list[dict],
            "total_duration_ms": float,
        }
    """
    if not results:
        return {
            "ok": True,
            "summary": "No subtasks to execute.",
            "subtask_results": [],
            "total_duration_ms": 0.0,
        }

    all_ok = all(r.get("ok") for r in results)
    total_ms = sum(r.get("duration_ms", 0.0) for r in results)

    # Compose the actual subtask answers into one coherent response (not just a status list).
    # Single subtask → return its answer verbatim (no scaffolding). Multiple → label each part.
    if len(results) == 1:
        summary = (results[0].get("result") or "").strip()
    else:
        blocks: list[str] = []
        for r in results:
            desc = (r.get("description") or "").strip()
            body = (r.get("result") or "").strip()
            if r.get("ok"):
                blocks.append(f"**{desc}**\n\n{body}" if body else f"**{desc}**")
            else:
                blocks.append(f"**{desc}** — could not complete: {body}")
        summary = "\n\n".join(blocks)
        failed = sum(1 for r in results if not r.get("ok"))
        if failed:
            summary += f"\n\n({failed}/{len(results)} subtask(s) did not complete.)"

    return {
        "ok": all_ok,
        "summary": summary,
        "subtask_results": results,
        "total_duration_ms": round(total_ms, 2),
    }


# ---------------------------------------------------------------------------
# 5. High-level entry point
# ---------------------------------------------------------------------------


def should_use_multi_agent(task: str, cfg: dict | None) -> bool:
    """Gate: route this turn through multi-agent decomposition?

    True only when the operator enabled it, we're not already inside a subtask (no recursion),
    the task looks compound, and it actually decomposes into 2+ independent parts.
    """
    cfg = cfg or {}
    if not cfg.get("multi_agent_orchestration_enabled"):
        return False
    if in_subtask():
        return False
    if not is_decomposable(task):
        return False
    return len(decompose_task(task)) >= 2


async def run_multi_agent(task: str, *, cfg: dict | None = None) -> dict:
    """Decompose *task*, dispatch sub-agents, and return the aggregated result.

    This is the main public entry point.  If the task is not decomposable it
    is executed as a single subtask.

    Returns the dict produced by :func:`aggregate_results`.
    """
    subtasks = decompose_task(task)
    logger.info(
        "multi_agent: decomposed into %d subtask(s) — %s",
        len(subtasks),
        [st["description"][:60] for st in subtasks],
    )
    results = await dispatch_subtasks(subtasks, cfg=cfg)
    return aggregate_results(results)


# ---------------------------------------------------------------------------
# 6. Status
# ---------------------------------------------------------------------------


def get_delegation_status() -> dict:
    """Return a snapshot of current multi-agent delegation state.

    Returns::

        {"active_tasks": int, "completed": int, "max_parallel": int}
    """
    return {
        "active_tasks": len(_active_tasks),
        "completed": _completed_count,
        "max_parallel": 3,
    }
