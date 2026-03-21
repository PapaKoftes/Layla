"""Human-readable comparison from ProductResult-like dicts (assist frames; kernel scores)."""

from __future__ import annotations

from typing import Any


def format_comparison_table(results: list[dict[str, Any]]) -> str:
    """Markdown table: variant, score, key metrics."""
    if not results:
        return "_No results to compare._\n"
    lines = ["| Variant | Score | Assembly | Material eff. | Machining proxy | Feasible |", "|---|---:|---:|---:|---:|:---:|"]
    for r in results:
        vid = str(r.get("variant_id", r.get("label", "?")))
        score = r.get("score", "")
        m = r.get("metrics") or {}
        if not isinstance(m, dict):
            m = {}
        a = m.get("assembly_simplicity", "")
        mat = m.get("material_efficiency", "")
        mach = m.get("machining_time_proxy", "")
        ok = "yes" if r.get("feasible", True) else "no"
        lines.append(f"| {vid} | {score} | {a} | {mat} | {mach} | {ok} |")
    return "\n".join(lines) + "\n"


def summarize_best(results: list[dict[str, Any]]) -> str:
    """Short UX copy: best-scoring variant by `score`."""
    if not results:
        return "No variants evaluated."
    best = max(results, key=lambda r: float(r.get("score") or 0.0))
    vid = best.get("label") or best.get("variant_id", "unknown")
    sc = best.get("score", "")
    notes = best.get("notes", "")
    return f"**Suggested focus:** {vid} (score {sc}). {notes}".strip()
