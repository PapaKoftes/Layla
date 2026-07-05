"""Cross-project reasoning router (BL-232)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["intelligence"])


@router.get("/intelligence/cross-project/graph")
def cross_project_graph(min_shared: int = 3):
    """Clusters of related projects (shared tooling/domain), by shared-term overlap."""
    from services.memory.cross_project import project_clusters
    return project_clusters(min_shared=min_shared)


@router.get("/intelligence/cross-project/related")
def cross_project_related(project: str, limit: int = 5, min_shared: int = 2):
    """The projects most related to `project` (name or workspace_root) + what they share."""
    from services.memory.cross_project import related_projects
    return related_projects(project, limit=limit, min_shared=min_shared)
