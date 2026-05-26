"""
Multi-repository cognition packs: scan canonical docs, build a deterministic markdown digest,
persist in SQLite, inject into system head (see agent_loop._build_system_head).

Does not replace RAG or workspace semantic index — it anchors norms, intent, and layout so
the model drifts less across long sessions. Re-sync after large repo changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# Ordered: most stable “intent / rules / architecture” signals first
PRIORITY_RELATIVE_PATHS: tuple[str, ...] = (
    "README.md",
    "README.rst",
    "PROJECT_BRAIN.md",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "LAYLA_NORTH_STAR.md",
    "VALUES.md",
    "docs/IMPLEMENTATION_STATUS.md",
    "docs/PRODUCTION_CONTRACT.md",
    "docs/GOLDEN_FLOW.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "requirements.txt",
    "CONTRIBUTING.md",
    "WORKFLOW.md",
)

IGNORE_DIR_PARTS = frozenset({
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".tox",
    ".eggs",
    "chroma_db",
})


def _read_text_head_tail(path: Path, *, head_lines: int = 200, tail_lines: int = 35, max_bytes: int = 96_000) -> str:
    try:
        raw = path.read_bytes()[:max_bytes]
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    if len(lines) <= head_lines + tail_lines + 5:
        return text.strip()
    head = "\n".join(lines[:head_lines])
    tail = "\n".join(lines[-tail_lines:])
    return f"{head}\n\n[... {len(lines) - head_lines - tail_lines} lines omitted ...]\n\n{tail}".strip()


def _git_remote(root: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "remote", "-v"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=4,
            encoding="utf-8",
            errors="replace",
        )
        out = (r.stdout or "").strip()
        return out[:800] if out else ""
    except Exception:
        return ""


def _tree_sample(root: Path, *, max_depth: int = 2, max_entries: int = 120) -> list[str]:
    out: list[str] = []

    def walk(p: Path, depth: int) -> None:
        if len(out) >= max_entries or depth > max_depth:
            return
        try:
            children = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except OSError:
            return
        for c in children:
            if len(out) >= max_entries:
                break
            if any(part in IGNORE_DIR_PARTS for part in c.parts):
                continue
            rel = c.relative_to(root)
            prefix = "  " * depth
            if c.is_dir():
                out.append(f"{prefix}{rel.as_posix()}/")
                walk(c, depth + 1)
            else:
                out.append(f"{prefix}{rel.as_posix()}")

    walk(root, 0)
    return out


def gather_repo_signals(root: Path, *, label: str = "") -> dict[str, Any]:
    signals: dict[str, Any] = {
        "root": str(root.resolve()),
        "label": (label or root.name)[:200],
        "files": {},
        "errors": [],
        "tree_sample": [],
        "git_remote": "",
        "architecture_excerpt": "",
    }
    if not root.is_dir():
        signals["errors"].append("not_a_directory")
        return signals
    signals["git_remote"] = _git_remote(root)
    try:
        signals["tree_sample"] = _tree_sample(root)
    except Exception as e:
        signals["errors"].append(f"tree:{e}")
    for rel in PRIORITY_RELATIVE_PATHS:
        p = root / rel
        if not p.is_file():
            continue
        try:
            st = p.stat()
            body = _read_text_head_tail(p)
            signals["files"][rel] = {
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "chars": len(body),
                "excerpt": body[:65_000],
            }
        except OSError as e:
            signals["errors"].append(f"{rel}:{e}")
    try:
        from services.workspace_index import get_architecture_summary

        arch = get_architecture_summary(root)
        if arch and str(arch).strip():
            signals["architecture_excerpt"] = str(arch).strip()[:4000]
    except Exception as e:
        logger.debug("repo_cognition architecture excerpt skipped: %s", e)
    return signals


def compute_fingerprint(signals: dict[str, Any]) -> str:
    parts: list[str] = []
    for rel in sorted((signals.get("files") or {}).keys()):
        meta = signals["files"][rel]
        parts.append(f"{rel}:{meta.get('size', 0)}:{meta.get('mtime', 0)}")
    raw = "|".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:32]


def build_pack_markdown(signals: dict[str, Any]) -> str:
    label = signals.get("label") or Path(signals.get("root", ".")).name
    root = signals.get("root", "")
    lines: list[str] = [
        f"# Repository cognition — {label}",
        f"**Root:** `{root}`",
        "",
        "## Consistency contract (for this workspace)",
        "- Prefer minimal diffs; match existing patterns and file layout.",
        "- Treat sections below as **declared intent**; if code disagrees, the code wins — note the gap.",
        "- For upgrades: cross-check `docs/IMPLEMENTATION_STATUS.md` / roadmap docs before proposing new architecture.",
        "",
    ]
    gr = (signals.get("git_remote") or "").strip()
    if gr:
        lines += ["## Git remotes (short)", "```", gr[:600], "```", ""]

    tree = signals.get("tree_sample") or []
    if tree:
        lines += ["## Top-of-tree sample (depth-limited)", "```", *tree[:100], "```", ""]

    arch = (signals.get("architecture_excerpt") or "").strip()
    if arch:
        lines += ["## Code architecture scan (Python tree-sitter summary)", arch[:3500], ""]

    files = signals.get("files") or {}
    if not files:
        lines += [
            "## Canonical docs",
            "_No priority docs found (README, AGENTS.md, ARCHITECTURE.md, etc.). Run sync from repo root or add docs._",
            "",
        ]
    else:
        lines.append("## Canonical docs (excerpts)")
        for rel in PRIORITY_RELATIVE_PATHS:
            if rel not in files:
                continue
            meta = files[rel]
            lines.append(f"### `{rel}` ({meta.get('size', 0)} bytes)")
            lines.append(meta.get("excerpt", "")[:60_000])
            lines.append("")

    errs = signals.get("errors") or []
    if errs:
        lines += ["## Gather warnings", "- " + "\n- ".join(str(e) for e in errs[:20]), ""]

    return "\n".join(lines).strip()


def sync_repo_cognition(
    workspace_roots: list[str],
    *,
    index_semantic: bool = False,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build and store cognition packs for each root. Optional semantic index per root."""
    from layla.memory.db import normalize_workspace_root, save_repo_cognition_snapshot

    labels = labels or {}
    results: list[dict[str, Any]] = []
    for raw in workspace_roots:
        s = (raw or "").strip()
        if not s:
            continue
        root = Path(s).expanduser().resolve()
        if not root.is_dir():
            results.append({"workspace_root": s, "ok": False, "error": "not_a_directory"})
            continue
        key = normalize_workspace_root(str(root))
        label = labels.get(s) or labels.get(key) or root.name
        sig = gather_repo_signals(root, label=label)
        fp = compute_fingerprint(sig)
        md = build_pack_markdown(sig)
        manifest = [{"path": k, "size": v.get("size"), "mtime": v.get("mtime")} for k, v in sorted(sig.get("files", {}).items())]
        pack_summary = {
            "root": key,
            "label": label,
            "fingerprint": fp,
            "doc_count": len(sig.get("files") or {}),
            "errors": sig.get("errors") or [],
        }
        save_repo_cognition_snapshot(
            {
                "workspace_root": key,
                "label": label,
                "fingerprint": fp,
                "pack_json": json.dumps(pack_summary, ensure_ascii=False)[:490_000],
                "pack_markdown": md,
                "file_manifest_json": json.dumps(manifest, ensure_ascii=False)[:190_000],
            }
        )
        if index_semantic:
            try:
                from services.workspace_index import index_workspace

                index_workspace(str(root))
            except Exception as e:
                results.append({"workspace_root": key, "ok": True, "fingerprint": fp, "indexed_semantic": False, "index_error": str(e)})
                continue
        results.append(
            {
                "workspace_root": key,
                "ok": True,
                "fingerprint": fp,
                "markdown_chars": len(md),
                "indexed_semantic": bool(index_semantic),
            }
        )
    return {"ok": True, "results": results}


