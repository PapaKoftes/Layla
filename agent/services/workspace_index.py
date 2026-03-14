"""
Workspace index. Index local projects using embeddings for semantic search.
Code intelligence: tree-sitter extracts functions, classes, imports, call graph.
Workspace dependency graph: files, functions, classes, imports; edges: calls, imports, inherits.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

# In-memory workspace dependency graph: {node_id: {type, label, file, ...}}, edges: [(src, tgt, edge_type)]
_workspace_graph: dict[str, dict[str, Any]] = {}
_workspace_graph_edges: list[tuple[str, str, str]] = []
_workspace_graph_root: Path | None = None

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
                bases: list[str] = []
                superclass = node.child_by_field_name("superclasses")
                if superclass:
                    raw_bases = _text(superclass).replace("(", "").replace(")", "").split(",")
                    bases = [b.strip().split(".")[-1] for b in raw_bases if b.strip()]
                if name:
                    classes.append({"name": name, "line": node.start_point[0] + 1, "bases": bases})
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


def build_workspace_graph(workspace_root: str | Path) -> dict[str, Any]:
    """
    Build semantic dependency graph for a repository.
    Nodes: files, functions, classes, imports.
    Edges: calls, imports, inherits.
    """
    global _workspace_graph, _workspace_graph_edges, _workspace_graph_root
    root = Path(workspace_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {"nodes": 0, "edges": 0}
    _workspace_graph = {}
    _workspace_graph_edges = []
    _workspace_graph_root = root

    for f in root.rglob("*.py"):
        if ".git" in str(f) or "__pycache__" in str(f) or "node_modules" in str(f):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = str(f.relative_to(root)).replace("\\", "/")
        arch = extract_code_architecture(text, rel)
        file_nid = f"file:{rel}"
        _workspace_graph[file_nid] = {"type": "file", "label": rel, "file": rel}
        for c in arch.get("classes", []):
            nid = f"{rel}::class:{c['name']}"
            _workspace_graph[nid] = {"type": "class", "label": c["name"], "file": rel, "line": c.get("line")}
            _workspace_graph_edges.append((file_nid, nid, "contains"))
            for base in c.get("bases", []):
                _workspace_graph_edges.append((nid, f"class:{base}", "inherits"))
                # implements: Python uses inheritance for interfaces; same edge type for reasoning
                if base and (base.endswith("Base") or "Interface" in base or "Protocol" in base or "ABC" in base):
                    _workspace_graph_edges.append((nid, f"class:{base}", "implements"))

        for fn in arch.get("functions", []):
            nid = f"{rel}::fn:{fn['name']}"
            ctx = fn.get("class") or "<module>"
            _workspace_graph[nid] = {"type": "function", "label": fn["name"], "file": rel, "class": ctx}
            _workspace_graph_edges.append((file_nid, nid, "contains"))
        for imp in arch.get("imports", []):
            raw = (imp.get("raw") or "")[:80]
            nid = f"{rel}::import:{hashlib.sha1(raw.encode()).hexdigest()[:8]}"
            _workspace_graph[nid] = {"type": "import", "label": raw, "file": rel}
            _workspace_graph_edges.append((file_nid, nid, "contains"))
            # depends_on: extract module from "from X import" or "import X"
            if " from " in raw.lower():
                mod = raw.lower().split(" from ")[-1].split(" import ")[0].strip().split(" as ")[0]
            elif " import " in raw.lower():
                mod = raw.lower().split(" import ")[0].replace("import ", "").strip().split(",")[0].split(" as ")[0]
            else:
                mod = ""
            if mod and "." in mod:
                mod = mod.split(".")[0]
            if mod and len(mod) > 1:
                _workspace_graph_edges.append((file_nid, f"module:{mod}", "depends_on"))
        for call in arch.get("calls", []):
            caller = call.get("caller") or "<module>"
            callee = call.get("callee") or ""
            if caller and callee:
                caller_nid = f"{rel}::fn:{caller}" if caller != "<module>" else file_nid
                _workspace_graph_edges.append((caller_nid, f"callee:{callee}", "calls"))

    return {"nodes": len(_workspace_graph), "edges": len(_workspace_graph_edges)}


def get_workspace_dependency_context(query: str, workspace_root: str | Path = "", max_chars: int = 800) -> str:
    """
    Return dependency context relevant to query for coding tasks.
    Uses workspace graph + architecture summary. Injected into _build_system_head when coding detected.
    """
    root = Path(workspace_root).expanduser().resolve() if workspace_root else _workspace_graph_root
    if not root or not root.exists():
        return ""
    if not _workspace_graph:
        try:
            build_workspace_graph(root)
        except Exception:
            pass
    if not _workspace_graph:
        return get_architecture_summary(root)[:max_chars]
    q_lower = (query or "").lower()
    relevant: list[str] = []
    seen: set[str] = set()
    for nid, data in _workspace_graph.items():
        label = (data.get("label") or "").lower()
        if any(w in label for w in q_lower.split() if len(w) > 2):
            file_path = data.get("file", "")
            if file_path and file_path not in seen:
                seen.add(file_path)
                node_type = data.get("type", "")
                if node_type == "class":
                    relevant.append(f"  class {data.get('label')} in {file_path}")
                elif node_type == "function":
                    relevant.append(f"  def {data.get('label')} in {file_path}")
    if not relevant:
        return get_architecture_summary(root)[:max_chars]
    header = "Workspace dependency context (relevant to query):\n"
    return header + "\n".join(relevant[:15])[:max_chars]


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
