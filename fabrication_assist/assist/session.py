"""Local JSON session for assist runs: history, variants, outcomes, preferences."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fabrication_assist.assist.errors import SessionIOError

# fabrication_assist/.assist_sessions/ (gitignored)
_ASSIST_SESSIONS_DIR = Path(__file__).resolve().parent.parent / ".assist_sessions"

MAX_SESSION_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_KEYS_ESTIMATE = 50_000


@dataclass
class AssistSession:
    """Persisted assist state. All fields are JSON-serializable."""

    history: list[dict[str, Any]] = field(default_factory=list)
    variants: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)

    def merge_outcomes(self, new_outcomes: list[dict[str, Any]]) -> None:
        self.outcomes.extend(new_outcomes)

    def merge_preferences(self, updates: dict[str, Any]) -> None:
        self.preferences.update(updates)

    def append_history(self, entry: dict[str, Any]) -> None:
        self.history.append(entry)


def _json_structure_guard(obj: Any, depth: int = 0, key_count: list[int] | None = None) -> None:
    """Reject absurd nesting or huge object graphs (metadata-only sessions)."""
    if key_count is None:
        key_count = [0]
    if depth > MAX_JSON_DEPTH:
        raise SessionIOError(f"session JSON exceeds max depth {MAX_JSON_DEPTH}")
    if isinstance(obj, dict):
        for _k, v in obj.items():
            key_count[0] += 1
            if key_count[0] > MAX_JSON_KEYS_ESTIMATE:
                raise SessionIOError("session JSON has too many keys")
            _json_structure_guard(v, depth + 1, key_count)
    elif isinstance(obj, list):
        for item in obj:
            _json_structure_guard(item, depth + 1, key_count)


def default_session_path(name: str = "default") -> Path:
    """Return path to `fabrication_assist/.assist_sessions/<name>.json`."""
    _ASSIST_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return _ASSIST_SESSIONS_DIR / f"{name}.json"


def load_session(path: Path | None = None) -> AssistSession:
    """Load session from JSON; missing file returns empty session. Corrupt/oversized raises SessionIOError."""
    p = path or default_session_path()
    if not p.exists():
        return AssistSession()
    try:
        st = p.stat()
    except OSError as e:
        raise SessionIOError(f"cannot stat session file: {e}", cause=e) from e
    if st.st_size > MAX_SESSION_BYTES:
        raise SessionIOError(f"session file too large ({st.st_size} bytes; max {MAX_SESSION_BYTES})")
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise SessionIOError(f"cannot read session file: {e}", cause=e) from e
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise SessionIOError(f"session JSON is invalid: {e}", cause=e) from e
    if not isinstance(raw, dict):
        raise SessionIOError("session root must be a JSON object")
    _json_structure_guard(raw)
    return AssistSession(
        history=list(raw.get("history") or []),
        variants=list(raw.get("variants") or []),
        outcomes=list(raw.get("outcomes") or []),
        preferences=dict(raw.get("preferences") or {}),
    )


def save_session(session: AssistSession, path: Path | None = None) -> Path:
    """Write session atomically via temp file + replace."""
    p = path or default_session_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        payload = json.dumps(asdict(session), indent=2)
        if len(payload.encode("utf-8")) > MAX_SESSION_BYTES:
            raise SessionIOError("session serializes larger than max allowed size")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(p)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise SessionIOError(f"cannot write session file: {e}", cause=e) from e
    return p
