"""The embedder loads from the local HuggingFace cache without asking huggingface.co.

from_pretrained(<repo id>) checks the Hub for the latest revision on every start, even when the files are
cached: one outbound request per launch from an app that promises no cloud, and a stall when offline.
"""
import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

VS = AGENT_DIR / "layla" / "memory" / "vector_store.py"


def test_cached_model_resolves_to_local_snapshot_without_network(monkeypatch):
    import huggingface_hub

    from layla.memory import vector_store as vs

    seen = {}

    def fake(repo_id, **kw):
        seen.update(kw, repo_id=repo_id)
        return "C:/cache/snapshots/abc"

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake)
    assert vs._local_model_path("org/model") == "C:/cache/snapshots/abc"
    assert seen == {"repo_id": "org/model", "local_files_only": True}


def test_uncached_model_falls_back_to_repo_id_for_first_download(monkeypatch):
    import huggingface_hub

    from layla.memory import vector_store as vs

    def missing(repo_id, **kw):
        raise FileNotFoundError("not in cache")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", missing)
    assert vs._local_model_path("org/model") == "org/model"


def test_both_embedder_loaders_go_through_the_local_path():
    tree = ast.parse(VS.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_get_embedder")
    loaders = {}
    for call in ast.walk(fn):
        if not isinstance(call, ast.Call) or not call.args:
            continue
        name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
        if name in ("from_pretrained", "SentenceTransformer"):
            a = call.args[0]
            loaders.setdefault(name, []).append(
                isinstance(a, ast.Call) and getattr(a.func, "id", None) == "_local_model_path")
    assert set(loaders) == {"from_pretrained", "SentenceTransformer"}, f"PROBE BROKEN: found {loaders}"
    assert loaders["from_pretrained"][0] and loaders["SentenceTransformer"][0], loaders
