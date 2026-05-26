"""
Phase 5.1 — Obsidian Vault Connector.
Syncs .md files from a user's Obsidian vault into the local /knowledge dir.
Bidirectional: Layla can also suggest notes to export back to the vault.
Conflict resolution: newer mtime wins; vault always wins on fresh import.
Sovereignty intact: all I/O is local filesystem only.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# Sub-directory inside /knowledge where vault-imported files are stored
VAULT_SUBDIR = "obsidian"

# Runtime config cache (reset on connect)
_vault_config: dict[str, Any] = {}


# ── Config ────────────────────────────────────────────────────────────────────

def set_vault_path(vault_path: str) -> dict:
    """Persist vault path to Layla config and update module cache."""
    vp = Path(vault_path).expanduser().resolve()
    if not vp.is_dir():
        return {"ok": False, "error": f"Vault path does not exist or is not a directory: {vp}"}
    _vault_config["vault_path"] = str(vp)
    _vault_config["connected"] = True
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        cfg["obsidian_vault_path"] = str(vp)
        runtime_safety.save_config(cfg)
    except Exception as e:
        logger.debug("obsidian_sync: could not persist vault path: %s", e)
    logger.info("obsidian_sync: vault connected at %s", vp)
    return {"ok": True, "vault_path": str(vp)}


def get_vault_path() -> Path | None:
    """Return the configured vault Path, or None if not set."""
    raw = _vault_config.get("vault_path") or ""
    if not raw:
        try:
            import runtime_safety
            cfg = runtime_safety.load_config()
            raw = cfg.get("obsidian_vault_path") or ""
            if raw:
                _vault_config["vault_path"] = raw
        except Exception:
            pass
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    return p if p.is_dir() else None


def get_knowledge_vault_dir(repo_root: Path | None = None) -> Path:
    """Return the knowledge/obsidian subdir, creating it if needed."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent
    d = repo_root / "knowledge" / VAULT_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Sync logic ────────────────────────────────────────────────────────────────

def _md_files(directory: Path) -> list[Path]:
    """Recursively collect all .md files under directory, excluding hidden dirs."""
    out: list[Path] = []
    for p in directory.rglob("*.md"):
        if any(part.startswith(".") for part in p.parts):
            continue
        out.append(p)
    return out


def _file_hash(path: Path) -> str:
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except Exception:
        return ""


def diff_vault(repo_root: Path | None = None) -> dict:
    """
    Compare vault .md files against /knowledge/obsidian copies.
    Returns lists of: new (vault-only), updated (vault newer), unchanged, conflicts.
    """
    vp = get_vault_path()
    if vp is None:
        return {"ok": False, "error": "No vault path configured. Call POST /obsidian/connect first."}

    dest = get_knowledge_vault_dir(repo_root)
    vault_files = _md_files(vp)

    result: dict[str, list] = {"new": [], "updated": [], "unchanged": [], "conflicts": [], "ok": True}

    for src in vault_files:
        rel = src.relative_to(vp)
        dst = dest / rel
        if not dst.exists():
            result["new"].append(str(rel))
        else:
            src_mtime = src.stat().st_mtime
            dst_mtime = dst.stat().st_mtime
            if _file_hash(src) == _file_hash(dst):
                result["unchanged"].append(str(rel))
            elif src_mtime >= dst_mtime:
                result["updated"].append(str(rel))
            else:
                # dest is newer — conflict
                result["conflicts"].append({"file": str(rel), "vault_mtime": src_mtime, "knowledge_mtime": dst_mtime})

    result["total_vault_files"] = len(vault_files)
    return result


