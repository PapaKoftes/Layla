# -*- coding: utf-8 -*-
"""
Multi-aspect deliberation engine.

Modes:
  SOLO     - current behavior (1 aspect, no change)
  DEBATE   - 2 aspects argue opposing positions, synthesize
  COUNCIL  - 3 aspects deliberate, weighted vote
  TRIBUNAL - all 6 aspects weigh in (expensive, rare)

Each mode follows a 3-phase pipeline:
  1. Independent generation - each aspect generates its response
  2. Cross-critique - each aspect evaluates the others' responses
  3. Synthesis - merge into a unified response with noted disagreements

Usage:
    from services.debate_engine import run_deliberation

    result = run_deliberation(
        goal="Should I refactor or rewrite?",
        state={},
        cfg=runtime_safety.load_config(),
    )
    # result.final_response, result.mode, result.synthesis_notes, etc.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Aspect domain mapping -- which aspects are best suited for which task types
# ---------------------------------------------------------------------------

ASPECT_DOMAINS: dict[str, list[str]] = {
    "morrigan":  ["code", "engineering", "implementation", "architecture", "debugging", "deploy"],
    "nyx":       ["research", "analysis", "investigation", "depth", "synthesis", "knowledge"],
    "echo":      ["empathy", "communication", "people", "feelings", "teaching", "patterns"],
    "eris":      ["creativity", "alternatives", "disruption", "brainstorm", "unconventional"],
    "cassandra": ["perception", "anomaly", "contradiction", "prediction", "review", "risk"],
    "lilith":    ["ethics", "boundaries", "safety", "autonomy", "consent", "governance"],
}

ALL_ASPECT_IDS: list[str] = list(ASPECT_DOMAINS.keys())

# ---------------------------------------------------------------------------
# Auto-trigger keyword patterns for mode detection
# ---------------------------------------------------------------------------

_DEBATE_TRIGGERS: list[str] = [
    "should i", "trade-off", "tradeoff", "compare", "pros and cons",
    "versus", " vs ", "which is better", "weigh",
]

_COUNCIL_TRIGGERS: list[str] = [
    "ethical", "risky", "dangerous", "controversial", "help me decide",
    "moral", "dilemma", "concern", "sensitive", "harm",
]

_TRIBUNAL_TRIGGERS: list[str] = [
    "comprehensive review", "full analysis", "all perspectives",
    "every angle", "thorough assessment", "complete evaluation",
]

# ---------------------------------------------------------------------------
# Mode constants
# ---------------------------------------------------------------------------

MODE_SOLO = "solo"
MODE_DEBATE = "debate"
MODE_COUNCIL = "council"
MODE_TRIBUNAL = "tribunal"

_MODE_ASPECT_COUNTS = {
    MODE_SOLO: 1,
    MODE_DEBATE: 2,
    MODE_COUNCIL: 3,
    MODE_TRIBUNAL: 6,
}

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DeliberationResult:
    """Structured output from a multi-aspect deliberation."""

    mode: str                                            # "solo" | "debate" | "council" | "tribunal"
    final_response: str                                  # Synthesized response
    aspect_responses: dict[str, str] = field(default_factory=dict)   # {aspect_id: response_text}
    critiques: dict[str, str] = field(default_factory=dict)          # {aspect_id: critique_text}
    participating_aspects: list[str] = field(default_factory=list)   # aspect IDs
    synthesis_notes: str = ""                             # Key agreements/disagreements


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_deliberation_mode(goal: str, state: dict, cfg: dict) -> str:
    """
    Auto-detect the best deliberation mode based on the goal text.

    Precedence: TRIBUNAL > COUNCIL > DEBATE > SOLO.
    Returns one of: "solo", "debate", "council", "tribunal".
    """
    if not goal:
        return MODE_SOLO

    gl = goal.lower()

    # Check tribunal triggers first (most expensive, highest bar)
    for trigger in _TRIBUNAL_TRIGGERS:
        if trigger in gl:
            return MODE_TRIBUNAL

    # Council triggers
    for trigger in _COUNCIL_TRIGGERS:
        if trigger in gl:
            return MODE_COUNCIL

    # Debate triggers
    for trigger in _DEBATE_TRIGGERS:
        if trigger in gl:
            return MODE_DEBATE

    # Fallback: use word count as a complexity heuristic
    word_count = len(gl.split())
    if word_count > 80:
        return MODE_COUNCIL
    if word_count > 40:
        return MODE_DEBATE

    return MODE_SOLO


def select_aspects_for_task(
    goal: str,
    mode: str,
    cfg: dict,
    *,
    exclude: list[str] | None = None,
) -> list[str]:
    """
    Pick the most relevant aspects for the task domain.

    Scores each aspect by keyword overlap between the goal and its domain list.
    Returns the top N aspects for the mode (2 for debate, 3 for council, 6 for tribunal).
    Always returns at least 1 aspect (morrigan as fallback).
    """
    n = _MODE_ASPECT_COUNTS.get(mode, 1)
    if n <= 1:
        return ["morrigan"]

    gl = goal.lower()
    exclude_set = set(exclude or [])

    # Score each aspect by domain keyword hits
    scores: list[tuple[float, str]] = []
    for aid, domains in ASPECT_DOMAINS.items():
        if aid in exclude_set:
            continue
        score = sum(1.0 for d in domains if d in gl)
        scores.append((score, aid))

    # Sort by score descending, then alphabetically for stability
    scores.sort(key=lambda x: (-x[0], x[1]))

    selected = [aid for _, aid in scores[:n]]

    # Guarantee morrigan is always included (she synthesizes)
    if "morrigan" not in selected and "morrigan" not in exclude_set:
        selected[-1] = "morrigan"

    # For tribunal mode, include all aspects
    if mode == MODE_TRIBUNAL:
        selected = [aid for aid in ALL_ASPECT_IDS if aid not in exclude_set]

    return selected


def _get_max_workers(cfg: dict) -> int:
    """Return the max parallel LLM workers from config, default 3."""
    try:
        return max(1, int(cfg.get("debate_max_workers", 3)))
    except (TypeError, ValueError):
        return 3


def _parallel_llm_calls(
    callables: list[tuple],
    max_workers: int = 3,
) -> list:
    """Run multiple LLM calls in parallel using ThreadPoolExecutor.

    *callables* is a list of ``(fn, args_tuple, kwargs_dict)`` triples.
    Returns results in the **same order** as the input list.
    Falls back to sequential execution when *max_workers* <= 1.
    """
    if max_workers <= 1:
        # Sequential fallback
        results = []
        for fn, args, kwargs in callables:
            try:
                results.append(fn(*args, **kwargs))
            except Exception as e:
                results.append({"error": str(e)})
        return results

    results: list = [None] * len(callables)
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = {
            pool.submit(fn, *args, **kwargs): idx
            for idx, (fn, args, kwargs) in enumerate(callables)
        }
        try:
            for f in as_completed(futures, timeout=55):
                idx = futures[f]
                try:
                    results[idx] = f.result(timeout=10)
                except Exception as e:
                    logger.warning("debate_engine: parallel call %d failed: %s", idx, e)
                    results[idx] = {"error": str(e)}
        except TimeoutError:
            logger.warning("debate_engine: parallel calls timed out after 55s")
            for f in futures:
                f.cancel()
    finally:
        # shutdown(wait=False) so we don't block if threads are stuck in native code
        pool.shutdown(wait=False, cancel_futures=True)
    return results


def run_deliberation(
    goal: str,
    state: dict,
    cfg: dict,
    *,
    mode: str = "auto",
    aspects: list[str] | None = None,
) -> DeliberationResult:
    """
    Main entry point for multi-aspect deliberation.

    Args:
        goal:     The user's request / question.
        state:    Current agent state dict.
        cfg:      Runtime config dict.
        mode:     "auto" to auto-detect, or explicit "solo"|"debate"|"council"|"tribunal".
        aspects:  Explicit aspect list override (None = auto-select).

    Returns:
        DeliberationResult with the synthesized response and metadata.
    """
    # Phase 0: determine mode
    if mode == "auto":
        mode = select_deliberation_mode(goal, state, cfg)

    if mode == MODE_SOLO:
        # Solo mode: single aspect, no pipeline
        aspect_id = (aspects or ["morrigan"])[0]
        text = _generate_aspect_response(goal, aspect_id, state, cfg)
        return DeliberationResult(
            mode=MODE_SOLO,
            final_response=text,
            aspect_responses={aspect_id: text},
            critiques={},
            participating_aspects=[aspect_id],
            synthesis_notes="",
        )

    # Phase 0b: select participating aspects
    if aspects is None:
        aspects = select_aspects_for_task(goal, mode, cfg)

    # Phase 1: Independent generation (parallel)
    max_workers = _get_max_workers(cfg)
    phase1_calls = [
        (_generate_aspect_response, (goal, aid, state, cfg), {})
        for aid in aspects
    ]
    phase1_results = _parallel_llm_calls(phase1_calls, max_workers=max_workers)

    aspect_responses: dict[str, str] = {}
    for aid, result in zip(aspects, phase1_results):
        if isinstance(result, dict) and "error" in result:
            logger.warning("debate_engine: aspect %s generation failed: %s", aid, result["error"])
            aspect_responses[aid] = f"[{aid} was unable to respond]"
        elif isinstance(result, str):
            aspect_responses[aid] = result
        else:
            aspect_responses[aid] = str(result) if result else f"[{aid} was unable to respond]"

    # Phase 2: Cross-critique (parallel — requires Phase 1 results)
    phase2_calls = [
        (_generate_critiques, (goal, aspect_responses, aid, state, cfg), {})
        for aid in aspects
    ]
    phase2_results = _parallel_llm_calls(phase2_calls, max_workers=max_workers)

    critiques: dict[str, str] = {}
    for aid, result in zip(aspects, phase2_results):
        if isinstance(result, dict) and "error" in result:
            logger.warning("debate_engine: aspect %s critique failed: %s", aid, result["error"])
            critiques[aid] = ""
        elif isinstance(result, str):
            critiques[aid] = result
        else:
            critiques[aid] = ""

    # Phase 3: Synthesis
    try:
        final_response, synthesis_notes = _synthesize(
            goal, aspect_responses, critiques, state, cfg,
        )
    except Exception as exc:
        logger.warning("debate_engine: synthesis failed: %s", exc)
        # Fallback: concatenate available aspect responses
        valid = [f"[{aid}] {r}" for aid, r in aspect_responses.items() if r and "unable to respond" not in r.lower()]
        final_response = "\n\n".join(valid) if valid else "[All aspects were unable to respond]"
        synthesis_notes = "synthesis_failed"

    return DeliberationResult(
        mode=mode,
        final_response=final_response,
        aspect_responses=aspect_responses,
        critiques=critiques,
        participating_aspects=list(aspects),
        synthesis_notes=synthesis_notes,
    )


# ---------------------------------------------------------------------------
# Internal: LLM call helpers
# ---------------------------------------------------------------------------


def _extract_text(result: dict | str) -> str:
    """Extract text content from run_completion result."""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        choices = result.get("choices") or [{}]
        first = choices[0] if choices else {}
        msg = first.get("message") or {}
        text = msg.get("content") or first.get("text") or ""
        return text.strip()
    return ""


def _load_aspect_personality(aspect_id: str) -> dict:
    """Load personality dict for an aspect, with fallback."""
    try:
        from orchestrator import _load_aspects
        aspects = _load_aspects()
        for a in aspects:
            if a.get("id") == aspect_id:
                return a
    except Exception as exc:
        logger.debug("debate_engine: failed to load personality for %s: %s", aspect_id, exc)
    return {"id": aspect_id, "name": aspect_id.capitalize(), "role": "", "voice": ""}


def _build_aspect_system_prompt(aspect: dict) -> str:
    """Build a short system prompt from the aspect personality."""
    name = aspect.get("name", aspect.get("id", "Layla"))
    role = aspect.get("role", "")
    voice = aspect.get("voice", "")
    addition = aspect.get("systemPromptAddition", "")

    parts = [f"You are {name}, an aspect of Layla."]
    if role:
        parts.append(f"Role: {role}")
    if voice:
        parts.append(f"Voice: {voice}")
    if addition:
        parts.append(addition[:500])
    return "\n".join(parts)


def _get_completion_params(cfg: dict) -> dict:
    """Extract LLM parameters from config with debate-appropriate defaults."""
    return {
        "max_tokens": int(cfg.get("debate_max_tokens", 800)),
        "temperature": float(cfg.get("debate_temperature", 0.7)),
        "stream": False,
    }


def _generate_aspect_response(
    goal: str,
    aspect_id: str,
    state: dict,
    cfg: dict,
) -> str:
    """
    Phase 1: Generate a single aspect's independent response to the goal.
    """
    from services.llm_gateway import run_completion

    aspect = _load_aspect_personality(aspect_id)
    sys_prompt = _build_aspect_system_prompt(aspect)
    name = aspect.get("name", aspect_id.capitalize())

    prompt = (
        f"{sys_prompt}\n\n"
        f"The user asks: {goal}\n\n"
        f"Respond as {name}. Give your perspective on this question. "
        f"Be direct, stay in character, and focus on your area of expertise.\n"
        f"{name}:"
    )

    params = _get_completion_params(cfg)
    result = run_completion(prompt, **params)
    return _extract_text(result)


def _generate_critiques(
    goal: str,
    responses: dict[str, str],
    aspect_id: str,
    state: dict,
    cfg: dict,
) -> str:
    """
    Phase 2: An aspect critiques the other aspects' responses.

    Each aspect reads what the others said and provides constructive critique,
    identifying strengths, weaknesses, and blind spots.
    """
    from services.llm_gateway import run_completion

    aspect = _load_aspect_personality(aspect_id)
    name = aspect.get("name", aspect_id.capitalize())

    # Build the other responses block
    others_block = ""
    for other_id, resp in responses.items():
        if other_id == aspect_id:
            continue
        other_aspect = _load_aspect_personality(other_id)
        other_name = other_aspect.get("name", other_id.capitalize())
        # Truncate long responses for the critique prompt
        truncated = resp[:600] if len(resp) > 600 else resp
        others_block += f"\n[{other_name}]: {truncated}\n"

    if not others_block.strip():
        return ""

    sys_prompt = _build_aspect_system_prompt(aspect)
    prompt = (
        f"{sys_prompt}\n\n"
        f"User question: {goal}\n\n"
        f"Other aspects have responded:\n{others_block}\n"
        f"As {name}, briefly critique these responses. "
        f"What did they get right? What are they missing? "
        f"What blind spots or risks do you see? Be constructive but honest. "
        f"Keep your critique to 2-4 sentences.\n"
        f"{name}'s critique:"
    )

    params = _get_completion_params(cfg)
    params["max_tokens"] = min(params["max_tokens"], 400)  # critiques should be shorter
    result = run_completion(prompt, **params)
    return _extract_text(result)


def _synthesize(
    goal: str,
    responses: dict[str, str],
    critiques: dict[str, str],
    state: dict,
    cfg: dict,
) -> tuple[str, str]:
    """
    Phase 3: Merge all aspect responses and critiques into a unified response.

    Returns (final_response, synthesis_notes).
    Morrigan leads the synthesis by default (implementation authority).
    """
    from services.llm_gateway import run_completion

    # Build the full deliberation transcript
    responses_block = ""
    for aid, resp in responses.items():
        aspect = _load_aspect_personality(aid)
        name = aspect.get("name", aid.capitalize())
        truncated = resp[:800] if len(resp) > 800 else resp
        responses_block += f"\n[{name}]: {truncated}\n"

    critiques_block = ""
    for aid, crit in critiques.items():
        if not crit.strip():
            continue
        aspect = _load_aspect_personality(aid)
        name = aspect.get("name", aid.capitalize())
        critiques_block += f"\n[{name}'s critique]: {crit[:400]}\n"

    prompt = (
        "You are Layla. Multiple aspects of your consciousness have deliberated on a question.\n\n"
        f"User question: {goal}\n\n"
        f"Aspect responses:\n{responses_block}\n"
    )
    if critiques_block.strip():
        prompt += f"Cross-critiques:\n{critiques_block}\n"

    prompt += (
        "Now synthesize these perspectives into one unified response for the user.\n"
        "Rules:\n"
        "- Lead with the strongest consensus point.\n"
        "- Note any significant disagreements transparently.\n"
        "- If aspects raised valid risks or concerns, acknowledge them.\n"
        "- Write as Layla (unified voice), not as individual aspects.\n"
        "- Be direct and actionable.\n\n"
        "After your response, on a new line starting with 'SYNTHESIS_NOTES:', "
        "briefly list key agreements and disagreements between aspects (1-3 bullet points).\n\n"
        "Layla:"
    )

    params = _get_completion_params(cfg)
    params["max_tokens"] = int(cfg.get("debate_synthesis_max_tokens", 1200))
    result = run_completion(prompt, **params)
    raw = _extract_text(result)

    # Split out synthesis notes if present
    final_response = raw
    synthesis_notes = ""

    notes_match = re.search(
        r"SYNTHESIS_NOTES:\s*(.+)",
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    if notes_match:
        synthesis_notes = notes_match.group(1).strip()
        final_response = raw[:notes_match.start()].strip()

    return final_response, synthesis_notes
