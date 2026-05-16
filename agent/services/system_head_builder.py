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
from services.context_manager import DEFAULT_BUDGETS, build_system_prompt
from services.llm_gateway import run_completion

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def load_learnings(aspect_id: str = "") -> str:
    """Load recent learnings text for the given aspect."""
    try:
        cfg = runtime_safety.load_config()
        n = cfg.get("learnings_n", 30)
        min_score = float(cfg.get("learning_min_score", 0.3) or 0.3)
        rows = _db_get_learnings(n=n, aspect_id=aspect_id or None, min_score=min_score)
        return "\n".join(r["content"] for r in rows if r.get("content"))
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
        if not results:
            return ""
        lines = [r.get("content", "") for r in results if r.get("content")]
        return "\n".join(lines)
    except Exception as e:
        logger.warning("ChromaDB failed, falling back to FTS: %s", e)
        try:
            from layla.memory.db import search_learnings_fts
            results = search_learnings_fts(query, n=k)
            lines = "\n".join(r.get("content", "") for r in results if r.get("content"))
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
        from services.relationship_codex import codex_has_entities, format_codex_prompt_digest, load_codex

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
# Main entry point
# ---------------------------------------------------------------------------

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

    if not knowledge.strip():
        knowledge = runtime_safety.load_knowledge_docs(max_bytes=cfg.get("knowledge_max_bytes", 4000)).strip()
    else:
        knowledge = knowledge.strip()

    learnings = load_learnings(aspect_id=(aspect.get("id") or "") if aspect else "").strip()

    # Build aspect identity
    if aspect:
        name = aspect.get("name", "Layla")
        title = (aspect.get("title") or "").strip()
        role = (aspect.get("role") or "").strip()[:120]
        anchor = f"{name} ({title})" if title else name
        if role:
            anchor += f" — {role}"
        anchor += ". Reply as her only. Do not output labels or repeat instructions."
        full_addition = (aspect.get("systemPromptAddition") or "").strip()
        if full_addition:
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

    # Aspect memories
    aspect_memories = ""
    n_mem = cfg.get("aspect_memories_n", 10)
    if aspect:
        aid = aspect.get("id", "")
        if aid:
            try:
                mems = _db_get_aspect_memories(aid, n_mem)
                if mems:
                    lines = [m.get("content", "") for m in mems if m.get("content")]
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

    coding_keywords = ("code", "debug", "fix", "implement", "refactor", "function", "class", "module", "file", "grep", "read_file", "write_file")
    if not _skip_expensive and goal and workspace_root and any(kw in goal.lower() for kw in coding_keywords):
        try:
            from services.workspace_index import get_workspace_dependency_context
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
    from services.prompt_builder import build_core_sys_parts
    sys_parts = build_core_sys_parts(
        cfg=cfg, aspect=aspect, identity=identity, personality=personality,
        goal=goal, reasoning_mode=reasoning_mode, repo_root=REPO_ROOT,
    )
    system_instructions = "\n\n".join(sys_parts)

    # Aspect behavioral instructions
    try:
        from services.aspect_behavior import build_behavior_block as _ab_block
        _behavior_block = _ab_block(aspect)
        if _behavior_block:
            system_instructions = system_instructions + "\n\n" + _behavior_block
    except Exception as _ab_e:
        logger.debug("aspect_behavior block inject failed: %s", _ab_e)

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
            from services.german_mode import build_german_system_block
            from services.german_mode import get_profile as _gprof
            _glevel = _gprof().get("level", "B1")
            _german_block = build_german_system_block(_glevel)
            system_instructions = system_instructions + "\n\n" + _german_block
    except Exception as _ge:
        logger.debug("german_mode inject failed: %s", _ge)

    # Memory sections (canonical order)
    from services.context_merge_layers import MEMORY_SECTION_ORDER
    memory_sections: dict[str, str] = {}
    _n_ctx = int(cfg.get("n_ctx", 4096) or 4096)
    _small_model = _n_ctx <= 4096

    if git_preamble and not _small_model:
        memory_sections["git_preamble"] = git_preamble
    if project_instructions and not _small_model:
        memory_sections["project_instructions"] = "Project instructions:\n" + project_instructions

    try:
        from services.repo_cognition import format_cognition_for_prompt, merge_cognition_roots
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
            from services.project_memory import (
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
        from services.working_memory import format_for_prompt as _wm_format
        _wm_text = _wm_format()
        if _wm_text.strip():
            memory_sections["working_memory"] = _wm_text
    except Exception as _wm_e:
        logger.debug("context[working_memory] failed: %s", _wm_e)

    if not _small_model:
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
            from services.style_profile import get_profile_summary
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
            parts = [f"{k}: {v}" for k, v in uid.items() if v]
            if parts:
                _style_identity_parts.append("User/companion context:\n" + "\n".join(parts))
            try:
                from services.frame_modifier import (
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
            from services.personal_knowledge_graph import get_personal_graph_context
            pkg_ctx = get_personal_graph_context(goal or "", max_chars=400)
            if pkg_ctx:
                memory_sections["personal_knowledge_graph"] = "Personal context (relevant):\n" + pkg_ctx
        except Exception as _e:
            logger.debug("context[personal_knowledge_graph] failed: %s", _e)

    if not _skip_expensive and not _small_model:
        try:
            from services.rl_feedback import get_rl_hint_for_prompt
            rl_hint = get_rl_hint_for_prompt()
            if rl_hint:
                memory_sections["rl_feedback"] = rl_hint
        except Exception:
            pass

    if goal and len(goal) > 100 and not _small_model:
        try:
            from services.reasoning_strategies import get_strategy_prompt_hint
            hint = get_strategy_prompt_hint(goal)
            if hint:
                memory_sections["reasoning_strategies"] = hint
        except Exception as _e:
            logger.debug("context[reasoning_strategies] failed: %s", _e)

    if not _skip_expensive and not _small_model:
        try:
            if cfg.get("golden_examples_enabled", True):
                from services.golden_examples import bump_usage as _ge_bump_usage
                from services.golden_examples import format_for_prompt as _ge_format
                from services.golden_examples import retrieve_relevant_examples as _ge_retrieve
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
        from services.context_manager import deduplicate_content
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
            from services.prompt_tier_budget import budgets_for_mode
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

    # Hardware capability injection
    try:
        from services.hardware_detect import get_capability_summary as _hw_cap_summary
        _hw_summary = _hw_cap_summary()
        if _hw_summary:
            system_instructions = (system_instructions or "") + "\n\n" + _hw_summary
    except Exception as _hw_e:
        logger.debug("hardware_probe capability_summary inject skipped: %s", _hw_e)

    # Section dict assembly
    sections = {
        "system_instructions": system_instructions,
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
        from services.context_manager import token_estimate_messages
        _hist_tokens = token_estimate_messages(_hist_for_pressure)
        _hist_ratio = _hist_tokens / _n_ctx
    except Exception:
        _hist_ratio = 0.0

    if _hist_ratio > 0.4:
        sys_parts.append(
            "Context pressure: conversation is using more than 40% of available context. "
            "Decompose tasks into the smallest possible steps. "
            "Do one thing per response. Prefer `think` actions over long in-context reasoning. "
            "Use `read_file` only for specific sections, not full files."
        )
        system_instructions = "\n\n".join(sys_parts)
        sections["system_instructions"] = system_instructions

    # Budget-enforced assembly
    if cfg.get("prompt_budget_enabled", True):
        _head_ratio = float(cfg.get("system_head_budget_ratio", 0.35) or 0.35)
        _head_ratio = max(0.15, min(0.55, _head_ratio))
        n_ctx = max(1024, int(_n_ctx * _head_ratio))
        assembled, _ctx_metrics = build_system_prompt(sections, n_ctx=n_ctx, budgets=budgets, reserve_for_response=512)
        if _ctx_metrics.get("truncated_sections") or _ctx_metrics.get("dropped_sections"):
            logger.debug(
                "context budget: truncated=%s dropped=%s total_tok=%d",
                _ctx_metrics.get("truncated_sections"),
                _ctx_metrics.get("dropped_sections"),
                _ctx_metrics.get("total_tokens", 0),
            )
        head = assembled if assembled.strip() else "You are Layla, a bounded AI companion and engineering agent."
        if cfg.get("custom_system_prefix"):
            head = head + "\n\n" + cfg["custom_system_prefix"].strip()
        return head

    # Legacy path: no budget enforcement
    parts = [system_instructions]
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
    return head
