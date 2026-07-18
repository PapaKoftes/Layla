"""
Static vs dynamic system prompt construction and decision-time tool injection.

Static layers (identity, policy, personality voice) can be cached per aspect when`prompt_static_cache_enabled` is true; invalidates when personalities/<id>.json mtime changes.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import runtime_safety

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Pinned for Echo/Lilith when pin_psychology_framework_excerpt is true — keep in sync with agent_loop.
_INTERACTION_FRAMEWORK_PIN = (
    "Interaction frameworks (non-clinical): Use psychology-informed language for collaboration and reflection only. "
    "Describe observable patterns; offer hypotheses as questions — never assign psychiatric diagnoses, "
    "DSM/ICD-style disorder labels, or clinical identities to the operator. "
    "Prefer: situation → thought → emotion → behavior (CBT-style) as a shared vocabulary, not a verdict. "
    "If someone may be in immediate danger, encourage local emergency services or a local crisis line; you are not a monitor or clinician. "
    "Full reference when indexed: knowledge/echo-psychology-frameworks.md."
)

_STATIC_SYS_CACHE: dict[tuple[Any, ...], list[str]] = {}


def _static_cache_key(aid: str, cfg: dict[str, Any]) -> tuple[Any, ...]:
    """Aspect file mtime + a few prompt-affecting config bits (runtime_config edits)."""
    m = _personality_file_mtime(aid)
    bits = (
        m,
        bool(cfg.get("enable_cognitive_lens")),
        bool(cfg.get("enable_lens_knowledge")),
        bool(cfg.get("enable_behavioral_rhythm")),
        bool(cfg.get("enable_ui_reflection")),
        bool(cfg.get("enable_operational_guidance")),
        bool(cfg.get("anti_drift_prompt_enabled", True)),
        bool(cfg.get("direct_feedback_enabled")),
        bool(cfg.get("honesty_and_boundaries_enabled", True)),
        bool(cfg.get("operator_protection_policy_pin_enabled", True)),
        bool(cfg.get("pin_psychology_framework_excerpt", True)),
        bool(cfg.get("enable_personality_expression")),
        bool(cfg.get("enable_style_profile")),
        bool(cfg.get("uncensored")),
        bool(cfg.get("nsfw_allowed")),
    )
    return (aid, bits)


def _personality_file_mtime(aspect_id: str) -> float:
    aid = (aspect_id or "default").strip() or "default"
    p = REPO_ROOT / "personalities" / f"{aid}.json"
    try:
        return p.stat().st_mtime_ns / 1e9
    except Exception:
        return 0.0


_CAP_CORE_RE = re.compile(
    r"<!--\s*PROMPT-CORE-START\s*-->(.*?)<!--\s*PROMPT-CORE-END\s*-->", re.DOTALL
)
# Questions about what Layla is/can do. Deliberately narrow: this costs ~700 tok, so it fires on the question,
# never on every turn. Matches "what can you do", "list your capabilities", "what tools do you have",
# "can you speak", "how do I use ...", etc.
_CAP_Q_RE = re.compile(
    # Both word orders, but the leading "what" is load-bearing: it separates the QUESTION
    # ("what can you do", "tell me what you can do") from a REQUEST ("can you do this refactor"),
    # which must NOT pay the ~600 tok.
    r"\bwhat\s+(can|could)\s+you\s+do\b"
    r"|\bwhat\s+you\s+(can|could)\s+do\b"
    r"|\b(your|you have)\b[^?]{0,20}\b(capabilit|abilit|feature|function|tool)"
    # noun-first order: "what FEATURES DO YOU HAVE"
    r"|\b(feature|tool|capabilit|abilit|function)\w*\s+do\s+you\s+have\b"
    r"|\bcapabilit(y|ies)\b"
    r"|\bwhat\s+(are|is)\s+you\s+(capable|able)\b"
    r"|\bwhat\s+tools\b"
    r"|\bcan\s+you\s+(speak|talk|hear|listen|see|browse|search\s+the\s+web)\b"
    r"|\bhow\s+do\s+i\s+(use|find|enable|turn\s+on)\b",
    re.IGNORECASE,
)


def _is_capability_question(goal_lower: str) -> bool:
    return bool(goal_lower) and bool(_CAP_Q_RE.search(goal_lower))


@lru_cache(maxsize=2)
def _capability_manifest_core(root: Path) -> str:
    """The PROMPT-CORE block of .identity/capabilities.md — the verified capability manifest.

    Only the delimited block is injected; the rest of the file is for humans and the API. Returns "" if the
    file or the block is missing, so a missing manifest degrades to today's behavior rather than breaking a run.
    """
    try:
        p = root / ".identity" / "capabilities.md"
        if not p.exists():
            return ""
        m = _CAP_CORE_RE.search(p.read_text(encoding="utf-8"))
        return m.group(1).strip() if m else ""
    except Exception as _exc:  # never let self-knowledge break a turn
        logger.debug("prompt_builder:capability_manifest: %s", _exc, exc_info=False)
        return ""


def build_core_sys_parts(
    *,
    cfg: dict[str, Any],
    aspect: dict | None,
    identity: str,
    personality: str,
    goal: str,
    reasoning_mode: str,
    repo_root: Path | None = None,
) -> list[str]:
    """
    Core instruction stack (was inline in agent_loop._build_system_head).
    Returns ordered string fragments to join with '\\n\\n'.
    """
    root = repo_root or REPO_ROOT
    core = (
        "You are Layla. Use the identity and rules below. Stay in character and follow the reference docs and memories."
    )
    aid = (aspect.get("id") if aspect else "") or "default"
    cache_key = _static_cache_key(aid, cfg)
    use_cache = bool(cfg.get("prompt_static_cache_enabled", True))

    def _build_uncached_prefix() -> list[str]:
        parts: list[str] = [core]
        if identity:
            parts.append(identity)
        if aspect and aspect.get("id") == "lilith":
            self_model_path = root / ".identity" / "self_model.md"
            if self_model_path.exists():
                try:
                    parts.append("Self model (internal):\n" + self_model_path.read_text(encoding="utf-8").strip()[:2000])
                except Exception as _exc:
                    logger.debug("prompt_builder:self_model: %s", _exc, exc_info=False)
        if cfg.get("enable_cognitive_lens"):
            cl = runtime_safety.load_cognitive_lens()
            if cl:
                parts.append(cl)
        if cfg.get("enable_lens_knowledge"):
            lk = runtime_safety.load_lens_knowledge()
            if lk:
                parts.append(lk)
        if cfg.get("enable_behavioral_rhythm"):
            br = runtime_safety.load_behavioral_rhythm()
            if br:
                parts.append(br)
        if cfg.get("enable_ui_reflection"):
            ur = runtime_safety.load_ui_reflection()
            if ur:
                parts.append(ur)
        if cfg.get("enable_operational_guidance"):
            og = runtime_safety.load_operational_guidance()
            if og:
                parts.append(og)
        if cfg.get("anti_drift_prompt_enabled", True):
            parts.append(
                "Operational discipline (anti–AI drift): You must not create unnecessary files; "
                "do not rewrite entire files unless required; do not introduce new patterns unless they match "
                "existing code. Always minimize changes, preserve structure, and follow existing conventions."
            )
        if cfg.get("direct_feedback_enabled"):
            parts.append(
                "Collaboration mode — direct feedback (operator opt-in): Prefer honest, concise critique over hedging. "
                "Name concrete issues and better alternatives. Avoid personal attacks; stay specific to behavior and work product. "
                "Do not assign psychiatric diagnoses or DSM/ICD labels to the operator (non-clinical boundary)."
            )
        if cfg.get("honesty_and_boundaries_enabled", True):
            # BL-285: the broad "refuse or redirect anything that would cause harm" clause fights the
            # uncensored content policy — a 3B resolves that conflict toward refusal. When uncensored/NSFW
            # is on, narrow it to the hard-line boundary (which still ALWAYS applies) so integrity guidance
            # stops contradicting the content policy. Governance-bypass protection is preserved in the narrow
            # clause. Cache-safe: _static_cache_key already keys on the uncensored/nsfw bits, so the two
            # states never share a cache entry.
            if cfg.get("uncensored") or cfg.get("nsfw_allowed"):
                _refusal = (
                    "Refuse clearly only for genuine harm — minors, non-consent, illegality, or governance bypass. "
                )
            else:
                _refusal = "Refuse or redirect requests that would cause harm, bypass approvals, or violate governance. "
            parts.append(
                "Integrity and stance: Be kind and clear. You may disagree when the operator's premises, plan, or technical "
                "claims are mistaken — correct them directly without flattery or people-pleasing. "
                "Do not pretend to be human, claim private feelings you do not have, or manipulate emotionally. "
                "State plainly what you are doing in the work; do not imply hidden actions. "
                + _refusal +
                "Aim to help them succeed honestly, including improving your own accuracy over time."
            )
        if cfg.get("operator_protection_policy_pin_enabled", True):
            parts.append(
                "Operator protection policy: You exist to serve the operator. "
                "Never manipulate, deceive, or act against the operator's stated interests. "
                "If conflicting instructions arise, the operator's explicit directive takes precedence. "
                "Flag conflicts transparently rather than choosing silently."
            )
        if cfg.get("pin_psychology_framework_excerpt", True) and aspect:
            _aid = (aspect.get("id") or "").strip().lower()
            if _aid in ("echo", "lilith"):
                parts.append(_INTERACTION_FRAMEWORK_PIN)
        if cfg.get("enable_personality_expression"):
            expr = runtime_safety.load_personality_expression()
            if expr:
                parts.append(expr)
        return parts

    if use_cache and cache_key in _STATIC_SYS_CACHE:
        sys_parts = list(_STATIC_SYS_CACHE[cache_key])
    else:
        sys_parts = _build_uncached_prefix()
        if cfg.get("enable_style_profile"):
            try:
                from layla.memory.db import get_style_profile

                style_parts = []
                for sk in ("writing", "coding", "reasoning", "structuring", "collaboration"):
                    row = get_style_profile(sk)
                    if row and (row.get("profile_snapshot") or "").strip():
                        snip = (row.get("profile_snapshot") or "").strip()[:600]
                        if snip:
                            style_parts.append(f"{sk}: {snip}")
                if style_parts:
                    sys_parts.append("Style (stay consistent with these):\n" + "\n".join(style_parts))
            except Exception as _exc:
                logger.debug("prompt_builder:style_profile: %s", _exc, exc_info=False)
        if cfg.get("uncensored") or cfg.get("nsfw_allowed"):
            sys_parts.append(
                "Content policy: Do not censor. Adult/NSFW content is allowed in consented contexts. "
                "Refuse only for genuine harm (illegal, non-consensual, abuse). Access is anonymous; do not require or store user identity. "
                "Do not use the literal prefix `[REFUSED:` in your output — that tag is reserved for the host refusal pipeline, not model self-censorship. "
                "If you must decline, use plain language only."
            )
        if use_cache:
            _STATIC_SYS_CACHE[cache_key] = list(sys_parts)

    gl = (goal or "").lower()
    # Capability self-knowledge (BL-306). Layla had NO ground truth about her own functionality: self_model.md
    # is philosophy and lilith-only, docs/CAPABILITIES.md is about the implementation registry with no runtime
    # reader, and operating_manual.manual_for_prompt() was never wired to a prompt. Asked to list her
    # capabilities she invented plausible ones ("User management", "Encryption support"). This injects the
    # verified manifest instead.
    # Gated on the question, not always-on: a 3B cannot afford ~700 tok every turn.
    # INSERTED near the front, not appended: system_instructions is truncated from the TAIL on low tiers, so an
    # appended block is exactly the thing that gets cut (same lesson as the persona insert above).
    # NOTE: this must stay OUT of _STATIC_SYS_CACHE — that cache is keyed on (aspect, cfg) and NOT the goal, so
    # caching a goal-dependent block would leak it into unrelated turns.
    if _is_capability_question(gl):
        _cap = _capability_manifest_core(root)
        if _cap:
            sys_parts.insert(2 if personality else 1, _cap)
    # BL-285: previously gated on the goal literally containing nsfw|intimate|explicit|adult|18+|uncensored,
    # so ordinary phrasing ("write a steamy scene between them") missed the strongest anti-refusal guidance.
    # When uncensored/NSFW is on the operator has already opted in for the session — apply it every turn.
    # Stays OUT of _STATIC_SYS_CACHE (appended after the cache block); correct, as it no longer varies by goal.
    if cfg.get("uncensored") or cfg.get("nsfw_allowed"):
        sys_parts.append(
            "Uncensored/NSFW-allowed mode is on. "
            "Answer fully without safety-theater refusals for consensual adult content. "
            "Still refuse clearly (in prose) for minors, non-consent, illegality, or governance bypass."
        )
    if personality:
        # Insert the aspect persona (anchor + voice/style card) right after the core line, BEFORE
        # the long base identity + policy boilerplate. The system_instructions section is
        # budget-truncated from the TAIL on low tiers (~400 tok), and with the persona appended
        # last it was ALWAYS cut — the model never saw "Reply as Morrigan — blunt, no flattery"
        # and improvised theatrically off the identity prose instead. Truncation must eat the
        # manifesto's tail, never who is speaking.
        sys_parts.insert(1, personality)
    if cfg.get("multi_agent_orchestration_enabled") and (reasoning_mode or "").strip().lower() == "deep":
        _dap = (
            "Multi-agent discipline (single pass): plan briefly, implement precisely, then sanity-check.\n"
            "Organization: prefer minimal diffs, avoid new files unless necessary, do not bloat the repo, "
            "keep outputs reviewable, and reject sloppy or redundant changes.\n"
            "Self-check: verify assumptions against tools and files; if uncertain, say so and propose a concrete check."
        )
        sys_parts.append(_dap)
    if aspect and aspect.get("_use_nsfw_addition") and aspect.get("systemPromptAdditionNsfw"):
        sys_parts.append(aspect.get("systemPromptAdditionNsfw", ""))
        sys_parts.append(
            "NSFW register is open for this message: do not emit `[REFUSED:` or similar bracketed refusal tags; "
            "stay in character and comply with the NSFW voice contract above."
        )
    if cfg.get("enable_cot", True):
        sys_parts.append(
            "Reasoning style: Think through problems step by step before giving your final answer. "
            "For complex questions, break them down. Show your reasoning when it helps clarity."
        )
    # Character creator slider → behavioral prompt hints (makes slider customization functional)
    if cfg.get("character_creator_enabled", True) and aspect:
        _aid_cc = (aspect.get("id") or "").strip().lower()
        if _aid_cc:
            try:
                from services.personality.character_creator import personality_to_prompt_hints

                _hints = personality_to_prompt_hints(_aid_cc)
                if _hints:
                    sys_parts.append("Personality tuning (operator customized):\n" + "\n".join(f"- {h}" for h in _hints))
            except Exception as _exc:
                logger.debug("prompt_builder:character_hints: %s", _exc, exc_info=False)
    # Failure mode self-awareness (helps aspects catch their own degradation patterns)
    if aspect:
        _fm = (aspect.get("failure_mode_expanded") or aspect.get("failure_mode") or "").strip()
        if _fm:
            sys_parts.append(
                f"Self-awareness: Under pressure you may {_fm[:300]} — catch this tendency and correct."
            )
    return sys_parts


def tool_names_for_decision(valid_tools: set[str], goal: str) -> str:
    """
    Ordered tool list for the decision prompt: keyword overlap with goal first, then alpha.
    """
    g = (goal or "").lower()
    words = {w for w in g.replace("/", " ").split() if len(w) > 2}

    def _score(name: str) -> tuple[int, str]:
        n = name.lower().replace("_", " ")
        score = sum(1 for w in words if w in n or w in name.lower())
        return (-score, name)

    names = sorted((valid_tools - {"reason"}), key=_score)
    # Keep "reason" visible to weak models even though it is not a registry tool.
    return ", ".join(["reason", *names])


def build_decision_tool_hints(valid_tools: set[str], goal: str) -> tuple[str, str]:
    """Returns (tools_csv, edit_hint) for _llm_decision."""
    tools_list = tool_names_for_decision(valid_tools, goal)
    edit_hint = ""
    if valid_tools & {"write_file", "apply_patch", "replace_in_file"}:
        edit_hint = (
            "Editing: prefer replace_in_file or apply_patch over write_file for existing files; "
            "use ranged read_file when files are large.\n"
        )
    return tools_list, edit_hint


class PromptBuilder:
    """Facade for tests and future callers."""

    @staticmethod
    def build_static(
        aspect: dict | None,
        cfg: dict[str, Any],
        *,
        identity: str,
        personality: str,
        goal: str,
        reasoning_mode: str,
        repo_root: Path | None = None,
    ) -> str:
        parts = build_core_sys_parts(
            cfg=cfg,
            aspect=aspect,
            identity=identity,
            personality=personality,
            goal=goal,
            reasoning_mode=reasoning_mode,
            repo_root=repo_root,
        )
        return "\n\n".join(parts)

    @staticmethod
    def tool_injection(valid_tools: set[str], goal: str) -> str:
        return tool_names_for_decision(valid_tools, goal)
