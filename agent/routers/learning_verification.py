"""Memory/learning verification router (BL-192)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/memory/verification", tags=["memory"])


@router.post("/run")
def run(sample: int = 200, prune: bool = True, prune_threshold: float = 0.08):
    from services.memory.learning_verification import run_verification_pass
    return run_verification_pass(sample=sample, prune=prune, prune_threshold=prune_threshold)


@router.get("/contradictions")
def contradictions(sample: int = 200):
    from layla.memory.learnings import get_recent_learnings
    from services.memory.learning_verification import find_contradictions
    return {"contradictions": find_contradictions(get_recent_learnings(n=sample) or [])}
