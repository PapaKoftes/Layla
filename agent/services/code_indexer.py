"""
Code indexing orchestration. Delegates storage and embeddings to workspace_index
(single Chroma collection `workspace` — no duplicate code stores).

Use index_repo() from automation/cron; retrieve_code_context() lives on workspace_index.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def index_repo(workspace_root: str | Path, extensions: tuple[str, ...] = (".py", ".md", ".txt", ".json")) -> dict[str, Any]:
    """Walk workspace_root and upsert chunks into the workspace Chroma collection."""
    from services.workspace_index import index_workspace

    return index_workspace(workspace_root, extensions=extensions)


def retrieve_code_context(query: str, workspace_root: str | Path = "", k: int = 5) -> list[dict]:
    """Public alias — implemented in workspace_index."""
    from services.workspace_index import retrieve_code_context as _rc

    return _rc(query, workspace_root=workspace_root, k=k)
