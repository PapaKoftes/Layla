"""
Workspace-scoped project memory (.layla/project_memory.json).

Structural repo map + optional plan/todos/decisions for long-horizon agent work.
See docs/RUNBOOKS.md (project memory section).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

RELATIVE_PATH = Path(".layla") / "project_memory.json"
SCHEMA_VERSION = 2
DEFAULT_MAX_BYTES = 1_500_000
DEFAULT_MAX_FILES = 500
DEFAULT_MAX_LIST = 200


def memory_file_path(workspace_root: Path) -> Path:
    return workspace_root.resolve() / RELATIVE_PATH


def empty_document(workspace_resolved: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "workspace_root": workspace_resolved,
        "files": {},
        "structure": {
            "top_level_dirs": [],
            "tree_sample": [],
            "entrypoint_hints": [],
        },
        "plan": {
            "goal": "",
            "steps": [],
            "current_step_index": 0,
            "status": "",
        },
        "decisions": [],
        "todos": [],
        "modules": {},
        "issues": [],
        "plans": [],
        "aspects": {
            "morrigan": {"notes": [], "focus": "execution"},
            "nyx": {"notes": [], "focus": "knowledge"},
            "echo": {"notes": [], "focus": "patterns"},
            "eris": {"notes": [], "focus": "ideas"},
            "lilith": {"notes": [], "focus": "governance"},
            "cassandra": {"notes": [], "focus": "reactive truth"},
        },
        "signals": {"last_step_count": 0},
        "last_iteration": "",
        "repo_map": {"roots": [], "entry_points": []},
        "preferences": {"style": "concise", "tone": "direct"},
        "semantic_sketch": {
            "ext_top": [],
            "path_tokens_top": [],
            "file_sample_count": 0,
        },
    }


def load_project_memory(workspace_root: Path) -> dict[str, Any] | None:
    p = memory_file_path(workspace_root)
    if not p.is_file():
        return None
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("project_memory load failed: %s", e)
        return None


def _json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def save_project_memory(
    workspace_root: Path,
    data: dict[str, Any],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[bool, str]:
    """Atomic write. Returns (ok, error_message)."""
    data = dict(data)
    data["schema_version"] = SCHEMA_VERSION
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    b = _json_bytes(data)
    if len(b) > max_bytes:
        return False, f"project_memory exceeds max_bytes ({len(b)} > {max_bytes})"
    dest = memory_file_path(workspace_root)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, str(e)
    try:
        fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(dest.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(b)
            os.replace(tmp, str(dest))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        return False, str(e)
    return True, ""


def _cap_files(files: dict[str, Any], max_entries: int) -> dict[str, Any]:
    if len(files) <= max_entries:
        return files
    # Keep lexicographic first N for determinism
    keys = sorted(files.keys())[:max_entries]
    return {k: files[k] for k in keys}


def _cap_list(xs: list[Any], max_n: int) -> list[Any]:
    if len(xs) <= max_n:
        return xs
    return xs[-max_n:]


def merge_patch(
    base: dict[str, Any],
    patch: dict[str, Any],
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_list: int = DEFAULT_MAX_LIST,
) -> dict[str, Any]:
    """Shallow-deep merge for known keys; caps files and list lengths."""

    def deep(a: Any, b: Any) -> Any:
        if isinstance(a, dict) and isinstance(b, dict):
            out = dict(a)
            for k, v in b.items():
                if v is None and k in out:
                    del out[k]
                elif k in out and isinstance(out[k], dict) and isinstance(v, dict):
                    out[k] = deep(out[k], v)
                elif k == "files" and isinstance(v, dict):
                    merged = dict((a.get("files") or {}))
                    merged.update(v)
                    out["files"] = _cap_files(merged, max_files)
                else:
                    out[k] = v
            return out
        return b

    out = deep(base, patch)
    if isinstance(out.get("files"), dict):
        out["files"] = _cap_files(out["files"], max_files)
    for key in ("decisions", "todos"):
        if isinstance(out.get(key), list):
            out[key] = _cap_list(out[key], max_list)
    if isinstance(out.get("plan"), dict) and isinstance(out["plan"].get("steps"), list):
        out["plan"]["steps"] = _cap_list(out["plan"]["steps"], max_list)
    if isinstance(out.get("issues"), list):
        out["issues"] = _cap_list(out["issues"], max_list)
    if isinstance(out.get("plans"), list):
        out["plans"] = _cap_list(out["plans"], max_list)
    if isinstance(out.get("modules"), dict):
        out["modules"] = _cap_files(out["modules"], max_files)
    if isinstance(out.get("last_iteration"), str) and len(out["last_iteration"]) > 4000:
        out["last_iteration"] = out["last_iteration"][:3990] + "…[truncated]"
    return out


def format_for_prompt(data: dict[str, Any], max_chars: int) -> str:
    """Compact text for system head injection."""
    if not data:
        return ""
    try:
        # Prefer high-signal slices
        plan = data.get("plan") or {}
        files = data.get("files") or {}
        sample_paths = sorted(files.keys())[:40]
        lines = [
            f"schema_version={data.get('schema_version')}",
            f"updated_at={data.get('updated_at', '')[:32]}",
        ]
        if plan.get("goal"):
            lines.append(f"plan.goal: {str(plan.get('goal'))[:500]}")
        if plan.get("status"):
            lines.append(f"plan.status: {plan.get('status')}")
        if isinstance(plan.get("steps"), list) and plan["steps"]:
            lines.append("plan.steps (preview):")
            for i, s in enumerate(plan["steps"][:12]):
                lines.append(f"  {i}. {str(s)[:200]}")
        if sample_paths:
            lines.append("files tracked (sample): " + ", ".join(sample_paths))
        sk = data.get("semantic_sketch") if isinstance(data.get("semantic_sketch"), dict) else {}
        if sk.get("file_sample_count"):
            ext_top = sk.get("ext_top") if isinstance(sk.get("ext_top"), list) else []
            tok_top = sk.get("path_tokens_top") if isinstance(sk.get("path_tokens_top"), list) else []
            et = ", ".join(str(x) for x in ext_top[:10])
            tt = ", ".join(str(x) for x in tok_top[:12])
            lines.append(f"semantic_sketch: files≈{sk.get('file_sample_count')} ext_top=[{et}] tokens=[{tt}]")
        if isinstance(data.get("todos"), list) and data["todos"]:
            lines.append("todos: " + "; ".join(str(x)[:120] for x in data["todos"][:8]))
        if isinstance(data.get("issues"), list) and data["issues"]:
            lines.append("issues: " + "; ".join(str(x)[:120] for x in data["issues"][:6]))
        pl = data.get("plans") if isinstance(data.get("plans"), list) else []
        if pl:
            lines.append("plans history (recent): " + "; ".join(str(p)[:100] for p in pl[-5:]))
        mods = data.get("modules") if isinstance(data.get("modules"), dict) else {}
        if mods:
            mk = sorted(mods.keys())[:15]
            lines.append("modules (sample): " + ", ".join(mk))
        sig = data.get("signals") if isinstance(data.get("signals"), dict) else {}
        if sig.get("last_step_count") is not None:
            lines.append(f"signals.last_step_count: {sig.get('last_step_count')}")
        li = data.get("last_iteration")
        if isinstance(li, str) and li.strip():
            lines.append("last_iteration: " + li.strip()[:240])
        text = "\n".join(lines)
        if len(text) > max_chars:
            return text[: max_chars - 20] + "\n[...truncated...]"
        return text
    except Exception:
        return ""


def persist_plan_to_memory(
    workspace_root: Path,
    goal: str,
    steps: list[Any],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
) -> tuple[bool, str]:
    base = load_project_memory(workspace_root) or empty_document(str(workspace_root.resolve()))
    patch = {
        "plan": {
            "goal": (goal or "")[:2000],
            "steps": list(steps) if isinstance(steps, list) else [],
            "current_step_index": 0,
            "status": "ready",
        }
    }
    merged = merge_patch(base, patch, max_files=max_files)
    return save_project_memory(workspace_root, merged, max_bytes=max_bytes)


def _semantic_sketch_from_files(files_meta: dict[str, Any]) -> dict[str, Any]:
    """Lightweight path/extension histograms for long-horizon context (no embeddings)."""
    from collections import Counter

    ext_c: Counter[str] = Counter()
    tok_c: Counter[str] = Counter()
    stop = frozenset({
        "", "py", "md", "txt", "json", "toml", "yaml", "yml", "src", "test", "tests", "init",
        "main", "lib", "docs", "agent", "www", "dist", "build",
    })
    for rel in list(files_meta.keys())[:3000]:
        if not isinstance(rel, str):
            continue
        for part in rel.replace("\\", "/").split("/"):
            if not part or part.startswith("."):
                continue
            stem = part.rsplit(".", 1)[0].lower()
            if len(stem) >= 3 and stem not in stop:
                tok_c[stem[:56]] += 1
        meta = files_meta.get(rel)
        ext = (meta or {}).get("ext") if isinstance(meta, dict) else ""
        if isinstance(ext, str) and ext:
            ext_c[ext.lower()[:16]] += 1
    return {
        "ext_top": [e for e, _ in ext_c.most_common(14)],
        "path_tokens_top": [t for t, _ in tok_c.most_common(28)],
        "file_sample_count": len(files_meta),
    }


def scan_workspace_into_memory(
    workspace_root: Path,
    *,
    dry_run: bool = False,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """
    Walk workspace (respecting repo_cognition ignore dirs), build files + structure, merge into memory.
    """
    from services.repo_cognition import IGNORE_DIR_PARTS, _tree_sample

    root = workspace_root.resolve()
    if not root.is_dir():
        return {"ok": False, "error": "not_a_directory", "path": str(root)}

    now = datetime.now(timezone.utc).isoformat()
    tree_lines: list[str] = []
    try:
        tree_lines = _tree_sample(root, max_depth=3, max_entries=160)
    except Exception as e:
        logger.debug("tree_sample: %s", e)

    top_dirs: list[str] = []
    try:
        for c in sorted(root.iterdir(), key=lambda x: x.name.lower()):
            if c.is_dir() and c.name not in IGNORE_DIR_PARTS and not c.name.startswith("."):
                top_dirs.append(c.name)
    except OSError:
        pass

    entry_hints: list[str] = []
    for hint in ("main.py", "pyproject.toml", "package.json", "go.mod", "Cargo.toml", "README.md"):
        if (root / hint).is_file():
            entry_hints.append(hint)

    existing = load_project_memory(root)
    prev_files: dict[str, Any] = {}
    if isinstance(existing, dict) and isinstance(existing.get("files"), dict):
        prev_files = existing["files"]

    files_meta: dict[str, Any] = {}
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dp = Path(dirpath)
        try:
            rel_dir = dp.relative_to(root)
        except ValueError:
            continue
        parts = rel_dir.parts
        if any(p in IGNORE_DIR_PARTS or p.startswith(".") for p in parts):
            continue
        dirnames[:] = [
            d
            for d in dirnames
            if d not in IGNORE_DIR_PARTS and not d.startswith(".") and d not in ("venv", "node_modules")
        ]
        for fn in filenames:
            if count >= max_files:
                break
            fp = dp / fn
            try:
                rel = fp.relative_to(root).as_posix()
            except ValueError:
                continue
            try:
                st = fp.stat()
            except OSError:
                continue
            ext = fp.suffix.lower()
            prev = prev_files.get(rel, {}) if isinstance(prev_files.get(rel), dict) else {}
            files_meta[rel] = {
                "size": st.st_size,
                "ext": ext,
                "purpose": prev.get("purpose", ""),
                "complexity": prev.get("complexity", ""),
                "issues": prev.get("issues", []) if isinstance(prev.get("issues"), list) else [],
                "last_scanned": now,
            }
            count += 1
        if count >= max_files:
            break

    base = existing if existing else empty_document(str(root))
    sketch = _semantic_sketch_from_files(files_meta)
    patch = {
        "workspace_root": str(root),
        "structure": {
            "top_level_dirs": top_dirs[:80],
            "tree_sample": tree_lines,
            "entrypoint_hints": entry_hints,
        },
        "repo_map": {
            "roots": top_dirs[:80],
            "entry_points": entry_hints,
        },
        "semantic_sketch": sketch,
        "files": files_meta,
    }
    merged = merge_patch(base, patch, max_files=max_files)

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_write": str(memory_file_path(root)),
            "file_entries": len(files_meta),
            "tree_lines": len(tree_lines),
        }

    ok, err = save_project_memory(root, merged, max_bytes=max_bytes)
    if not ok:
        return {"ok": False, "error": err or "save_failed"}
    return {
        "ok": True,
        "path": str(memory_file_path(root)),
        "file_entries": len(files_meta),
        "tree_lines": len(tree_lines),
        "entrypoint_hints": entry_hints,
    }


def summarize_memory(mem: dict[str, Any] | None) -> str:
    """Short token-efficient summary for plan headers."""
    if not mem or not isinstance(mem, dict):
        return "0 files, 0 modules, 0 issues tracked."
    files = mem.get("files") if isinstance(mem.get("files"), dict) else {}
    modules = mem.get("modules") if isinstance(mem.get("modules"), dict) else {}
    issues = mem.get("issues") if isinstance(mem.get("issues"), list) else []
    return f"{len(files)} files, {len(modules)} modules, {len(issues)} issues tracked."


def aspect_hint(mem: dict[str, Any], aspect: str = "morrigan") -> str:
    """Short header line: focus + last notes for one aspect (memory-driven personalities, lightweight)."""
    aid = (aspect or "morrigan").strip()
    if not aid:
        return ""
    aspects = mem.get("aspects") if isinstance(mem.get("aspects"), dict) else {}
    block = aspects.get(aid.lower()) or aspects.get(aid)
    if not isinstance(block, dict):
        return ""
    focus = str(block.get("focus") or "").strip()
    notes_raw = block.get("notes")
    notes = notes_raw if isinstance(notes_raw, list) else []
    recent = [str(n).strip() for n in notes[-2:] if str(n).strip()]
    label = aid.lower()
    tail = recent if recent else "[]"
    return f"{label} focus: {focus or '—'}. Recent notes: {tail}"[:500]


def format_aspects_hint(mem: dict[str, Any], aspect_id: str) -> str:
    """Prefer aspect_hint; fall back to longer note tail if needed."""
    short = aspect_hint(mem, aspect_id or "morrigan")
    if short.strip():
        return short
    aid = (aspect_id or "").strip().lower()
    if not aid:
        return ""
    aspects = mem.get("aspects")
    if not isinstance(aspects, dict):
        return ""
    block = aspects.get(aid) or aspects.get(aspect_id.strip())
    if not isinstance(block, dict):
        return ""
    notes = block.get("notes")
    if not isinstance(notes, list) or not notes:
        return ""
    lines = [str(n).strip() for n in notes[-5:] if str(n).strip()]
    if not lines:
        return ""
    tail = "; ".join(lines)[:400]
    return f"Aspect notes ({aid}) from project memory: {tail}"


def load_memory(workspace_root: str) -> dict[str, Any]:
    """Alias for file-based iteration code: load `.layla/project_memory.json` or empty schema."""
    raw = (workspace_root or "").strip()
    if not raw:
        return empty_document("")
    root = Path(raw).expanduser().resolve()
    return load_project_memory(root) or empty_document(str(root))


def save_memory(workspace_root: str, data: dict[str, Any]) -> tuple[bool, str]:
    """Alias: atomic save project memory for workspace string path."""
    raw = (workspace_root or "").strip()
    if not raw:
        return False, "workspace_root required"
    root = Path(raw).expanduser().resolve()
    return save_project_memory(root, data, max_bytes=DEFAULT_MAX_BYTES)
