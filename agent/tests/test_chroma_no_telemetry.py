"""No outbound telemetry from the vector store (VALUES.md: anti-surveillance).

chromadb's default Settings enable anonymized PostHog telemetry on every client start / collection op. It
only failed by accident (posthog API drift logged "capture() takes 1 positional argument"), so every client
must be built by vector_store.chroma_client(), which turns it off.
"""
import ast
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _client_constructions():
    hits = []
    for f in AGENT_DIR.rglob("*.py"):
        rel = f.relative_to(AGENT_DIR).as_posix()
        if rel.startswith(("tests/", "scripts/")) or "__pycache__" in rel or "/.venv" in f"/{rel}":
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            continue
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and "chromadb" in ast.unparse(n.func)
                    and getattr(n.func, "attr", "") in ("PersistentClient", "HttpClient", "EphemeralClient", "Client")):
                continue
            a, owner = n, "<module>"
            while a in parents:
                a = parents[a]
                if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner = a.name
                    break
            hits.append((rel, owner, n.lineno))
    return hits


def test_every_chroma_client_goes_through_the_helper():
    hits = _client_constructions()
    assert hits, "PROBE BROKEN: found no chromadb client construction at all"
    stray = {(r, o) for r, o, _ in hits} - {("layla/memory/vector_store.py", "chroma_client")}
    assert not stray, f"build chroma clients with vector_store.chroma_client() (telemetry off): {sorted(stray)}"


def test_helper_disables_telemetry(monkeypatch, tmp_path):
    chromadb = pytest.importorskip("chromadb")
    from layla.memory import vector_store

    seen = {}

    def _fake(path=None, settings=None, **kw):
        seen["path"], seen["settings"] = path, settings
        return object()

    monkeypatch.setattr(chromadb, "PersistentClient", _fake)
    vector_store.chroma_client(tmp_path)
    assert seen["path"] == str(tmp_path)
    assert seen["settings"] is not None and seen["settings"].anonymized_telemetry is False
