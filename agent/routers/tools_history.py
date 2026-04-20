"""
Tool call history and analysis endpoints (Phase 0.2).

GET /tools/history  — paginated list of tool calls with success rate and duration
GET /tools/analysis — aggregated health dashboard: rates, slowest tools, failure modes
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("layla")

router = APIRouter(tags=["tools"])


def _since_iso(days: int) -> str:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    return cutoff.isoformat()


@router.get("/tools/history")
def tools_history(tool_name: str = "", days: int = 7, limit: int = 100, offset: int = 0):
    """
    List recent tool call trace records.

    Filter by tool_name (optional) and recency window (days, default 7).
    Returns rows with: id, run_id, tool_name, result_ok, error_code, duration_ms, created_at.
    """
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        cutoff = _since_iso(max(1, min(days, 365)))
        with _conn() as db:
            if tool_name.strip():
                rows = db.execute(
                    "SELECT id, run_id, tool_name, result_ok, error_code, duration_ms, created_at"
                    " FROM tool_calls"
                    " WHERE tool_name=? AND created_at >= ?"
                    " ORDER BY id DESC LIMIT ? OFFSET ?",
                    (tool_name.strip(), cutoff, max(1, min(limit, 500)), max(0, offset)),
                ).fetchall()
                total = db.execute(
                    "SELECT COUNT(*) FROM tool_calls WHERE tool_name=? AND created_at >= ?",
                    (tool_name.strip(), cutoff),
                ).fetchone()[0]
            else:
                rows = db.execute(
                    "SELECT id, run_id, tool_name, result_ok, error_code, duration_ms, created_at"
                    " FROM tool_calls"
                    " WHERE created_at >= ?"
                    " ORDER BY id DESC LIMIT ? OFFSET ?",
                    (cutoff, max(1, min(limit, 500)), max(0, offset)),
                ).fetchall()
                total = db.execute(
                    "SELECT COUNT(*) FROM tool_calls WHERE created_at >= ?",
                    (cutoff,),
                ).fetchone()[0]

        records = [
            {
                "id": r["id"],
                "run_id": r["run_id"],
                "tool_name": r["tool_name"],
                "result_ok": bool(r["result_ok"]),
                "error_code": r["error_code"] or None,
                "duration_ms": r["duration_ms"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        return {"ok": True, "total": total, "offset": offset, "records": records}
    except Exception as e:
        logger.debug("tools/history error: %s", e)
        return JSONResponse({"ok": False, "error": str(e), "records": []}, status_code=500)


@router.get("/tools/analysis")
def tools_analysis(days: int = 7):
    """
    Aggregated tool health dashboard.

    Returns per-tool: call count, success rate, avg/p95 duration, top error codes.
    Also returns: slowest tools, most-failed tools, overall success rate.
    """
    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        cutoff = _since_iso(max(1, min(days, 365)))
        with _conn() as db:
            agg = db.execute(
                """
                SELECT
                    tool_name,
                    COUNT(*) AS calls,
                    SUM(result_ok) AS successes,
                    AVG(duration_ms) AS avg_ms,
                    MAX(duration_ms) AS max_ms
                FROM tool_calls
                WHERE created_at >= ?
                GROUP BY tool_name
                ORDER BY calls DESC
                """,
                (cutoff,),
            ).fetchall()

            error_agg = db.execute(
                """
                SELECT tool_name, error_code, COUNT(*) AS cnt
                FROM tool_calls
                WHERE created_at >= ? AND result_ok=0 AND error_code != ''
                GROUP BY tool_name, error_code
                ORDER BY cnt DESC
                """,
                (cutoff,),
            ).fetchall()

        error_map: dict[str, list[dict]] = {}
        for row in error_agg:
            error_map.setdefault(row["tool_name"], []).append(
                {"error_code": row["error_code"], "count": row["cnt"]}
            )

        tools = []
        total_calls = total_ok = 0
        for row in agg:
            calls = row["calls"]
            ok = row["successes"] or 0
            success_rate = round(ok / calls, 3) if calls else 0.0
            tools.append(
                {
                    "tool_name": row["tool_name"],
                    "calls": calls,
                    "successes": ok,
                    "failures": calls - ok,
                    "success_rate": success_rate,
                    "avg_duration_ms": round(row["avg_ms"] or 0, 1),
                    "max_duration_ms": row["max_ms"] or 0,
                    "top_errors": error_map.get(row["tool_name"], [])[:3],
                }
            )
            total_calls += calls
            total_ok += ok

        slowest = sorted(tools, key=lambda x: x["avg_duration_ms"], reverse=True)[:5]
        most_failed = sorted(tools, key=lambda x: x["failures"], reverse=True)[:5]

        return {
            "ok": True,
            "days": days,
            "summary": {
                "total_calls": total_calls,
                "total_successes": total_ok,
                "overall_success_rate": round(total_ok / total_calls, 3) if total_calls else 0.0,
                "distinct_tools": len(tools),
            },
            "tools": tools,
            "slowest_tools": [{"tool_name": t["tool_name"], "avg_duration_ms": t["avg_duration_ms"]} for t in slowest],
            "most_failed_tools": [{"tool_name": t["tool_name"], "failures": t["failures"]} for t in most_failed],
        }
    except Exception as e:
        logger.debug("tools/analysis error: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
