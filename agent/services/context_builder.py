"""
Central context assembly for planners and the agent loop.

Combines memory retrieval, codebase retrieval, optional pinned files (chunked, ranked),
and identity snippets without replacing context_manager.build_system_prompt.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")


def summarize_old_context(text: str, max_tokens: int = 400) -> str:
    """Cheap trim for stale context blobs (compression hook per North Star budgets)."""
    if not text or max_tokens <= 0:
        return ""
    try:
        from services.context_budget import truncate_section

        return truncate_section(text, max_tokens, section_name="context_summarize")
    except Exception:
        return text[: max(100, max_tokens * 4)]


def trim_scored_chunks(chunks: list[dict], max_chars: int) -> list[dict]:
    """Drop lowest-score chunks first until under max_chars."""
    if not chunks or max_chars <= 0:
        return []
    ranked = sorted(
        chunks,
        key=lambda x: float(x.get("score", 0.0)),
        reverse=True,
    )
    out: list[dict] = []
    used = 0
    for c in ranked:
        t = str(c.get("text") or "")
        if used + len(t) > max_chars and out:
            break
        out.append(c)
        used += len(t)
    return out


def _rank_file_chunks(workspace_root: Path, rel: str, task: str, max_chunks: int = 6) -> list[dict]:
    """Chunk a file and rank chunks by ephemeral BM25 vs task query."""
    root = workspace_root.expanduser().resolve()
    try:
        p = (root / rel.strip().replace("\\", "/").lstrip("/")).resolve()
        p.relative_to(root)
    except Exception:
        return []
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    chunks: list[str] = []
    for i in range(0, len(text), 520):
        part = text[i : i + 520].strip()
        if len(part) >= 40:
            chunks.append(part)
    if not chunks:
        return []
    ids = [f"{rel}:{i}" for i in range(len(chunks))]
    try:
        from services.keyword_search import build_index

        idx = build_index(ids, chunks)
        scores = idx.score_query(task)
    except Exception:
        scores = {ids[i]: 1.0 - (i / max(len(ids), 1)) for i in range(len(ids))}
    ranked: list[dict] = []
    for i, cid in enumerate(ids):
        sc = float(scores.get(cid, 0.5))
        ranked.append({"text": chunks[i], "score": sc, "metadata": {"path": rel, "chunk_index": i}})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:max_chunks]


def build_context(task: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Assemble structured context for planning and prompting.

    Returns dict with text fields and chunk metadata for budget trimming.
    """
    opts = options or {}
    workspace_root = str(opts.get("workspace_root") or "").strip()
    k_mem = max(1, int(opts.get("k_memory", 5)))
    k_code = max(1, int(opts.get("k_code", 5)))
    reasoning_mode = str(opts.get("reasoning_mode") or "light")
    coding_boost = reasoning_mode in ("deep", "heavy", "reasoning")
    context_files = opts.get("context_files") if isinstance(opts.get("context_files"), list) else []

    mem_rows: list[dict] = []
    try:
        from services.retrieval import retrieve_relevant_memory

        mem_rows = retrieve_relevant_memory(task, k=k_mem, coding_boost=coding_boost)
    except Exception as e:
        logger.debug("build_context memory: %s", e)

    memory_recall_text = "\n".join(
        (r.get("content") or "").strip() for r in mem_rows if (r.get("content") or "").strip()
    )

    retrieved_layer = ""
    try:
        from services.retrieval import build_retrieved_context

        retrieved_layer = (build_retrieved_context(task, k=min(k_mem, 5), reasoning_mode=reasoning_mode) or "").strip()
    except Exception as e:
        logger.debug("build_context retrieval merge: %s", e)

    code_chunks: list[dict] = []
    try:
        if workspace_root:
            from services.workspace_index import retrieve_code_context

            code_chunks = retrieve_code_context(task, workspace_root=workspace_root, k=k_code)
    except Exception as e:
        logger.debug("build_context code: %s", e)

    code_text = ""
    if code_chunks:
        lines = []
        for c in code_chunks:
            src = (c.get("metadata") or {}).get("source", "") if isinstance(c.get("metadata"), dict) else ""
            sc = c.get("score", 0.0)
            txt = (c.get("text") or "").strip()[:700]
            if txt:
                lines.append(f"[{src}] (sim={sc:.2f})\n{txt}")
        code_text = "\n\n".join(lines)

    file_chunks: list[dict] = []
    if workspace_root and context_files:
        root = Path(workspace_root).expanduser().resolve()
        for rel in context_files[:12]:
            if not isinstance(rel, str) or not rel.strip():
                continue
            file_chunks.extend(_rank_file_chunks(root, rel.strip(), task))

    files_text = ""
    if file_chunks:
        file_chunks = trim_scored_chunks(file_chunks, max_chars=int(opts.get("max_file_context_chars", 6000)))
        files_text = "\n\n".join(
            (c.get("text") or "").strip() for c in file_chunks if (c.get("text") or "").strip()
        )

    identity_snippet = str(opts.get("identity_snippet") or "").strip()

    combined_memory = ""
    parts_m = [memory_recall_text, retrieved_layer]
    combined_memory = "\n\n".join(p for p in parts_m if p)

    return {
        "task": task,
        "memory_recall_text": memory_recall_text,
        "retrieved_knowledge_text": retrieved_layer,
        "memory_block": combined_memory,
        "code_chunks": code_chunks,
        "code_text": code_text,
        "file_chunks": file_chunks,
        "files_text": files_text,
        "identity_snippet": identity_snippet,
        "chunks_meta": {
            "memory_items": [{"score": None, "id": r.get("embedding_id")} for r in mem_rows],
            "code": [{"score": c.get("score"), "source": (c.get("metadata") or {}).get("source")} for c in code_chunks],
            "files": [{"score": c.get("score"), "path": (c.get("metadata") or {}).get("path")} for c in file_chunks],
        },
    }


def format_tool_context(packed: dict[str, Any] | None, max_chars: int = 1200) -> str:
    """Compact context string for tool payloads (not full memory dump)."""
    if not packed:
        return ""
    bits = []
    mb = (packed.get("memory_block") or "")[: max_chars // 2]
    cb = (packed.get("code_text") or "")[: max_chars // 3]
    fb = (packed.get("files_text") or "")[: max_chars // 4]
    if mb.strip():
        bits.append("Memory:\n" + mb.strip())
    if cb.strip():
        bits.append("Code:\n" + cb.strip())
    if fb.strip():
        bits.append("Files:\n" + fb.strip())
    out = "\n\n".join(bits)
    if len(out) > max_chars:
        return out[:max_chars].rsplit("\n", 1)[0] + "\n...[truncated]"
    return out
