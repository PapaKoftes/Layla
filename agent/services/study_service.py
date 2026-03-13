"""Study plan autonomous step: one Nyx-style research run per plan."""
import logging
from agent_loop import autonomous_run

logger = logging.getLogger("layla")


def run_autonomous_study_for_plan(plan: dict) -> str | None:
    """Run one Nyx-style research step for a study plan; return summary text or None.
    Saves extracted learnings to the DB after every successful study run."""
    from layla.memory.db import update_study_progress, save_learning
    topic = (plan.get("topic") or "").strip()
    plan_id = plan.get("id")
    if not topic or not plan_id:
        return None

    # Try to fetch reference material first
    ref_text = ""
    try:
        import urllib.parse
        from layla.tools.registry import TOOLS
        fetch_fn = TOOLS.get("fetch_article", {}).get("fn") or TOOLS.get("fetch_url", {}).get("fn")
        if fetch_fn:
            slug = urllib.parse.quote(topic.strip().replace(" ", "_"))
            r = fetch_fn(url=f"https://en.wikipedia.org/wiki/{slug}")
            if r.get("ok") and r.get("text"):
                ref_text = (r.get("text") or "")[:3000]
    except Exception:
        pass

    goal = f"Study topic: {topic}\n\nProvide 3-5 key facts, concepts, or insights about this topic. Be specific and educational. Format as a numbered list."
    if ref_text:
        goal += f"\n\nReference material:\n{ref_text[:2500]}"

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

    summary = summary.strip()

    # Persist study progress
    try:
        update_study_progress(plan_id, summary)
    except Exception:
        pass

    # Extract and save learnings from the study output
    try:
        import re as _re
        lines = summary.split("\n")
        saved = 0
        for line in lines:
            line = line.strip()
            # Numbered list items are prime learning candidates
            m = _re.match(r'^[\d]+[\.\)]\s+(.{20,200})$', line)
            if m:
                fact = m.group(1).strip()
                if not fact.endswith(":"):  # skip section headers
                    save_learning(content=f"[{topic}] {fact}", kind="fact")
                    saved += 1
            if saved >= 3:
                break
        # If no numbered items found, save the whole summary as one fact
        if saved == 0 and len(summary) >= 60:
            save_learning(content=f"[{topic}] {summary[:300]}", kind="fact")
            saved = 1
        logger.info("study: saved %d learnings for topic=%s", saved, topic)
    except Exception as e:
        logger.debug("study: learning save failed: %s", e)

    return summary