def sync_vault(
    repo_root: Path | None = None,
    force: bool = False,
) -> dict:
    """
    Copy new/updated vault .md files into knowledge/obsidian.
    Skips conflicts unless force=True (vault wins).
    Returns a summary dict.
    """
    vp = get_vault_path()
    if vp is None:
        return {"ok": False, "error": "No vault path configured."}

    dest = get_knowledge_vault_dir(repo_root)
    vault_files = _md_files(vp)

    copied = 0
    skipped_conflicts = 0
    errors: list[str] = []

    for src in vault_files:
        rel = src.relative_to(vp)
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists() and not force:
            src_mtime = src.stat().st_mtime
            dst_mtime = dst.stat().st_mtime
            if dst_mtime > src_mtime and _file_hash(src) != _file_hash(dst):
                skipped_conflicts += 1
                logger.debug("obsidian_sync: conflict skipped: %s (knowledge is newer)", rel)
                continue

        try:
            shutil.copy2(src, dst)
            copied += 1
            logger.debug("obsidian_sync: copied %s", rel)
        except Exception as e:
            errors.append(f"{rel}: {e}")

    # Trigger knowledge re-index if Chroma is enabled
    if copied > 0:
        try:
            import runtime_safety
            if runtime_safety.load_config().get("use_chroma"):
                from layla.memory.vector_store import index_knowledge_docs
                index_knowledge_docs(str(dest))
                logger.info("obsidian_sync: re-indexed %d docs in Chroma", copied)
        except Exception as e:
            logger.debug("obsidian_sync: chroma re-index failed: %s", e)

    return {
        "ok": True,
        "copied": copied,
        "skipped_conflicts": skipped_conflicts,
        "errors": errors,
        "vault_path": str(vp),
        "dest_path": str(dest),
    }


# ── Suggest (Layla → Obsidian) ────────────────────────────────────────────────

def suggest_export(n: int = 10) -> dict:
    """
    Suggest top high-confidence learnings as Obsidian-ready .md notes.
    Returns formatted note content; user must approve and call export_to_vault().
    """
    vp = get_vault_path()
    suggestions: list[dict] = []
    try:
        from layla.memory.db import get_top_learnings_for_planning
        top = get_top_learnings_for_planning(limit=n, min_confidence=0.75)
        for row in top:
            content = (row.get("content") or "").strip()
            if not content:
                continue
            learning_type = row.get("type") or row.get("learning_type") or "fact"
            confidence = row.get("confidence") or row.get("adjusted_confidence") or 0.5
            lid = row.get("id") or ""
            # Format as a clean Obsidian note
            slug = content[:40].lower().replace(" ", "-").strip("-")
            slug = "".join(c for c in slug if c.isalnum() or c == "-")
            note_md = (
                f"---\n"
                f"source: layla\n"
                f"type: {learning_type}\n"
                f"confidence: {confidence:.2f}\n"
                f"layla_id: {lid}\n"
                f"---\n\n"
                f"# {content[:60]}\n\n"
                f"{content}\n"
            )
            suggestions.append({
                "id": lid,
                "filename": f"layla-{slug}.md",
                "learning_type": learning_type,
                "confidence": confidence,
                "note_md": note_md,
            })
    except Exception as e:
        logger.debug("obsidian_sync: suggest_export failed: %s", e)

    return {
        "ok": True,
        "count": len(suggestions),
        "vault_connected": vp is not None,
        "vault_path": str(vp) if vp else None,
        "suggestions": suggestions,
    }


def export_to_vault(note_ids: list[str], repo_root: Path | None = None) -> dict:
    """
    Write approved suggestions into the vault's /layla-exports sub-directory.
    Only works when vault is connected.
    """
    vp = get_vault_path()
    if vp is None:
        return {"ok": False, "error": "No vault path configured."}

    export_dir = vp / "layla-exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    suggestions = suggest_export(n=50).get("suggestions", [])
    id_set = set(note_ids)
    written: list[str] = []
    errors: list[str] = []

    for s in suggestions:
        if s.get("id") not in id_set:
            continue
        dst = export_dir / s["filename"]
        try:
            dst.write_text(s["note_md"], encoding="utf-8")
            written.append(s["filename"])
        except Exception as e:
            errors.append(f"{s['filename']}: {e}")

    return {"ok": True, "written": written, "errors": errors, "export_dir": str(export_dir)}
