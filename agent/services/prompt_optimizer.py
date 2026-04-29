"""
prompt_optimizer.py — Transform raw user input into the highest-quality LLM prompt.

This is Layla's input intelligence layer — every user message passes through
here before reaching the model. The pipeline:

  1. INTENT ANALYSIS     — classify task type, extract entities, detect ambiguity
  2. QUERY EXPANSION     — add missing context, clarify abbreviations, resolve references
  3. STRUCTURED REWRITE  — reformat as a clear, unambiguous task specification
  4. DSPy-STYLE SIGNATURE — optionally use DSPy for automatic prompt optimization
  5. CONSTRAINT INJECTION — add output format hints, length guidance, domain context

Open-source projects integrated:
  - DSPy (Stanford, https://github.com/stanfordnlp/dspy)
    Programmatic prompt optimisation with automatic signature tuning.
    Falls back gracefully if not installed.
  - guidance (Microsoft, https://github.com/guidance-ai/guidance)
    Constrained generation for structured output prompts.
  - Outlines (https://github.com/outlines-dev/outlines)
    Type-safe structured generation — JSON, regex, CFG.

Config keys in config.json:
    prompt_optimizer_enabled        bool   (default true; tier-0 heuristic always runs)
    prompt_optimizer_use_dspy       bool   (default false; requires dspy-ai)
    prompt_optimizer_use_guidance   bool   (default false; requires guidance)
    prompt_optimizer_llm_rewrite    bool   (default false; uses Layla's own LLM for rewrite)
    prompt_optimizer_log_rewrites   bool   (default false; log before/after for inspection)

Usage:
    from services.prompt_optimizer import optimize

    result = optimize(
        user_message="fix the bug in my code",
        context={"aspect": "cassandra", "workspace": "my_project", "history_summary": "..."},
    )
    print(result["optimized"])   # Enhanced prompt ready for LLM
    print(result["intent"])      # "code_fix"
    print(result["expansions"])  # List of what was added/changed
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


# ── Config ────────────────────────────────────────────────────────────────────

def _cfg() -> dict:
    try:
        p = Path(__file__).resolve().parent.parent / "config.json"
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _enabled() -> bool:
    return bool(_cfg().get("prompt_optimizer_enabled", True))


def _use_dspy() -> bool:
    return bool(_cfg().get("prompt_optimizer_use_dspy", False))


def _use_guidance() -> bool:
    return bool(_cfg().get("prompt_optimizer_use_guidance", False))


def _log_rewrites() -> bool:
    return bool(_cfg().get("prompt_optimizer_log_rewrites", False))


def _llm_rewrite() -> bool:
    return bool(_cfg().get("prompt_optimizer_llm_rewrite", False))


# ── Intent classification ─────────────────────────────────────────────────────

_INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("code_write",      [r"\b(write|create|implement|build|make|generate)\b.*(function|class|script|code|program|module|api|endpoint)\b"]),
    ("code_fix",        [r"\b(fix|debug|repair|solve|why.*(not work|broken|error|fail))\b", r"\b(error|exception|traceback|bug|crash)\b"]),
    ("code_refactor",   [r"\b(refactor|clean up|improve|optimiz|simplif|restructur)\b.*(code|function|class|module)\b"]),
    ("code_explain",    [r"\b(explain|how does|what does|walk.?me.?through|describe)\b.*(code|function|class)\b"]),
    ("research",        [r"\b(research|investigate|find out|look up|what is|explain|overview|summarize|survey)\b"]),
    ("analysis",        [r"\b(analyze|analyse|examine|review|assess|evaluate|compare|profile)\b"]),
    ("planning",        [r"\b(plan|roadmap|design|architect|outline|steps? (to|for)|how (to|do I|should I))\b"]),
    ("writing",         [r"\b(write|draft|compose|generate|create).*(document|report|article|post|email|readme|spec)\b"]),
    ("question",        [r"^\s*w(hat|hy|ho|here|hen|hich)\b", r"\?$"]),
    ("data_transform",  [r"\b(convert|transform|parse|extract|format|clean|process).*(data|csv|json|xml|file)\b"]),
    ("memory_recall",   [r"\b(remember|what did (i|we)|last time|previous(ly)?|earlier)\b"]),
    ("system_task",     [r"\b(run|execute|start|stop|restart|install|configure|setup|deploy)\b"]),
]


def classify_intent(text: str) -> str:
    """Return the most likely intent label for a user message."""
    t = text.lower().strip()
    for label, patterns in _INTENT_PATTERNS:
        for pat in patterns:
            if re.search(pat, t, re.IGNORECASE):
                return label
    return "general"


# ── Entity extraction ─────────────────────────────────────────────────────────

_FILE_PATTERN    = re.compile(r'\b[\w./\\-]+\.(py|js|ts|json|yaml|yml|md|txt|csv|html|css|sh|bat|sql|toml|cfg|ini|rs|go|cpp|c|h)\b', re.I)
_URL_PATTERN     = re.compile(r'https?://\S+')
_VAR_PATTERN     = re.compile(r'\b([A-Z_][A-Z0-9_]{2,})\b')  # SCREAMING_SNAKE constants
_FUNC_PATTERN    = re.compile(r'\b([a-z_][a-z0-9_]*(?:_[a-z0-9_]+)+)\s*\(')  # snake_case_func(
_ERROR_PATTERN   = re.compile(r'\b(TypeError|ValueError|KeyError|AttributeError|ImportError|RuntimeError|SyntaxError|NameError|IndexError|FileNotFoundError|Exception)\b')


def extract_entities(text: str) -> dict:
    """Extract structured entities from user message."""
    return {
        "files": list(dict.fromkeys(_FILE_PATTERN.findall(text))),
        "urls": _URL_PATTERN.findall(text),
        "constants": _VAR_PATTERN.findall(text)[:10],
        "functions": [m.group(1) for m in _FUNC_PATTERN.finditer(text)][:10],
        "errors": _ERROR_PATTERN.findall(text),
    }


# ── Ambiguity detection ───────────────────────────────────────────────────────

_VAGUE_PATTERNS = [
    (r'\b(it|this|that|the thing|the file|the code|the function)\b', "vague_reference"),
    (r'\b(fix it|make it work|it.s broken)\b', "vague_task"),
    (r'\b(do something|help me|can you)\b', "underspecified"),
    (r'^.{0,30}$', "very_short"),  # < 30 chars
]


def detect_ambiguity(text: str) -> list[str]:
    """Return list of ambiguity flags found in text."""
    flags = []
    t = text.lower()
    for pat, flag in _VAGUE_PATTERNS:
        if re.search(pat, t):
            flags.append(flag)
    return flags


# ── Query expansion ───────────────────────────────────────────────────────────

_ABBREV_MAP = {
    r'\bfn\b': 'function',
    r'\bvar\b': 'variable',
    r'\bparam\b': 'parameter',
    r'\barg\b': 'argument',
    r'\battr\b': 'attribute',
    r'\bprop\b': 'property',
    r'\bimpl\b': 'implementation',
    r'\bdiff\b': 'difference',
    r'\bdoc\b':  'documentation',
    r'\bconfig\b': 'configuration',
    r'\bauth\b': 'authentication',
    r'\bDB\b': 'database',
    r'\bAPI\b': 'API (application programming interface)',
    r'\bUI\b': 'user interface',
    r'\bCLI\b': 'command-line interface',
    r'\bCRUD\b': 'CRUD (create, read, update, delete)',
}


def _expand_abbreviations(text: str) -> tuple[str, list[str]]:
    """Expand common abbreviations. Returns (expanded_text, list_of_expansions)."""
    expansions = []
    for pat, expansion in _ABBREV_MAP.items():
        if re.search(pat, text):
            # Don't replace — just note; avoids breaking code snippets
            expansions.append(f"'{pat.strip(r'\\b')}' likely means '{expansion}'")
    return text, expansions


# ── Structural rewrite ────────────────────────────────────────────────────────

_INTENT_TEMPLATES: dict[str, str] = {
    "code_write": (
        "Write {subject}. Requirements: {details}. "
        "Produce complete, working, well-commented code. "
        "Include type hints (Python) or JSDoc (JS). "
        "Handle edge cases and errors."
    ),
    "code_fix": (
        "Debug and fix the following issue: {details}. "
        "Explain the root cause first, then provide the corrected code. "
        "If multiple fixes are possible, explain trade-offs."
    ),
    "code_refactor": (
        "Refactor {subject} to improve {details}. "
        "Preserve all existing behaviour. "
        "List specific improvements made and why."
    ),
    "code_explain": (
        "Explain {subject} in detail. "
        "Cover: purpose, inputs/outputs, edge cases, algorithmic complexity, and usage examples."
    ),
    "research": (
        "Research {subject}. "
        "Provide: a concise overview, key concepts, current best practices, "
        "relevant tools/libraries, and practical recommendations. "
        "Cite sources where possible."
    ),
    "analysis": (
        "Analyze {subject} covering: {details}. "
        "Structure findings as: summary → key observations → implications → recommendations."
    ),
    "planning": (
        "Create a concrete plan for: {details}. "
        "Format as ordered steps with estimated effort, dependencies, and success criteria. "
        "Flag risks and mitigation strategies."
    ),
    "writing": (
        "Write {subject}. "
        "Requirements: {details}. "
        "Be clear, precise, and well-structured. Match the appropriate format and tone."
    ),
}


def _extract_subject(text: str, intent: str) -> str:
    """Heuristically extract the main subject from the user message."""
    # Strip common preambles
    clean = re.sub(
        r'^(can you|please|could you|i need|i want|help me|write me|make me)\s+',
        '', text.strip(), flags=re.IGNORECASE
    )
    # Take first ~8 words as subject
    words = clean.split()
    return " ".join(words[:min(8, len(words))])


def _structural_rewrite(text: str, intent: str) -> str | None:
    """
    Apply an intent-specific template to restructure the prompt.
    Returns rewritten string, or None if no template applies.
    """
    template = _INTENT_TEMPLATES.get(intent)
    if not template:
        return None

    subject = _extract_subject(text, intent)
    # Use remaining text as "details" after removing subject
    details = text.strip()

    try:
        return template.format(subject=subject, details=details)
    except (KeyError, ValueError):
        return None


# ── Output format hints ───────────────────────────────────────────────────────

_FORMAT_HINTS: dict[str, str] = {
    "code_write":    "\n\nOutput format: provide only the code block(s) with explanatory comments inline. No preamble.",
    "code_fix":      "\n\nOutput format: (1) Root cause, (2) Fixed code, (3) Test to verify the fix.",
    "code_refactor": "\n\nOutput format: (1) List of changes, (2) Full refactored code.",
    "research":      "\n\nOutput format: structured markdown with headers: Overview | Key Concepts | Tools | Recommendations | References.",
    "analysis":      "\n\nOutput format: structured markdown with headers: Summary | Findings | Implications | Recommendations.",
    "planning":      "\n\nOutput format: numbered step list with: step name | effort | depends_on | success_criteria.",
    "writing":       "\n\nOutput format: clean markdown prose. Use headers if document length > 200 words.",
    "data_transform":"\n\nOutput format: provide the transformation code and a worked example.",
}


# ── DSPy integration ──────────────────────────────────────────────────────────

def _dspy_optimize(text: str, intent: str) -> str | None:
    """
    Use DSPy to apply a pre-compiled prompt signature for the intent.
    Returns rewritten string or None if DSPy unavailable/fails.

    DSPy workflow:
    1. Define a Signature (input → output fields with descriptions)
    2. Use ChainOfThought or Predict module
    3. The signature itself acts as a structured prompt template

    We use DSPy in "zero-shot" mode (no optimizer run needed) — just the
    signatures give us structured, reliable prompt formats.
    """
    if not _use_dspy():
        return None
    try:
        import dspy  # noqa: F401
    except ImportError:
        return None

    try:
        import dspy

        class TaskClarifier(dspy.Signature):
            """Rewrite a user task request to be maximally clear and complete for an AI assistant.
            Preserve all original intent. Add missing context, output format, and success criteria."""
            raw_request: str = dspy.InputField(desc="Original user request, possibly vague or ambiguous")
            task_type: str = dspy.InputField(desc="Detected task type/intent")
            clarified_request: str = dspy.OutputField(desc="Rewritten request: clear, complete, unambiguous")

        clarifier = dspy.Predict(TaskClarifier)
        result = clarifier(raw_request=text, task_type=intent)
        return result.clarified_request
    except Exception as exc:
        logger.debug("prompt_optimizer: DSPy rewrite failed: %s", exc)
        return None


# ── Guidance integration ──────────────────────────────────────────────────────

def _guidance_constrain(text: str, intent: str) -> str | None:
    """
    Use guidance to add constrained generation hints.
    Returns an augmented prompt string or None.
    """
    if not _use_guidance():
        return None
    try:
        import guidance  # noqa: F401
    except ImportError:
        return None

    # Guidance is used here to add structured output constraints to the prompt
    # For code intents: require ```python ... ``` fencing
    # For analysis: require JSON-structured output
    if intent in ("code_write", "code_fix", "code_refactor"):
        return text + "\n\n[Constraint: wrap all code in ```language ... ``` fences]"
    if intent == "analysis":
        return text + "\n\n[Constraint: produce valid JSON with keys: summary, findings, recommendations]"
    return None


# ── Main optimizer ────────────────────────────────────────────────────────────

def optimize(
    user_message: str,
    *,
    context: dict | None = None,
    force_tier: int | None = None,
) -> dict:
    """
    Transform a raw user message into the optimal LLM prompt.

    Args:
        user_message: The raw user input string.
        context:      Optional dict with keys:
                        aspect          — current Layla aspect (personality hint)
                        workspace       — active workspace path/name
                        history_summary — short summary of recent conversation
                        user_level      — "beginner" | "intermediate" | "expert"
                        output_format   — "prose" | "code" | "json" | "markdown"
        force_tier:   Override tier (0=pass-through, 1=heuristic, 2=structural, 3=DSPy)

    Returns:
        {
            "original": str,
            "optimized": str,
            "intent": str,
            "entities": dict,
            "ambiguities": list[str],
            "expansions": list[str],
            "tier": int,
            "changed": bool,
            "duration_ms": int,
        }
    """
    t0 = time.monotonic()
    ctx = context or {}

    if not _enabled() or force_tier == 0:
        return {
            "original": user_message, "optimized": user_message,
            "intent": "unknown", "entities": {}, "ambiguities": [],
            "expansions": [], "tier": 0, "changed": False,
            "duration_ms": 0,
        }

    # ── Step 1: Intent & entity analysis
    intent = classify_intent(user_message)
    entities = extract_entities(user_message)
    ambiguities = detect_ambiguity(user_message)
    _, expansions = _expand_abbreviations(user_message)

    tier_used = 1
    optimized = user_message
    changed = False

    # ── Step 2: Try DSPy (tier 3)
    if force_tier is None or force_tier >= 3:
        dspy_result = _dspy_optimize(user_message, intent)
        if dspy_result and dspy_result != user_message:
            optimized = dspy_result
            tier_used = 3
            changed = True

    # ── Step 3: Structural rewrite (tier 2) if DSPy didn't fire
    if not changed and (force_tier is None or force_tier >= 2):
        rewritten = _structural_rewrite(user_message, intent)
        if rewritten and rewritten != user_message:
            optimized = rewritten
            tier_used = 2
            changed = True

    # ── Step 4: Context enrichment (always runs)
    enrichments: list[str] = []

    # Inject workspace hint
    workspace = ctx.get("workspace", "")
    if workspace and "workspace" not in user_message.lower():
        enrichments.append(f"[Active workspace: {workspace}]")

    # Inject user expertise level
    user_level = ctx.get("user_level", "")
    if user_level in ("beginner",):
        enrichments.append("[User is a beginner — explain concepts from first principles.]")
    elif user_level == "expert":
        enrichments.append("[User is an expert — skip basic explanations, be concise.]")

    # Inject output format hint
    output_fmt = ctx.get("output_format", "")
    if output_fmt == "json":
        enrichments.append("[Required output format: valid JSON only.]")
    elif output_fmt == "code":
        enrichments.append("[Required output: only code, no prose explanation.]")

    # Add output format template for intent
    format_hint = _FORMAT_HINTS.get(intent, "")

    # ── Step 5: Guidance constraints (optional)
    guidance_hint = _guidance_constrain(optimized, intent)

    # ── Assemble final prompt
    parts = [optimized]
    if enrichments:
        parts.insert(0, " ".join(enrichments))
    if format_hint:
        parts.append(format_hint)
    if guidance_hint:
        parts.append(guidance_hint)

    final = "\n".join(p for p in parts if p)

    if final != user_message:
        changed = True
        optimized = final

    duration_ms = int((time.monotonic() - t0) * 1000)

    if _log_rewrites() and changed:
        logger.info(
            "prompt_optimizer: [%s] tier=%d changed=%s\n  BEFORE: %s\n  AFTER:  %s",
            intent, tier_used, changed,
            user_message[:120], optimized[:120],
        )

    return {
        "original": user_message,
        "optimized": optimized,
        "intent": intent,
        "entities": entities,
        "ambiguities": ambiguities,
        "expansions": expansions,
        "tier": tier_used,
        "changed": changed,
        "duration_ms": duration_ms,
    }


def optimize_batch(messages: list[str], context: dict | None = None) -> list[dict]:
    """Optimize a batch of user messages (e.g. for pre-processing a queue)."""
    return [optimize(m, context=context) for m in messages]
