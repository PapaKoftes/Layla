"""LLM decision extraction strategies (P5-4).

Extracted from agent_loop.py ``_llm_decision`` (~370 lines) to reduce file
size and enable isolated testing.

This module provides:
  * ``DecisionStrategy`` -- base class for extraction strategies
  * ``OutlinesStrategy`` -- structured generation via the outlines library
  * ``InstructorStrategy`` -- grammar-constrained JSON via the instructor library
  * ``PlainJsonStrategy`` -- plain LLM completion + JSON parsing
  * ``extract_decision`` -- facade that mirrors the original ``_llm_decision``
    signature and tries strategies in priority order

**Conservative integration note:**  The original ``_llm_decision`` in
``agent_loop.py`` is *not* removed.  This module serves as an **alternative
entry point** that can be adopted incrementally.  See the comment added to
``agent_loop.py`` near the original function.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


# ---------------------------------------------------------------------------
# Strategy base class
# ---------------------------------------------------------------------------

class DecisionStrategy:
    """Base class for LLM decision extraction strategies."""

    name: str = "base"

    def extract(
        self,
        prompt: str,
        valid_tools: frozenset[str],
        *,
        max_tokens: int = 80,
        temperature: float = 0.1,
        cfg: dict | None = None,
    ) -> dict | None:
        """Attempt to extract a structured decision dict from *prompt*.

        Returns a normalised decision dict on success, ``None`` to signal
        that the next strategy should be tried.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Strategy: Outlines (structured generation)
# ---------------------------------------------------------------------------

class OutlinesStrategy(DecisionStrategy):
    """Use the ``outlines`` library with a local Llama model for
    grammar-constrained structured output."""

    name = "outlines"

    def extract(
        self,
        prompt: str,
        valid_tools: frozenset[str],
        *,
        max_tokens: int = 80,
        temperature: float = 0.1,
        cfg: dict | None = None,
    ) -> dict | None:
        cfg = cfg or {}
        if not cfg.get("structured_generation_enabled", True):
            return None
        # Outlines requires a locally loaded Llama model and no remote server
        if (cfg.get("llama_server_url") or "").strip():
            return None
        try:
            from services.llm_gateway import _get_llm
            from services.structured_gen import run_outlines_agent_decision

            llm = _get_llm()
            if llm is None:
                return None
            decision = run_outlines_agent_decision(
                llm,
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                valid_tools=valid_tools,
            )
            if decision is not None:
                return decision
        except Exception as exc:
            logger.debug("llm_decision: OutlinesStrategy skipped: %s", exc, exc_info=False)
        return None


# ---------------------------------------------------------------------------
# Strategy: Instructor (Pydantic-constrained)
# ---------------------------------------------------------------------------

class InstructorStrategy(DecisionStrategy):
    """Use the ``instructor`` library to patch a local Llama model's
    ``create_chat_completion_openai_v1`` for Pydantic-validated output."""

    name = "instructor"

    def extract(
        self,
        prompt: str,
        valid_tools: frozenset[str],
        *,
        max_tokens: int = 80,
        temperature: float = 0.1,
        cfg: dict | None = None,
    ) -> dict | None:
        cfg = cfg or {}
        if not cfg.get("use_instructor_for_decisions", True):
            return None
        # Instructor path uses local Llama when no server URL is configured
        if (cfg.get("llama_server_url") or "").strip():
            return None
        for _attempt in range(2):
            try:
                import instructor

                from decision_schema import AgentDecision
                from services.llm_gateway import _get_llm

                llm = _get_llm()
                if llm is None:
                    return None
                create = instructor.patch(
                    create=llm.create_chat_completion_openai_v1,
                    mode=instructor.Mode.JSON_SCHEMA,
                )
                decision_obj = create(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_model=AgentDecision,
                )
                d = decision_obj.model_dump()
                action = (d.get("action") or "reason").lower()
                if action not in ("tool", "reason", "think"):
                    action = "reason"
                tool = (d.get("tool") or "").strip() or None
                if action in ("think",):
                    tool = None
                if action == "tool" and tool and tool not in valid_tools:
                    tool = None
                d["action"] = action
                d["tool"] = tool
                return d
            except Exception as exc:
                logger.debug(
                    "llm_decision: InstructorStrategy attempt %d failed: %s",
                    _attempt, exc,
                )
        return None


# ---------------------------------------------------------------------------
# Strategy: Plain JSON (completion + parse)
# ---------------------------------------------------------------------------

class PlainJsonStrategy(DecisionStrategy):
    """Fall back to a plain LLM completion and parse the JSON response."""

    name = "plain_json"

    def extract(
        self,
        prompt: str,
        valid_tools: frozenset[str],
        *,
        max_tokens: int = 80,
        temperature: float = 0.1,
        cfg: dict | None = None,
    ) -> dict | None:
        from decision_schema import parse_decision as _parse_decision
        from services.llm_gateway import run_completion

        retry_suffix = " Output only a single JSON line, no other text or commentary.\n"
        for attempt in range(2):
            effective_prompt = prompt + (retry_suffix if attempt > 0 else "")
            out = run_completion(
                effective_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
            if isinstance(out, dict):
                choices = out.get("choices") or [{}]
                first = choices[0] if choices else {}
                text = (
                    first.get("message", {}).get("content")
                    or first.get("text")
                    or ""
                )
            else:
                text = ""
            text = (text or "").strip()
            decision = _parse_decision(text, valid_tools)
            if decision is not None:
                return decision
        return None


# ---------------------------------------------------------------------------
# Default strategy chain
# ---------------------------------------------------------------------------

DEFAULT_STRATEGIES: list[DecisionStrategy] = [
    OutlinesStrategy(),
    InstructorStrategy(),
    PlainJsonStrategy(),
]


# ---------------------------------------------------------------------------
# Facade function
# ---------------------------------------------------------------------------

def extract_decision(
    prompt: str,
    valid_tools: frozenset[str],
    *,
    max_tokens: int = 80,
    temperature: float = 0.1,
    cfg: dict | None = None,
    strategies: list[DecisionStrategy] | None = None,
) -> dict | None:
    """Try each strategy in order and return the first successful decision.

    This is the **alternative entry point** for ``agent_loop._llm_decision``.
    It encapsulates only the extraction/parsing logic -- prompt *construction*
    remains in ``agent_loop.py`` because it depends on agent state, aspect
    personalities, routing hints, etc.

    Parameters
    ----------
    prompt : str
        The fully-assembled decision prompt (built by ``_llm_decision``).
    valid_tools : frozenset[str]
        Set of tool names the agent is allowed to choose from.
    max_tokens : int
        Token budget for the LLM response.
    temperature : float
        Sampling temperature.
    cfg : dict | None
        Runtime config dict (``runtime_safety.load_config()``).
    strategies : list[DecisionStrategy] | None
        Custom strategy chain.  Defaults to
        ``[OutlinesStrategy, InstructorStrategy, PlainJsonStrategy]``.

    Returns
    -------
    dict | None
        Normalised decision dict, or ``None`` if all strategies failed.
    """
    cfg = cfg or {}
    chain = strategies if strategies is not None else DEFAULT_STRATEGIES
    for strategy in chain:
        try:
            result = strategy.extract(
                prompt,
                valid_tools,
                max_tokens=max_tokens,
                temperature=temperature,
                cfg=cfg,
            )
            if result is not None:
                logger.debug("llm_decision: strategy '%s' succeeded", strategy.name)
                return result
        except Exception as exc:
            logger.debug(
                "llm_decision: strategy '%s' raised: %s",
                strategy.name, exc,
            )
    return None
