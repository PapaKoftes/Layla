"""
Research intelligence layer: confidence, consistency, risk, tradeoffs, patterns,
actions, agenda, journal, summary. Runs AFTER synthesis when mission_depth == "full".
All stages are read-only over .research_brain; no sandbox changes.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from research_utils import normalize_stage_text, _extract_json_block

AGENT_DIR = Path(__file__).resolve().parent
RESEARCH_BRAIN = AGENT_DIR / ".research_brain"

INTELLIGENCE_ORDER = (
    "confidence", "consistency", "risk", "tradeoffs", "patterns",
    "actions", "agenda", "journal", "summary",
)

# Stage -> (subdir, filename)
INTELLIGENCE_OUTPUTS = {
    "confidence": ("confidence", "confidence.json"),
    "consistency": ("consistency", "consistency.md"),
    "risk": ("risk", "risk_model.md"),
    "tradeoffs": ("tradeoffs", "tradeoffs.md"),
    "patterns": ("patterns", "patterns.md"),
    "actions": ("actions", "action_queue.md"),
    "agenda": ("agenda", "research_agenda.md"),
    "journal": ("journal", "mission_journal.md"),
    "summary": ("summaries", "24h_summary.md"),
}


def _ensure_brain_dirs() -> None:
    from research_stages import ensure_research_brain_dirs
    ensure_research_brain_dirs()


def _mark_stage_completed(stage_name: str) -> None:
    from research_stages import load_mission_state, save_mission_state
    mission = load_mission_state()
    mission["completed"] = list(mission.get("completed") or [])
    if stage_name not in mission["completed"]:
        mission["completed"].append(stage_name)
    mission["stage"] = stage_name
    save_mission_state(mission)


def load_intelligence_context(for_stage: str) -> str:
    """
    Load all previous stage outputs: base 5 (maps → strategic) then intelligence
    stages up to (not including) for_stage. Use for prompt continuity.
    """
    _ensure_brain_dirs()
    parts = []
    # Base stages
    base_files = [
        ("maps", "system_map.json"),
        ("investigations", "notes.md"),
        ("verifications", "verified.md"),
        ("distilled", "knowledge.md"),
        ("strategic", "model.md"),
    ]
    for sub, name in base_files:
        p = RESEARCH_BRAIN / sub / name
        if p.exists():
            try:
                parts.append(f"## {sub.title()} ({name})\n{p.read_text(encoding='utf-8')[:12000]}")
            except Exception:
                pass
    try:
        idx = INTELLIGENCE_ORDER.index(for_stage)
    except ValueError:
        return "\n\n".join(parts) if parts else ""
    for i in range(idx):
        stage = INTELLIGENCE_ORDER[i]
        sub, name = INTELLIGENCE_OUTPUTS[stage]
        p = RESEARCH_BRAIN / sub / name
        if p.exists():
            try:
                parts.append(f"## {stage.title()} ({name})\n{p.read_text(encoding='utf-8')[:8000]}")
            except Exception:
                pass
    return "\n\n".join(parts) if parts else ""


# _extract_json_block and normalize_stage_text imported from research_utils


async def _run_stage(
    goal: str,
    lab_workspace: str,
    context: str,
    conversation_history: list,
) -> tuple[str, dict, str]:
    """Run stage via autonomous_run. Stage goal passed as goal only; never executed as Python."""
    from agent_loop import autonomous_run
    goal = normalize_stage_text(goal)
    result = await asyncio.to_thread(
        autonomous_run,
        goal,
        context=context,
        workspace_root=lab_workspace,
        allow_write=False,
        allow_run=False,
        conversation_history=conversation_history or [],
        aspect_id="",
        show_thinking=False,
        stream_final=False,
        research_mode=True,
    )
    steps = result.get("steps") or []
    final = steps[-1].get("result", "") if steps else ""
    text = final if isinstance(final, str) else json.dumps(final, indent=2)
    text = text or ""
    data = _extract_json_block(text) if text else None
    status = "no_progress" if len(text) < 500 else "ok"
    return text, (data if isinstance(data, dict) else {}), status


async def run_confidence_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    previous_stage_context: str = "",
    stage_name: str = "confidence",
) -> tuple[str, dict, str]:
    """
    Score findings as low/medium/high based on verified evidence, repeated signals, speculative inference.
    Output structured JSON. Persist to confidence/confidence.json.
    """
    _ensure_brain_dirs()
    continuity = load_intelligence_context("confidence") or previous_stage_context
    goal = (
        "Research intelligence - Confidence. "
        "Score all findings from previous stages as low, medium, or high confidence. "
        "Criteria: verified evidence = high; repeated signals = medium; speculative inference = low. "
        "Output a single JSON object with keys like findings, scores, criteria. "
        "Do not ask the user questions. You may write only inside .research_lab."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity[:15000]
    md, data, status = await _run_stage(goal, lab_workspace, context, conversation_history or [])
    sub, name = INTELLIGENCE_OUTPUTS["confidence"]
    out = RESEARCH_BRAIN / sub / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data if data else {"raw": md[:5000]}, indent=2), encoding="utf-8")
    _mark_stage_completed(stage_name)
    return md, data, status


async def run_consistency_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    previous_stage_context: str = "",
    stage_name: str = "consistency",
) -> tuple[str, dict, str]:
    """
    Detect contradictions across maps, investigations, verifications, distilled knowledge.
    Output: confirmed truths, open questions, conflicts. Persist to consistency/consistency.md.
    """
    _ensure_brain_dirs()
    continuity = load_intelligence_context("consistency") or previous_stage_context
    goal = (
        "Research intelligence - Consistency. "
        "Compare maps, investigations, verifications, and distilled knowledge. "
        "List: confirmed truths, open questions, conflicts. "
        "Output clear markdown. Do not ask the user questions. You may write only inside .research_lab."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity[:15000]
    md, data, status = await _run_stage(goal, lab_workspace, context, conversation_history or [])
    sub, name = INTELLIGENCE_OUTPUTS["consistency"]
    out = RESEARCH_BRAIN / sub / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md or "(no output)", encoding="utf-8")
    _mark_stage_completed(stage_name)
    return md, data, status


async def run_risk_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    previous_stage_context: str = "",
    stage_name: str = "risk",
) -> tuple[str, dict, str]:
    """
    Detect fragility, tight coupling, maintenance burden, operational risk, hidden complexity.
    Persist to risk/risk_model.md.
    """
    _ensure_brain_dirs()
    continuity = load_intelligence_context("risk") or previous_stage_context
    goal = (
        "Research intelligence - Risk. "
        "Identify: fragility, tight coupling, maintenance burden, operational risk, hidden complexity. "
        "Output a risk model in markdown. Do not ask the user questions. You may write only inside .research_lab."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity[:15000]
    md, data, status = await _run_stage(goal, lab_workspace, context, conversation_history or [])
    sub, name = INTELLIGENCE_OUTPUTS["risk"]
    out = RESEARCH_BRAIN / sub / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md or "(no output)", encoding="utf-8")
    _mark_stage_completed(stage_name)
    return md, data, status


async def run_tradeoff_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    previous_stage_context: str = "",
    stage_name: str = "tradeoffs",
) -> tuple[str, dict, str]:
    """
    Structure all upgrades as: benefit, cost, risk, reversibility.
    Persist to tradeoffs/tradeoffs.md.
    """
    _ensure_brain_dirs()
    continuity = load_intelligence_context("tradeoffs") or previous_stage_context
    goal = (
        "Research intelligence - Tradeoffs. "
        "For each upgrade or change, output: benefit, cost, risk, reversibility. "
        "Use markdown. Do not ask the user questions. You may write only inside .research_lab."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity[:15000]
    md, data, status = await _run_stage(goal, lab_workspace, context, conversation_history or [])
    sub, name = INTELLIGENCE_OUTPUTS["tradeoffs"]
    out = RESEARCH_BRAIN / sub / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md or "(no output)", encoding="utf-8")
    _mark_stage_completed(stage_name)
    return md, data, status


async def run_pattern_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    previous_stage_context: str = "",
    stage_name: str = "patterns",
) -> tuple[str, dict, str]:
    """
    Identify recurring weaknesses, architecture smells, reusable strategies.
    Persist to patterns/patterns.md.
    """
    _ensure_brain_dirs()
    continuity = load_intelligence_context("patterns") or previous_stage_context
    goal = (
        "Research intelligence - Patterns. "
        "Extract: recurring weaknesses, architecture smells, reusable strategies. "
        "Output markdown. Do not ask the user questions. You may write only inside .research_lab."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity[:15000]
    md, data, status = await _run_stage(goal, lab_workspace, context, conversation_history or [])
    sub, name = INTELLIGENCE_OUTPUTS["patterns"]
    out = RESEARCH_BRAIN / sub / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md or "(no output)", encoding="utf-8")
    _mark_stage_completed(stage_name)
    return md, data, status


async def run_action_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    previous_stage_context: str = "",
    stage_name: str = "actions",
) -> tuple[str, dict, str]:
    """
    Propose top 3 high-impact next steps. Each: impact, effort, risk, confidence.
    Persist to actions/action_queue.md.
    """
    _ensure_brain_dirs()
    continuity = load_intelligence_context("actions") or previous_stage_context
    goal = (
        "Research intelligence - Actions. "
        "Propose exactly 3 high-impact next steps. For each give: impact, effort, risk, confidence. "
        "Output markdown. Do not ask the user questions. You may write only inside .research_lab."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity[:15000]
    md, data, status = await _run_stage(goal, lab_workspace, context, conversation_history or [])
    sub, name = INTELLIGENCE_OUTPUTS["actions"]
    out = RESEARCH_BRAIN / sub / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md or "(no output)", encoding="utf-8")
    _mark_stage_completed(stage_name)
    return md, data, status


async def run_agenda_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    previous_stage_context: str = "",
    stage_name: str = "agenda",
) -> tuple[str, dict, str]:
    """
    Generate next research direction from uncertainty, leverage, risk.
    Persist to agenda/research_agenda.md.
    """
    _ensure_brain_dirs()
    continuity = load_intelligence_context("agenda") or previous_stage_context
    goal = (
        "Research intelligence - Agenda. "
        "Define next research direction using: uncertainty, leverage, risk. "
        "Output markdown. Do not ask the user questions. You may write only inside .research_lab."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity[:15000]
    md, data, status = await _run_stage(goal, lab_workspace, context, conversation_history or [])
    sub, name = INTELLIGENCE_OUTPUTS["agenda"]
    out = RESEARCH_BRAIN / sub / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md or "(no output)", encoding="utf-8")
    _mark_stage_completed(stage_name)
    return md, data, status


async def run_journal_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    previous_stage_context: str = "",
    stage_name: str = "journal",
) -> tuple[str, dict, str]:
    """
    Track: what was explored, what changed, what failed, what evolved.
    Persist to journal/mission_journal.md.
    """
    _ensure_brain_dirs()
    continuity = load_intelligence_context("journal") or previous_stage_context
    goal = (
        "Research intelligence - Journal. "
        "Record: what was explored, what changed, what failed, what evolved. "
        "Output markdown. Do not ask the user questions. You may write only inside .research_lab."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity[:15000]
    md, data, status = await _run_stage(goal, lab_workspace, context, conversation_history or [])
    sub, name = INTELLIGENCE_OUTPUTS["journal"]
    out = RESEARCH_BRAIN / sub / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md or "(no output)", encoding="utf-8")
    _mark_stage_completed(stage_name)
    return md, data, status


async def run_summary_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    previous_stage_context: str = "",
    stage_name: str = "summary",
) -> tuple[str, dict, str]:
    """
    Final synthesis: what was learned, what is verified, what is uncertain, recommended next actions.
    Persist to summaries/24h_summary.md.
    """
    _ensure_brain_dirs()
    continuity = load_intelligence_context("summary") or previous_stage_context
    goal = (
        "Research intelligence - Summary. "
        "Produce final synthesis: what was learned, what is verified, what is uncertain, recommended next actions. "
        "Output markdown. Do not ask the user questions. You may write only inside .research_lab."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity[:15000]
    md, data, status = await _run_stage(goal, lab_workspace, context, conversation_history or [])
    sub, name = INTELLIGENCE_OUTPUTS["summary"]
    out = RESEARCH_BRAIN / sub / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md or "(no output)", encoding="utf-8")
    _mark_stage_completed(stage_name)
    return md, data, status


INTELLIGENCE_RUNNERS = {
    "confidence": run_confidence_stage,
    "consistency": run_consistency_stage,
    "risk": run_risk_stage,
    "tradeoffs": run_tradeoff_stage,
    "patterns": run_pattern_stage,
    "actions": run_action_stage,
    "agenda": run_agenda_stage,
    "journal": run_journal_stage,
    "summary": run_summary_stage,
}


def get_promotable_research_learnings() -> list[str]:
    """
    Memory stabilization: only verified truths, patterns, and strategic insights
    may be promoted to learnings. Do NOT store speculative output.
    Returns list of content strings safe to save as learnings.
    """
    _ensure_brain_dirs()
    out = []
    # Verified: verifications + consistency (confirmed truths)
    for sub, name in [("verifications", "verified.md"), ("consistency", "consistency.md")]:
        p = RESEARCH_BRAIN / sub / name
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8")
                if "confirmed" in text.lower() or "verified" in text.lower() or sub == "verifications":
                    out.append(text[:3000].strip())
            except Exception:
                pass
    # Patterns
    p = RESEARCH_BRAIN / "patterns" / "patterns.md"
    if p.exists():
        try:
            out.append(p.read_text(encoding="utf-8")[:3000].strip())
        except Exception:
            pass
    # Strategic insights
    p = RESEARCH_BRAIN / "strategic" / "model.md"
    if p.exists():
        try:
            out.append(p.read_text(encoding="utf-8")[:3000].strip())
        except Exception:
            pass
    return out
