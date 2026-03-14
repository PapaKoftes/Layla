"""
Self-improvement module. Analyze Layla's codebase and propose improvements.
Read-only analysis; proposals require approval to apply.
Extended: evaluate capabilities, detect missing capabilities, propose integrations.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla")

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent


def evaluate_capabilities() -> dict[str, Any]:
    """
    Evaluate current capability implementations and benchmark status.
    Returns {capabilities: [...], missing: [...], proposals: [...]}.
    """
    result: dict[str, Any] = {"capabilities": [], "missing": [], "proposals": []}
    try:
        import runtime_safety
        from capabilities.registry import CAPABILITIES, get_active_implementation
        cfg = runtime_safety.load_config()
        for cap_name, impls in CAPABILITIES.items():
            active = get_active_implementation(cap_name, cfg)
            result["capabilities"].append({
                "name": cap_name,
                "active_impl": active.id if active else None,
                "impl_count": len(impls),
            })
    except ImportError as e:
        result["missing"].append(f"capabilities.registry: {e}")
    try:
        from layla.memory.db import list_capability_implementations
        stored = list_capability_implementations()
        benchmarked = [r for r in stored if r.get("status") in ("active", "benchmarked")]
        result["benchmarked_count"] = len(benchmarked)
    except Exception:
        result["benchmarked_count"] = 0
    return result


def detect_missing_capabilities() -> list[dict[str, Any]]:
    """
    Detect capabilities that have no valid benchmarked implementation.
    Returns list of {capability, suggestion}.
    """
    missing: list[dict[str, Any]] = []
    try:
        from capabilities.registry import CAPABILITIES
        from layla.memory.db import get_best_capability_implementation
        for cap_name in CAPABILITIES:
            best = get_best_capability_implementation(cap_name)
            if not best:
                missing.append({
                    "capability": cap_name,
                    "suggestion": f"Run benchmark or sandbox validation for {cap_name}",
                })
    except ImportError:
        pass
    return missing


def propose_capability_integrations() -> list[dict[str, Any]]:
    """
    Propose new capability integrations from discovery.
    Returns list of {capability, implementation_id, package, source}.
    """
    proposals: list[dict[str, Any]] = []
    try:
        from services.capability_discovery import discover_all_capabilities
        discovered = discover_all_capabilities()
        from capabilities.registry import CAPABILITIES
        for cap_name, candidates in discovered.items():
            known_ids = {i.id for i in CAPABILITIES.get(cap_name, [])}
            for c in candidates[:5]:
                impl_id = c.name.lower().replace("-", "_").replace(".", "_")[:30]
                if impl_id not in known_ids:
                    proposals.append({
                        "capability": cap_name,
                        "implementation_id": impl_id,
                        "package": c.name,
                        "source": c.source,
                        "description": c.description[:80] if c.description else "",
                    })
    except ImportError as e:
        logger.debug("propose_capability_integrations: %s", e)
    return proposals


def analyze_codebase() -> dict[str, Any]:
    """
    Analyze agent codebase: structure, patterns, potential improvements.
    Returns structured report. No file modifications.
    """
    report: dict[str, Any] = {
        "modules": [],
        "tool_count": 0,
        "skill_count": 0,
        "suggestions": [],
    }
    try:
        for p in sorted(AGENT_DIR.rglob("*.py")):
            if "__pycache__" in str(p) or ".venv" in str(p):
                continue
            rel = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
            try:
                lines = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
            except Exception:
                lines = 0
            report["modules"].append({"path": rel, "lines": lines})
    except Exception as e:
        report["suggestions"].append(f"Analysis error: {e}")
    try:
        from layla.tools.registry import TOOLS
        report["tool_count"] = len(TOOLS)
    except Exception:
        pass
    try:
        from layla.skills.registry import SKILLS
        report["skill_count"] = len(SKILLS)
    except Exception:
        pass
    return report


def propose_improvements(goal: str = "") -> list[dict[str, Any]]:
    """
    Use LLM to propose codebase improvements based on analysis.
    Returns list of {area, suggestion, priority}. No modifications.
    Extended: includes capability evaluation and integration proposals.
    """
    report = analyze_codebase()
    cap_eval = evaluate_capabilities()
    missing = detect_missing_capabilities()
    proposals = propose_capability_integrations()
    cap_context = ""
    if missing:
        cap_context += f"\nMissing benchmarked capabilities: {[m['capability'] for m in missing]}."
    if proposals:
        cap_context += f"\nDiscovery found {len(proposals)} candidate integrations."
    try:
        from services.llm_gateway import run_completion
        prompt = (
            f"Codebase summary: {len(report['modules'])} modules, {report['tool_count']} tools, {report['skill_count']} skills.\n"
            f"Capabilities: {len(cap_eval.get('capabilities', []))} registered, {cap_eval.get('benchmarked_count', 0)} benchmarked."
            f"{cap_context}\n"
            f"Goal: {goal or 'general improvement'}\n\n"
            "Propose 1-3 specific improvements. For each: area (file or component), suggestion (one line), priority (1-3, 1=high). "
            "Output as JSON array: [{\"area\": \"...\", \"suggestion\": \"...\", \"priority\": 1}]. No other text."
        )
        out = run_completion(prompt, max_tokens=400, temperature=0.2, stream=False)
        if not isinstance(out, dict):
            return []
        text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        if not text:
            return []
        import json
        import re
        m = re.search(r"\[[\s\S]*?\]", text)
        if m:
            arr = json.loads(m.group(0))
            if isinstance(arr, list):
                return [x for x in arr if isinstance(x, dict) and x.get("suggestion")][:5]
    except Exception as e:
        logger.warning("self_improvement propose failed: %s", e)
    return []
