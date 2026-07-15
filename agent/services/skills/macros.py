"""Workflow recorder & macro engine (BL-231).

A *macro* is a named, ordered sequence of tool steps (`{tool, args}`) that Layla
can save from a completed run and later **replay** — turning a one-off task into a
reusable, parameterised routine. Records from a run's step trace (which now carries
a compact `args` snapshot per step), replays by dispatching each step through the
live `TOOLS` registry, and supports simple `{{param}}` substitution so a recorded
workflow can be re-run against new inputs.

Storage: a small SQLite table next to the other Layla stores. Replay executes real
tools, so it is gated the same way tool execution is (caller passes `confirm=True`).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


def _data_dir() -> Path:
    """Layla's data directory (same LAYLA_DATA_DIR the memory layer uses)."""
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.home() / ".layla"

# actions that are loop bookkeeping, never part of a replayable macro
_NON_TOOL_ACTIONS = {
    "reason", "none", "finish", "think", "wakeup", "client_abort", "plan",
}
_PARAM = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


# ── storage ──────────────────────────────────────────────────────────────────
def _db_path() -> Path:
    return _data_dir() / "macros.db"


@contextmanager
def _db():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS macro (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                steps TEXT NOT NULL,
                params TEXT DEFAULT '[]',
                source_run TEXT DEFAULT '',
                created_at REAL NOT NULL,
                run_count INTEGER DEFAULT 0,
                last_run_at REAL
            )"""
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── recording ────────────────────────────────────────────────────────────────
def extract_steps_from_run(state: dict) -> list[dict]:
    """Pull the replayable `{tool, args}` steps out of a run's step trace."""
    steps: list[dict] = []
    for s in (state or {}).get("steps") or []:
        if not isinstance(s, dict):
            continue
        tool = str(s.get("action") or "").strip()
        if not tool or tool in _NON_TOOL_ACTIONS:
            continue
        # only keep steps that actually succeeded — a macro shouldn't re-run failures
        res = s.get("result")
        if isinstance(res, dict) and res.get("ok") is False:
            continue
        steps.append({"tool": tool, "args": dict(s.get("args") or {})})
    return steps


def _discover_params(steps: list[dict]) -> list[str]:
    found: list[str] = []
    for st in steps:
        for v in (st.get("args") or {}).values():
            for m in _PARAM.findall(str(v)):
                if m not in found:
                    found.append(m)
    return found


def _validate_steps(steps: Any) -> list[dict]:
    from layla.tools.registry import TOOLS
    if not isinstance(steps, list) or not steps:
        raise ValueError("a macro needs at least one step")
    clean: list[dict] = []
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            raise ValueError(f"step {i} is not an object")
        tool = str(st.get("tool") or "").strip()
        if tool not in TOOLS:
            raise ValueError(f"step {i}: unknown tool {tool!r}")
        args = st.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError(f"step {i}: args must be an object")
        clean.append({"tool": tool, "args": args})
    return clean


