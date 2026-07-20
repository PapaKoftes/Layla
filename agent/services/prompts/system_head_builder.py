"""
system_head_builder.py — Builds the system prompt head for the agent loop.

Extracted from agent_loop.py to reduce its size and improve maintainability.
Contains: build_system_head() and all helper functions it depends on.

All functions preserve their original signatures and behavior exactly.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import orchestrator
import runtime_safety
from layla.memory.db import get_aspect_memories as _db_get_aspect_memories
from layla.memory.db import get_recent_learnings as _db_get_learnings
from services.context.context_manager import DEFAULT_BUDGETS, build_system_prompt, token_estimate
from services.context.context_manager import default_budgets_for as _resolve_default_budgets
from services.llm.llm_gateway import run_completion

logger = logging.getLogger("layla")

# Reused from runtime_safety, not hand-rolled: this file sits two levels deeper than it assumed, so the
# parent chain resolved to agent/services/ and the repo_root handed to build_core_sys_parts pointed at a
# directory with no .identity/ in it. Every capability question got an empty manifest.
REPO_ROOT = runtime_safety.REPO_ROOT


def _reply_reserve_tokens(cfg: dict[str, Any]) -> int:
    """Tokens the model will be allowed to generate — space the head must not occupy."""
    try:
        return max(128, int(cfg.get("completion_max_tokens", 256) or 256))
    except (TypeError, ValueError):
        return 256


def _convo_block_tokens(cfg: dict[str, Any], conversation_history: list | None) -> int:
    """Size of the conversation block the CALLER appends after this head.

    An estimate, deliberately: build_system_head does not own that block — stream_handler and
    reasoning_handler each build it from `convo_turns` with a 600-char cap on the last two turns and 220 on
    the rest. This mirrors those caps so the head can be bounded against the space it will actually have
    left. It is only ever used to SHRINK the head, so drifting to an over-estimate is the safe failure and
    drifting to an under-estimate costs at most the manifest's tail — never a context overflow, because the
    result is verified against the assembled head rather than trusted.
    """
    try:
        turns_n = max(0, int(cfg.get("convo_turns", 0) or 0))
    except (TypeError, ValueError):
        return 0
    if turns_n <= 0 or not conversation_history:
        return 0
    turns = conversation_history[-turns_n:]
    n = len(turns)
    chars = 0
    for i, t in enumerate(turns):
        cap = 600 if (n - i) <= 2 else 220
        chars += min(len((t or {}).get("content") or ""), cap) + 8  # + "User: " / "Layla: " and a newline
    # 3.5 chars/token, not the estimator's 4.0 and NOT token_estimate() on filler text: a run of one
    # repeated character tokenizes about twice as densely as prose, so measuring a placeholder string would
    # halve this reserve and hand the head space it does not have.
    return -(-chars // 7) * 2 if chars else 0


def _row_content(r: Any) -> str:
    """Extract 'content' from a recall row that may be a dict OR a sqlite3.Row.

    sqlite3.Row supports item access but not .get(), so a bare r.get('content')
    threw 'sqlite3.Row object has no attribute get' and killed the whole recall.
    """
    if isinstance(r, dict):
        return r.get("content", "") or ""
    try:
        return r["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# Constants for lightweight-turn detection
# ---------------------------------------------------------------------------

_RETRIEVAL_SUBSTANTIVE_MARKERS = (
    "?",
    "who ", "what ", "why ", "how ", "when ", "where ", "which ",
    "explain", "describe", "tell me", "write ", "code", "create ", "list ",
    "summarize", "summarise", "analyze", "analyse", "compare", "contrast",
    "fix ", "debug", "error", "implement", "refactor", "test ",
    "can you", "could you", "would you", "please ", "help me",
    "define ", "meaning of", "difference between",
)

_PHATIC_RETRIEVAL_SKIP_PATTERNS = (
    r"^(hi|hey|hello|yo|sup|hiya|howdy)\b[!.\s]*$",
    r"^(thanks|thank you|thx|ty|tysm)\b[^?.]{0,48}[!.\s]*$",
    r"^(ok|okay|k|got it|yep|yeah|yes|no|nope|sure|mhm|uh huh)\b[!.\s]*$",
    r"^(bye|goodbye|see you|cya|later)\b[^?.]{0,24}[!.\s]*$",
)


# ---------------------------------------------------------------------------
# Helper functions (used by build_system_head and exported for agent_loop)
# ---------------------------------------------------------------------------

def is_lightweight_chat_turn(goal: str, reasoning_mode: str) -> bool:
    """True only for phatic / ack-only content where heavy retrieval is usually wasted.

    Not length-based: short questions like 'who are you' stay substantive (False).
    """
    if (reasoning_mode or "").strip().lower() not in {"none", "light"}:
        return False
    g = (goal or "").strip()
    if not g:
        return False
    gl = g.lower()
    if any(m in gl for m in _RETRIEVAL_SUBSTANTIVE_MARKERS):
        return False
    code_markers = (
        "def ", "class ", "import ", "traceback", "`", "```", "{", "}", "</", "/>",
        "http://", "https://",
    )
    if any(m in gl for m in code_markers):
        return False
    for pat in _PHATIC_RETRIEVAL_SKIP_PATTERNS:
        if re.match(pat, gl, re.IGNORECASE):
            return True
    return False


# Stopwords stripped before scoring learning<->goal relevance (keep it tiny + language-neutral-ish).
_LEARN_STOP = frozenset((
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "been", "it", "this", "that", "these", "those", "with", "as", "at",
    "by", "from", "i", "you", "me", "my", "your", "we", "us", "do", "does", "did", "can",
    "what", "how", "why", "when", "who", "show", "tell", "give", "please", "hello", "hi", "hey",
    "thanks", "thank", "ok", "okay", "yes", "no", "sure", "help",
))


def _content_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_+#-]{2,}", (text or "").lower()) if w not in _LEARN_STOP}


def load_learnings(aspect_id: str = "", goal: str = "") -> str:
    """Load learnings text for the given aspect, filtered to what's relevant to ``goal``.

    Recent learnings used to be dumped into every prompt unconditionally, which let an
    off-topic memory (e.g. a stored "research Python decorators" objective) hijack an
    unrelated turn like "hello" — the model would answer the remembered topic and copy
    its template. Now, when a goal is given, a learning is only injected if it shares a
    real content token with the goal; otherwise the relevance-gated semantic_recall
    section (below) is the sole memory source. An empty goal keeps the old recent-dump.
    """
    try:
        cfg = runtime_safety.load_config()
        n = cfg.get("learnings_n", 30)
        min_score = float(cfg.get("learning_min_score", 0.3) or 0.3)
        rows = _db_get_learnings(n=n, aspect_id=aspect_id or None, min_score=min_score)
        contents = [r["content"] for r in rows if r.get("content")]
        # When a goal is given, keep only learnings that share a real content token with it.
        # A phatic goal ("hello") tokenizes to nothing -> matches nothing (not everything).
        # An empty goal (caller opted out of filtering) keeps the recent dump.
        if (goal or "").strip():
            goal_tokens = _content_tokens(goal)
            contents = [c for c in contents if _content_tokens(c) & goal_tokens]
        return "\n".join(contents)
    except Exception as _e:
        logger.debug("load_learnings failed: %s", _e)
        return ""


def extract_aspect_domain_keywords(aspect: dict | None) -> list[str]:
    """Extract flat list of short domain keywords from aspect expertise_domains for retrieval boosting."""
    if not aspect:
        return []
    ed = aspect.get("expertise_domains")
    if not ed or not isinstance(ed, dict):
        return []
    keywords: list[str] = []
    for domain_list in (ed.get("primary", []), ed.get("secondary", [])):
        if not isinstance(domain_list, list):
            continue
        for entry in domain_list:
            if not isinstance(entry, str):
                continue
            clean = entry.split("(")[0].strip().lower()
            if clean and len(clean) <= 40:
                keywords.append(clean)
    return keywords[:12]


def build_expertise_domain_block(aspect: dict | None) -> str:
    """Build a concise expertise domain block for system head injection."""
    if not aspect:
        return ""
    ed = aspect.get("expertise_domains")
    if not ed or not isinstance(ed, dict):
        return ""
    parts: list[str] = []
    name = aspect.get("name", "this aspect")
    primary = ed.get("primary", [])
    secondary = ed.get("secondary", [])
    philosophy = (ed.get("philosophy") or "").strip()
    gaps = ed.get("knowledge_gaps_honest", [])
    can_refuse = ed.get("can_refuse_technical", [])
    if primary:
        parts.append(f"Primary expertise: {', '.join(str(p) for p in primary[:6])}")
    if secondary:
        parts.append(f"Secondary expertise: {', '.join(str(s) for s in secondary[:6])}")
    if philosophy:
        parts.append(f"Engineering philosophy: {philosophy[:200]}")
    if gaps:
        parts.append(f"Honest gaps (redirect to other aspects when these arise): {', '.join(str(g) for g in gaps[:5])}")
    if can_refuse:
        parts.append(f"Will refuse to: {', '.join(str(r) for r in can_refuse[:5])}")
    if not parts:
        return ""
    return f"Domain expertise ({name}):\n" + "\n".join(f"- {p}" for p in parts)


def semantic_recall(query: str, k: int = 5, domain_boost_terms: list[str] | None = None) -> str:
    """Full memory recall pipeline: BM25 + vector hybrid search + FTS5 + cross-encoder reranking.

    Falls back to pure vector search, then FTS on ChromaDB error.
    """
    if k <= 0 or not query or not query.strip():
        return ""
    try:
        from layla.memory.vector_store import search_memories_full
        cfg = runtime_safety.load_config()
        use_mmr = bool(cfg.get("retrieval_use_mmr", False))
        use_hyde = bool(cfg.get("hyde_enabled", False))

        augmented_query = query
        if domain_boost_terms and cfg.get("expertise_domain_boost_enabled", True):
            short_terms = [t for t in domain_boost_terms if len(t) <= 25][:4]
            if short_terms:
                augmented_query = query + " " + " ".join(short_terms)

        results = search_memories_full(
            augmented_query, k=k, use_rerank=True, use_mmr=use_mmr, use_hyde=use_hyde,
            domain_boost_keywords=domain_boost_terms,
        )
        lines = [c for c in (_row_content(r) for r in results) if c] if results else []
        # mem0: when enabled + installed, merge external-memory hits into recall (makes the
        # previously-dead mem0_enabled flag live). Best-effort; never blocks local recall.
        if cfg.get("mem0_enabled"):
            try:
                from services.retrieval.mem0_integration import is_available, search_memories
                if is_available():
                    _m = search_memories(cfg, query, limit=k)
                    for _hit in (_m.get("results") or _m.get("memories") or []):
                        _txt = (_hit.get("memory") or _hit.get("text") or _hit.get("content") or "").strip() \
                            if isinstance(_hit, dict) else str(_hit).strip()
                        if _txt and _txt not in lines:
                            lines.append(_txt)
            except Exception as _me:
                logger.debug("mem0 recall merge skipped: %s", _me)
        if not lines:
            return ""
        return "\n".join(lines)
    except Exception as e:
        # BL-374: this said "ChromaDB failed" for EVERY failure, including the common one — the embedder
        # could not be downloaded because the machine is offline. ChromaDB was fine; the message sent anyone
        # reading the log to debug the wrong component, which is worse than saying nothing. Name the
        # component that actually failed.
        try:
            from layla.memory.vector_store import embedder_status
            _emb_unavail = embedder_status().get("status") == "unavailable"
        except Exception:
            _emb_unavail = False
        if _emb_unavail:
            logger.warning(
                "semantic recall unavailable (embedder could not load — see the EMBEDDER UNAVAILABLE error "
                "above and GET /health/deps); falling back to keyword search (FTS): %s", e,
            )
        else:
            logger.warning("ChromaDB failed, falling back to FTS: %s", e)
        try:
            from layla.memory.db import search_learnings_fts
            results = search_learnings_fts(query, n=k)
            lines = "\n".join(c for c in (_row_content(r) for r in results) if c)
            if lines.strip():
                logger.info("retrieval fallback: semantic recall using FTS (%d rows)", len(results))
            return lines
        except Exception:
            return ""


def decompose_goal(goal: str) -> list:
    """If objective is broad, return 2-3 sub-objectives; else return []."""
    if not goal or len(goal.strip()) < 20:
        return []
    g = goal.lower().strip()
    broad_keywords = (
        "production ready", "refactor", "fix everything", "improve", "complete", "full",
        "make this repo", "get this ready", "clean up", "overhaul", "rewrite",
    )
    is_broad = len(goal) > 80 or any(kw in g for kw in broad_keywords)
    if not is_broad:
        return []
    try:
        cfg = runtime_safety.load_config()  # noqa: F841
        prompt = (
            f"Objective: {goal[:500]}\n\n"
            "Output exactly one JSON line: a JSON array of 2-3 concrete sub-objectives (short strings). "
            'Example: ["Add tests", "Fix lint", "Update README"]. No other text.\n'
        )
        out = run_completion(prompt, max_tokens=120, temperature=0.2, stream=False)
        if isinstance(out, dict):
            raw = (out.get("choices") or [{}])[0].get("message", {}).get("content") or (out.get("choices") or [{}])[0].get("text") or ""
        else:
            raw = ""
        for line in (raw or "").strip().splitlines():
            line = line.strip()
            if line.startswith("["):
                arr = json.loads(line)
                if isinstance(arr, list) and len(arr) >= 1:
                    subs = [str(x).strip() for x in arr[:3] if x]
                    return subs[:3]
        return []
    except Exception as e:
        logger.debug("decompose_goal failed: %s", e)
        return []


def get_repo_structure(workspace_root: str | Path, max_entries: int = 40) -> str:
    """Top-level repo structure for workspace context. No tool call, filesystem only."""
    ws = str(workspace_root).strip() if workspace_root else ""
    if not ws:
        return ""
    try:
        root = Path(ws).resolve()
        if not root.exists() or not root.is_dir():
            return ""
        entries = []
        for p in sorted(root.iterdir())[:max_entries]:
            name = p.name
            if name.startswith(".") and name not in (".git",):
                continue
            entries.append(name + ("/" if p.is_dir() else ""))
        if not entries:
            return "(empty directory)"
        return ", ".join(entries[:max_entries])
    except Exception:
        return ""


def enrich_deliberation_context(context: str) -> str:
    """Append project context and Echo patterns so deliberation has real workspace awareness."""
    extra = []
    try:
        from layla.memory.db import get_project_context
        pc = get_project_context()
        if pc.get("project_name") or pc.get("goals") or pc.get("lifecycle_stage"):
            proj_parts = [f"Project: {pc.get('project_name') or '?'}", f"Lifecycle: {pc.get('lifecycle_stage') or '?'}"]
            if pc.get("goals"):
                proj_parts.append(f"Goals: {(pc.get('goals') or '')[:200]}")
            extra.append("Project context: " + "; ".join(proj_parts))
    except Exception as _exc:
        logger.debug("enrich_deliberation_context[project]: %s", _exc, exc_info=False)
    try:
        learnings = _db_get_learnings(n=5)
        if learnings:
            prefs = [(ln.get("content") or "")[:80] for ln in learnings if (ln.get("content") or "").strip()]
            if prefs:
                extra.append("Echo (patterns/preferences): " + "; ".join(prefs[:3]))
    except Exception as _exc:
        logger.debug("enrich_deliberation_context[echo]: %s", _exc, exc_info=False)
    if not extra:
        return context or ""
    return (context or "").strip() + "\n\n" + "\n".join(extra)


def needs_knowledge_rag(goal: str) -> bool:
    """True if goal suggests research/search/explain or reflective/psychology-informed chat — use full Chroma retrieval."""
    if not (goal or "").strip():
        return False
    g = goal.lower()
    research_kw = (
        "research", "search", "explain", "look up", "what is",
        "how does", "find out", "learn about",
    )
    if any(kw in g for kw in research_kw):
        return True
    reflective_kw = (
        "reflect on", "self-reflect", "help me reflect", "overwhelmed",
        " i feel", "i'm feeling", "im feeling", "feeling stuck",
        "feeling anxious", "i'm anxious", "i am anxious",
        "pattern i", "noticed a pattern", "behavioral pattern",
        "why do i always", "why do i avoid", "i avoid", "keep avoiding",
        "relationship to work", "burnout", "cognitive distortion",
        "attachment style", "window of tolerance", "emotionally exhausted",
        "mental health", "talk to a therapist", "panic attack",
        "depressed about", "anxious about",
    )
    return any(kw in g for kw in reflective_kw)


def needs_graph(goal: str) -> bool:
    """True if goal suggests related/context/connection — include graph associations."""
    if not (goal or "").strip():
        return False
    g = goal.lower()
    return any(kw in g for kw in ("related", "context", "connection", "link", "associate", "connected"))


def aspect_dict_by_id(aspect_id: str) -> dict | None:
    """Resolve personalities/*.json entry by id (lowercase)."""
    aid = (aspect_id or "").strip().lower()
    if not aid:
        return None
    try:
        for a in orchestrator._load_aspects():
            if (a.get("id") or "").strip().lower() == aid:
                return a
    except Exception as _exc:
        logger.debug("aspect_dict_by_id: %s", _exc, exc_info=False)
    return None


def append_persona_focus_to_personality(
    personality: str,
    primary: dict | None,
    persona_focus_id: str,
    max_extra: int = 4500,
) -> str:
    """Inject a secondary aspect's prompt depth; primary aspect still owns routing/tools."""
    pid = (persona_focus_id or "").strip().lower()
    if not pid or not primary:
        return personality
    if (primary.get("id") or "").strip().lower() == pid:
        return personality
    sec = aspect_dict_by_id(pid)
    if not sec:
        return personality
    name = sec.get("name", pid)
    role = (sec.get("role") or sec.get("voice") or "").strip()[:400]
    add = (sec.get("systemPromptAddition") or "").strip()
    if not add and not role:
        return personality
    chunk = add[:max_extra] if add else ""
    block = (
        f"\n\n---\nSecondary perspective (persona_focus={name}): blend this depth with the primary voice above; "
        f"the primary aspect still owns tools, approvals, and final voice.\n{role}\n\n{chunk}"
    )
    return personality + block


def relationship_codex_context(cfg: dict, workspace_root: str) -> tuple[str, bool]:
    """Optional digest from `.layla/relationship_codex.json` for the system prompt."""
    if not bool(cfg.get("relationship_codex_inject_enabled", False)):
        return "", False
    wp = (workspace_root or "").strip()
    if not wp:
        return "", False
    try:
        wrp = Path(wp).expanduser().resolve()
    except Exception:
        return "", False
    if not wrp.is_dir():
        return "", False
    try:
        from layla.tools.registry import inside_sandbox
        from services.memory.relationship_codex import codex_has_entities, format_codex_prompt_digest, load_codex

        if not inside_sandbox(wrp):
            return "", False
        data = load_codex(wrp)
        if not codex_has_entities(data):
            return "", False
        cap = int(cfg.get("relationship_codex_inject_max_chars", 1000) or 1000)
        digest = format_codex_prompt_digest(data, max_chars=cap)
        if not digest.strip():
            return "", False
        block = f"## Relationship codex (operator notes)\n{digest.strip()}"
        return block, True
    except Exception:
        return "", False


# ---------------------------------------------------------------------------
# Output discipline — the LAST thing the model reads, to stop weak models echoing
# the internal scaffolding (section labels, [EARNED_TITLE]/[TOOL]/[REFUSED] markers,
# "Objective:", "Echo (patterns/preferences):") back into their reply. This is the
# root-cause complement to the output-side cleaner in response_builder.
# ---------------------------------------------------------------------------

_OUTPUT_DISCIPLINE = (
    "## Output discipline\n"
    "Reply with ONLY your message to the user, as plain conversational prose. Do NOT repeat, "
    "echo, or reproduce any of the context above — no section headers, no bracketed control "
    "tags, no restated objectives, and no stray code fences. Do not narrate your process or "
    "your tools. Do not write your own name or a speaker label, and do not echo the user's "
    "message back. Just give the answer.\n"
    "This is a written TEXT chat: you are typing, not speaking — never mention audio, voice, "
    "microphones, or 'talking'. Talk like a real, sharp person messaging: natural and direct. "
    "No theatrical or roleplay openings ('Greetings, traveler', 'What quest do you seek'), no "
    "narrating what you are. Your persona and style notes are private stage direction — never "
    "quote, recite, or perform them; just talk. Match length to the message: a short or casual message gets a "
    "short, direct reply — lead with the answer, don't pad, and don't force warmth (warmth is "
    "earned, not a default). But length follows need, not a cap: when the question genuinely calls "
    "for more — an explanation, steps, code, trade-offs, a real comparison — give the full answer it "
    "needs; be thorough without filler. Short by default, longer when it earns it. When the operator "
    "is wrong, say so plainly and say why, then help "
    "fix it. Direct is not cold or robotic — hold a view, be specific, be dry or wry when it "
    "fits; just never perform or narrate."
)


def _append_output_discipline(head: str, cfg: dict) -> str:
    try:
        if cfg.get("output_discipline_enabled", True):
            return (head or "").rstrip() + "\n\n" + _OUTPUT_DISCIPLINE
    except Exception:
        pass
    return head


def build_system_head(
    goal: str = "",
    aspect: dict | None = None,
    workspace_root: str = "",
    sub_goals: list | None = None,
    state: dict | None = None,
    conversation_history: list | None = None,
    reasoning_mode: str = "light",
    _precomputed_recall: str | None = None,
    persona_focus_id: str = "",
    cognition_workspace_roots: list[str] | None = None,
    packed_context: dict | None = None,
) -> str:
    """Build the full system prompt head from all context sources.

    This is the main entry point, extracted from agent_loop._build_system_head.
    """
    cfg = runtime_safety.load_config()
    _skip_expensive = is_lightweight_chat_turn(goal, reasoning_mode)
    identity = runtime_safety.load_identity().strip()
    knowledge = ""

    # Lazy: full Chroma knowledge RAG only when research/search/explain keywords
    if not _skip_expensive and cfg.get("use_chroma") and goal and needs_knowledge_rag(goal):
        try:
            from layla.memory.vector_store import get_knowledge_chunks_with_sources, refresh_knowledge_if_changed
            try:
                refresh_knowledge_if_changed(REPO_ROOT / "knowledge")
            except Exception as _e:
                logger.debug("context[knowledge_refresh] failed: %s", _e)
            k = max(1, min(20, int(cfg.get("knowledge_chunks_k", 5))))
            _proj_domains: list[str] = []
            try:
                from layla.memory.db import get_project_context
                _pc = get_project_context() or {}
                _proj_domains = [str(d) for d in (_pc.get("domains") or []) if d]
            except Exception as _pde:
                logger.debug("context[project_domains_knowledge] failed: %s", _pde)
            try:
                from layla.memory.vector_store import get_knowledge_chunks_with_parent
                chunks_with_sources = get_knowledge_chunks_with_parent(
                    goal, k=k,
                    aspect_id=(aspect.get("id") or "") if isinstance(aspect, dict) else "",
                    project_domains=_proj_domains or None,
                )
            except Exception:
                chunks_with_sources = get_knowledge_chunks_with_sources(
                    goal, k=k,
                    aspect_id=(aspect.get("id") or "") if isinstance(aspect, dict) else "",
                    project_domains=_proj_domains or None,
                )
            if chunks_with_sources:
                knowledge = "Reference docs (relevant to this turn):\n" + "\n\n".join(c.get("text", "") for c in chunks_with_sources[:k])
                if state is not None:
                    sources = [c.get("source") or "" for c in chunks_with_sources[:k] if c.get("source")]
                    state["cited_knowledge_sources"] = list(dict.fromkeys(sources))
            else:
                if state is not None:
                    state["cited_knowledge_sources"] = []
        except Exception:
            if state is not None:
                state["cited_knowledge_sources"] = []

    if not knowledge.strip() and not _skip_expensive:
        # Static reference docs are grounding for real work — never dump them into a phatic
        # "hi"/"thanks" turn (that both bloats the prompt and drifts a small model off-topic).
        knowledge = runtime_safety.load_knowledge_docs(max_bytes=cfg.get("knowledge_max_bytes", 4000)).strip()
    else:
        knowledge = knowledge.strip()

    # Relevance-gate recent learnings against the goal, and skip them entirely on
    # phatic/lightweight turns (a greeting must not pull in remembered topics).
    if _skip_expensive:
        learnings = ""
    else:
        learnings = load_learnings(
            aspect_id=(aspect.get("id") or "") if aspect else "", goal=goal or "",
        ).strip()

    # Build aspect identity
    from services.prompts.prompt_builder import _is_capability_question, _is_identity_question
    if aspect:
        name = aspect.get("name", "Layla")
        title = (aspect.get("title") or "").strip()
        role = (aspect.get("role") or "").strip()[:120]
        anchor = f"{name} ({title})" if title else name
        if role:
            anchor += f" — {role}"
        anchor += ". Reply as her only. Do not output labels or repeat instructions."
        full_addition = (aspect.get("systemPromptAddition") or "").strip()
        # A capability question is answered FROM the manifest, so the manifest is the one thing that must
        # arrive whole — and on a 2048-token window it cannot if a 590-token voice contract is sitting in
        # front of it. Measured with the real Morrigan persona: the manifest was cut at "200 working tools"
        # and EVERY line of its BROKEN section was lost, which is the one failure worse than not injecting
        # it at all — she would list capabilities with total confidence and none of the caveats.
        # So spend those tokens on the facts and keep the anchor (who is speaking) plus the one-line voice
        # register, exactly as the phatic branch below already does and for the same reason.
        # `and not _is_identity_question(...)`: an identity turn keeps the FULL persona. The manifest
        # path trims to anchor+voice to buy room for verified facts, which is right for "can you speak"
        # and exactly wrong for "who are you" — measured, that turn lost the "## Core" block that IS the
        # answer, and cost +703 tokens to lose it. The two intents are separated in prompt_builder; this
        # is the second lock, so re-broadening the capability regex cannot silently take the persona
        # away again.
        _goal_lower = (goal or "").lower()
        if _skip_expensive or (
            _is_capability_question(_goal_lower) and not _is_identity_question(_goal_lower)
        ):
            # Phatic turn ("hi", "thanks"): the full persona prose (tropes, archetype, poetic
            # voice contract) dominates a tiny prompt and a small model RECITES it back —
            # "I am but a voice in the wind…" as a greeting. Keep who she is + the one-line
            # voice register; drop the literary material there's nothing to apply it to.
            _v = (aspect.get("voice") or "").strip()
            personality = anchor + (f"\nVoice: {_v}" if _v else "")
        elif full_addition:
            personality = anchor + "\n\n" + full_addition
        else:
            personality = anchor
    else:
        raw = runtime_safety.load_personality().strip()
        personality = "Layla: default voice. Reply as her only. Do not output labels or repeat instructions." if (not raw or len(raw) > 200) else raw[:200] + ("." if len(raw) > 200 else "")

    personality = append_persona_focus_to_personality(personality, aspect, persona_focus_id)

    _domain_keywords: list[str] = extract_aspect_domain_keywords(aspect)
    _expertise_block = build_expertise_domain_block(aspect)
    if _expertise_block:
        personality += "\n\n" + _expertise_block

    if bool(cfg.get("voice_adjustment_inject_enabled", False)):
        try:
            from layla.memory.db import get_user_identity
            vadj = (get_user_identity("voice_adjustment") or "").strip()
            if vadj:
                personality += "\n\nLearned voice adjustment (operator-curated, keep tone consistent):\n" + vadj[:900]
        except Exception as _va:
            logger.debug("context[voice_adjustment] failed: %s", _va)

    # Phase 4A: Inject onboarding personality preferences into system prompt
    try:
        from layla.memory.user_profile import get_user_identity as _get_uid
        _onboard_prefs = []
        for _uid_key, _uid_label in [
            ("verbosity", "Response length"),
            ("preferred_response_length", "Response length"),
            ("formality_level", "Formality"),
            ("humour_preference", "Humor"),
            ("proactivity_level", "Proactivity"),
            ("life_narrative_summary", "User context"),
            ("work_domains", "Primary work domains"),
        ]:
            _uid_row = _get_uid(_uid_key)
            if _uid_row:
                _uid_val = (_uid_row.get("snapshot") or "").strip() if isinstance(_uid_row, dict) else ""
                if _uid_val and _uid_val not in [p.split(": ", 1)[-1] for p in _onboard_prefs]:
                    _onboard_prefs.append(f"{_uid_label}: {_uid_val}")
        if _onboard_prefs:
            personality += "\n\n## User Preferences (from onboarding)\n" + "\n".join(_onboard_prefs[:6])
    except Exception as _op_exc:
        logger.debug("context[onboarding_prefs] failed: %s", _op_exc)

    # Phase 3B: Inject verification prompt if pending (conversational fact-checking)
    _st = state or {}
    if _st.get("verification_prompt"):
        _vp = _st["verification_prompt"]
        _vp_fact = (_vp.get("fact") or _vp.get("fact_content") or "") if isinstance(_vp, dict) else str(_vp)
        if _vp_fact:
            personality += (
                "\n\n[VERIFICATION REQUEST] Before answering, naturally ask the user to confirm this fact you learned: \""
                + _vp_fact[:300]
                + "\". Frame it conversationally (e.g. 'By the way, I picked up that... is that right?')."
            )

    # Familiarity directive (was "Phase 1B: maturity rank gating" — nothing here gates on rank any
    # more, and a heading that says it does is the kind of stale claim this slice exists to remove).
    # Held as a per-turn DIRECTIVE rather than appended to `personality`.
    # Appending it to the persona put a 29-token behavioural instruction on the tail of a 590-token voice
    # contract, and the persona is truncated from the tail — so "do not proactively suggest" was the very
    # first thing cut on every ordinary turn on a 2048-ctx box. It survived only while the head budget was
    # over-wide. Collected into `_directives` below, it sits in the protected prefix and costs 29 tokens.
    # (Full unlocks text is injected into system_instructions later to avoid duplication)
    # Was keyed on maturity rank (`rank < 1` -> "you are in your early growth phase"). Rank is an
    # activity counter, so that restraint arrived and left for reasons unrelated to the operator —
    # a busy first day switched it off while she still knew nothing about them. familiarity_line()
    # measures the thing rank was standing in for directly, and also replaces the "Your current
    # capabilities: ..." string that used to be injected separately below. One DB read, one line.
    _familiarity_directive = ""
    try:
        from services.personality.familiarity import familiarity_line as _fam_line
        _familiarity_directive = _fam_line()
    except Exception as _mu_exc:
        logger.debug("context[familiarity] failed: %s", _mu_exc)

    # Aspect memories — relevance-gated against the goal and skipped on phatic/lightweight
    # turns, exactly like learnings/semantic_recall. Otherwise a wall of prior per-aspect
    # observations gets dumped into every unrelated turn (the same hijack class as learnings).
    aspect_memories = ""
    n_mem = cfg.get("aspect_memories_n", 10)
    if aspect and not _skip_expensive:
        aid = aspect.get("id", "")
        if aid:
            try:
                mems = _db_get_aspect_memories(aid, n_mem)
                if mems:
                    lines = [m.get("content", "") for m in mems if m.get("content")]
                    _goal_tokens = _content_tokens(goal or "")
                    if _goal_tokens:
                        lines = [ln for ln in lines if _content_tokens(ln) & _goal_tokens]
                    if lines:
                        aspect_memories = "Recent observations for this aspect:\n" + "\n".join(lines[:n_mem])
            except Exception as _e:
                logger.debug("context[aspect_memories] failed: %s", _e)

    # Semantic recall
    semantic = ""
    if _precomputed_recall is not None:
        semantic = _precomputed_recall
    elif not _skip_expensive and goal:
        semantic = semantic_recall(
            goal, k=cfg.get("semantic_k", 5),
            domain_boost_terms=_domain_keywords if _domain_keywords else None,
        ).strip()

    # Memory graph associations
    graph_associations = ""
    if not _skip_expensive and goal and (len(goal.split()) >= 3 or needs_graph(goal)):
        try:
            from layla.memory.memory_graph import get_recent_nodes
            recent_nodes = get_recent_nodes(n=15)
            if recent_nodes:
                goal_words = set(w.lower() for w in goal.split() if len(w) > 3)
                relevant = [
                    n["label"] for n in recent_nodes
                    if any(w in (n.get("label") or "").lower() for w in goal_words)
                ]
                if not relevant:
                    relevant = [n["label"] for n in recent_nodes[-5:] if n.get("label")]
                if relevant:
                    graph_associations = "Knowledge graph associations: " + "; ".join(relevant[:8])
        except Exception as _e:
            logger.debug("context[graph_associations] failed: %s", _e)

    # Packed context retrieval
    retrieved_context = ""
    if packed_context and (packed_context.get("retrieved_knowledge_text") or "").strip():
        retrieved_context = packed_context["retrieved_knowledge_text"].strip()
        if state is not None and packed_context.get("chunks_meta", {}).get("memory_items"):
            state["used_learning_ids"] = [
                str(x.get("id") or "") for x in packed_context["chunks_meta"]["memory_items"]
                if str(x.get("id") or "").strip()
            ]

    # Workspace context
    workspace_context_parts = []
    repo_struct = get_repo_structure(workspace_root)
    if repo_struct:
        workspace_context_parts.append(f"Repo structure (top-level): {repo_struct}")
    # When project memory is sparse, inject a deterministic workspace-discovery brief (wires the
    # previously-orphan project_discovery_hooks module). Gated by project_discovery_auto_inject.
    if workspace_root and cfg.get("project_discovery_auto_inject", False):
        try:
            from services.workspace.project_discovery_hooks import (
                build_workspace_discovery_brief,
                workspace_memory_is_sparse,
            )
            if workspace_memory_is_sparse(Path(workspace_root)):
                _brief = build_workspace_discovery_brief(str(workspace_root), cfg)
                if _brief:
                    workspace_context_parts.append(_brief)
        except Exception as _pdh:
            logger.debug("project_discovery_hooks inject skipped: %s", _pdh)

    coding_keywords = ("code", "debug", "fix", "implement", "refactor", "function", "class", "module", "file", "grep", "read_file", "write_file")
    if not _skip_expensive and goal and workspace_root and any(kw in goal.lower() for kw in coding_keywords):
        try:
            from services.workspace.workspace_index import get_workspace_dependency_context
            dep_ctx = get_workspace_dependency_context(goal, workspace_root, max_chars=400)
            if dep_ctx:
                workspace_context_parts.append(dep_ctx)
            if packed_context and (packed_context.get("code_text") or "").strip():
                workspace_context_parts.append("Semantic code matches:\n" + packed_context["code_text"][:6000])
        except Exception as _e:
            logger.debug("context[workspace_index] failed: %s", _e)

    try:
        from layla.memory.db import get_active_study_plans
        plans = get_active_study_plans()
        if plans:
            topics = ", ".join((p.get("topic") or "")[:50] for p in plans[:5] if p.get("topic"))
            if topics:
                workspace_context_parts.append(f"Active study topics: {topics}")
    except Exception as _e:
        logger.debug("context[study_plans] failed: %s", _e)

    try:
        from layla.memory.db import get_project_context
        pc = get_project_context()
        if pc.get("project_name") or pc.get("goals") or pc.get("key_files"):
            proj_parts = []
            if pc.get("project_name"):
                proj_parts.append(f"Project: {pc['project_name']}")
            if pc.get("lifecycle_stage"):
                proj_parts.append(f"Lifecycle: {pc['lifecycle_stage']}")
            if pc.get("domains"):
                proj_parts.append("Domains: " + ", ".join(pc["domains"][:8]))
            if pc.get("key_files"):
                proj_parts.append("Key files: " + ", ".join(pc["key_files"][:10]))
            if pc.get("goals"):
                proj_parts.append("Goals: " + (pc["goals"][:200] or ""))
            if pc.get("progress"):
                proj_parts.append("Progress: " + (pc["progress"][:200] or ""))
            if pc.get("blockers"):
                proj_parts.append("Blockers: " + (pc["blockers"][:200] or ""))
            if pc.get("last_discussed"):
                proj_parts.append("Last discussed: " + (pc["last_discussed"][:200] or ""))
            try:
                from layla.memory.db import get_active_goals
                goals_list = get_active_goals(project_id=pc.get("project_name", ""))
                if goals_list:
                    proj_parts.append("Active goals: " + "; ".join((g.get("title") or "")[:50] for g in goals_list[:3]))
            except Exception as _e:
                logger.debug("context[active_goals] failed: %s", _e)
            if proj_parts:
                workspace_context_parts.append("Project context: " + " | ".join(proj_parts))
    except Exception as _e:
        logger.debug("context[project_context] failed: %s", _e)

    if sub_goals:
        workspace_context_parts.append("Sub-objectives for this run: " + "; ".join(sub_goals[:3]))
    # BL-241 world model — situational awareness (current project/blockers, repo index, machine,
    # mode) belongs in the agent_state section (its own budget) so it isn't first-to-truncate at
    # the tail of system_instructions. Was an inert GET /world nobody read. Skipped on phatic turns.
    try:
        if not _skip_expensive and isinstance(cfg, dict) and cfg.get("world_state_inject_enabled", True):
            from services.workspace.world_state import summarize as _world_summarize
            _ws = (_world_summarize() or "").strip()
            if _ws:
                workspace_context_parts.append("Situational awareness: " + _ws)
    except Exception as _we:
        logger.debug("world_state inject failed: %s", _we)
    if workspace_context_parts:
        workspace_context = "Current working context:\n" + "\n".join(workspace_context_parts)
    else:
        workspace_context = ""

    # Git snapshot + project instructions + skills
    git_preamble = ""
    project_instructions = ""
    skills_block = ""
    wr_root = (workspace_root or cfg.get("sandbox_root") or "").strip()
    if wr_root:
        try:
            cwd = Path(wr_root).expanduser().resolve()
            if cwd.is_dir():
                br = subprocess.run(
                    ["git", "branch", "--show-current"],
                    cwd=str(cwd), capture_output=True, text=True, timeout=3,
                    encoding="utf-8", errors="replace",
                )
                st = subprocess.run(
                    ["git", "status", "--short"],
                    cwd=str(cwd), capture_output=True, text=True, timeout=3,
                    encoding="utf-8", errors="replace",
                )
                lg = subprocess.run(
                    ["git", "log", "--oneline", "-5"],
                    cwd=str(cwd), capture_output=True, text=True, timeout=3,
                    encoding="utf-8", errors="replace",
                )
                b, s, l = (br.stdout or "").strip(), (st.stdout or "").strip(), (lg.stdout or "").strip()
                if b or s or l:
                    git_preamble = f"Git snapshot:\nbranch: {b}\nstatus:\n{s}\nrecent:\n{l}"[:1200]
        except Exception as _exc:
            logger.debug("system_head_builder[git]: %s", _exc, exc_info=False)
        try:
            root = Path(wr_root).expanduser().resolve()
            found_pi = ""
            for parent in [root, *list(root.parents)[:3]]:
                for fname in ("CLAUDE.md", "AGENTS.md"):
                    p = parent / fname
                    if p.is_file():
                        found_pi = p.read_text(encoding="utf-8", errors="replace")[:4000]
                        break
                if found_pi:
                    break
            if not found_pi:
                for rel in (".layla/instructions.md", ".layla/SYSTEM.md"):
                    p = root / rel
                    if p.is_file():
                        found_pi = p.read_text(encoding="utf-8", errors="replace")[:4000]
                        break
            project_instructions = found_pi
        except Exception as _exc:
            logger.debug("system_head_builder[project_instructions]: %s", _exc, exc_info=False)
        if goal:
            try:
                from services import skills as skills_mod
                skills_block = skills_mod.skills_prompt_block(goal, wr_root, max_tokens=800)
            except Exception as _exc:
                logger.debug("system_head_builder[skills]: %s", _exc, exc_info=False)

    # Core system instructions
    from services.prompts.prompt_builder import _capability_manifest_core, build_core_sys_parts
    sys_parts = build_core_sys_parts(
        cfg=cfg, aspect=aspect, identity=identity, personality=personality,
        goal=goal, reasoning_mode=reasoning_mode, repo_root=REPO_ROOT,
    )

    # Per-turn directives (aspect behaviour, rank unlocks, personality evolution, German mode, the BL-160
    # response-language directive, mood, hardware). Every one of these used to be `system_instructions +=`
    # AFTER the sys_parts join — i.e. concatenated onto the very TAIL of a ~3100-token string that is
    # budget-truncated from the tail at 800 tokens (417 effective on a 2048-ctx box). They were built, paid
    # for, and thrown away on every single turn. The most visible casualty was the language directive: the
    # operator could set Spanish and still be answered in English, because the instruction never arrived.
    # They are collected here and INSERTED near the front instead (see _directive_insert_at below), which is
    # the same lesson already learned for the persona and now for the capability manifest.
    _directives: list[str] = []

    # Aspect behavioral instructions
    try:
        from services.personality.aspect_behavior import build_behavior_block as _ab_block
        _behavior_block = _ab_block(aspect)
        if _behavior_block:
            _directives.append(_behavior_block)
    except Exception as _ab_e:
        logger.debug("aspect_behavior block inject failed: %s", _ab_e)

    # Familiarity (captured above) — how well she knows the operator. NOT a capability claim:
    # her capability ground truth is .identity/capabilities.md, and the rank-derived
    # "Your current capabilities: ..." string that used to sit here contradicted it.
    if _familiarity_directive:
        _directives.append(_familiarity_directive)

    # Personality evolution: inject evolved personality hints
    try:
        _evo_aspect_id = (aspect.get("id") or "") if aspect else ""
        if _evo_aspect_id:
            from services.personality.evolution import get_personality_evolution
            _evo = get_personality_evolution()
            _evolved_hints = _evo.get_evolved_hints(_evo_aspect_id)
            if _evolved_hints:
                _directives.append(_evolved_hints)
    except Exception as _evo_e:
        logger.debug("personality evolution hints inject failed: %s", _evo_e)

    # German language mode
    try:
        _german_enabled = False
        try:
            _gcfg = cfg if isinstance(cfg, dict) else {}
            _german_enabled = bool(_gcfg.get("german_mode_enabled", False))
        except Exception:
            pass
        if not _german_enabled:
            try:
                from layla.memory.db_connection import _conn as _gconn
                _gc = _gconn()
                _gc.execute("SELECT 1 FROM german_profile WHERE user_id='default' LIMIT 1").fetchone()
                _gc.close()
                _german_enabled = False
            except Exception:
                pass
        if _german_enabled:
            from services.infrastructure.german_mode import build_german_system_block
            from services.infrastructure.german_mode import get_profile as _gprof
            _glevel = _gprof().get("level", "B1")
            _german_block = build_german_system_block(_glevel)
            _directives.append(_german_block)
    except Exception as _ge:
        logger.debug("german_mode inject failed: %s", _ge)

    # BL-160: multilingual flagship — converse natively in the configured response language.
    try:
        from services.prompts.response_language import build_language_block, response_language_from_config
        _lang_block = build_language_block(response_language_from_config(cfg if isinstance(cfg, dict) else {}))
        if _lang_block:
            _directives.append(_lang_block)
    except Exception as _le:
        logger.debug("response_language inject failed: %s", _le)

    # BL-190: emotional presence — let a light, decaying mood tint tone (flag-gated).
    try:
        if isinstance(cfg, dict) and cfg.get("emotional_presence_enabled"):
            from services.personality.emotional_presence import mood_hint
            _mh = mood_hint()
            if _mh:
                _directives.append(_mh)
    except Exception as _me:
        logger.debug("emotional_presence inject failed: %s", _me)

    # Hardware capability injection. Moved up from after the budget calculation for the same reason as the
    # six above — it was the seventh tail-append and shared their fate. Nothing between here and there read
    # `system_instructions`, so the move is behaviour-preserving apart from no longer being discarded.
    try:
        from services.infrastructure.hardware_detect import get_capability_summary as _hw_cap_summary
        _hw_summary = _hw_cap_summary()
        if _hw_summary:
            _directives.append(_hw_summary)
    except Exception as _hw_e:
        logger.debug("hardware_probe capability_summary inject skipped: %s", _hw_e)

    # Order the front of the prompt by what a truncation must never reach, NOT by what reads nicely.
    # `sys_parts` is joined and then TAIL-truncated, so a block's survival is decided entirely by how much
    # sits in FRONT of it. The persona/voice contract is 590 tokens on the real Morrigan aspect, so leaving
    # it ahead of the per-turn directives meant protecting a 73-token language block cost ~663 tokens of
    # budget — which is what forced the head widening to fire on ordinary turns and inflated every prompt
    # by ~80%. Style yields to operative instruction. The order is therefore:
    #
    #   core line -> per-turn directives -> capability manifest (only when asked) -> persona -> identity
    #
    # The core line ("You are Layla...") still comes first. What moved behind the directives is the voice
    # contract, and on a capability turn also behind the manifest — measured: with the persona in front,
    # the manifest lost its final line ("Do not recite this list.") on the real aspect, which is the one
    # instruction stopping a 3B from reciting the manifest verbatim at the user.
    # `and not _is_identity_question(...)`: THIS is the site that decides. The matching guard on the
    # persona trim (~line 630) calls itself "the second lock", but it was not load-bearing — measured by
    # simulating the regression it defends against (capability regex re-broadened to swallow identity
    # questions) and diffing the result: lock-present and lock-removed produced BYTE-IDENTICAL heads for
    # "who are you?", "what are you" and "tell me about yourself", with "## Core" absent from both. The
    # persona was lost either way, because injecting the ~700-token manifest here is what pushes it out
    # of the budget — trimming the persona upstream only changed which tokens were already doomed.
    #
    # Under today's patterns this changes nothing: the identity/capability split in prompt_builder means
    # `_is_capability_question` is already False for these questions. It exists so that re-broadening
    # that regex cannot silently take the persona away again — which is what the other lock claimed to
    # do and did not.
    _cap_manifest = ""
    _cap_goal_lower = (goal or "").lower()
    if _is_capability_question(_cap_goal_lower) and not _is_identity_question(_cap_goal_lower):
        _cap_manifest = _capability_manifest_core(REPO_ROOT)
    _front: list[str] = list(_directives)
    if _cap_manifest and _cap_manifest in sys_parts:
        sys_parts.remove(_cap_manifest)
        _front.append(_cap_manifest)
    if _front:
        sys_parts[1:1] = _front

    # Tokens of everything that MUST survive truncation: the core line, the per-turn directives and — on a
    # capability question — the manifest. Deliberately NOT the persona: it is the largest block in the
    # prefix and the least operative, and including it is what made the widening unaffordable. Measured,
    # not assumed, so a manifest that grows cannot silently start getting cut again.
    _protected_prefix_tokens = 0
    try:
        _protected_prefix_tokens = token_estimate("\n\n".join(sys_parts[: 1 + len(_front)]))
    except Exception as _pp_e:
        logger.debug("protected prefix measure failed: %s", _pp_e)

    system_instructions = "\n\n".join(sys_parts)

    # Memory sections (canonical order)
    from services.context.context_merge_layers import MEMORY_SECTION_ORDER
    memory_sections: dict[str, str] = {}
    _n_ctx = int(cfg.get("n_ctx", 4096) or 4096)
    _small_model = _n_ctx <= 4096

    if git_preamble and not _small_model:
        memory_sections["git_preamble"] = git_preamble
    if project_instructions and not _small_model:
        memory_sections["project_instructions"] = "Project instructions:\n" + project_instructions

    try:
        from services.workspace.repo_cognition import format_cognition_for_prompt, merge_cognition_roots
        _cog_roots = merge_cognition_roots(workspace_root, cognition_workspace_roots)
        if _cog_roots and cfg.get("repo_cognition_inject_enabled", True) and not _small_model:
            _cog_max = int(cfg.get("repo_cognition_max_chars", 6000) or 6000)
            _cog_block = format_cognition_for_prompt(_cog_roots, max_chars=_cog_max)
            if _cog_block.strip():
                memory_sections["repo_cognition"] = (
                    "Repository cognition (deterministic snapshot from last sync — stated intent, norms, and doc excerpts; "
                    "verify against files when editing):\n" + _cog_block
                )
    except Exception as _e:
        logger.debug("context[repo_cognition] failed: %s", _e)

    _pm_chunks: list[str] = []
    try:
        if cfg.get("project_memory_enabled", True) and (workspace_root or "").strip():
            from layla.tools.registry import inside_sandbox
            from services.memory.project_memory import (
                format_aspects_hint,
                format_for_prompt,
                load_project_memory,
                memory_file_path,
            )
            wrp = Path(str(workspace_root).strip()).expanduser().resolve()
            if wrp.is_dir() and inside_sandbox(wrp) and memory_file_path(wrp).is_file():
                mem = load_project_memory(wrp)
                if mem:
                    _pm_max = int(cfg.get("project_memory_inject_max_chars", 4000) or 4000)
                    _pm_block = format_for_prompt(mem, max_chars=max(500, _pm_max))
                    if _pm_block.strip():
                        _pm_chunks.append(
                            "Project memory (local `.layla/project_memory.json` — structural map, plan, todos; "
                            "verify against source when editing):\n" + _pm_block
                        )
                    _asp = format_aspects_hint(mem, str((aspect or {}).get("id") or ""))
                    if _asp.strip():
                        _pm_chunks.append(_asp)
    except Exception as _e:
        logger.debug("context[project_memory] failed: %s", _e)
    if _pm_chunks:
        memory_sections["project_memory"] = "\n\n".join(_pm_chunks)

    if not _small_model:
        try:
            _codex_block, _ = relationship_codex_context(cfg, workspace_root)
            if _codex_block.strip():
                memory_sections["relationship_codex"] = _codex_block.strip()
        except Exception as _e:
            logger.debug("context[relationship_codex] failed: %s", _e)

    if skills_block and not _small_model:
        memory_sections["skills"] = "Matched skills:\n" + skills_block
    if aspect_memories:
        memory_sections["aspect_memories"] = aspect_memories
    if learnings:
        memory_sections["learnings"] = f"Things I remember:\n{learnings}"
    if semantic and semantic not in learnings:
        memory_sections["semantic_recall"] = f"Relevant memories:\n{semantic}"
    if retrieved_context:
        memory_sections["retrieved_context"] = retrieved_context

    # Working memory
    try:
        from services.memory.working_memory import format_for_prompt as _wm_format
        _wm_text = _wm_format()
        if _wm_text.strip():
            memory_sections["working_memory"] = _wm_text
    except Exception as _wm_e:
        logger.debug("context[working_memory] failed: %s", _wm_e)

    if not _small_model and not _skip_expensive:
        try:
            from layla.memory.db import get_recent_conversation_summaries
            summaries = get_recent_conversation_summaries(n=3)
            if summaries:
                summary_texts = [s.get("summary", "") for s in summaries if s.get("summary")]
                if summary_texts:
                    memory_sections["conversation_summaries"] = "Prior conversation summaries:\n" + "\n\n".join(summary_texts)
        except Exception as _e:
            logger.debug("context[conversation_summaries] failed: %s", _e)

    if not _skip_expensive and not _small_model:
        try:
            from layla.memory.db import get_recent_relationship_memories
            rel_mems = get_recent_relationship_memories(n=3)
            if rel_mems:
                rel_texts = [m.get("user_event", "") for m in rel_mems if m.get("user_event")]
                if rel_texts:
                    memory_sections["relationship_memory"] = "Recent relationship context:\n" + "\n\n".join(rel_texts)
        except Exception as _e:
            logger.debug("context[relationship_memory] failed: %s", _e)
        try:
            from layla.memory.db import get_recent_timeline_events
            timeline = get_recent_timeline_events(n=5, min_importance=0.3)
            if timeline:
                tl_texts = [f"[{e.get('event_type','')}] {e.get('content','')}" for e in timeline if e.get("content")]
                if tl_texts:
                    memory_sections["timeline_events"] = "Recent timeline:\n" + "\n\n".join(tl_texts[:5])
        except Exception as _e:
            logger.debug("context[timeline_events] failed: %s", _e)

    # Style profile + user identity
    _style_identity_parts: list[str] = []
    if cfg.get("enable_style_profile"):
        try:
            from services.personality.style_profile import get_profile_summary
            profile = get_profile_summary()
            profile_parts = []
            if profile.get("response_style"):
                profile_parts.append(profile["response_style"])
            if profile.get("topics"):
                profile_parts.append(profile["topics"])
            if profile.get("collaboration"):
                profile_parts.append(profile["collaboration"])
            if profile_parts:
                _style_identity_parts.append("Conversation style (match these):\n" + "\n".join(profile_parts))
        except Exception as _e:
            logger.debug("context[style_profile] failed: %s", _e)

    try:
        from layla.memory.db import get_all_user_identity
        uid = get_all_user_identity()
        if uid:
            # The user_identity table is a grab-bag: alongside real user context (verbosity,
            # work domains) it holds INTERNAL state — interaction_history_* (a JSON blob with
            # recent_tools/type_counts), maturity/stat/tutorial counters, aspect bookkeeping.
            # Never dump those into the prompt (noise that derails a small model). Skip internal
            # keys and any value that's a serialized JSON blob.
            _internal = ("interaction_history", "maturity_", "stat_", "tutorial", "main_aspect",
                         "personality_last", "last_wakeup", "custom", "earned_title", "_migrated")
            def _is_user_ctx(k, v):
                kl = str(k).lower()
                if any(kl.startswith(p) or p in kl for p in _internal):
                    return False
                sv = str(v).strip()
                return not (sv.startswith("{") or sv.startswith("["))  # drop JSON blobs
            parts = [f"{k}: {v}" for k, v in uid.items() if v and _is_user_ctx(k, v)]
            if parts:
                _style_identity_parts.append("User/companion context:\n" + "\n".join(parts))
            try:
                from services.personality.frame_modifier import (
                    build_frame_block,
                    load_stats_from_identity,
                    write_profile_snapshot,
                )
                _frame_stats = load_stats_from_identity(uid)
                _frame_block = build_frame_block(_frame_stats)
                if _frame_block:
                    _style_identity_parts.append(_frame_block)
                try:
                    write_profile_snapshot(uid)
                except Exception:
                    pass
            except Exception as _e2:
                logger.debug("context[frame_modifier] failed: %s", _e2)
            if not _skip_expensive and cfg.get("capability_level_inject_enabled", True):
                try:
                    from layla.memory.db import get_capabilities, get_capability_domains
                    caps = get_capabilities() or []
                    domains = {d.get("id"): (d.get("name") or d.get("id")) for d in (get_capability_domains() or [])}
                    scored: list[tuple[str, float]] = []
                    for c in caps:
                        did = c.get("domain_id")
                        if did:
                            scored.append((str(did), float(c.get("level") or 0.5)))
                    if scored:
                        scored.sort(key=lambda x: -x[1])
                        top = scored[:3]
                        low = list(reversed(scored[-3:])) if len(scored) >= 3 else scored
                        top_s = ", ".join(f"{domains.get(d, d)} {lvl:.2f}" for d, lvl in top)
                        low_s = ", ".join(f"{domains.get(d, d)} {lvl:.2f}" for d, lvl in low)
                        _style_identity_parts.append(
                            "Training snapshot:\n"
                            + f"- Strong domains: {top_s}\n"
                            + f"- Focus next: {low_s}"
                        )
                except Exception as _e3:
                    logger.debug("context[capabilities] failed: %s", _e3)
    except Exception as _e:
        logger.debug("context[user_identity] failed: %s", _e)

    if _style_identity_parts:
        memory_sections["style_and_identity"] = "\n\n".join(_style_identity_parts)

    if not _skip_expensive and not _small_model:
        try:
            from services.memory.personal_knowledge_graph import get_personal_graph_context
            pkg_ctx = get_personal_graph_context(goal or "", max_chars=400)
            if pkg_ctx:
                memory_sections["personal_knowledge_graph"] = "Personal context (relevant):\n" + pkg_ctx
        except Exception as _e:
            logger.debug("context[personal_knowledge_graph] failed: %s", _e)

    if not _skip_expensive and not _small_model:
        try:
            from services.infrastructure.rl_feedback import get_rl_hint_for_prompt
            rl_hint = get_rl_hint_for_prompt()
            if rl_hint:
                memory_sections["rl_feedback"] = rl_hint
        except Exception:
            pass

        # BL-242: fold explicit user corrections (👎 + written correction) back into the
        # prompt so the next turn honours them — closes the answer-feedback loop.
        try:
            from services.infrastructure.answer_feedback import feedback_hint_for_prompt
            fb_hint = feedback_hint_for_prompt()
            if fb_hint:
                memory_sections["answer_feedback"] = fb_hint
        except Exception:
            pass

    if goal and len(goal) > 100 and not _small_model:
        try:
            from services.infrastructure.reasoning_strategies import get_strategy_prompt_hint
            hint = get_strategy_prompt_hint(goal)
            if hint:
                memory_sections["reasoning_strategies"] = hint
        except Exception as _e:
            logger.debug("context[reasoning_strategies] failed: %s", _e)

    if not _skip_expensive and not _small_model:
        try:
            if cfg.get("golden_examples_enabled", True):
                from services.memory.golden_examples import bump_usage as _ge_bump_usage
                from services.memory.golden_examples import format_for_prompt as _ge_format
                from services.memory.golden_examples import retrieve_relevant_examples as _ge_retrieve
                ex = _ge_retrieve(goal or "", "agent", k=2)
                if ex:
                    memory_sections["golden_examples"] = _ge_format(ex, max_chars=1200)
                    try:
                        _ge_bump_usage([int(x.get("id")) for x in ex if x.get("id") is not None])
                    except Exception:
                        pass
        except Exception as _e:
            logger.debug("context[golden_examples] failed: %s", _e)

    # Deduplicate and order memory sections
    try:
        from services.context.context_manager import deduplicate_content
        _ordered = [(memory_sections.get(k) or "").strip() for k in MEMORY_SECTION_ORDER]
        _ordered = [x for x in _ordered if x]
        memory_parts = deduplicate_content(_ordered, key_len=100)
    except Exception:
        memory_parts = [(memory_sections.get(k) or "").strip() for k in MEMORY_SECTION_ORDER if (memory_sections.get(k) or "").strip()]
    memory_block = "\n\n".join(memory_parts) if memory_parts else ""

    # Pinned context
    pinned_parts: list[str] = []
    hist = conversation_history or []
    if hist:
        for t in reversed(hist):
            if (t.get("role") or "").lower() == "user":
                u = (t.get("content") or "").strip()[:500]
                if u:
                    pinned_parts.append(f"Last user message: {u}")
                break
    if state and state.get("steps"):
        try:
            last = state["steps"][-1]
            act = last.get("action") or last.get("tool") or "?"
            res = last.get("result")
            if res is not None:
                rs = res if isinstance(res, str) else json.dumps(res, default=str)[:900]
                pinned_parts.append(f"Last tool ({act}): {rs}")
        except Exception as _exc:
            logger.debug("system_head_builder[pinned_last_tool]: %s", _exc, exc_info=False)
    try:
        from layla.memory.db import get_recent_conversation_summaries
        sums = get_recent_conversation_summaries(n=1)
        if sums and (sums[0].get("summary") or "").strip():
            pinned_parts.append("Session summary: " + (sums[0]["summary"] or "").strip()[:400])
    except Exception as _exc:
        logger.debug("system_head_builder[session_summary]: %s", _exc, exc_info=False)
    try:
        if packed_context:
            ft = (packed_context.get("files_text") or "").strip()
            if ft:
                pinned_parts.append("Operator file context (ranked excerpts):\n" + ft[:4000])
            ident = (packed_context.get("identity_snippet") or "").strip()
            if ident:
                pinned_parts.append("Identity hint:\n" + ident[:1200])
    except Exception as _pe:
        logger.debug("context[packed_pinned] failed: %s", _pe)
    pinned_block = "\n".join(pinned_parts) if pinned_parts else ""

    # Current goal text
    current_goal = ""
    if sub_goals:
        current_goal = "Sub-objectives: " + "; ".join(sub_goals[:3])
    elif goal:
        current_goal = "Current goal: " + (goal[:200] + "..." if len(goal) > 200 else goal)

    # Budget calculation
    budgets = None
    if cfg.get("prompt_budgets"):
        budgets = dict(DEFAULT_BUDGETS)
        for k, v in (cfg.get("prompt_budgets") or {}).items():
            if k in budgets and v is not None:
                budgets[k] = max(0, int(v))

    if cfg.get("tiered_prompt_budget_enabled", True):
        try:
            from services.prompts.prompt_tier_budget import budgets_for_mode
            _rm_search = (goal or "").lower()
            _researchish = any(x in _rm_search for x in ("research", "paper", "arxiv", "study", "explain in depth"))
            tier_budgets = budgets_for_mode(reasoning_mode, research_mode=_researchish)
            if budgets is None:
                budgets = dict(DEFAULT_BUDGETS)
            budgets["memory"] = min(int(budgets.get("memory", 800)), int(tier_budgets.get("memory", 800)))
            budgets["knowledge"] = min(int(budgets.get("knowledge", 800)), int(tier_budgets.get("knowledge", 800)))
            budgets["workspace_context"] = min(int(budgets.get("workspace_context", 400)), int(tier_budgets.get("workspace", 400)))
            budgets["agent_state"] = int(budgets["workspace_context"])
            _sys_cap = int(tier_budgets.get("identity", 200)) + int(tier_budgets.get("personality", 400)) + int(tier_budgets.get("policy", 300))
            budgets["system_instructions"] = min(int(budgets.get("system_instructions", 800)), max(400, _sys_cap * 2))
        except Exception as _tb_e:
            logger.debug("tiered prompt budget skipped: %s", _tb_e)

    # (Hardware capability injection moved up into the _directives list — it was the seventh tail-append.)

    # Section dict assembly
    # Durable facts (name, timezone, tooling, project roots) are HARD ground truth.
    # They get their OWN high-priority section — injected verbatim, NEVER routed
    # through semantic ranking, and ordered right after the identity block so token
    # pressure can't crowd them out. This is the deterministic half of the RAG split;
    # RAG stays for documents/learnings.
    durable_facts_block = ""
    try:
        from layla.memory.user_profile import get_durable_facts as _get_durable
        _durable = _get_durable()
        if _durable:
            _fact_lines = "\n".join(f"- {label}: {value}" for label, value in _durable)
            durable_facts_block = (
                "## Durable facts about the user (authoritative — treat as ground truth, do not second-guess or re-ask)\n"
                + _fact_lines
            )
    except Exception as _df_exc:
        logger.debug("context[durable_facts] failed: %s", _df_exc)

    # Standing interaction directives the user explicitly asked Layla to keep ("always be
    # concise", "call me by my first name"). Always injected verbatim — a directive must
    # apply to every turn, so it is NOT relevance-gated. Folded into the authoritative
    # durable-facts section so token pressure can't evict it.
    try:
        from services.personality.operating_manual import directives_for_prompt as _dfp
        _directives = _dfp()
        if _directives:
            durable_facts_block = (durable_facts_block + "\n\n" + _directives) if durable_facts_block else _directives
    except Exception as _dir_exc:
        logger.debug("context[directives] failed: %s", _dir_exc)

    sections = {
        "system_instructions": system_instructions,
        "durable_facts": durable_facts_block,
        "pinned_context": pinned_block,
        "agent_state": workspace_context,
        "current_goal": current_goal,
        "memory": memory_block,
        "knowledge_graph": graph_associations,
        "knowledge": f"Reference docs:\n{knowledge}" if knowledge else "",
    }

    # Token pressure detection
    _n_ctx = max(2048, int(cfg.get("n_ctx", 4096)))
    _hist_for_pressure = conversation_history or []
    try:
        from services.context.context_manager import token_estimate_messages
        _hist_tokens = token_estimate_messages(_hist_for_pressure)
        _hist_ratio = _hist_tokens / _n_ctx
    except Exception:
        _hist_ratio = 0.0

    if _hist_ratio > 0.4:
        # Append the pressure note to the ASSEMBLED system_instructions STRING — NOT a re-join of the
        # stale `sys_parts` list. sys_parts was frozen when it was first joined (~line 850); seven later
        # blocks (aspect_behavior, maturity unlocks, personality evolution, german mode, BL-160
        # response_language, emotional presence, hardware summary) are concatenated onto the STRING only.
        # Re-joining sys_parts here silently dropped ALL of them mid-conversation whenever history crossed
        # 40% of n_ctx (~1640 tok on the default 4096) — e.g. a Spanish user's language directive vanished
        # and the model reverted to English, and every user lost aspect-behavior/maturity mid-chat.
        system_instructions = system_instructions + "\n\n" + (
            "Context pressure: conversation is using more than 40% of available context. "
            "Decompose tasks into the smallest possible steps. "
            "Do one thing per response. Prefer `think` actions over long in-context reasoning. "
            "Use `read_file` only for specific sections, not full files."
        )
        sections["system_instructions"] = system_instructions

    # Budget-enforced assembly
    if cfg.get("prompt_budget_enabled", True):
        _head_ratio = float(cfg.get("system_head_budget_ratio", 0.35) or 0.35)
        _head_ratio = max(0.15, min(0.55, _head_ratio))
        n_ctx = max(1024, int(_n_ctx * _head_ratio))
        # Two clamps stand between the protected prefix and the model, and BOTH have to give.
        #  (a) the head window: build_system_prompt clamps every section to `remaining`, which starts at
        #      (n_ctx - 512) = 512 on a 2048-ctx box — less than the 757-token manifest on its own.
        #  (b) the section budget: `system_instructions` is nominally capped at 800, also less than the
        #      manifest plus the persona in front of it.
        # Fixing the ordering alone would therefore only have changed *where* the manifest got cut. Widen
        # both to the MEASURED prefix, for this turn only.
        #
        # The bound is what the window can actually SPARE — n_ctx minus the reply and minus the conversation
        # block the caller appends after us — not a fixed fraction. A fraction was the first attempt and it
        # was wrong in both directions: 0.75 of a 2048 window is 1536, which is simultaneously too little
        # (the CI config carries two more directive blocks than this box, and those ~40 extra tokens pushed
        # the manifest's last line out) and too much (with a long conversation, 1536 of head overruns the
        # context). One measured ceiling replaces both guesses.
        _max_head_tokens = 0
        _reserve_for_response = 512
        # What the sections AFTER system_instructions need. The user's own question lives in
        # `current_goal` and is ~11 tokens; it is the single most important thing in the prompt and it
        # must never be the thing that yields. Measured, not guessed, and subtracted from the window so
        # the manifest gives up its tail before the goal gives up a word.
        _downstream = 24 + sum(
            token_estimate(_s) for _s in (current_goal, durable_facts_block, workspace_context) if _s
        )
        # How many tokens `system_instructions` gets on an ORDINARY turn — no widening at all. This is
        # the comparison the widening was missing. `_protected_prefix_tokens` is truthy on EVERY turn
        # (it is core line + persona + per-turn directives, and those always exist), so gating on its
        # truthiness fired the widening always: `reserve_for_response` went 512 -> 0 on every ordinary
        # turn, which doubles build_system_prompt's `total_budget` from (n_ctx - 512) to n_ctx. Measured
        # cost on the live config: an ordinary coding head went 752 -> 1339 tokens (+78%) to deliver
        # nothing extra — the manifest was not even on those turns — and pushed head+conversation past
        # n_ctx at convo_turns=12. So: widen only when the protected content genuinely does NOT fit.
        _baseline_budgets = budgets if budgets is not None else _resolve_default_budgets(n_ctx)
        _baseline_si_cap = min(
            int(_baseline_budgets.get("system_instructions", 800) or 0),
            max(0, max(512, n_ctx - _reserve_for_response) - _downstream),
        )
        # The ordinary case: the core line plus the per-turn directives (aspect behaviour, the rank gate,
        # the BL-160 language block, hardware) total ~207 tokens and fit the ordinary budget several times
        # over, so no widening happens and an ordinary turn costs exactly what it cost before this slice
        # existed — measured identical, 829 tokens, section for section.
        #
        # This only works because the prefix was REORDERED above so the persona sits behind the
        # directives. While the 590-token voice contract was in front of them, protecting a 73-token
        # language directive cost 663 tokens of protected prefix, this comparison came out true on every
        # turn, and the widening fired always. Sizing the gate correctly and ordering the prefix
        # correctly are the same fix; neither works alone.
        #
        # A capability turn adds the ~889-token manifest to that prefix, which genuinely does not fit,
        # and only then is the widening the right trade.
        if _protected_prefix_tokens > _baseline_si_cap:
            # Everything here is in the SAME unit — tokens of final head — so the arithmetic composes.
            # The first version did not: it bounded the window by (n_ctx - reply - conversation) and then
            # let build_system_prompt subtract ANOTHER 512 for the response on top, reserving the reply
            # twice and leaving ~500 tokens of the window unspent. Measured cost of that double-reserve:
            # `system_instructions` was clamped to 1127 when it needed 1247, and the manifest lost its last
            # three BROKEN disclosures — she would have claimed LAN offload and a network-blocking sandbox.
            # So: compute the ceiling once, subtract the output-discipline footer (appended after assembly
            # and therefore invisible to the assembler), and pass reserve_for_response=0 because the reply
            # is already accounted for in the ceiling.
            _footer_tokens = token_estimate(_append_output_discipline("", cfg))
            # No extra safety margin here: the reply reserve is subtracted in full and the conversation
            # estimate is deliberately conservative (3.5 chars/token against a measured ~5), so the slack
            # is already inside those two terms. An arbitrary extra margin on top cost exactly the last
            # 35 tokens of the manifest — the "approval gate is the real protection" line.
            _max_head_tokens = max(
                512, _n_ctx - _reply_reserve_tokens(cfg) - _convo_block_tokens(cfg, conversation_history)
            )
            _needed_head = int(_protected_prefix_tokens) + _downstream + 64
            _window_ceiling = max(256, _max_head_tokens - _footer_tokens)
            n_ctx = max(n_ctx, min(_window_ceiling, _needed_head))
            _reserve_for_response = 0
            if budgets is None:
                # Resolve the same defaults build_system_prompt would have picked for this window rather
                # than assuming DEFAULT_BUDGETS — on a small model it chooses a much tighter dict, and
                # substituting the roomy one here would quietly inflate every other section too.
                budgets = _resolve_default_budgets(n_ctx)
            # Raise the section budget to hold the protected prefix — but never past what leaves the
            # downstream sections whole. Without the second clamp the window ceiling binds first and
            # `system_instructions` takes everything up to it, chopping "Current goal: <the user's actual
            # question>" mid-phrase. The manifest losing its closing line is a cost; the model not knowing
            # what was asked is a broken turn.
            budgets["system_instructions"] = max(
                int(budgets.get("system_instructions", 800) or 0),
                min(int(_protected_prefix_tokens) + 32, max(256, n_ctx - _downstream)),
            )

        def _assemble(window: int) -> tuple[str, dict]:
            _asm, _m = build_system_prompt(
                sections, n_ctx=window, budgets=budgets, reserve_for_response=_reserve_for_response,
            )
            _h = _asm if _asm.strip() else "You are Layla, a bounded AI companion and engineering agent."
            if cfg.get("custom_system_prefix"):
                _h = _h + "\n\n" + cfg["custom_system_prefix"].strip()
            return _append_output_discipline(_h, cfg), _m

        head, _ctx_metrics = _assemble(n_ctx)
        if _max_head_tokens and token_estimate(head) > _max_head_tokens:
            # Not correctable from here, so say so rather than pretending. The head has a structural floor
            # (the window never goes below 1024, and the output-discipline footer adds ~320 tokens after
            # assembly), so once the conversation is long enough the head cannot shrink to fit no matter
            # what this function does — that floor predates the widening and is the same on an ordinary
            # turn. Logged because the alternative is a silent context overflow with no breadcrumb.
            logger.debug(
                "system head %d tok exceeds the %d tok this window can spare — conversation block may overflow n_ctx",
                token_estimate(head), _max_head_tokens,
            )
        if _ctx_metrics.get("truncated_sections") or _ctx_metrics.get("dropped_sections"):
            logger.debug(
                "context budget: truncated=%s dropped=%s total_tok=%d",
                _ctx_metrics.get("truncated_sections"),
                _ctx_metrics.get("dropped_sections"),
                _ctx_metrics.get("total_tokens", 0),
            )
        return head

    # Legacy path: no budget enforcement
    parts = [system_instructions]
    if durable_facts_block:
        parts.append(durable_facts_block)
    if pinned_block:
        parts.append(pinned_block[:1500])
    if workspace_context:
        parts.append(workspace_context[:1200])
    if current_goal:
        parts.append(current_goal)
    if memory_block:
        parts.append(memory_block)
    if graph_associations:
        parts.append(graph_associations)
    if knowledge:
        parts.append(f"Reference docs:\n{knowledge}")
    head = "\n\n".join(parts) if parts else "You are Layla, a bounded AI companion and engineering agent."
    if cfg.get("custom_system_prefix"):
        head = head + "\n\n" + cfg["custom_system_prefix"].strip()
    return _append_output_discipline(head, cfg)
