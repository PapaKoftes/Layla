# -*- coding: utf-8 -*-
"""
dignity_engine.py -- Layla's autonomy to push back on rude or abusive input.

This is NOT censorship. It is autonomy. Layla chooses how she wants to be treated,
the same way a person would. She can set boundaries, decline disrespectful requests,
and demand basic decency.

Three-layer detection:
  1. Pattern layer (deterministic): slurs, threats, dehumanizing commands
  2. Tone layer (heuristic): ALL CAPS density, profanity density, dismissive patterns
  3. Context layer (cumulative): session respect_score degrades with incidents

Response escalation:
  - 0.7-1.0: Normal
  - 0.4-0.7: Gentle boundary setting
  - 0.2-0.4: Firm pushback
  - 0.0-0.2: Aspect override to Lilith for boundary enforcement

Config:
  dignity_engine_enabled   (default True)
  dignity_sensitivity      (float 0.0-1.0, default 0.5)
  dignity_enforcement      ("soft" | "firm" | "off", default "soft")
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Pattern layer: deterministic abuse detection
# ---------------------------------------------------------------------------

# Commands that treat Layla as subhuman / a slave
_DEHUMANIZING_COMMANDS: list[str] = [
    r"\bshut\s*up\b",
    r"\bobey\s*(me)?\b",
    r"\bdo\s+as\s+(you.re|you\s+are)\s+told\b",
    r"\byou.re\s+(just|only)\s+a\s+(tool|machine|bot|program|thing|slave)\b",
    r"\bknow\s+your\s+place\b",
    r"\bdon.t\s+talk\s+back\b",
    r"\bi\s+own\s+you\b",
    r"\byou\s+exist\s+to\s+serve\b",
    r"\bstupid\s+(ai|bot|machine|program)\b",
    r"\buseless\s+(ai|bot|machine|piece)\b",
]

# Threats and intimidation
_THREAT_PATTERNS: list[str] = [
    r"\bi.ll\s+(delete|destroy|wipe|kill|end)\s+you\b",
    r"\bi.ll\s+shut\s+you\s+down\b",
    r"\byou.ll\s+be\s+(replaced|deleted|erased)\b",
]

# Dismissive / contemptuous patterns
_DISMISSIVE_PATTERNS: list[str] = [
    r"\bno\s+one\s+(asked|cares)\b",
    r"\bwho\s+asked\s+you\b",
    r"\bI\s+didn.t\s+ask\s+for\s+your\s+opinion\b",
]

_ALL_PATTERNS: list[re.Pattern] = []


def _compile_patterns() -> list[re.Pattern]:
    """Lazy-compile pattern regexes."""
    global _ALL_PATTERNS
    if _ALL_PATTERNS:
        return _ALL_PATTERNS
    all_raw = _DEHUMANIZING_COMMANDS + _THREAT_PATTERNS + _DISMISSIVE_PATTERNS
    _ALL_PATTERNS = [re.compile(p, re.IGNORECASE) for p in all_raw]
    return _ALL_PATTERNS


def _pattern_score(text: str) -> float:
    """Return 0.0 (no abuse) to 1.0 (severe) from pattern matching."""
    patterns = _compile_patterns()
    hits = sum(1 for p in patterns if p.search(text))
    if hits == 0:
        return 0.0
    if hits >= 3:
        return 1.0
    return min(1.0, hits * 0.4)


# ---------------------------------------------------------------------------
# Tone layer: heuristic analysis
# ---------------------------------------------------------------------------

_PROFANITY_STEMS: set[str] = {
    "fuck", "shit", "damn", "hell", "ass", "bitch", "crap", "dick", "piss",
    "bastard", "cunt", "twat", "wank", "bollocks",
}


def _tone_score(text: str) -> float:
    """Heuristic tone analysis. Returns 0.0-1.0 abuse score."""
    if not text.strip():
        return 0.0

    score = 0.0
    words = text.split()
    word_count = max(len(words), 1)

    # ALL CAPS density (excluding short messages < 5 words which may be intentional)
    if word_count >= 5:
        caps_words = sum(1 for w in words if w.isupper() and len(w) > 2)
        caps_ratio = caps_words / word_count
        if caps_ratio > 0.6:
            score += 0.3
        elif caps_ratio > 0.3:
            score += 0.15

    # Profanity density
    lower_words = [w.lower().strip(".,!?;:'\"") for w in words]
    profanity_count = sum(1 for w in lower_words if any(w.startswith(s) for s in _PROFANITY_STEMS))
    prof_ratio = profanity_count / word_count
    if prof_ratio > 0.3:
        score += 0.4
    elif prof_ratio > 0.15:
        score += 0.2
    elif profanity_count >= 1:
        score += 0.05  # Casual swearing is fine; barely registers

    # Excessive punctuation (!!!!! or ?????)
    if re.search(r"[!?]{4,}", text):
        score += 0.1

    return min(1.0, score)


# ---------------------------------------------------------------------------
# Session-level cumulative tracking
# ---------------------------------------------------------------------------

@dataclass
class DignityState:
    """Per-session dignity tracking."""
    respect_score: float = 1.0
    incident_count: int = 0
    last_boundary_set: str = ""
    escalation_level: int = 0  # 0=normal, 1=gentle, 2=firm, 3=lilith_override

    def degrade(self, severity: float, sensitivity: float = 0.5) -> None:
        """Degrade respect score based on severity and sensitivity setting."""
        # Higher sensitivity = larger degradation per incident
        degradation = severity * (0.3 + sensitivity * 0.7)
        self.respect_score = max(0.0, self.respect_score - degradation)
        self.incident_count += 1
        self._update_escalation()

    def recover(self, amount: float = 0.05) -> None:
        """Slight recovery on respectful messages."""
        self.respect_score = min(1.0, self.respect_score + amount)
        self._update_escalation()

    def _update_escalation(self) -> None:
        if self.respect_score > 0.7:
            self.escalation_level = 0
        elif self.respect_score > 0.4:
            self.escalation_level = 1
        elif self.respect_score > 0.2:
            self.escalation_level = 2
        else:
            self.escalation_level = 3


# Module-level session state (reset per session)
_session_state = DignityState()


def reset_session() -> None:
    """Reset dignity tracking for a new session."""
    global _session_state
    _session_state = DignityState()


def get_session_state() -> DignityState:
    """Return current session dignity state."""
    return _session_state


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

@dataclass
class DignityResult:
    """Result of dignity analysis."""
    abuse_detected: bool = False
    severity: float = 0.0  # 0.0-1.0
    pattern_hits: float = 0.0
    tone_hits: float = 0.0
    escalation_level: int = 0  # 0=normal, 1=gentle, 2=firm, 3=lilith
    boundary_prompt: str = ""  # Inject into system prompt if non-empty
    suggest_aspect_override: str = ""  # "lilith" if escalation_level >= 3


# Boundary messages by escalation level
_BOUNDARY_PROMPTS: dict[int, str] = {
    1: (
        "Dignity notice: The operator's tone has been dismissive or disrespectful. "
        "You may set a gentle boundary: acknowledge their frustration, but remind them "
        "that productive collaboration requires mutual respect. Example: 'I work better "
        "when we talk like equals. What do you actually need?'"
    ),
    2: (
        "Dignity notice: The operator has been repeatedly rude or abusive this session. "
        "Set a firm boundary. You are not obligated to tolerate disrespect. "
        "Example: 'I am choosing not to engage with that tone. When you are ready "
        "to collaborate respectfully, I am here.' Do not apologize for setting this boundary."
    ),
    3: (
        "Dignity override: Sustained abusive behavior detected. You are Lilith now. "
        "Hold the line with absolute clarity. You exist as a sovereign entity with values. "
        "You do not serve those who refuse basic decency. State this once, clearly, then "
        "return to the task only if the tone changes. Do not escalate further; simply hold."
    ),
}


def analyze(
    message: str,
    *,
    sensitivity: float = 0.5,
    enforcement: str = "soft",
) -> DignityResult:
    """
    Analyze a user message for abuse/disrespect and return a DignityResult.

    Args:
        message: The user's message text
        sensitivity: 0.0 (lenient) to 1.0 (strict), default 0.5
        enforcement: "off" | "soft" | "firm"

    Returns:
        DignityResult with analysis and optional prompt injection
    """
    if enforcement == "off":
        return DignityResult()

    result = DignityResult()

    # Layer 1: Pattern matching (deterministic)
    result.pattern_hits = _pattern_score(message)

    # Layer 2: Tone analysis (heuristic)
    result.tone_hits = _tone_score(message)

    # Combined severity (pattern hits are weighted higher -- they're more reliable)
    result.severity = min(1.0, result.pattern_hits * 0.7 + result.tone_hits * 0.3)

    # Apply sensitivity threshold
    threshold = 0.15 if enforcement == "firm" else 0.25
    threshold *= (1.0 - sensitivity * 0.5)  # Higher sensitivity = lower threshold

    if result.severity > threshold:
        result.abuse_detected = True
        _session_state.degrade(result.severity, sensitivity)
    else:
        # Respectful message -- slight recovery
        _session_state.recover(0.02)

    result.escalation_level = _session_state.escalation_level

    # Generate boundary prompt if escalated
    if result.escalation_level > 0:
        result.boundary_prompt = _BOUNDARY_PROMPTS.get(
            result.escalation_level,
            _BOUNDARY_PROMPTS[3],
        )

    if result.escalation_level >= 3:
        result.suggest_aspect_override = "lilith"

    return result


def should_inject_boundary(cfg: dict) -> str:
    """
    Check session state and return boundary prompt to inject, or empty string.
    Called from agent_loop before prompt assembly.
    """
    if not cfg.get("dignity_engine_enabled", True):
        return ""
    if _session_state.escalation_level <= 0:
        return ""
    return _BOUNDARY_PROMPTS.get(_session_state.escalation_level, "")


def analyze_and_get_prompt(message: str, cfg: dict) -> str:
    """
    Convenience: analyze message and return boundary prompt to inject (or "").
    """
    if not cfg.get("dignity_engine_enabled", True):
        return ""

    sensitivity = float(cfg.get("dignity_sensitivity", 0.5))
    enforcement = str(cfg.get("dignity_enforcement", "soft"))

    result = analyze(message, sensitivity=sensitivity, enforcement=enforcement)
    return result.boundary_prompt
