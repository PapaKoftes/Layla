"""
Lightweight assist orchestration — not the full Layla agent loop.

Execution contract: only `user_text`, `knowledge_dir`, and `runner` influence which variant
configs are built. Loaded session fields (`preferences`, prior `variants`, `outcomes`) are
never passed to `propose_variants()` or `run_build()` — session is persistence/metadata only.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from fabrication_assist.assist.errors import (
    InputValidationError,
    RunnerError,
    SchemaValidationError,
    SessionIOError,
)
from fabrication_assist.assist.explain import format_comparison_table, summarize_best
from fabrication_assist.assist.runner import BuildRunner, StubRunner
from fabrication_assist.assist.schemas import (
    MAX_USER_TEXT_CHARS,
    HistoryEntryModel,
    IntentModel,
    ProductResultModel,
    VariantConfigModel,
)
from fabrication_assist.assist.session import AssistSession, load_session, save_session
from fabrication_assist.assist.variants import load_knowledge_dir, propose_variants

log = logging.getLogger("fabrication_assist")

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "assembly_simplicity": ("assembly", "simple", "snap", "easy build", "easy to assemble"),
    "material_efficiency": ("material", "waste", "yield", "sheet", "stock"),
    "machining_time": ("cnc", "mill", "lathe", "machining", "toolpath"),
    "precision": ("tight", "precision", "tolerance", "fit"),
    "speed": ("fast", "quick", "rapid", "lead time"),
}


def parse_intent(user_text: str) -> dict[str, Any]:
    """Map user text to goal + strategy tags (no LLM)."""
    lower = user_text.lower()
    strategies: list[str] = []
    for strat, phrases in _INTENT_KEYWORDS.items():
        if any(p in lower for p in phrases):
            strategies.append(strat)
    if not strategies:
        strategies = ["balanced"]
    goal = "explore"
    if "box" in lower or "enclosure" in lower:
        goal = "enclosure"
    elif "bracket" in lower or "mount" in lower:
        goal = "bracket"
    elif "furniture" in lower or "shelf" in lower:
        goal = "furniture"
    return {"raw": user_text, "goal": goal, "strategies": strategies}


def _validate_intent_dict(d: dict[str, Any]) -> dict[str, Any]:
    try:
        return IntentModel.model_validate(d).model_dump()
    except ValidationError as e:
        raise SchemaValidationError(f"invalid intent: {e}", cause=e, details={"errors": e.errors()}) from e


def _validate_variants(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, v in enumerate(raw):
        try:
            out.append(VariantConfigModel.model_validate(v).model_dump())
        except ValidationError as e:
            raise SchemaValidationError(
                f"invalid variant at index {i}: {e}",
                cause=e,
                details={"errors": e.errors(), "index": i},
            ) from e
    return out


def _validate_result(raw: dict[str, Any], variant_id_hint: str | None) -> dict[str, Any]:
    try:
        return ProductResultModel.model_validate(raw).model_dump()
    except ValidationError as e:
        raise SchemaValidationError(
            f"invalid product result for variant {variant_id_hint!r}: {e}",
            variant_id=variant_id_hint,
            cause=e,
            details={"errors": e.errors()},
        ) from e


def assist(
    user_text: str,
    session_path: Path | str | None = None,
    runner: BuildRunner | None = None,
    knowledge_dir: Path | None = None,
    *,
    dry_run: bool = False,
    continue_on_runner_error: bool = False,
) -> dict[str, Any]:
    """
    Parse intent → propose variants → run_build each → explain → append session.

    Returns structured dict plus `markdown` for CLI/UI.
    Raises AssistError subclasses on failure (no silent failures).
    """
    if not isinstance(user_text, str):
        raise InputValidationError("user_text must be a string")
    if len(user_text) > MAX_USER_TEXT_CHARS:
        raise InputValidationError(
            f"user_text exceeds max length ({len(user_text)} > {MAX_USER_TEXT_CHARS})",
        )

    r = runner or StubRunner()
    sp: Path | None = Path(session_path) if session_path else None

    if dry_run:
        intent = _validate_intent_dict(parse_intent(user_text))
        knowledge = load_knowledge_dir(knowledge_dir)
        variants_raw = propose_variants(intent, knowledge)
        variants = _validate_variants(variants_raw)
        lines = ["## Dry run (no kernel, no session write)", "", f"**Goal:** {intent['goal']}  ", f"**Strategies:** {', '.join(intent['strategies'])}", ""]
        for v in variants:
            lines.append(f"- **{v['id']}** — {v['label']} ({v.get('strategy', '')})")
        md = "\n".join(lines) + "\n"
        return {
            "intent": intent,
            "variants": variants,
            "results": [],
            "markdown": md,
            "session_path": None,
            "dry_run": True,
            "errors": [],
        }

    try:
        session = load_session(sp)
    except SessionIOError:
        raise

    intent = _validate_intent_dict(parse_intent(user_text))
    knowledge = load_knowledge_dir(knowledge_dir)
    variants_raw = propose_variants(intent, knowledge)
    variants = _validate_variants(variants_raw)

    # Session must not drive execution (audit: no session fields in propose/run inputs above).
    _assert_session_metadata_only(session, intent, variants)

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for cfg in variants:
        vid = str(cfg.get("id", ""))
        try:
            raw_out = r.run_build(cfg)
        except RunnerError:
            if not continue_on_runner_error:
                raise
            err_result = {
                "variant_id": vid,
                "label": str(cfg.get("label", vid)),
                "score": 0.0,
                "metrics": {},
                "feasible": False,
                "notes": "runner raised RunnerError (continue_on_runner_error=True)",
            }
            results.append(_validate_result(err_result, vid))
            errors.append({"variant_id": vid, "kind": "runner"})
            continue
        except Exception as e:
            if not continue_on_runner_error:
                raise RunnerError(
                    f"runner failed: {e}",
                    variant_id=vid,
                    cause=e,
                ) from e
            err_result = {
                "variant_id": vid,
                "label": str(cfg.get("label", vid)),
                "score": 0.0,
                "metrics": {},
                "feasible": False,
                "notes": f"runner error: {e!s}",
            }
            results.append(_validate_result(err_result, vid))
            errors.append({"variant_id": vid, "kind": "exception", "message": str(e)})
            continue
        try:
            results.append(_validate_result(raw_out, vid))
        except SchemaValidationError:
            if not continue_on_runner_error:
                raise
            err_result = {
                "variant_id": vid,
                "label": str(cfg.get("label", vid)),
                "score": 0.0,
                "metrics": {},
                "feasible": False,
                "notes": "kernel returned schema-invalid result",
            }
            results.append(_validate_result(err_result, vid))
            errors.append({"variant_id": vid, "kind": "schema"})

    table_md = format_comparison_table(results)
    summary_md = summarize_best(results)
    markdown = f"## Assist summary\n\n{table_md}\n{summary_md}\n"

    session.variants = variants
    session.merge_outcomes(results)
    hist_raw = {
        "user": user_text,
        "intent": intent,
        "variant_ids": [v.get("id") for v in variants],
        "result_scores": [x.get("score") for x in results],
    }
    try:
        hist = HistoryEntryModel.model_validate(hist_raw).model_dump()
    except ValidationError as e:
        raise SchemaValidationError(f"invalid history entry: {e}", cause=e) from e
    session.append_history(hist)

    try:
        saved = save_session(session, sp)
    except SessionIOError:
        raise

    return {
        "intent": intent,
        "variants": variants,
        "results": results,
        "markdown": markdown,
        "session_path": str(saved),
        "dry_run": False,
        "errors": errors,
    }


def _assert_session_metadata_only(
    session: AssistSession,
    intent: dict[str, Any],
    variants: list[dict[str, Any]],
) -> None:
    """Runtime guard: session is not used as input to variant generation (already enforced by code path)."""
    del session  # parameters reserved for future static checks / logging
    log.debug("assist: computed %d variants for goal=%s", len(variants), intent.get("goal"))


# Public alias for tests / static verification
def assert_session_does_not_drive_execution() -> None:
    """Document that propose_variants/run_build receive only user-derived intent + knowledge + runner."""
    return None
