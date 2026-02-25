"""Study plan autonomous step: one Nyx-style research run per plan."""
from agent_loop import autonomous_run


def run_autonomous_study_for_plan(plan: dict) -> str | None:
    """Run one Nyx-style research step for a study plan; return summary text or None."""
    from jinx.memory.db import update_study_progress
    topic = (plan.get("topic") or "").strip()
    plan_id = plan.get("id")
    if not topic or not plan_id:
        return None
    ref_text = ""
    try:
        from jinx.tools.web import fetch_url
        slug = "_".join(topic.replace(",", " ").split()[:2])
        if slug:
            url = f"https://en.wikipedia.org/wiki/{slug}"
            r = fetch_url(url, store=False)
            if r.get("ok") and r.get("text"):
                ref_text = (r.get("text") or "")[:2000]
    except Exception:
        pass
    goal = (
        f"Summarize the following in 2-3 key points for study progress (topic: {topic}). Be concise."
    )
    if ref_text:
        goal += f"\n\nReference text:\n{ref_text}"
    else:
        goal += f"\n\nUse your knowledge of '{topic}' to write 2-3 sentences."
    result = autonomous_run(
        goal, context="", workspace_root="", allow_write=False, allow_run=False,
        conversation_history=[], aspect_id="nyx", show_thinking=False,
    )
    if not result.get("steps"):
        return None
    summary = result["steps"][-1].get("result")
    if isinstance(summary, dict):
        summary = summary.get("content") or summary.get("output") or str(summary)
    if not isinstance(summary, str) or not summary.strip():
        return None
    try:
        update_study_progress(plan_id, summary.strip())
    except Exception:
        pass
    return summary.strip()
