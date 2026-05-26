"""Tiered retry instructions for plan step execution (file + SQLite paths)."""

from __future__ import annotations

from typing import Any


def sqlite_step_retry_suffix(attempt: int, max_retries: int) -> str:
    """Append to step_goal on retries after the first attempt."""
    if attempt <= 0:
        return ""
    if attempt == 1:
        return (
            f"\n\n[Retry {attempt}/{max_retries}] Simplified pass: do ONE concrete action with minimal tools; "
            "cite paths or command output as proof."
        )
    return (
        f"\n\n[Retry {attempt}/{max_retries}] Fallback: prefer read_file/list_dir/grep_code only. "
        "If writes or tests are required but blocked, say exactly what is missing (e.g. allow_write). "
        "Do not claim success without tool evidence."
    )


def file_plan_retry_suffix(attempt: int, max_retries: int) -> str:
    """Append to full file-plan step prompt on retries."""
    if attempt <= 0:
        return ""
    if attempt == 1:
        return (
            f"\n\n[Retry {attempt}/{max_retries}] Shorter path: satisfy the step with the fewest tool calls; "
            "one verifiable outcome is enough."
        )
    return (
        f"\n\n[Retry {attempt}/{max_retries}] Read-only fallback unless the step explicitly requires mutation: "
        "summarize findings; if mutation is required, list blockers instead of assuming changes."
    )


def step_title_desc(step: Any) -> tuple[str, str]:
    t = str(getattr(step, "title", None) or "").strip()
    d = str(getattr(step, "description", None) or "").strip()
    return t, d
