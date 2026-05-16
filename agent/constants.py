"""Shared constants used across the Layla agent codebase.

Centralizes magic numbers, default timeouts, size limits, and keyword lists
that were previously scattered across modules. Import from here instead of
redefining in each file.
"""
from __future__ import annotations

# ── File size / reading limits ───────────────────────────────────────────────
MAX_SAFE_READ_BYTES: int = 250 * 1024       # ~250 KB — planning signal for large files
LARGE_FILE_HINT_LINES: int = 2000           # files with more lines get a "large file" hint
MAX_MESSAGE_LENGTH: int = 100_000           # max user message length (Pydantic validation)
MAX_IMAGE_BASE64_LENGTH: int = 10_000_000   # max base64 image payload (~7.5 MB decoded)

# ── Subprocess / tool timeouts ───────────────────────────────────────────────
DEFAULT_TOOL_TIMEOUT_S: int = 120           # default subprocess timeout (seconds)
DEFAULT_AGENT_TIMEOUT_MS: int = 120_000     # default agent request timeout (milliseconds)
MAX_AGENT_TIMEOUT_MS: int = 600_000         # maximum allowed agent timeout (10 minutes)

# ── Agent loop limits ────────────────────────────────────────────────────────
DEFAULT_MAX_TOOL_CALLS: int = 5             # normal mode
RESEARCH_MAX_TOOL_CALLS: int = 20           # research mode
DEFAULT_MAX_RUNTIME_S: int = 900            # normal mode (15 min)
RESEARCH_MAX_RUNTIME_S: int = 1800          # research mode (30 min)
DEFAULT_TEMPERATURE: float = 0.2

# ── Reasoning modes ─────────────────────────────────────────────────────────
VALID_REASONING_MODES: tuple[str, ...] = (
    "auto", "solo", "debate", "council", "tribunal",
)

# ── Memory / learning ───────────────────────────────────────────────────────
LEARNING_RATE_LIMIT: int = 20               # max saves per window
LEARNING_RATE_WINDOW_S: float = 60.0        # rate limit window
MAX_LEARNING_CONTENT_LENGTH: int = 240      # truncation limit for saved learnings
DEFAULT_RETENTION_DAYS: int = 90            # default data retention (days)

# ── Scheduler intervals ─────────────────────────────────────────────────────
BACKUP_INTERVAL_HOURS: int = 24
REINDEX_INTERVAL_MINUTES: int = 30
CLEANUP_INTERVAL_HOURS: int = 24
DEFAULT_STUDY_INTERVAL_MINUTES: int = 30

# ── Security ─────────────────────────────────────────────────────────────────
LOCALHOST_HOSTS: frozenset[str] = frozenset((
    "127.0.0.1", "::1", "localhost", "0.0.0.0", "testclient",
))
ALLOWED_URL_SCHEMES: frozenset[str] = frozenset(("https", "git"))
SLUG_PATTERN: str = r"^[a-zA-Z0-9_-]+$"

# ── Keyword sets ─────────────────────────────────────────────────────────────
GREETING_WORDS: frozenset[str] = frozenset((
    "hi", "hello", "hey", "thanks", "thank", "ok", "okay",
    "yes", "no", "sure", "cool",
))
