"""Temporal memory timeline router (BL-234)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/timeline", tags=["timeline"])


@router.get("")
def timeline(
    since: str = "",
    until: str = "",
    event_type: str = "",
    project_id: str = "",
    min_importance: float = 0.0,
    limit: int = 50,
    offset: int = 0,
):
    from services.memory.timeline import query_timeline
    return query_timeline(
        since=since, until=until, event_type=event_type, project_id=project_id,
        min_importance=min_importance, limit=limit, offset=offset,
    )


@router.get("/days")
def timeline_days(limit_days: int = 60):
    from services.memory.timeline import timeline_days as _days
    return _days(limit_days=limit_days)


@router.get("/episodes")
def episodes(limit: int = 20):
    from services.memory.timeline import list_episodes
    return list_episodes(limit=limit)


@router.get("/episodes/{episode_id}")
def episode(episode_id: str):
    from services.memory.timeline import reconstruct_episode
    return reconstruct_episode(episode_id)