def record_macro(
    name: str,
    steps: list[dict],
    *,
    description: str = "",
    source_run: str = "",
) -> dict[str, Any]:
    """Save a named macro. `steps` = `[{tool, args}, …]` (validated against TOOLS)."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "name required"}
    try:
        clean = _validate_steps(steps)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    params = _discover_params(clean)
    with _db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO macro (name, description, steps, params, source_run, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (name, description, json.dumps(clean), json.dumps(params), source_run, time.time()),
            )
        except sqlite3.IntegrityError:
            return {"ok": False, "error": f"a macro named {name!r} already exists"}
        return {"ok": True, "id": cur.lastrowid, "name": name, "steps": len(clean), "params": params}


# ── query ────────────────────────────────────────────────────────────────────
def _row(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "description": r["description"],
        "steps": json.loads(r["steps"]),
        "params": json.loads(r["params"] or "[]"),
        "source_run": r["source_run"],
        "created_at": r["created_at"],
        "run_count": r["run_count"],
        "last_run_at": r["last_run_at"],
    }


def list_macros() -> list[dict]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM macro ORDER BY last_run_at DESC, created_at DESC").fetchall()
        return [_row(r) for r in rows]


def get_macro(macro_id: int | str) -> dict | None:
    with _db() as conn:
        if isinstance(macro_id, str) and not str(macro_id).isdigit():
            r = conn.execute("SELECT * FROM macro WHERE name=?", (macro_id,)).fetchone()
        else:
            r = conn.execute("SELECT * FROM macro WHERE id=?", (int(macro_id),)).fetchone()
        return _row(r) if r else None


def delete_macro(macro_id: int | str) -> dict[str, Any]:
    with _db() as conn:
        if isinstance(macro_id, str) and not str(macro_id).isdigit():
            cur = conn.execute("DELETE FROM macro WHERE name=?", (macro_id,))
        else:
            cur = conn.execute("DELETE FROM macro WHERE id=?", (int(macro_id),))
        return {"ok": cur.rowcount > 0, "deleted": cur.rowcount}


# ── replay ───────────────────────────────────────────────────────────────────
def _resolve_tool_fn(tool: str, tools: dict) -> Any:
    """Get the callable for a tool. Registry entries are `{"fn": fn, ...}`; also
    tolerate a bare callable (used in tests / lightweight registries)."""
    entry = tools.get(tool)
    if entry is None:
        return None
    if callable(entry):
        return entry
    if isinstance(entry, dict):
        fn = entry.get("fn")
        return fn if callable(fn) else None
    return None


def _apply_params(value: Any, params: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _PARAM.sub(lambda m: str(params.get(m.group(1), m.group(0))), value)
    if isinstance(value, dict):
        return {k: _apply_params(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_apply_params(v, params) for v in value]
    return value


def replay_macro(
    macro_id: int | str,
    *,
    params: dict[str, str] | None = None,
    confirm: bool = False,
    stop_on_error: bool = True,
) -> dict[str, Any]:
    """Re-execute a macro's steps through the live TOOLS registry.

    Runs real tools — the caller must pass `confirm=True`. `{{param}}` placeholders
    in step args are substituted from `params`. Returns a per-step result trace.
    """
    macro = get_macro(macro_id)
    if not macro:
        return {"ok": False, "error": "macro not found"}
    if not confirm:
        return {
            "ok": False,
            "error": "replay requires confirm=True",
            "macro": macro["name"],
            "steps": macro["steps"],
            "params": macro["params"],
        }
    from layla.tools.registry import TOOLS

    params = params or {}
    results: list[dict] = []
    ok_all = True
    for i, st in enumerate(macro["steps"]):
        tool = st["tool"]
        args = _apply_params(dict(st.get("args") or {}), params)
        fn = _resolve_tool_fn(tool, TOOLS)
        if fn is None:
            results.append({"step": i, "tool": tool, "ok": False, "error": "tool no longer available"})
            ok_all = False
            if stop_on_error:
                break
            continue
        try:
            res = fn(**args)
            step_ok = not (isinstance(res, dict) and res.get("ok") is False)
            results.append({"step": i, "tool": tool, "ok": step_ok, "result": res})
            if not step_ok:
                ok_all = False
                if stop_on_error:
                    break
        except Exception as e:  # noqa: BLE001 — surface the failure, keep the trace
            logger.warning("macro replay: step %d (%s) failed: %s", i, tool, e)
            results.append({"step": i, "tool": tool, "ok": False, "error": str(e)})
            ok_all = False
            if stop_on_error:
                break

    with _db() as conn:
        conn.execute(
            "UPDATE macro SET run_count = run_count + 1, last_run_at = ? WHERE id = ?",
            (time.time(), macro["id"]),
        )
    return {"ok": ok_all, "macro": macro["name"], "ran": len(results), "results": results}
