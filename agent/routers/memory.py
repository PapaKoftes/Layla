"""
Memory bundle export and import router.

GET  /memory/export  — Download a ZIP of all curated knowledge + learnings
POST /memory/import  — Upload a ZIP to merge knowledge and learnings into this instance
GET  /memory/stats   — Summary of current memory state
"""
import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/memory", tags=["memory"])

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
DB_PATH = AGENT_DIR / "layla.db"


def _get_db():
    """Lazy import to avoid circular dep at import time."""
    import sys
    sys.path.insert(0, str(AGENT_DIR))
    from layla.memory.db import get_recent_learnings, save_learning
    return get_recent_learnings, save_learning


@router.get("/stats")
async def memory_stats():
    """Return a summary of current memory state."""
    stats = {
        "knowledge_docs": 0,
        "knowledge_files": [],
        "learnings_count": 0,
        "db_size_kb": 0,
    }
    if KNOWLEDGE_DIR.exists():
        docs = list(KNOWLEDGE_DIR.rglob("*.md")) + list(KNOWLEDGE_DIR.rglob("*.txt"))
        stats["knowledge_docs"] = len(docs)
        stats["knowledge_files"] = [f.name for f in docs[:50]]
    if DB_PATH.exists():
        stats["db_size_kb"] = round(DB_PATH.stat().st_size / 1024, 1)
    try:
        get_recent_learnings, _ = _get_db()
        rows = get_recent_learnings(n=1000)
        stats["learnings_count"] = len(rows)
    except Exception:
        pass
    return JSONResponse(stats)


@router.get("/export")
async def export_bundle():
    """
    Export a ZIP bundle containing:
    - All knowledge/*.md and knowledge/*.txt files
    - All learnings as learnings.json
    - A manifest.json with export metadata
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Export knowledge docs
        if KNOWLEDGE_DIR.exists():
            for f in sorted(KNOWLEDGE_DIR.rglob("*.md")):
                if ".identity" in str(f):
                    continue
                rel = f.relative_to(REPO_ROOT)
                zf.writestr(str(rel).replace("\\", "/"), f.read_text(encoding="utf-8", errors="replace"))
            for f in sorted(KNOWLEDGE_DIR.rglob("*.txt")):
                rel = f.relative_to(REPO_ROOT)
                zf.writestr(str(rel).replace("\\", "/"), f.read_text(encoding="utf-8", errors="replace"))

        # Export learnings
        learnings = []
        try:
            get_recent_learnings, _ = _get_db()
            rows = get_recent_learnings(n=5000)
            learnings = [{"content": r.get("content", ""), "kind": r.get("kind", "note")} for r in rows]
        except Exception as e:
            learnings = [{"error": str(e)}]
        zf.writestr("learnings.json", json.dumps(learnings, indent=2, ensure_ascii=False))

        # Manifest
        from layla.time_utils import utcnow
        manifest = {
            "exported_at": utcnow().isoformat(),
            "knowledge_docs": len([f for f in KNOWLEDGE_DIR.rglob("*.md")] if KNOWLEDGE_DIR.exists() else []),
            "learnings_count": len(learnings),
            "format_version": "1.0",
            "description": "Layla memory bundle — drop knowledge/ folder and learnings.json into a fresh Layla install.",
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buf.seek(0)
    from layla.time_utils import utcnow
    filename = f"layla-memory-bundle-{utcnow().strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_bundle(file: UploadFile = File(...)):
    """
    Import a memory bundle ZIP.
    - Merges knowledge docs into knowledge/ (new files only; does not overwrite existing)
    - Merges learnings (deduplicates by content prefix)
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Expected a .zip file")

    content = await file.read()
    if len(content) > 100 * 1024 * 1024:  # 100 MB limit
        raise HTTPException(status_code=413, detail="Bundle too large (100 MB max)")

    results = {"knowledge_imported": [], "knowledge_skipped": [], "learnings_added": 0, "errors": []}

    try:
        buf = io.BytesIO(content)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()

            # Import knowledge docs (Zip slip: ensure path stays under knowledge/)
            knowledge_base = (REPO_ROOT / "knowledge").resolve()
            for name in names:
                if name.startswith("knowledge/") and (name.endswith(".md") or name.endswith(".txt")):
                    target = (REPO_ROOT / name).resolve()
                    try:
                        target.relative_to(knowledge_base)
                    except ValueError:
                        continue  # path traversal attempt
                    if target.exists():
                        results["knowledge_skipped"].append(name)
                        continue
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(zf.read(name))
                        results["knowledge_imported"].append(name)
                    except Exception as e:
                        results["errors"].append(f"{name}: {e}")

            # Import learnings
            if "learnings.json" in names:
                try:
                    raw = json.loads(zf.read("learnings.json").decode("utf-8", errors="replace"))
                    if isinstance(raw, list):
                        _, save_learning = _get_db()
                        # Get existing content prefixes for dedup
                        get_recent_learnings, _ = _get_db()
                        existing = {r.get("content", "")[:60] for r in get_recent_learnings(n=5000)}
                        added = 0
                        for item in raw:
                            if not isinstance(item, dict):
                                continue
                            c = (item.get("content") or "").strip()
                            if not c or c[:60] in existing:
                                continue
                            save_learning(content=c[:800], kind=item.get("kind", "imported"))
                            existing.add(c[:60])
                            added += 1
                        results["learnings_added"] = added
                except Exception as e:
                    results["errors"].append(f"learnings.json: {e}")

        results["ok"] = True
        return JSONResponse(results)

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/elasticsearch/search")
async def memory_elasticsearch_search_route(
    q: str = Query("", description="Search query"),
    limit: int = Query(20, ge=1, le=100),
):
    """Full-text search over learnings mirrored to Elasticsearch (optional; requires elasticsearch package + server)."""
    try:
        import sys

        sys.path.insert(0, str(AGENT_DIR))
        import runtime_safety
        from services.elasticsearch_bridge import search_learnings

        out = search_learnings(runtime_safety.load_config(), q, limit=limit)
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "hits": []})


