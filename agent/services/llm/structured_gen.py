"""
Optional structured generation for agent decisions.

Tries ``outlines`` + llama-cpp-python when installed (wheels for Python 3.11–3.12).
Falls back to instructor / plain completion in ``agent_loop._llm_decision``.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def outlines_available() -> bool:
    try:
        import outlines  # noqa: F401

        return True
    except ImportError:
        return False


def _normalize_outlines_result(raw: Any, valid_tools: frozenset[str]) -> dict | None:
    """Turn outlines / pydantic output into the decision dict shape used by the loop."""
    try:
        if hasattr(raw, "model_dump"):
            d = raw.model_dump()
        elif isinstance(raw, dict):
            d = dict(raw)
        else:
            return None
        action = (d.get("action") or "reason").lower().strip()
        if action not in ("tool", "reason", "none", "think"):
            action = "reason"
        tool = (d.get("tool") or "").strip() or None
        if action in ("none", "think"):
            tool = None
        elif action == "tool" and tool and tool not in valid_tools:
            tool = None
        args = d.get("args")
        if not isinstance(args, dict):
            args = {}
        batch_raw = d.get("batch_tools")
        batch_tools: list[dict] = []
        if isinstance(batch_raw, list):
            for bt in batch_raw:
                if isinstance(bt, dict):
                    bt_name = (bt.get("tool") or "").strip()
                    bt_args = bt.get("args") if isinstance(bt.get("args"), dict) else {}
                    if bt_name and bt_name in valid_tools:
                        batch_tools.append({"tool": bt_name, "args": bt_args})
        pl = (d.get("priority_level") or "").strip().lower()
        if pl not in ("low", "medium", "high"):
            pl = "medium"
        return {
            "action": action,
            "tool": tool,
            "args": args,
            "batch_tools": batch_tools,
            "thought": (str(d.get("thought")).strip()[:4000] if d.get("thought") else None),
            "objective_complete": bool(d.get("objective_complete", False)),
            "revised_objective": (str(d.get("revised_objective") or "").strip()[:500] or None),
            "priority_level": pl,
            "impact_estimate": (str(d.get("impact_estimate") or "").strip()[:80] or None),
            "effort_estimate": (str(d.get("effort_estimate") or "").strip()[:80] or None),
            "risk_estimate": (str(d.get("risk_estimate") or "").strip()[:80] or None),
        }
    except Exception as e:
        logger.debug("structured_gen: normalize failed: %s", e)
        return None


def run_outlines_agent_decision(
    llm: Any,
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
    valid_tools: frozenset[str],
) -> dict | None:
    """
    Run one structured decision via outlines + local Llama instance.
    Returns None if outlines is missing or generation fails.
    """
    if not outlines_available():
        return None
    try:
        from decision_schema import AgentDecision
    except Exception as e:
        logger.debug("structured_gen: AgentDecision import: %s", e)
        return None

    # Outlines API has shifted across versions; try a few entry points.
    try:
        raw = None
        # outlines >= 1.x style (common): models.llamacpp + generate.json
        try:
            import outlines.generate as og
            import outlines.models as om

            model = None
            if hasattr(om, "llamacpp"):
                model = om.llamacpp(llm)
            elif hasattr(om, "LlamaCpp"):
                model = om.LlamaCpp(llm)  # type: ignore[misc]

            if model is not None:
                if hasattr(og, "json"):
                    gen = og.json(model, AgentDecision)
                else:
                    gen = None
                if gen is not None:
                    # Call signature varies: try keyword then positional
                    try:
                        raw = gen(prompt, max_tokens=max_tokens, temperature=temperature)
                    except TypeError:
                        try:
                            raw = gen(prompt, max_tokens=max_tokens)
                        except TypeError:
                            raw = gen(prompt)
        except Exception as e:
            logger.debug("structured_gen: outlines llamacpp path: %s", e)

        # outlines 0.0.x alternate: from outlines import generate; generate.json(model, schema)
        if raw is None:
            try:
                import outlines.models as om2
                from outlines import generate as gen_mod  # type: ignore

                m2 = om2.llamacpp(llm) if hasattr(om2, "llamacpp") else om2.LlamaCpp(llm)  # type: ignore
                g2 = gen_mod.json(m2, AgentDecision)
                try:
                    raw = g2(prompt, max_tokens=max_tokens, temperature=temperature)
                except TypeError:
                    raw = g2(prompt)
            except Exception as e:
                logger.debug("structured_gen: outlines alt path: %s", e)

        if raw is None:
            return None
        return _normalize_outlines_result(raw, valid_tools)
    except Exception as e:
        logger.debug("structured_gen: run_outlines_agent_decision failed: %s", e)
        return None
