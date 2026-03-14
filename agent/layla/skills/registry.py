"""
Skills registry. Skills are named workflows that combine tools.
Skills can call other skills (sub_skills). Stored in agent/layla/skills/.
The planner injects skill descriptions so the LLM prefers skills over raw tools.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

SKILLS_DIR = Path(__file__).resolve().parent

SKILLS: dict[str, dict[str, Any]] = {
    "analyze_repo": {
        "description": "Analyze a codebase: tech stack, entry points, key docs, structure.",
        "tools": ["workspace_map", "project_discovery", "list_dir", "grep_code", "python_ast"],
        "sub_skills": [],
        "execution_steps": [
            "Run workspace_map or project_discovery for overview",
            "Use list_dir and grep_code to explore structure",
            "Use python_ast for key Python files",
        ],
    },
    "research_topic": {
        "description": "Research a topic: web search, articles, Wikipedia.",
        "tools": ["ddg_search", "fetch_article", "wiki_search", "arxiv_search"],
        "sub_skills": [],
        "execution_steps": [
            "Search with ddg_search for overview",
            "Fetch key articles with fetch_article",
            "Use wiki_search for definitions, arxiv_search for papers",
        ],
    },
    "write_python_module": {
        "description": "Write a Python module: read context, implement, verify.",
        "tools": ["read_file", "list_dir", "write_file", "run_python"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Read existing code with read_file",
            "Write new code with write_file",
            "Run tests with run_python",
        ],
    },
    "debug_code": {
        "description": "Debug code: locate issues, trace execution, suggest fixes.",
        "tools": ["read_file", "grep_code", "python_ast", "run_python", "diff_files"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Read relevant files with read_file",
            "Search for patterns with grep_code",
            "Inspect structure with python_ast",
            "Run code with run_python to reproduce",
        ],
    },
    "document_codebase": {
        "description": "Document a codebase: summarize structure, key files, usage.",
        "tools": ["workspace_map", "read_file", "python_ast", "write_file"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Get overview with workspace_map",
            "Read key files for context",
            "Write documentation with write_file",
        ],
    },
}


def get_skills_prompt_hint(cfg: dict | None = None) -> str:
    """
    Return a prompt hint listing skills and their tools.
    Empty string if skills_enabled is False.
    """
    if cfg is not None and not cfg.get("skills_enabled", True):
        return ""
    lines = ["Skills (prefer these over raw tools when task matches):"]
    for name, s in SKILLS.items():
        tools = ", ".join(s.get("tools", [])[:5])
        sub = s.get("sub_skills", [])
        sub_str = f" [calls: {', '.join(sub)}]" if sub else ""
        desc = (s.get("description") or "")[:80]
        lines.append(f"  - {name}: {desc} [tools: {tools}]{sub_str}")
    return "\n".join(lines) + "\n"


def get_skill_dependencies(skill_name: str, visited: set[str] | None = None) -> list[str]:
    """Return flattened list of skills to run (this skill + sub_skills in dependency order)."""
    visited = visited or set()
    if skill_name in visited:
        return []
    visited.add(skill_name)
    s = SKILLS.get(skill_name)
    if not s:
        return []
    result: list[str] = []
    for sub in s.get("sub_skills", []):
        result.extend(get_skill_dependencies(sub, visited))
    result.append(skill_name)
    return result


def resolve_skill_chain(skill_name: str) -> list[str]:
    """Return ordered list of skills: sub_skills first, then this skill."""
    return get_skill_dependencies(skill_name)