@router.get("/file_checkpoints")
async def list_file_checkpoints_http(limit: int = Query(40, ge=1, le=200)):
    """List recent pre-write file checkpoints for the configured sandbox (newest first)."""
    import sys

    sys.path.insert(0, str(AGENT_DIR))
    import runtime_safety
    from services.file_checkpoints import list_checkpoints

    cfg = runtime_safety.load_config()
    sandbox = Path(cfg.get("sandbox_root", str(Path.home()))).expanduser().resolve()
    out = list_checkpoints(workspace_root=sandbox, agent_dir=AGENT_DIR, path_filter=None, limit=limit)
    return JSONResponse(out)


@router.post("/file_checkpoints/restore")
async def restore_file_checkpoint_http(request: Request):
    """
    Queue restore_file_checkpoint for approval (safe_mode) or run immediately when safe_mode is false.
    """
    import sys

    sys.path.insert(0, str(AGENT_DIR))
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    cid = str(body.get("checkpoint_id") or "").strip()
    if not cid:
        return JSONResponse({"ok": False, "error": "checkpoint_id required"}, status_code=400)
    import runtime_safety

    cfg = runtime_safety.load_config()
    if cfg.get("safe_mode", True):
        from agent_loop import _write_pending

        aid = _write_pending("restore_file_checkpoint", {"checkpoint_id": cid})
        return JSONResponse({"ok": True, "approval_required": True, "approval_id": aid})
    from layla.tools.registry import restore_file_checkpoint

    res = restore_file_checkpoint(checkpoint_id=cid)
    return JSONResponse(res)


# ── Phase 1.3: Memory/Learnings Browser ─────────────────────────────────────

@router.get("/browse")
async def browse_learnings(
    type: str = Query("", description="Filter by learning type (fact, strategy, outcome, preference, …)"),
    q: str = Query("", description="Keyword filter on content"),
    sort: str = Query("recent", description="Sort order: recent | confidence"),
    page: int = Query(0, ge=0),
    limit: int = Query(40, ge=1, le=200),
):
    """
    Paginated browser for learnings. Supports type filter, keyword filter, and sort order.
    Returns {ok, total, page, learnings:[{id, content, type, confidence, tags, created_at, source}]}.
    """
    try:
        import sys
        sys.path.insert(0, str(AGENT_DIR))
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        offset = page * limit
        order = "confidence DESC, id DESC" if sort == "confidence" else "id DESC"

        conditions = []
        params: list = []
        if type.strip():
            conditions.append("(type=? OR learning_type=?)")
            params += [type.strip(), type.strip()]
        if q.strip():
            conditions.append("content LIKE ?")
            params.append(f"%{q.strip()}%")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with _conn() as db:
            rows = db.execute(
                f"SELECT id, content, type, confidence, tags, created_at, source, learning_type"
                f" FROM learnings {where} ORDER BY {order} LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            total = db.execute(
                f"SELECT COUNT(*) FROM learnings {where}", params
            ).fetchone()[0]

        learnings = [
            {
                "id": r["id"],
                "content": r["content"],
                "type": r["learning_type"] or r["type"] or "fact",
                "confidence": float(r["confidence"] or 0.5),
                "tags": r["tags"] or "",
                "created_at": r["created_at"] or "",
                "source": r["source"] or "",
            }
            for r in rows
        ]
        return {"ok": True, "total": total, "page": page, "limit": limit, "learnings": learnings}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "learnings": []}, status_code=500)


@router.patch("/{learning_id}")
async def update_learning(learning_id: int, request: Request):
    """
    Update a learning's content and/or tags.
    Body: {content?: string, tags?: string}.
    """
    try:
        import sys
        sys.path.insert(0, str(AGENT_DIR))
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "body must be object"}, status_code=400)

    updates: list[str] = []
    params: list = []
    if "content" in body and isinstance(body["content"], str):
        c = body["content"].strip()
        if c:
            updates.append("content=?")
            params.append(c)
    if "tags" in body and isinstance(body["tags"], str):
        updates.append("tags=?")
        params.append(body["tags"].strip())

    if not updates:
        return JSONResponse({"ok": False, "error": "nothing to update"}, status_code=400)

    try:
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        params.append(learning_id)
        with _conn() as db:
            cur = db.execute(
                "UPDATE learnings SET " + ", ".join(updates) + " WHERE id=?",
                params,
            )
            db.commit()
        if cur.rowcount == 0:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.delete("/{learning_id}")
async def delete_learning(learning_id: int):
    """Delete a learning by id. Also removes its Chroma embedding if one exists."""
    try:
        import sys
        sys.path.insert(0, str(AGENT_DIR))
        from layla.memory.db_connection import _conn
        from layla.memory.migrations import migrate

        migrate()
        with _conn() as db:
            row = db.execute(
                "SELECT embedding_id FROM learnings WHERE id=?", (learning_id,)
            ).fetchone()
            cur = db.execute("DELETE FROM learnings WHERE id=?", (learning_id,))
            db.commit()
        if cur.rowcount == 0:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
        eid = (row["embedding_id"] if row and hasattr(row, "keys") else (row[0] if row else None)) or ""
        if eid:
            try:
                from layla.memory.vector_store import delete_learning_embedding
                delete_learning_embedding(str(eid))
            except Exception:
                pass
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
