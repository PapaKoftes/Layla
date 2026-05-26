"""
repo_indexer.py — Phase B: Persistent SQLite code symbol index.

Stores functions, classes, imports, and file metadata extracted from
workspace Python files. Provides fast symbol lookup by name/file.
Complements workspace_index.py (ChromaDB semantic) with an exact/structural index.

Schema:
  repo_files  (path, language, size_bytes, mtime, indexed_at)
  repo_symbols (id, file_path, kind, name, line, parent, signature, indexed_at)
  repo_imports (id, file_path, raw, module, line, indexed_at)
  repo_calls   (id, file_path, caller, callee, line, indexed_at)

Usage:
  from services.repo_indexer import index_workspace_repo, get_symbols, search_symbols
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

_AGENT_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _AGENT_DIR / ".layla" / "repo_index.db"

_MIGRATED: bool = False
_DB_PATH: Path = _DEFAULT_DB


# ── DB bootstrap ──────────────────────────────────────────────────────────────

@contextmanager
def _conn(db_path: Path | None = None):
    """Context manager yielding a SQLite row-factory connection."""
    path = db_path or _DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    try:
        yield con
    finally:
        con.close()


def migrate(db_path: Path | None = None) -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    global _MIGRATED
    if _MIGRATED and db_path is None:
        return
    with _conn(db_path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS repo_files (
                path        TEXT PRIMARY KEY,
                language    TEXT DEFAULT 'python',
                size_bytes  INTEGER DEFAULT 0,
                mtime       REAL DEFAULT 0.0,
                indexed_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS repo_symbols (
                id          TEXT PRIMARY KEY,
                file_path   TEXT NOT NULL,
                kind        TEXT NOT NULL,   -- 'function' | 'class' | 'method'
                name        TEXT NOT NULL,
                line        INTEGER DEFAULT 0,
                parent      TEXT DEFAULT '',  -- class name for methods
                signature   TEXT DEFAULT '',
                indexed_at  TEXT,
                FOREIGN KEY(file_path) REFERENCES repo_files(path) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS repo_imports (
                id          TEXT PRIMARY KEY,
                file_path   TEXT NOT NULL,
                raw         TEXT,
                module      TEXT DEFAULT '',
                line        INTEGER DEFAULT 0,
                indexed_at  TEXT,
                FOREIGN KEY(file_path) REFERENCES repo_files(path) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS repo_calls (
                id          TEXT PRIMARY KEY,
                file_path   TEXT NOT NULL,
                caller      TEXT DEFAULT '',
                callee      TEXT DEFAULT '',
                line        INTEGER DEFAULT 0,
                indexed_at  TEXT,
                FOREIGN KEY(file_path) REFERENCES repo_files(path) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_symbols_name     ON repo_symbols(name);
            CREATE INDEX IF NOT EXISTS idx_symbols_file     ON repo_symbols(file_path);
            CREATE INDEX IF NOT EXISTS idx_symbols_kind     ON repo_symbols(kind);
            CREATE INDEX IF NOT EXISTS idx_imports_module   ON repo_imports(module);
            CREATE INDEX IF NOT EXISTS idx_calls_callee     ON repo_calls(callee);
        """)
        db.commit()
    if db_path is None:
        _MIGRATED = True


# ── Extraction helpers ────────────────────────────────────────────────────────

def _extract_symbols_ast(source: str, file_path: str) -> dict[str, list[dict]]:
    """Extract symbols using Python's stdlib ast module (no tree-sitter required)."""
    import ast as _ast
    symbols: list[dict] = []
    imports: list[dict] = []
    calls: list[dict] = []

    try:
        tree = _ast.parse(source, filename=file_path)
    except SyntaxError:
        return {"symbols": symbols, "imports": imports, "calls": calls}

    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            # Determine parent class if any
            parent = ""
            for parent_node in _ast.walk(tree):
                if isinstance(parent_node, _ast.ClassDef):
                    for child in _ast.walk(parent_node):
                        if child is node:
                            parent = parent_node.name
                            break
            kind = "method" if parent else "function"
            # Build minimal signature
            args = getattr(node.args, "args", []) or []
            arg_names = [a.arg for a in args if a.arg != "self"][:6]
            sig = f"({', '.join(arg_names)}{'...' if len(args) > 7 else ''})"
            symbols.append({
                "kind": kind,
                "name": node.name,
                "line": node.lineno,
                "parent": parent,
                "signature": sig,
            })
        elif isinstance(node, _ast.ClassDef):
            bases = []
            for b in node.bases:
                if isinstance(b, _ast.Name):
                    bases.append(b.id)
                elif isinstance(b, _ast.Attribute):
                    bases.append(b.attr)
            sig = f"({', '.join(bases)})" if bases else ""
            symbols.append({
                "kind": "class",
                "name": node.name,
                "line": node.lineno,
                "parent": "",
                "signature": sig,
            })
        elif isinstance(node, _ast.Import):
            for alias in node.names:
                imports.append({
                    "raw": f"import {alias.name}",
                    "module": alias.name.split(".")[0],
                    "line": node.lineno,
                })
        elif isinstance(node, _ast.ImportFrom):
            mod = node.module or ""
            names = ", ".join(a.name for a in node.names[:5])
            imports.append({
                "raw": f"from {mod} import {names}",
                "module": mod.split(".")[0] if mod else "",
                "line": node.lineno,
            })
        elif isinstance(node, _ast.Call):
            if isinstance(node.func, _ast.Name):
                calls.append({"caller": "<module>", "callee": node.func.id, "line": getattr(node, "lineno", 0)})
            elif isinstance(node.func, _ast.Attribute):
                calls.append({"caller": "<module>", "callee": node.func.attr, "line": getattr(node, "lineno", 0)})

    return {"symbols": symbols, "imports": imports, "calls": calls}


