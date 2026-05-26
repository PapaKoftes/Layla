"""
Knowledge distiller: periodically compress multiple learnings into higher-level insights.
Stores distilled knowledge as learnings. Complements layla.memory.distill (merge similar).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def distill_learnings_to_insights(n: int = 20) -> dict[str, Any]:
    """
    Compress recent learnings into higher-level insights.
    Uses LLM when available; fallback to rule extraction from distill.
    Returns {insights_added, learnings_processed, error}.
    """
    try:
        from layla.memory.db import get_recent_learnings
        from services.memory_router import save_learning  # canonical write path
        learnings = get_recent_learnings(n=n)
        if len(learnings) < 3:
            return {"insights_added": 0, "learnings_processed": len(learnings)}

        contents = [(L.get("content") or "").strip() for L in learnings if (L.get("content") or "").strip()]
        if len(contents) < 3:
            return {"insights_added": 0, "learnings_processed": len(learnings)}

        # Try LLM to synthesize higher-level insight
        try:
            from services.llm_gateway import run_completion
            sample = "\n".join(f"- {c[:150]}" for c in contents[:10])
            prompt = (
                f"From these learnings:\n{sample}\n\n"
                "Synthesize 1-2 higher-level insights or patterns (one sentence each). "
                "Output only the insight sentences, one per line."
            )
            out = run_completion(prompt, max_tokens=200, temperature=0.2, stream=False)
            if isinstance(out, dict):
                text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "") or ""
                if text and len(text.strip()) > 20:
                    lines = [ln.strip() for ln in text.strip().split("\n") if len(ln.strip()) > 15]
                    added = 0
                    for line in lines[:2]:
                        if line and not line.startswith("-"):
                            save_learning(content=f"Insight: {line[:400]}", kind="strategy", source="knowledge_distiller")
                            added += 1
                    return {"insights_added": added, "learnings_processed": len(learnings)}
        except Exception as e:
            logger.debug("knowledge distiller LLM skipped: %s", e)

        # Fallback: use distill rules
        from layla.memory.distill import distill_rules
        rules = distill_rules(learnings, max_rules=2)
        for r in rules:
            if r and len(r) > 20:
                save_learning(content=f"Pattern: {r[:400]}", kind="strategy", source="knowledge_distiller")
        return {"insights_added": len(rules), "learnings_processed": len(learnings)}
    except Exception as e:
        logger.debug("knowledge distiller failed: %s", e)
        return {"insights_added": 0, "learnings_processed": 0, "error": str(e)}


def run_periodic_distillation() -> dict[str, Any]:
    """
    Entry point for scheduler or manual trigger.
    Runs knowledge distillation on recent learnings.
    """
    return distill_learnings_to_insights(n=25)