def format_cognition_for_prompt(resolved_roots: list[str], *, max_chars: int = 6000) -> str:
    """Load stored snapshots and merge with a per-root budget."""
    from layla.memory.db import get_repo_cognition_snapshot, normalize_workspace_root

    roots: list[str] = []
    for r in resolved_roots:
        k = normalize_workspace_root(r)
        if k and k not in roots:
            roots.append(k)
    if not roots:
        return ""
    budget = max(1500, int(max_chars)) // max(1, len(roots))
    chunks: list[str] = []
    for k in roots:
        row = get_repo_cognition_snapshot(k)
        if not row:
            chunks.append(f"### No snapshot for `{k}`\nRun `POST /workspace/cognition/sync` or tool `sync_repo_cognition`.")
            continue
        text = (row.get("pack_markdown") or "").strip()
        if len(text) > budget:
            text = text[: budget - 120] + "\n\n[... truncated for token budget ...]"
        chunks.append(text)
    return "\n\n---\n\n".join(chunks)


def merge_cognition_roots(workspace_root: str, extras: list[str] | None) -> list[str]:
    """Primary workspace first, then extras, deduped."""
    from layla.memory.db import normalize_workspace_root

    out: list[str] = []
    w = (workspace_root or "").strip()
    if w:
        nw = normalize_workspace_root(w)
        if nw:
            out.append(nw)
    for e in extras or []:
        s = (e or "").strip()
        if not s:
            continue
        nk = normalize_workspace_root(s)
        if nk and nk not in out:
            out.append(nk)
    return out
