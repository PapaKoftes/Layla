"""
Unified intent router (single source of truth).

This module intentionally uses deterministic heuristics (no LLM calls) to produce a
RouteDecision that downstream layers decorate (tool allow-set, decision prompt hints,
model selection), rather than re-classifying the same prompt in multiple places.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

TaskType = str  # "chat" | "coding" | "research" | "reasoning" | "default"


_CODEBLOCK_RE = re.compile(r"```")
_PATHLIKE_RE = re.compile(r"([A-Za-z]:\\|/|\\\\)")
_URL_RE = re.compile(r"https?://", re.I)

_META_SELF_KW = (
    "your capabilities",
    "full capabilities",
    "what can you do",
    "what are you capable",
    "who are you",
    "introduce yourself",
    "describe yourself",
    "what tools do you have",
    "what tools can you use",
    "list your tools",
    "how do you work",
    "how does this work",
)

_RESEARCH_KW = (
    "research",
    "look up",
    "find sources",
    "citations",
    "arxiv",
    "paper",
    "evidence",
)

_ACTION_VERBS = (
    "read ",
    "open ",
    "show ",
    "write ",
    "edit ",
    "modify ",
    "apply patch",
    "replace ",
    "run ",
    "execute ",
    "install ",
    "delete ",
    "remove ",
    "grep ",
    "search code",
)


@dataclass(frozen=True)
class RouteDecision:
    task_type: TaskType
    is_meta_self: bool
    has_workspace_signals: bool
    has_path_like: bool
    has_url_like: bool
    intent_categories: list[str]
    routing_hints: list[str]
    confidence: str = "medium"  # "low" | "medium" | "high"
    multi_intent: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _has_path_like(text: str) -> bool:
    if not text:
        return False
    if _PATHLIKE_RE.search(text):
        return True
    # file extensions are often signals even without path separators
    low = text.lower()
    return any(ext in low for ext in (".py", ".ts", ".tsx", ".js", ".json", ".toml", ".yml", ".yaml", ".md"))


def _has_url_like(text: str) -> bool:
    if not text:
        return False
    return bool(_URL_RE.search(text))


def _is_meta_self(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in _META_SELF_KW)


def _detect_multi_intent(text: str) -> bool:
    low = (text or "").lower()
    if " and " not in low:
        return False
    # heuristic: meta/self + concrete file/URL mention
    if _is_meta_self(low) and (_has_path_like(low) or _has_url_like(low)):
        return True
    return False


def _default_categories() -> list[str]:
    # Kept in sync with services.intent_detection._DEFAULT_CATEGORIES (import-free here).
    return ["filesystem", "web", "code", "data", "memory", "system", "automation", "analysis"]


def route_intent(goal: str, context: str = "", workspace_root: str = "") -> RouteDecision:
    """
    Deterministically route a turn into a single TaskType and provide prompt hints.

    This should be called once per turn and reused downstream.
    """
    g = (goal or "").strip()
    c = (context or "").strip()
    combined = f"{g}\n{c}".strip()
    low = combined.lower()

    has_path = _has_path_like(combined)
    has_url = _has_url_like(combined)
    has_codeblock = bool(_CODEBLOCK_RE.search(combined))
    has_ws_root = bool((workspace_root or "").strip())
    has_workspace_signals = has_ws_root or has_path or has_url or has_codeblock

    meta_self = _is_meta_self(combined)
    multi_intent = _detect_multi_intent(combined)

    # Categories: default broad unless we have strong signals.
    intent_categories = _default_categories()
    routing_hints: list[str] = []

    # Conversation-first default when no workspace signals and no explicit action verbs.
    explicit_action = any(v in low for v in _ACTION_VERBS)

    if meta_self and not (has_path or has_url):
        task_type: TaskType = "chat"
        routing_hints.append(
            "Route=meta_self: prefer action=\"reason\". Use tools only if the operator provided a concrete file path, URL, or command."
        )
        conf = "high"
    elif any(k in low for k in _RESEARCH_KW) or has_url:
        task_type = "research"
        routing_hints.append("Route=research: use web/memory tools when needed; otherwise answer directly.")
        conf = "medium"
    else:
        # Delegate to model_router for coarse coding/reasoning/chat when not explicitly research/meta.
        try:
            from services.model_router import classify_task

            tt = str(classify_task(g, c) or "").strip().lower()
        except Exception:
            tt = ""
        if not has_workspace_signals and not explicit_action:
            task_type = "chat"
            conf = "medium"
        else:
            task_type = tt if tt in ("coding", "reasoning", "chat") else "default"
            conf = "medium"

    if not has_workspace_signals:
        routing_hints.append("Conversation-first: when no workspace signals are present, prefer action=\"reason\".")

    if multi_intent:
        routing_hints.append(
            "Multi-intent detected: prefer action=\"think\" first to split the request into two parts; then do the concrete tool request (if fully specified) and answer the meta part."
        )

    # Attach intent categories as a hint for tool filtering (downstream may override/cap).
    try:
        from services.intent_detection import detect_intent

        intent_categories = detect_intent(g)
    except Exception:
        intent_categories = _default_categories()

    return RouteDecision(
        task_type=task_type,
        is_meta_self=bool(meta_self),
        has_workspace_signals=bool(has_workspace_signals),
        has_path_like=bool(has_path),
        has_url_like=bool(has_url),
        intent_categories=list(intent_categories),
        routing_hints=routing_hints[:6],
        confidence=conf,
        multi_intent=bool(multi_intent),
    )