def _try_tree_sitter(source: str, file_path: str) -> dict[str, list[dict]] | None:
    """Try tree-sitter extraction; return None if unavailable."""
    try:
        from services.workspace_index import extract_code_architecture
        arch = extract_code_architecture(source, file_path)
        if not arch:
            return None
        symbols: list[dict] = []
        for fn in arch.get("functions", []):
            symbols.append({
                "kind": "function",
                "name": fn["name"],
                "line": fn.get("line", 0),
                "parent": fn.get("class") or "",
                "signature": "",
            })
        for cls in arch.get("classes", []):
            symbols.append({
                "kind": "class",
                "name": cls["name"],
                "line": cls.get("line", 0),
                "parent": "",
                "signature": "(" + ", ".join(cls.get("bases", [])) + ")",
            })
        imports = [
            {"raw": imp.get("raw", ""), "module": imp.get("raw", "").split()[1].split(".")[0] if len(imp.get("raw", "").split()) > 1 else "", "line": imp.get("line", 0)}
            for imp in arch.get("imports", [])
        ]
        calls = [
            {"caller": c.get("caller", ""), "callee": c.get("callee", ""), "line": 0}
            for c in arch.get("calls", [])
        ]
        return {"symbols": symbols, "imports": imports, "calls": calls}
    except Exception:
        return None


# ── Index a single file ───────────────────────────────────────────────────────

