"""
Workspace index. Index local projects using embeddings for semantic search.
Code intelligence: tree-sitter extracts functions, classes, imports, call graph.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKSPACE_INDEX_PATH = Path(__file__).resolve().parent.parent / "chroma_db"
_COLLECTION_NAME = "workspace"
_collection = None

_parser = None
_parser_failed = False


def _get_parser():
    """Lazy-load tree-sitter Python parser. Returns None if unavailable."""
    global _parser, _parser_failed
    if _parser_failed:
        return None
    if _parser is not None:
        return _parser
    try:
        from tree_sitter import Parser
        from tree_sitter_python import language
        _parser = Parser(language())
    except Exception as e:
        logger.debug("tree-sitter unavailable for workspace_index: %s", e)
        _parser_failed = True
    return _parser


def extract_code_architecture(source: str, file_path: str = "") -> dict[str, Any]:
    """
    Extract functions, classes, imports, and call graph from Python source.
    Returns {functions, classes, imports, calls}. Empty when tree-sitter unavailable.
    """
    parser = _get_parser()
    if parser is None or not (source or "").strip():
        return {"functions": [], "classes": [], "imports": [], "calls": []}

    try:
        tree = parser.parse(source.encode("utf-8"))
        root = tree.root_node
        functions: list[dict] = []
        classes: list[dict] = []
        imports: list[dict] = []
        calls: list[dict] = []  # {caller, callee}

        def _text(node) -> str:
            return source[node.start_byte : node.end_byte].strip()

        def _walk(node, current_class: str = "", current_func: str = ""):
            if node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                name = _text(name_node) if name_node else ""
                if name and not name.startswith("_"):
                    functions.append({
                        "name": name,
                        "class": current_class or None,
                        "line": node.start_point[0] + 1,
                    })
                for c in node.children:
                    _walk(c, current_class, name)
                return
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                name = _text(name_node) if name_node else ""
                if name:
                    classes.append({"name": name, "line": node.start_point[0] + 1})
                for c in node.children:
                    _walk(c, name, "")
                return
            if node.type in ("import_statement", "import_from_statement"):
                imports.append({"raw": _text(node)[:120], "line": node.start_point[0] + 1})
            if node.type == "call":
                # caller is current_func or current_class
                callee_node = node.child_by_field_name("function")
                callee = _text(callee_node) if callee_node else ""
                if callee and "." not in callee:  # simple name
                    calls.append({
                        "caller": current_func or current_class or "<module>",
                        "callee": callee,
                    })
            for c in node.children:
                _walk(c, current_class, current_func)

        _walk(root)
        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "calls": calls,
            "file": file_path,
        }
    except Exception as e:
        logger.debug("extract_code_architecture failed: %s", e)
        return {"functions": [], "classes": [], "imports": [], "calls": []}


def get_architecture_summary(workspace_root: str | Path) -> str:
    """
    Build a text summary of repo architecture from .py files.
    Uses tree-sitter when available; fallback to empty string.
    """
    root = Path(workspace_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return ""
    parts: list[str] = []
    for f in root.rglob("*.py"):
        if ".git" in str(f) or "__pycache__" in str(f) or "node_modules" in str(f):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        arch = extract_code_architecture(text, str(f.relative_to(root)))
        if not arch.get("functions") and not arch.get("classes"):
            continue
        rel = str(f.relative_to(root)).replace("\\", "/")
        lines = [f"  {rel}:"]
        for c in arch.get("classes", [])[:5]:
            lines.append(f"    class {c['name']}")
        for fn in arch.get("functions", [])[:8]:
            ctx = f" ({fn['class']})" if fn.get("class") else ""
            lines.append(f"    def {fn['name']}{ctx}")
        parts.append("\n".join(lines))
    return "\n".join(parts[:20]) if parts else ""


def _get_collection():
    global _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(WORKSPACE_INDEX_PATH))
        _collection = client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        logger.warning("workspace_index chroma unavailable: %s", e)
    return _collection


def index_workspace(workspace_root: str | Path, extensions: tuple[str, ...] = (".py", ".md", ".txt", ".json")) -> dict[str, Any]:
    """
    Index workspace files. Chunks by file, embeds, stores in Chroma.
    Returns {indexed: int, skipped: int, errors: list}.
    """
    root = Path(workspace_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {"indexed": 0, "skipped": 0, "errors": [f"Invalid path: {workspace_root}"]}
    coll = _get_collection()
    if coll is None:
        return {"indexed": 0, "skipped": 0, "errors": ["ChromaDB unavailable"]}
    try:
        from layla.memory.vector_store import embed_batch
    except ImportError:
        return {"indexed": 0, "skipped": 0, "errors": ["vector_store unavailable"]}
    indexed = 0
    skipped = 0
    errors: list[str] = []
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    for ext in extensions:
        for f in root.rglob(f"*{ext}"):
            if ".git" in str(f) or "__pycache__" in str(f) or "node_modules" in str(f):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                errors.append(f"{f}: {e}")
                skipped += 1
                continue
            if len(text.strip()) < 30:
                skipped += 1
                continue
            rel = str(f.relative_to(root)).replace("\\", "/")
            for i in range(0, len(text), 600):
                chunk = text[i : i + 600].strip()
                if len(chunk) < 20:
                    continue
                cid = hashlib.sha1(f"{rel}:{i}".encode()).hexdigest()[:16]
                ids.append(cid)
                docs.append(chunk)
                metas.append({"source": rel, "chunk_index": i // 600})
                indexed += 1
    if not docs:
        return {"indexed": 0, "skipped": skipped, "errors": errors}
    try:
        embs = embed_batch(docs)
        coll.upsert(ids=ids, embeddings=[e.tolist() for e in embs], documents=docs, metadatas=metas)
    except Exception as e:
        errors.append(str(e))
    return {"indexed": indexed, "skipped": skipped, "errors": errors}


def search_workspace(query: str, workspace_root: str | Path = "", k: int = 5) -> list[dict]:
    """Semantic search over indexed workspace. Returns list of {text, source}."""
    coll = _get_collection()
    if coll is None:
        return []
    try:
        from layla.memory.vector_store import embed
        qvec = embed(query)
        res = coll.query(
            query_embeddings=[qvec.tolist()],
            n_results=min(k, coll.count()),
            include=["documents", "metadatas"],
        )
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        out = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            out.append({"text": doc or "", "source": meta.get("source", "")})
        return out
    except Exception:
        return []
