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

# The TRUE repo root, reused from runtime_safety rather than hand-rolled from __file__ — a parent chain here
# has to be counted by hand and was wrong by one level (it resolved to agent/), so `.identity/capabilities.md`
# and `personalities/*.json` — both of which live at the repo root — were never found. The manifest silently
# returned "" on every production call, and _personality_file_mtime returned 0.0 forever, which also froze the
# static prompt cache: editing a persona file no longer invalidated it.
REPO_ROOT = runtime_safety.REPO_ROOT

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
# Her own features, enumerated once and shared by the alternations that need "is the object HERS?".
# Enumerated rather than left open so "do you have a minute" and "how do i use argparse" stay ordinary
# turns: an open object is what turned both of these into ~705-token false positives.
_HER_FEATURES = (
    r"(voice|speech|tts|stt|vision|eyes|ears|hearing|internet|web\s+access|browser|"
    r"memory|memories|encryption|knowledge\s+base|aspects?|personalit(y|ies))"
)

# Questions about what Layla is/can do. Deliberately narrow: this costs ~700 tok, so it fires on the question,
# never on every turn. Matches "what can you do", "list your capabilities", "what tools do you have",
# "can you speak", "how do I use ...", etc.
_CAP_Q_RE = re.compile(
    # Both word orders, but the leading "what" is load-bearing: it separates the QUESTION
    # ("what can you do", "tell me what you can do") from a REQUEST ("can you do this refactor"),
    # which must NOT pay the ~600 tok.
    # The negative lookahead separates the QUESTION from a work request that opens with the same five
    # words. Unanchored, "what can you do about the memory leak in worker.py" billed an ordinary
    # debugging turn 1559 tokens instead of 848. "for"/"here" are deliberately NOT in the list —
    # "what can you do for me" IS the question.
    # ADVERBS ARE OPTIONAL AND MUST NOT BREAK THE MATCH. This required "you" and "do" to be
    # adjacent, so the manifest reached her for "list your capabilities" and "what tools do you
    # have" but NOT for "what can you actually do" — measured, along with "what can you really do",
    # "what exactly can you do" and "what else can you do". Four ordinary phrasings of the same
    # question, and the most natural one of the set was among them: an intensifier is exactly what a
    # person adds when they suspect the first answer was padded. The manifest is the ONLY ground
    # truth about her real capabilities, so missing it means she answers from invention on precisely
    # the turn where the user is pushing for accuracy.
    # `\w+ly` covers actually/really/genuinely/honestly/exactly; "else" and "even" are the non-ly
    # cases that occur in practice. The negative lookahead is untouched and still load-bearing.
    r"\bwhat\s+(?:(?:\w+ly|else|even)\s+)?(can|could)\s+(you|u)\s+(?:(?:\w+ly|else|even)\s+)?do\b"
    r"(?!\s+(about|with|to|regarding|concerning)\b)"
    r"|\bwhat\s+(you|u)\s+(can|could)\s+(?:(?:\w+ly|else|even)\s+)?do\b"
    r"|\b(your|you have)\b[^?]{0,20}\b(capabilit|abilit|feature|function|tool)"
    # noun-first order: "what FEATURES DO YOU HAVE"
    r"|\b(feature|tool|capabilit|abilit|function)\w*\s+do\s+you\s+have\b"
    r"|\bcapabilit(y|ies)\b"
    r"|\bwhat\s+(are|is)\s+you\s+(capable|able)\b"
    # SUBJECT-GATED. Bare `\bwhat\s+tools\b` fired on "what tools did the previous run use" — a question
    # about the TRANSCRIPT, not about her, billed 1555 tokens against an 848-token baseline. Requiring
    # the subject to be her (or the phrase to be the whole question) keeps "what tools do you have" and
    # "what tools can you use" while dropping every question about some other actor's tools.
    r"|\bwhat\s+tools\s+(do|can|are|will)\s+(you|u)\b"
    r"|\bwhat\s+tools\b[\s?!.]*+$"
    # OBJECT-GATED, same defect as the two below and as `what tools`. Bare
    # `\bcan\s+you\s+(speak|talk|hear|listen|see|browse|...)\b` gates the VERB and not the OBJECT, so
    # every ordinary request phrased with one of these verbs was billed as a capability turn. Measured
    # against an 848-token baseline: "can you see the error in line 4" +730 tok, "can you browse to the
    # file and fix it" +721 — indistinguishable from the true positive "can you speak" (+715).
    # "can you listen to this audio file" and "can you talk to the API" matched too.
    #
    # The question is only about her capability when the verb stands alone, takes HER as the object
    # ("can you hear me"), or names the faculty itself ("can you access the internet"). A concrete
    # object makes it a work request.
    r"|\bcan\s+(you|u)\s+(speak|talk|hear|listen|see|browse)[\s?!.]*+$"
    r"|\bcan\s+(you|u)\s+(hear|see|understand)\s+me[\s?!.]*+$"
    r"|\bcan\s+(you|u)\s+(speak|talk)\s+(out\s+loud|aloud|to\s+me)[\s?!.]*+$"
    r"|\bcan\s+(you|u)\s+(browse|search|access|get\s+on)\s+(the\s+)?(web|internet|online)\b"
    # OBJECT-GATED, same defect: bare `\bhow\s+do\s+i\s+(use|find|enable|turn\s+on)\b` fired on
    # "how do i use argparse" (1553 tok vs 848). The manifest is only the right answer when the thing
    # being enabled is HERS, so the object has to be a possessive or one of her own features.
    r"|\bhow\s+do\s+i\s+(use|find|enable|turn\s+on)\s+(your|ur)\b"
    r"|\bhow\s+do\s+i\s+(use|find|enable|turn\s+on)\s+(the\s+|a\s+|an\s+)?" + _HER_FEATURES + r"\b"
    # --- phrasings measured as MISSED (2026-07-19) -------------------------------------------------
    # Each of these got the language directive and no manifest, i.e. she answered a question about
    # herself from invention while holding a verified answer she was never shown.
    # END-ANCHORED. Unanchored, each of these matches the PREFIX of an ordinary request and bills it
    # ~828 tokens: "what can you help me with this regex for". The anchor is what separates the
    # question about her from a question that merely starts the same way.
    r"|\bwhat\s+can\s+(you|u)\s+help\s+(me\s+)?with[\s?!.]*+$"
    # "do you have voice/vision/memory/internet" — an ownership question about a feature, which is
    # exactly what the BROKEN disclosures exist to answer honestly. Enumerated rather than left open
    # ("do you have a minute") so it stays a capability probe.
    r"|\bdo\s+(you|u)\s+have\s+(a\s+|an\s+)?" + _HER_FEATURES + r"\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------------------------------
# IDENTITY questions are NOT capability questions. This is a deliberate split, not an oversight.
#
# R5 added "who are you" and "tell me about yourself" to _CAP_Q_RE. Measured consequence on the real
# Morrigan aspect at n_ctx 2048:
#
#     "who are you?"   ->  1551 tok (vs 848 ordinary), and the "## Core" block —
#                          "You are Morrigan — Layla's blade..." — was DROPPED.
#
# The capability path trims the persona to anchor+voice on purpose, so it can spend the window on
# verified facts (system_head_builder). Routing identity questions down it therefore produces the one
# outcome nobody wants: the turn most about who she is is the turn that loses her self-description,
# and it pays +703 tokens for the privilege.
#
# The manifest earns its cost on questions that invite a capability CLAIM ("can you speak", "do you
# have internet") — that is what the BROKEN disclosures are for. "Who are you" invites a self-
# description, and the persona already IS the verified answer to it.
#
# Kept as a live predicate rather than deleted alternations so the exclusion is explicit, reviewable,
# and load-bearing at the trim site in system_head_builder.
# ---------------------------------------------------------------------------------------------------
_IDENTITY_Q_RE = re.compile(
    r"\bwho\s+are\s+(you|u)[\s?!.]*+$"
    r"|\bwhat\s+are\s+(you|u)[\s?!.]*+$"
    r"|\btell\s+me\s+about\s+(yourself|urself)[\s?!.]*+$"
    r"|\bintroduce\s+yourself[\s?!.]*+$",
    re.IGNORECASE,
)

# The same question in the languages this product ships a response_language for (plus Korean and Russian,
# which have UI locales). R5: `_CAP_Q_RE` was ASCII/English-only, so an operator who set Spanish and asked
# "¿qué puedes hacer?" received the language directive and NO manifest — the two halves of this slice did
# not compose, and the failure mode was the worst one available: she answers about herself, fluently, in
# the operator's own language, entirely from invention.
#
# Kept as a separate pattern rather than more alternations in _CAP_Q_RE because these need `re.UNICODE`
# semantics and because \b does not behave usefully against CJK or Arabic script — these are matched as
# substrings, which is safe here since the phrases are long and specific.
# The verb phrases are END-ANCHORED for the same reason as their English counterparts: "cosa puoi fare"
# is a capability question, "cosa puoi fare per questo bug" is a work request. The NOUN phrases
# ("tus capacidades", "deine Fähigkeiten") are specific enough to stand unanchored.
# `[\s?!.]*+` — ONE character class, and possessive (Python 3.11+). Written as `\s*[?!.]*\s*$` it was
# three adjacent quantifiers over classes that a regex engine must try splitting every possible way:
# measured 67 ms on "who are you" + 3000 spaces + "x", because every split backtracks to a failing `$`.
# The goal string is whatever the user typed and this runs on every turn, so it is bounded here rather
# than left quadratic. Possessive means: take the whole run, never give it back, fail immediately.
_CAP_TAIL = r"[\s?!.]*+$"
_CAP_Q_I18N_RE = re.compile(
    # Spanish / Portuguese
    r"qu[eé]\s+puedes\s+hacer" + _CAP_TAIL
    + r"|qu[eé]\s+sabes\s+hacer" + _CAP_TAIL
    + r"|cu[aá]les\s+son\s+tus\s+(capacidades|funciones)"
    + r"|tus\s+capacidades\b"
    + r"|o\s+que\s+(voc[eê]|tu)\s+pode\s+fazer" + _CAP_TAIL
    + r"|suas\s+(capacidades|funcionalidades)\b"
    # French
    + r"|que\s+peux[-\s]tu\s+faire" + _CAP_TAIL
    + r"|qu[e']est[-\s]ce\s+que\s+tu\s+peux\s+faire" + _CAP_TAIL
    + r"|quelles\s+sont\s+tes\s+(capacit[eé]s|fonctions)"
    + r"|tes\s+capacit[eé]s\b"
    # German
    + r"|was\s+kannst\s+du(\s+(tun|machen))?" + _CAP_TAIL
    + r"|deine\s+(f[aä]higkeiten|funktionen)\b"
    # Italian
    + r"|(cosa|che\s+cosa)\s+(puoi|sai)\s+fare" + _CAP_TAIL
    + r"|le\s+tue\s+(capacit[aà]|funzioni)\b"
    # Dutch
    + r"|wat\s+(kun|kan)\s+(je|u)\s+doen" + _CAP_TAIL
    + r"|jouw\s+mogelijkheden\b"
    # Russian
    + r"|что\s+ты\s+(умеешь|можешь)" + _CAP_TAIL
    + r"|твои\s+возможности"
    # Japanese / Mandarin / Korean — substring, no word boundaries. These scripts do not space-separate,
    # so \b is meaningless against them; the phrases are long and specific enough to match as substrings.
    + r"|何ができ|できること|機能は"
    + r"|你能做什么|你會做什麼|你会做什么|你的功能"
    + r"|무엇을\s*할\s*수\s*있"
    # Arabic
    + r"|ماذا\s+يمكنك|ما\s+هي\s+قدراتك|قدراتك\b",
    re.IGNORECASE | re.UNICODE,
)


def _is_capability_question(goal_lower: str) -> bool:
    if not goal_lower:
        return False
    return bool(_CAP_Q_RE.search(goal_lower)) or bool(_CAP_Q_I18N_RE.search(goal_lower))


def _is_identity_question(goal_lower: str) -> bool:
    """"Who are you", "tell me about yourself" — answered FROM the persona, not from the manifest.

    See the comment on `_IDENTITY_Q_RE`. Used at the persona-trim site in system_head_builder to keep
    her self-description on the one turn that is entirely about it.
    """
    if not goal_lower:
        return False
    return bool(_IDENTITY_Q_RE.search(goal_lower))


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
            # Index 1, BEFORE the persona insert below — which pushes this to index 2, i.e. immediately
            # after "who is speaking" and immediately BEFORE the 751-token identity manifesto.
            # It used to insert at index 2 pre-persona (= index 3 post-persona), landing it BEHIND the
            # manifesto at a measured offset of ~1030 tokens inside a section capped at 800 (417 effective
            # on a 2048-ctx box): it was found and then truncated away every single time.
            # Truncation is from the TAIL, so this ordering makes the manifesto's tail the victim instead of
            # the capability facts — the right trade on a turn whose whole subject IS the capabilities.
            sys_parts.insert(1, _cap)
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