def index_file(file_path: Path, workspace_root: Path, db_path: Path | None = None) -> bool:
    """
    Index a single Python file into the repo index.
    Returns True if indexed, False if skipped/errored.
    """
    migrate(db_path)
    try:
        rel = str(file_path.relative_to(workspace_root)).replace("\\", "/")
    except ValueError:
        rel = str(file_path).replace("\\", "/")

    try:
        stat = file_path.stat()
        mtime = stat.st_mtime
        size = stat.st_size
    except Exception:
        return False

    # Check if already indexed and unchanged
    with _conn(db_path) as db:
        row = db.execute("SELECT mtime FROM repo_files WHERE path = ?", (rel,)).fetchone()
        if row and abs(float(row["mtime"]) - mtime) < 0.01:
            return True  # Already up-to-date

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False

    if len(source.strip()) < 10:
        return False

    # Extract with tree-sitter first, fall back to ast
    _ts = _try_tree_sitter(source, rel)
    # Fall back to ast if tree-sitter returned empty symbols (dict is truthy even when empty lists)
    extracted = _ts if (_ts and _ts.get("symbols")) else _extract_symbols_ast(source, rel)

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with _conn(db_path) as db:
        # Upsert file record
        db.execute("""
            INSERT OR REPLACE INTO repo_files (path, language, size_bytes, mtime, indexed_at)
            VALUES (?, 'python', ?, ?, ?)
        """, (rel, size, mtime, now_iso))

        # Delete old symbols/imports/calls for this file
        db.execute("DELETE FROM repo_symbols WHERE file_path = ?", (rel,))
        db.execute("DELETE FROM repo_imports WHERE file_path = ?", (rel,))
        db.execute("DELETE FROM repo_calls WHERE file_path = ?", (rel,))

        # Insert symbols
        for sym in extracted.get("symbols", []):
            sid = hashlib.sha1(f"{rel}:{sym['kind']}:{sym['name']}:{sym['line']}".encode()).hexdigest()[:20]
            db.execute("""
                INSERT OR REPLACE INTO repo_symbols (id, file_path, kind, name, line, parent, signature, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (sid, rel, sym["kind"], sym["name"], sym["line"], sym.get("parent", ""), sym.get("signature", ""), now_iso))

        # Insert imports
        for imp in extracted.get("imports", [])[:50]:
            iid = hashlib.sha1(f"{rel}:imp:{imp['raw']}:{imp['line']}".encode()).hexdigest()[:20]
            db.execute("""
                INSERT OR REPLACE INTO repo_imports (id, file_path, raw, module, line, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (iid, rel, imp.get("raw", "")[:200], imp.get("module", "")[:80], imp.get("line", 0), now_iso))

        # Insert calls
        for call in extracted.get("calls", [])[:100]:
            cid = hashlib.sha1(f"{rel}:call:{call['caller']}:{call['callee']}:{call.get('line',0)}".encode()).hexdigest()[:20]
            db.execute("""
                INSERT OR REPLACE INTO repo_calls (id, file_path, caller, callee, line, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (cid, rel, call.get("caller", "")[:80], call.get("callee", "")[:80], call.get("line", 0), now_iso))

        db.commit()

    return True


# ── Index entire workspace ────────────────────────────────────────────────────

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", "dist", "build", ".layla", "chroma_db"}


def index_workspace_repo(
    workspace_root: str | Path,
    db_path: Path | None = None,
    max_files: int = 2000,
    force_reindex: bool = False,
) -> dict[str, Any]:
    """
    Walk workspace_root and index all Python files.
    Returns {indexed, skipped, errors, duration_ms}.
    """
    migrate(db_path)
    root = Path(workspace_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {"indexed": 0, "skipped": 0, "errors": [f"Not a directory: {workspace_root}"], "duration_ms": 0}

    t0 = time.monotonic()
    indexed = 0
    skipped = 0
    errors: list[str] = []

    if force_reindex:
        with _conn(db_path) as db:
            db.execute("DELETE FROM repo_calls")
            db.execute("DELETE FROM repo_imports")
            db.execute("DELETE FROM repo_symbols")
            db.execute("DELETE FROM repo_files")
            db.commit()

    file_count = 0
    for py_file in root.rglob("*.py"):
        if any(skip in py_file.parts for skip in SKIP_DIRS):
            continue
        if file_count >= max_files:
            skipped += 1
            continue
        file_count += 1
        try:
            ok = index_file(py_file, root, db_path)
            if ok:
                indexed += 1
            else:
                skipped += 1
        except Exception as e:
            errors.append(f"{py_file.name}: {e}")
            skipped += 1

    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info("repo_indexer: indexed %d files (%d skipped) in %dms", indexed, skipped, duration_ms)
    return {"indexed": indexed, "skipped": skipped, "errors": errors[:20], "duration_ms": duration_ms}


# ── Query API ────────────────────────────────────────────────────────────────

def get_symbols(
    name: str | None = None,
    kind: str | None = None,
    file_path: str | None = None,
    limit: int = 50,
    db_path: Path | None = None,
) -> list[dict]:
    """
    Retrieve symbols from the index.
    name: exact or LIKE match (use % for wildcard)
    kind: 'function' | 'class' | 'method'
    file_path: filter by file path (LIKE match)
    """
    migrate(db_path)
    clauses: list[str] = []
    params: list[Any] = []
    if name:
        clauses.append("name LIKE ?")
        params.append(name if "%" in name else f"%{name}%")
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if file_path:
        clauses.append("file_path LIKE ?")
        params.append(file_path if "%" in file_path else f"%{file_path}%")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    try:
        with _conn(db_path) as db:
            rows = db.execute(
                f"SELECT * FROM repo_symbols {where} ORDER BY name LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.debug("repo_indexer: get_symbols failed: %s", e)
        return []


def search_symbols(query: str, limit: int = 20, db_path: Path | None = None) -> list[dict]:
    """Full-text search across symbol names (LIKE %query%)."""
    return get_symbols(name=f"%{query}%", limit=limit, db_path=db_path)


def get_file_symbols(file_path: str, db_path: Path | None = None) -> dict[str, Any]:
    """Return all symbols/imports for a specific file."""
    migrate(db_path)
    try:
        with _conn(db_path) as db:
            syms = db.execute(
                "SELECT * FROM repo_symbols WHERE file_path = ? ORDER BY line",
                (file_path,),
            ).fetchall()
            imps = db.execute(
                "SELECT * FROM repo_imports WHERE file_path = ? ORDER BY line",
                (file_path,),
            ).fetchall()
            return {
                "symbols": [dict(r) for r in syms],
                "imports": [dict(r) for r in imps],
            }
    except Exception as e:
        logger.debug("repo_indexer: get_file_symbols failed: %s", e)
        return {"symbols": [], "imports": []}


def get_callers_of(callee: str, limit: int = 20, db_path: Path | None = None) -> list[dict]:
    """Find all places that call a given function/method name."""
    migrate(db_path)
    try:
        with _conn(db_path) as db:
            rows = db.execute(
                "SELECT * FROM repo_calls WHERE callee LIKE ? LIMIT ?",
                (f"%{callee}%", limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.debug("repo_indexer: get_callers_of failed: %s", e)
        return []


def get_stats(db_path: Path | None = None) -> dict[str, int]:
    """Return counts for each table."""
    migrate(db_path)
    try:
        with _conn(db_path) as db:
            return {
                "files": db.execute("SELECT COUNT(*) FROM repo_files").fetchone()[0],
                "symbols": db.execute("SELECT COUNT(*) FROM repo_symbols").fetchone()[0],
                "imports": db.execute("SELECT COUNT(*) FROM repo_imports").fetchone()[0],
                "calls": db.execute("SELECT COUNT(*) FROM repo_calls").fetchone()[0],
            }
    except Exception as e:
        logger.debug("repo_indexer: get_stats failed: %s", e)
        return {"files": 0, "symbols": 0, "imports": 0, "calls": 0}


def get_symbol_context(symbol_name: str, db_path: Path | None = None) -> str:
    """
    Build a short text summary of a symbol for LLM context injection.
    Returns e.g. 'def foo(bar, baz) in services/foo.py:42'
    """
    syms = get_symbols(name=symbol_name, limit=5, db_path=db_path)
    if not syms:
        return ""
    parts = []
    for s in syms:
        kind = s.get("kind", "")
        name = s.get("name", "")
        sig = s.get("signature", "")
        file_ = s.get("file_path", "")
        line = s.get("line", 0)
        parent = s.get("parent", "")
        if kind == "class":
            parts.append(f"class {name}{sig} in {file_}:{line}")
        elif parent:
            parts.append(f"def {name}{sig} (method of {parent}) in {file_}:{line}")
        else:
            parts.append(f"def {name}{sig} in {file_}:{line}")
    return "; ".join(parts)


# ── GraphML export ────────────────────────────────────────────────────────────

def export_graphml(workspace_root: str | Path, output_path: Path | None = None, db_path: Path | None = None) -> bool:
    """
    Export the symbol dependency graph as GraphML for NetworkX/visualization.
    Nodes: files, symbols. Edges: calls, imports, class membership.
    Returns True on success.
    """
    migrate(db_path)
    try:
        import networkx as nx
    except ImportError:
        logger.debug("repo_indexer: networkx not available, skipping GraphML export")
        return False

    root = Path(workspace_root).expanduser().resolve()
    output = output_path or (root / ".layla" / "repo_graph.graphml")
    output.parent.mkdir(parents=True, exist_ok=True)

    G = nx.DiGraph()

    with _conn(db_path) as db:
        # Add file nodes
        files = db.execute("SELECT * FROM repo_files").fetchall()
        for f in files:
            G.add_node(f["path"], kind="file", label=Path(f["path"]).name)

        # Add symbol nodes and file→symbol edges
        syms = db.execute("SELECT * FROM repo_symbols").fetchall()
        for s in syms:
            nid = f"{s['file_path']}::{s['kind']}::{s['name']}"
            G.add_node(nid, kind=s["kind"], label=s["name"], file=s["file_path"], line=str(s["line"]))
            G.add_edge(s["file_path"], nid, edge_type="defines")
            if s["parent"]:
                parent_id = f"{s['file_path']}::class::{s['parent']}"
                G.add_edge(parent_id, nid, edge_type="has_method")

        # Add call edges
        calls = db.execute("SELECT * FROM repo_calls").fetchall()
        for c in calls:
            caller_id = f"{c['file_path']}::function::{c['caller']}"
            callee_id = c["callee"]
            if G.has_node(caller_id):
                G.add_edge(caller_id, callee_id, edge_type="calls")

    try:
        nx.write_graphml(G, str(output))
        logger.info("repo_indexer: GraphML exported to %s (%d nodes, %d edges)", output, G.number_of_nodes(), G.number_of_edges())
        return True
    except Exception as e:
        logger.warning("repo_indexer: GraphML write failed: %s", e)
        return False
