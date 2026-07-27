"""
Phase 5.1 / Plan-13 — Obsidian Vault Connector.

Two layers live here:

  * One-way ingest (vault → knowledge/obsidian mirror): ``diff_vault`` / ``sync_vault``.
    This is the always-available, read-only-to-the-vault path.

  * True TWO-WAY sync + structured writeback (``two_way_sync`` / ``writeback_learnings``).
    This reconciles the vault and its mirror in BOTH directions off a per-file
    sync-state store (last-synced hash + mtime), so an edit made on either side is
    carried across — and an edit made on BOTH sides is detected as a conflict and
    NEVER silently clobbered. Layla also fills the vault with well-formed, structured
    notes (frontmatter + body + wikilinks) built from her own learnings.

    Because these paths WRITE INTO THE USER'S REAL VAULT they are gated behind the
    ``obsidian_sync_enabled`` config flag (default off) — a deliberate opt-in.

Frontmatter round-trip uses ``python-frontmatter`` (MIT, optional dependency),
imported lazily; when it is absent the feature degrades to a deterministic plain
writer/parser instead of raising.

Sovereignty intact: all I/O is local filesystem only. All Layla-side state
(the sync-state store) resolves off ``LAYLA_DATA_DIR``. Nothing is ever written
outside the configured vault path.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# Sub-directory inside /knowledge where vault-imported files are stored
VAULT_SUBDIR = "obsidian"

# Sub-directory inside the user's vault where Layla writes her structured notes back.
LAYLA_WRITEBACK_SUBDIR = "layla"

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


# ── Opt-in gate ────────────────────────────────────────────────────────────────

def sync_enabled() -> bool:
    """
    True only when ``obsidian_sync_enabled`` is set in config.

    Two-way sync and writeback WRITE INTO THE USER'S REAL VAULT, so they stay a
    deliberate opt-in even under a "nothing off unless necessary" default — a
    vault-clobber risk is exactly the kind of thing that necessitates opt-in.
    """
    try:
        import runtime_safety
        return bool(runtime_safety.load_config().get("obsidian_sync_enabled", False))
    except Exception:
        return False


# ── Frontmatter round-trip (python-frontmatter, optional) ───────────────────────

_FRONTMATTER_MOD: Any = None
_FRONTMATTER_CHECKED = False


def _load_frontmatter():
    """
    Lazily import python-frontmatter. Returns the module, or None so callers
    degrade to the plain writer/parser instead of raising. Cached after first look.
    """
    global _FRONTMATTER_MOD, _FRONTMATTER_CHECKED
    if _FRONTMATTER_CHECKED:
        return _FRONTMATTER_MOD
    _FRONTMATTER_CHECKED = True
    try:
        import frontmatter  # type: ignore
        _FRONTMATTER_MOD = frontmatter
    except Exception as e:
        logger.info(
            "obsidian_sync: python-frontmatter not installed; frontmatter round-trip "
            "degrades to plain mode (%s)", e,
        )
        _FRONTMATTER_MOD = None
    return _FRONTMATTER_MOD


def _serialize_note(metadata: dict, content: str) -> str:
    """
    Serialize metadata + body into a note string. Byte-stable and idempotent:
    ``_read_note`` ∘ ``_serialize_note`` is a fixed point, so read→write never
    drifts. Author key order is preserved (sort_keys=False) and exactly one
    trailing newline is emitted. Degrades to a deterministic plain writer when
    python-frontmatter is absent.
    """
    meta = dict(metadata or {})
    body = (content or "").strip("\n")
    fm = _load_frontmatter()
    if fm is not None:
        post = fm.Post(body, **meta)
        text = fm.dumps(post, sort_keys=False)
        return text if text.endswith("\n") else text + "\n"
    return _serialize_note_plain(meta, body)


def _serialize_note_plain(metadata: dict, body: str) -> str:
    """Deterministic frontmatter writer used when python-frontmatter is absent."""
    lines = ["---"]
    for k, v in metadata.items():
        if isinstance(v, (list, tuple)):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"- {item}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip("\n") + "\n"


def _read_note(path: Path) -> dict:
    """
    Read a note into ``{"metadata": dict, "content": str}`` losslessly.

    Uses python-frontmatter when available; otherwise a minimal plain parser that
    recovers scalar and simple-list frontmatter keys and preserves the body
    (wikilinks and all).
    """
    raw = Path(path).read_text(encoding="utf-8")
    fm = _load_frontmatter()
    if fm is not None:
        post = fm.loads(raw)
        return {"metadata": dict(post.metadata), "content": post.content}
    return _read_note_plain(raw)


def _read_note_plain(raw: str) -> dict:
    """Minimal frontmatter parser (degrade path). Handles scalars + ``- item`` lists."""
    if not raw.startswith("---"):
        return {"metadata": {}, "content": raw.strip("\n")}
    rest = raw[3:]
    end = rest.find("\n---")
    if end == -1:
        return {"metadata": {}, "content": raw.strip("\n")}
    block = rest[:end].strip("\n")
    body = rest[end + 4:].lstrip("\n").strip("\n")
    meta: dict[str, Any] = {}
    cur_key: str | None = None
    for line in block.splitlines():
        if line.startswith("- ") and cur_key is not None and isinstance(meta.get(cur_key), list):
            meta[cur_key].append(line[2:].strip())
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if v == "":
                cur_key = k
                meta[k] = []
            else:
                cur_key = None
                meta[k] = v
    return {"metadata": meta, "content": body}


# ── Path safety + atomic writes ─────────────────────────────────────────────────

def _within(base: Path, target: Path) -> bool:
    """True iff ``target`` resolves to ``base`` or somewhere beneath it."""
    try:
        base_r = Path(base).resolve()
        target_r = Path(target).resolve()
        return base_r == target_r or base_r in target_r.parents
    except Exception:
        return False


def _atomic_write_text(target: Path, text: str) -> None:
    """Write ``text`` atomically with LF newlines (byte-stable across platforms)."""
    tmp = target.with_name(f"{target.name}.tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, target)


def _write_note(path: Path, metadata: dict, content: str, *, vault_root: Path | None = None) -> None:
    """
    Write a note atomically. When ``vault_root`` is given, refuse to write anywhere
    outside it — the hard guarantee that Layla never touches a path outside the vault.
    """
    target = Path(path)
    if vault_root is not None and not _within(vault_root, target):
        raise ValueError(f"refusing to write outside vault: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(target, _serialize_note(metadata, content))


# ── Per-file sync-state store (last-synced hash + mtime) ─────────────────────────

def _sync_state_path() -> Path:
    """Layla-side sync-state file, resolved off LAYLA_DATA_DIR (never in the vault)."""
    from services.infrastructure.data_paths import layla_data_file
    return layla_data_file("obsidian_sync_state.json")


def _load_sync_state() -> dict:
    p = _sync_state_path()
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("obsidian_sync: could not read sync-state: %s", e)
    return {}


def _save_sync_state(state: dict) -> None:
    p = _sync_state_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:
        logger.warning("obsidian_sync: could not persist sync-state: %s", e)


def _safe_mtime(p: Path) -> float | None:
    try:
        return p.stat().st_mtime
    except Exception:
        return None


def _record(state: dict, rel: str, vault_hash: str | None, local_hash: str | None,
            src: Path, dst: Path) -> None:
    """Update the sync-state row for ``rel`` after a successful reconcile."""
    state[rel] = {
        "vault_hash": vault_hash,
        "local_hash": local_hash,
        "vault_mtime": _safe_mtime(src),
        "local_mtime": _safe_mtime(dst),
        "synced_at": time.time(),
    }


def _copy_within(src: Path, dst: Path, allowed_root: Path) -> None:
    """Copy ``src`` → ``dst``, refusing to write outside ``allowed_root``."""
    if not _within(allowed_root, dst):
        raise ValueError(f"refusing to write outside {allowed_root}: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _write_conflict_marker(dest: Path, rel: str, vault_src: Path) -> str:
    """
    On an edit-both-sides conflict, snapshot the vault's current version beside the
    mirror copy (Layla-side only — never into the vault) so BOTH versions survive
    for the user to reconcile. Returns the mirror-relative sidecar path.
    """
    ts = time.strftime("%Y%m%d-%H%M%S")
    sidecar = dest / f"{rel}.conflict-{ts}.md"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(vault_src, sidecar)
    except Exception as e:
        logger.debug("obsidian_sync: could not write conflict sidecar for %s: %s", rel, e)
    return str(sidecar.relative_to(dest)).replace("\\", "/")


# ── True two-way sync ───────────────────────────────────────────────────────────

def _rel_key(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def two_way_sync(repo_root: Path | None = None, force: bool = False) -> dict:
    """
    Reconcile the vault and its knowledge/obsidian mirror in BOTH directions, using
    the per-file sync-state store to decide which side changed since the last sync:

      * vault changed, mirror didn't  → import   (vault → mirror)
      * mirror changed, vault didn't  → export   (mirror → vault)   [Layla → vault]
      * new on exactly one side        → propagate to the other
      * BOTH changed and they differ   → CONFLICT: keep both, snapshot the vault
                                          version beside the mirror, log, and leave
                                          the vault + mirror originals untouched
      * neither changed / equal        → unchanged

    ``force=True`` lets the vault win a conflict, but only in the import direction —
    the user's vault file is never overwritten by force. A file that has vanished on
    one side is treated as a no-op (we never delete the surviving copy).

    Gated behind ``obsidian_sync_enabled`` — see ``sync_enabled``.
    """
    if not sync_enabled():
        return {"ok": False, "disabled": True,
                "error": "Obsidian two-way sync is disabled. Set obsidian_sync_enabled=true to opt in."}
    vp = get_vault_path()
    if vp is None:
        return {"ok": False, "error": "No vault path configured."}

    dest = get_knowledge_vault_dir(repo_root)
    state = _load_sync_state()

    rels: set[str] = {_rel_key(f, vp) for f in _md_files(vp)}
    rels |= {_rel_key(f, dest) for f in _md_files(dest)}

    imported: list[str] = []
    exported: list[str] = []
    conflicts: list[dict] = []
    unchanged: list[str] = []
    errors: list[str] = []

    for rel in sorted(rels):
        src, dst = vp / rel, dest / rel
        v_exists, l_exists = src.is_file(), dst.is_file()
        v_hash = _file_hash(src) if v_exists else None
        l_hash = _file_hash(dst) if l_exists else None
        prev = state.get(rel) or {}
        prev_v, prev_l = prev.get("vault_hash"), prev.get("local_hash")
        v_changed, l_changed = (v_hash != prev_v), (l_hash != prev_l)

        try:
            # New on exactly one side → propagate to the other.
            if v_exists and not l_exists and prev_l is None:
                _copy_within(src, dst, dest)
                imported.append(rel)
                _record(state, rel, v_hash, v_hash, src, dst)
                continue
            if l_exists and not v_exists and prev_v is None:
                _copy_within(dst, src, vp)
                exported.append(rel)
                _record(state, rel, l_hash, l_hash, src, dst)
                continue
            # Vanished on one side → never delete the survivor.
            if not v_exists or not l_exists:
                unchanged.append(rel)
                continue
            # Both present.
            if v_hash == l_hash:
                unchanged.append(rel)
                _record(state, rel, v_hash, l_hash, src, dst)
                continue
            if v_changed and not l_changed:
                _copy_within(src, dst, dest)          # vault → mirror
                imported.append(rel)
                _record(state, rel, v_hash, v_hash, src, dst)
            elif l_changed and not v_changed:
                _copy_within(dst, src, vp)            # mirror → vault (Layla → vault)
                exported.append(rel)
                _record(state, rel, l_hash, l_hash, src, dst)
            elif force:
                _copy_within(src, dst, dest)          # conflict, vault wins (import only)
                imported.append(rel)
                _record(state, rel, v_hash, v_hash, src, dst)
            else:
                kept = _write_conflict_marker(dest, rel, src)
                conflicts.append({"file": rel, "vault_hash": v_hash, "local_hash": l_hash, "kept": kept})
                logger.warning(
                    "obsidian_sync: edit-both-sides conflict on %s — kept both, "
                    "vault and mirror left untouched", rel,
                )
                # Deliberately do NOT update state → stays flagged until resolved.
        except Exception as e:
            errors.append(f"{rel}: {e}")

    _save_sync_state(state)

    if imported:
        try:
            import runtime_safety
            if runtime_safety.load_config().get("use_chroma"):
                from layla.memory.vector_store import index_knowledge_docs
                index_knowledge_docs(str(dest))
        except Exception as e:
            logger.debug("obsidian_sync: chroma re-index failed: %s", e)

    return {
        "ok": True,
        "imported": imported,
        "exported": exported,
        "conflicts": conflicts,
        "unchanged": unchanged,
        "errors": errors,
        "vault_path": str(vp),
        "dest_path": str(dest),
    }


# ── Structured writeback (Layla learnings → vault notes) ─────────────────────────

def _slugify(text: str) -> str:
    slug = text[:48].lower().replace(" ", "-").strip("-")
    return "".join(c for c in slug if c.isalnum() or c == "-") or "note"


def writeback_learnings(n: int = 10, repo_root: Path | None = None) -> dict:
    """
    Fill the vault with Layla's high-confidence learnings as well-formed, structured
    notes under ``<vault>/layla/`` — frontmatter (source, type, confidence, created,
    tags, layla_id), a titled body, and ``[[wikilinks]]`` for any known entities.

    This is the "keep the vault prepared/structured, fill it with learnings over
    time" writeback. It NEVER clobbers a user-authored note: if the target path
    already holds a note that Layla did not write (``source != layla``), it is
    skipped and reported. Gated behind ``obsidian_sync_enabled``.
    """
    if not sync_enabled():
        return {"ok": False, "disabled": True,
                "error": "Obsidian writeback is disabled. Set obsidian_sync_enabled=true to opt in."}
    vp = get_vault_path()
    if vp is None:
        return {"ok": False, "error": "No vault path configured."}

    try:
        from layla.memory.db import get_top_learnings_for_planning
        rows = get_top_learnings_for_planning(limit=n, min_confidence=0.75)
    except Exception as e:
        logger.debug("obsidian_sync: writeback could not load learnings: %s", e)
        return {"ok": False, "error": f"could not load learnings: {e}"}

    layla_dir = vp / LAYLA_WRITEBACK_SUBDIR
    state = _load_sync_state()
    written: list[str] = []
    skipped: list[dict] = []
    errors: list[str] = []

    for row in rows:
        content = (row.get("content") or "").strip()
        if not content:
            continue
        learning_type = row.get("type") or row.get("learning_type") or "fact"
        confidence = float(row.get("confidence") or row.get("adjusted_confidence") or 0.5)
        lid = str(row.get("id") or "")
        entities = [str(e).strip() for e in (row.get("entities") or []) if str(e).strip()]

        target = layla_dir / f"{_slugify(content)}.md"
        rel = _rel_key(target, vp)

        # Never clobber a user-authored note that happens to sit at this path.
        if target.exists():
            try:
                existing = _read_note(target)
                if str(existing.get("metadata", {}).get("source", "")).lower() != "layla":
                    skipped.append({"file": rel, "reason": "user-authored note present — not clobbered"})
                    continue
            except Exception as e:
                skipped.append({"file": rel, "reason": f"unreadable existing note — not clobbered ({e})"})
                continue

        metadata = {
            "source": "layla",
            "type": learning_type,
            "confidence": round(confidence, 2),
            "created": date.today().isoformat(),
            "tags": ["layla", learning_type],
            "layla_id": lid,
        }
        title = content[:60].strip()
        body = f"# {title}\n\n{content}\n"
        if entities:
            links = " ".join(f"[[{e}]]" for e in entities)
            body += f"\nRelated: {links}\n"

        try:
            _write_note(target, metadata, body, vault_root=vp)
            written.append(rel)
            h = _file_hash(target)
            _record(state, rel, h, None, target, target)  # mirror picks it up on next two_way_sync
        except Exception as e:
            errors.append(f"{rel}: {e}")

    _save_sync_state(state)
    return {
        "ok": True,
        "written": written,
        "skipped": skipped,
        "errors": errors,
        "writeback_dir": str(layla_dir),
    }
