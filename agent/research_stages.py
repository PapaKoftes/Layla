"""
Multi-stage research pipeline: Mapping → Investigation → Verification → Distillation → Synthesis.
All stages run inside the existing research_mission sandbox (.research_lab only).
No changes to approval, refusal, or tool registry.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
RESEARCH_BRAIN = AGENT_DIR / ".research_brain"

STAGE_ORDER = ("mapping", "investigation", "verification", "contradiction_check", "distillation", "synthesis")
SUBDIRS = (
    "maps", "investigations", "verifications", "contradictions", "distilled", "strategic",
    "confidence", "consistency", "risk", "tradeoffs", "patterns",
    "actions", "agenda", "journal", "summaries",
)
STAGE_TO_SUBDIR = dict(zip(STAGE_ORDER, SUBDIRS[:6]))


def normalize_stage_text(text: str) -> str:
    """Replace Unicode em-dash with ASCII hyphen so stage goals are never invalid if mistaken for code."""
    if not text or not isinstance(text, str):
        return text or ""
    return text.replace("\u2014", "-").replace("—", "-")


def ensure_research_brain_dirs() -> None:
    """Create .research_brain and all stage subdirs (base + intelligence)."""
    RESEARCH_BRAIN.mkdir(parents=True, exist_ok=True)
    for sub in SUBDIRS:
        (RESEARCH_BRAIN / sub).mkdir(parents=True, exist_ok=True)


def load_mission_state() -> dict:
    """Load mission state from .research_brain/mission_state.json for resume and status."""
    path = RESEARCH_BRAIN / "mission_state.json"
    if not path.exists():
        return {"stage": None, "progress": {}, "completed": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"stage": None, "progress": {}, "completed": []}


def save_mission_state(state: dict) -> None:
    """Persist mission state to .research_brain/mission_state.json."""
    ensure_research_brain_dirs()
    path = RESEARCH_BRAIN / "mission_state.json"
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def is_useful_output(text: str) -> bool:
    """Usefulness gate: True if output contains actionable insight signals."""
    if not (text or "").strip():
        return False
    signals = [
        "recommend", "should", "risk", "improve", "replace", "refactor",
        "adopt", "avoid", "opportunity", "tradeoff",
    ]
    return any(s in (text or "").lower() for s in signals)


def load_research_context(for_stage: str) -> str:
    """
    Load previous stage outputs to inject into the prompt.
    for_stage: one of mapping, investigation, verification, distillation, synthesis.
    Returns concatenated content from all completed stages before this one.
    """
    ensure_research_brain_dirs()
    try:
        idx = STAGE_ORDER.index(for_stage)
    except ValueError:
        return ""
    parts = []
    # Mapping output: maps/system_map.json
    if idx > 0:
        map_path = RESEARCH_BRAIN / "maps" / "system_map.json"
        if map_path.exists():
            try:
                parts.append("## System map (previous stage)\n" + map_path.read_text(encoding="utf-8"))
            except Exception:
                pass
    if idx > 1:
        inv_path = RESEARCH_BRAIN / "investigations" / "notes.md"
        if inv_path.exists():
            try:
                parts.append("## Investigation notes (previous stage)\n" + inv_path.read_text(encoding="utf-8"))
            except Exception:
                pass
    if idx > 2:
        ver_path = RESEARCH_BRAIN / "verifications" / "verified.md"
        if ver_path.exists():
            try:
                parts.append("## Verification (previous stage)\n" + ver_path.read_text(encoding="utf-8"))
            except Exception:
                pass
    if idx > 3:
        contra_path = RESEARCH_BRAIN / "contradictions" / "check.md"
        if contra_path.exists():
            try:
                parts.append("## Contradiction check (previous stage)\n" + contra_path.read_text(encoding="utf-8"))
            except Exception:
                pass
    if idx > 4:
        dist_path = RESEARCH_BRAIN / "distilled" / "knowledge.md"
        if dist_path.exists():
            try:
                parts.append("## Distilled knowledge (previous stage)\n" + dist_path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return "\n\n".join(parts) if parts else ""


def _extract_json_block(text: str) -> dict | None:
    """Try to extract a JSON object from markdown or raw text."""
    if not text:
        return None
    # Code block
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Raw JSON
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


async def _run_stage(
    stage_name: str,
    goal: str,
    lab_workspace: str,
    context: str,
    conversation_history: list,
) -> tuple[str, dict, str]:
    """Run one stage via autonomous_run; returns (markdown_text, json_dict, status). Stage goal is passed as goal only; never executed as Python."""
    from agent_loop import autonomous_run

    goal = normalize_stage_text(goal)
    result = await asyncio.to_thread(
        autonomous_run,
        goal,
        context=context,
        workspace_root=lab_workspace,
        allow_write=True,
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


async def run_mapping_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    stage_name: str = "mapping",
) -> tuple[str, dict, str]:
    """
    Stage 1 — Mapping. Map repo structure, entrypoints, dependencies.
    Writes: .research_brain/maps/system_map.json
    Returns: (markdown_text, json_data, status).
    """
    ensure_research_brain_dirs()
    continuity = load_research_context("mapping")
    goal = (
        "Research mission - Stage 1: Mapping. "
        "Map the repository structure, key entrypoints, and dependencies. "
        "Use read_file, list_dir, grep_code only. "
        "Produce a structured system map. "
        "End with a valid JSON object (e.g. {\"entrypoints\": [], \"modules\": [], \"dependencies\": []}). "
        "You may write notes only inside .research_lab. "
        "Do not ask the user questions; complete the map."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity
    md, data, status = await _run_stage("mapping", goal, lab_workspace, context, conversation_history or [])
    out_path = RESEARCH_BRAIN / "maps" / "system_map.json"
    try:
        out_path.write_text(json.dumps(data if data else {"raw": md}, indent=2), encoding="utf-8")
    except Exception:
        out_path.write_text(json.dumps({"raw": md[:5000]}, indent=2), encoding="utf-8")
    mission = load_mission_state()
    mission["completed"] = list(mission.get("completed") or [])
    if stage_name not in mission["completed"]:
        mission["completed"].append(stage_name)
    mission["stage"] = stage_name
    save_mission_state(mission)
    return md, data, status


async def run_investigation_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    stage_name: str = "investigation",
) -> tuple[str, dict, str]:
    """
    Stage 2 — Investigation. Use source + fetch_url to summarize docs and compare patterns.
    Writes: .research_brain/investigations/notes.md
    Returns: (markdown_text, json_data, status).
    """
    ensure_research_brain_dirs()
    continuity = load_research_context("investigation")
    goal = (
        "Research mission - Stage 2: Investigation. "
        "Use read_file, list_dir, grep_code, fetch_url to investigate. "
        "Summarize external documentation and compare patterns. "
        "Write findings. You may write only inside .research_lab. "
        "Do not ask the user questions; complete the investigation."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity
    md, data, status = await _run_stage("investigation", goal, lab_workspace, context, conversation_history or [])
    out_path = RESEARCH_BRAIN / "investigations" / "notes.md"
    out_path.write_text(md or "(no output)", encoding="utf-8")
    mission = load_mission_state()
    mission["completed"] = list(mission.get("completed") or [])
    if stage_name not in mission["completed"]:
        mission["completed"].append(stage_name)
    mission["stage"] = stage_name
    save_mission_state(mission)
    return md, data, status


async def run_verification_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    stage_name: str = "verification",
) -> tuple[str, dict, str]:
    """
    Stage 3 — Verification. Run small probes in .research_lab only (run_python with cwd in lab). No shell.
    Writes: .research_brain/verifications/verified.md
    Returns: (markdown_text, json_data, status).
    """
    ensure_research_brain_dirs()
    continuity = load_research_context("verification")
    goal = (
        "Research mission - Stage 3: Verification. "
        "Run small read-only or lab-scoped probes using run_python with cwd inside .research_lab only. "
        "Do not use shell. Verify findings from previous stages. "
        "Write verification results. Do not ask the user questions; complete verification."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity
    md, data, status = await _run_stage("verification", goal, lab_workspace, context, conversation_history or [])
    out_path = RESEARCH_BRAIN / "verifications" / "verified.md"
    out_path.write_text(md or "(no output)", encoding="utf-8")
    mission = load_mission_state()
    mission["completed"] = list(mission.get("completed") or [])
    if stage_name not in mission["completed"]:
        mission["completed"].append(stage_name)
    mission["stage"] = stage_name
    save_mission_state(mission)
    return md, data, status


async def run_contradiction_check_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    stage_name: str = "contradiction_check",
) -> tuple[str, dict, str]:
    """
    Stage 3.5 — Contradiction check. Compare key claims, detect conflicts, annotate uncertainty, surface confidence.
    Writes: .research_brain/contradictions/check.md
    """
    ensure_research_brain_dirs()
    continuity = load_research_context("contradiction_check")
    goal = (
        "Research mission - Stage: Contradiction check. "
        "Compare key claims from the system map, investigation, and verification. "
        "Detect conflicts and contradictions. Annotate uncertainty. Surface confidence signals. "
        "Use only read_file to read from .research_brain if needed. "
        "Write a short report: conflicts found, confidence levels, and any unresolved tensions. "
        "Do not ask the user questions; complete the check."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity
    md, data, status = await _run_stage("contradiction_check", goal, lab_workspace, context, conversation_history or [])
    out_path = RESEARCH_BRAIN / "contradictions" / "check.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md or "(no output)", encoding="utf-8")
    mission = load_mission_state()
    mission["completed"] = list(mission.get("completed") or [])
    if stage_name not in mission["completed"]:
        mission["completed"].append(stage_name)
    mission["stage"] = stage_name
    save_mission_state(mission)
    return md, data, status


async def run_distillation_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    stage_name: str = "distillation",
) -> tuple[str, dict, str]:
    """
    Stage 4 — Distillation. Distill previous outputs into concise knowledge.
    Writes: .research_brain/distilled/knowledge.md
    Returns: (markdown_text, json_data, status).
    """
    ensure_research_brain_dirs()
    continuity = load_research_context("distillation")
    goal = (
        "Research mission - Stage 4: Distillation. "
        "Distill all previous stage outputs into a concise knowledge base. "
        "Use only read_file to read from .research_brain if needed; do not modify source. "
        "Write distilled knowledge. Do not ask the user questions; complete distillation."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity
    md, data, status = await _run_stage("distillation", goal, lab_workspace, context, conversation_history or [])
    out_path = RESEARCH_BRAIN / "distilled" / "knowledge.md"
    out_path.write_text(md or "(no output)", encoding="utf-8")
    mission = load_mission_state()
    mission["completed"] = list(mission.get("completed") or [])
    if stage_name not in mission["completed"]:
        mission["completed"].append(stage_name)
    mission["stage"] = stage_name
    save_mission_state(mission)
    return md, data, status


async def run_synthesis_stage(
    lab_workspace: str,
    context: str = "",
    conversation_history: list | None = None,
    stage_name: str = "synthesis",
) -> tuple[str, dict, str]:
    """
    Stage 5 — Strategic Synthesis. Produce strategic synthesis and recommendations.
    Writes: .research_brain/strategic/model.md
    Returns: (markdown_text, json_data, status).
    """
    ensure_research_brain_dirs()
    continuity = load_research_context("synthesis")
    goal = (
        "Research mission - Stage 5: Strategic Synthesis. "
        "Produce strategic synthesis and recommendations from all previous stages. "
        "Use only read_file to read from .research_brain if needed. "
        "Write the strategic model. Do not ask the user questions; complete synthesis."
    )
    if continuity:
        goal = goal + "\n\nPrevious context:\n" + continuity
    md, data, status = await _run_stage("synthesis", goal, lab_workspace, context, conversation_history or [])
    if not is_useful_output(md or ""):
        md = (md or "") + "\n\nINSUFFICIENT_ACTIONABLE_INSIGHT"
    out_path = RESEARCH_BRAIN / "strategic" / "model.md"
    out_path.write_text(md or "(no output)", encoding="utf-8")
    mission = load_mission_state()
    mission["completed"] = list(mission.get("completed") or [])
    if stage_name not in mission["completed"]:
        mission["completed"].append(stage_name)
    mission["stage"] = stage_name
    save_mission_state(mission)
    return md, data, status


# Stage name -> runner (base 6 with contradiction_check; intelligence runners added when available)
STAGE_RUNNERS = {
    "mapping": run_mapping_stage,
    "investigation": run_investigation_stage,
    "verification": run_verification_stage,
    "contradiction_check": run_contradiction_check_stage,
    "distillation": run_distillation_stage,
    "synthesis": run_synthesis_stage,
}

# Full pipeline = base 5 + intelligence 9 (only when mission_depth == "full")
FULL_PIPELINE_ORDER = list(STAGE_ORDER)
try:
    from research_intelligence import INTELLIGENCE_ORDER, INTELLIGENCE_RUNNERS
    FULL_PIPELINE_ORDER = list(STAGE_ORDER) + list(INTELLIGENCE_ORDER)
    STAGE_RUNNERS = {**STAGE_RUNNERS, **INTELLIGENCE_RUNNERS}
except ImportError:
    pass


def stages_for_depth(depth: str, next_stage: bool) -> list[str]:
    """
    Return list of stage names to run.
    depth: "map" -> [mapping]; "deep" -> [mapping, investigation]; "full" -> base 5 + intelligence 9.
    If next_stage, append the next stage after the last one (if not already at end).
    """
    if depth == "map":
        stages = ["mapping"]
    elif depth == "deep":
        stages = ["mapping", "investigation"]
    elif depth == "full":
        stages = list(FULL_PIPELINE_ORDER)
    else:
        stages = list(STAGE_ORDER)
    if next_stage and stages:
        order = FULL_PIPELINE_ORDER if depth == "full" else STAGE_ORDER
        last = stages[-1]
        idx = order.index(last) if last in order else -1
        if idx >= 0 and idx + 1 < len(order):
            next_name = order[idx + 1]
            if next_name not in stages:
                stages.append(next_name)
    return stages


# Ensure .research_brain dirs exist when module is loaded
ensure_research_brain_dirs()
