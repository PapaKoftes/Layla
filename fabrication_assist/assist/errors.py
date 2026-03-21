"""Typed errors for assist orchestration and CLI exit mapping."""

from __future__ import annotations

from typing import Any


class AssistError(Exception):
    """Base assist failure; carries optional variant context for runners."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "assist",
        variant_id: str | None = None,
        cause: BaseException | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.variant_id = variant_id
        self.cause_exc = cause
        self.details = details or {}


class InputValidationError(AssistError):
    """User input or args failed validation (CLI exit 2)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="input_validation", **kwargs)


class RunnerError(AssistError):
    """Subprocess/kernel failed or timed out (CLI exit 3)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="runner", **kwargs)


class SchemaValidationError(AssistError):
    """Pydantic or structural validation failed (CLI exit 4)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="schema", **kwargs)


class SessionIOError(AssistError):
    """Session file corrupt, too large, or unreadable (CLI exit 5)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, kind="session_io", **kwargs)
