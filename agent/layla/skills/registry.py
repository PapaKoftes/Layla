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
    "fabrication_workflow": {
        "description": "Analyze fabrication files: DXF, G-code, STL. Geometry to machine intent.",
        "tools": [
            "understand_file",
            "parse_gcode",
            "stl_mesh_info",
            "read_file",
            "generate_gcode",
            "geometry_validate_program",
            "geometry_execute_program",
            "geometry_list_frameworks",
        ],
        "sub_skills": [],
        "execution_steps": [
            "Use understand_file for DXF layers/entities",
            "Use parse_gcode for G-code moves, tools, bounds",
            "Use stl_mesh_info for mesh stats",
            "Use generate_gcode for DXF to G-code (approval required)",
            "For parametric CAD-style sequences: geometry_validate_program then geometry_execute_program (approval); geometry_list_frameworks checks ezdxf/cadquery/openscad/trimesh",
        ],
    },
    "fabrication_assist_kernel": {
        "description": "Run Fabrication Assist deterministic kernel (StubRunner by default; subprocess runner only when operator enables fabrication_assist.enable_subprocess and the plan step explicitly requests it).",
        "tools": ["fabrication_assist_run", "read_file", "write_file", "write_files_batch", "list_dir"],
        "sub_skills": ["fabrication_workflow"],
        "execution_steps": [
            "Prepare objective and any inputs under the workspace sandbox",
            "Run fabrication_assist_run (approval-gated; deterministic by default)",
            "Write outputs to files via write_file/write_files_batch if needed",
        ],
    },
    "run_test_suite": {
        "description": "Run project test suite, summarize results, suggest fixes.",
        "tools": ["run_tests", "run_python", "glob_files", "read_file", "grep_code"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Run run_tests in project root",
            "If failures: read_file on failing tests, grep_code for patterns",
            "Suggest fixes based on output",
        ],
    },
    "setup_project": {
        "description": "Create venv, install deps, run first test.",
        "tools": ["list_dir", "pip_install", "run_tests", "run_python", "read_file"],
        "sub_skills": [],
        "execution_steps": [
            "Check for requirements.txt or pyproject.toml",
            "pip_install dependencies",
            "run_tests to verify",
        ],
    },
    "create_pr": {
        "description": "Stage, commit, push, create GitHub PR.",
        "tools": ["git_status", "git_add", "git_commit", "git_push", "github_pr"],
        "sub_skills": [],
        "execution_steps": [
            "git_status to see changes",
            "git_add and git_commit",
            "git_push (approval required)",
            "github_pr with title/head/base (approval required)",
        ],
    },
    "investigate_bug": {
        "description": "Trace bug: blame, grep, audit log, code context.",
        "tools": ["git_blame", "grep_code", "trace_last_run", "read_file", "code_symbols"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "git_blame on affected file",
            "grep_code for related patterns",
            "trace_last_run for recent agent actions",
            "read_file and code_symbols for context",
        ],
    },
    "code_review": {
        "description": "Review code: structure, style, security, best practices.",
        "tools": ["read_file", "python_ast", "code_metrics", "code_lint", "security_scan", "grep_code"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Read target files with read_file",
            "Run code_metrics and code_lint",
            "Run security_scan (bandit/secrets)",
            "Provide structured feedback",
        ],
    },
    "generate_tests": {
        "description": "Generate unit tests from existing code.",
        "tools": ["read_file", "python_ast", "code_symbols", "write_file", "run_tests"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Read source with read_file and python_ast",
            "Identify functions/classes to test",
            "Write test file with write_file",
            "Run run_tests to verify",
        ],
    },
    "generate_docs": {
        "description": "Generate documentation from code (README, docstrings, API docs).",
        "tools": ["read_file", "python_ast", "code_symbols", "workspace_map", "write_file"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Get overview with workspace_map",
            "Read key modules with read_file",
            "Extract structure with python_ast",
            "Write README or docstrings with write_file",
        ],
    },
    "data_analysis": {
        "description": "Analyze data: load, summarize, visualize.",
        "tools": ["read_csv", "read_excel", "json_query", "dataset_summary", "plot_chart", "scipy_compute", "cluster_data"],
        "sub_skills": [],
        "execution_steps": [
            "Load data with read_csv/read_excel",
            "Run dataset_summary for stats",
            "Use plot_chart for visualization",
            "scipy_compute or cluster_data for analysis",
        ],
    },
    "refactor_code": {
        "description": "Refactor code: rename, extract, format.",
        "tools": ["read_file", "rename_symbol", "search_replace", "code_format", "run_tests"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Read code with read_file",
            "Use rename_symbol or search_replace",
            "code_format for style",
            "run_tests to verify",
        ],
    },
    "performance_audit": {
        "description": "Audit code performance: complexity, bottlenecks.",
        "tools": ["code_metrics", "read_file", "python_ast", "grep_code", "run_python"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Run code_metrics for complexity",
            "Identify hot paths with grep_code",
            "Suggest optimizations",
        ],
    },
    "security_audit": {
        "description": "Security audit: scan for vulnerabilities and secrets.",
        "tools": ["security_scan", "grep_code", "read_file", "trace_last_run"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Run security_scan (bandit, secrets, deps)",
            "grep_code for sensitive patterns",
            "Review findings",
        ],
    },
    "create_presentation": {
        "description": "Create presentation content: outline, slides text, speaker notes.",
        "tools": ["write_file", "read_file", "summarize_text", "fetch_article"],
        "sub_skills": ["research_topic"],
        "execution_steps": [
            "Research with fetch_article if needed",
            "Write outline and slide content",
            "summarize_text for key points",
        ],
    },
    "compare_versions": {
        "description": "Compare code or config across versions/branches.",
        "tools": ["git_diff", "git_log", "diff_files", "read_file"],
        "sub_skills": [],
        "execution_steps": [
            "git_diff for changes",
            "diff_files for specific files",
            "Summarize differences",
        ],
    },
    "extract_insights": {
        "description": "Extract insights from text: summarize, classify, extract entities.",
        "tools": ["summarize_text", "classify_text", "nlp_analyze", "extract_entities", "translate_text"],
        "sub_skills": [],
        "execution_steps": [
            "summarize_text for overview",
            "classify_text or nlp_analyze",
            "extract_entities for structured data",
        ],
    },
    "api_exploration": {
        "description": "Explore API: fetch, parse, document endpoints.",
        "tools": ["http_request", "fetch_url", "read_file", "json_query", "write_file"],
        "sub_skills": [],
        "execution_steps": [
            "http_request or fetch_url",
            "json_query to parse response",
            "Document with write_file",
        ],
    },
    "backup_and_restore": {
        "description": "Backup files or create/restore archives.",
        "tools": ["create_archive", "extract_archive", "list_dir", "hash_file"],
        "sub_skills": [],
        "execution_steps": [
            "create_archive for backup",
            "hash_file for integrity",
            "extract_archive to restore",
        ],
    },
    # ─── Full coding skills ────────────────────────────────────────────────────
    "optimize_code": {
        "description": "Optimize code: performance, complexity, memory. Improve efficiency.",
        "tools": ["code_metrics", "read_file", "python_ast", "grep_code", "search_replace", "run_tests"],
        "sub_skills": ["analyze_repo", "performance_audit"],
        "execution_steps": [
            "Run code_metrics for hotspots",
            "Identify bottlenecks with grep_code",
            "Refactor with search_replace",
            "run_tests to verify",
        ],
    },
    "migrate_codebase": {
        "description": "Migrate code: framework upgrade, API changes, deprecations.",
        "tools": ["read_file", "grep_code", "search_replace", "rename_symbol", "run_tests", "pip_list"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Map current deps with pip_list",
            "grep_code for deprecated patterns",
            "search_replace and rename_symbol",
            "run_tests after each change",
        ],
    },
    "review_pull_request": {
        "description": "Full PR review: diff, security, style, tests.",
        "tools": ["git_diff", "read_file", "python_ast", "code_metrics", "code_lint", "security_scan", "run_tests"],
        "sub_skills": [],
        "execution_steps": [
            "git_diff for changes",
            "Read changed files",
            "Run code_lint and security_scan",
            "Suggest improvements",
        ],
    },
    "fix_imports": {
        "description": "Fix and organize imports (isort-style).",
        "tools": ["read_file", "grep_code", "search_replace", "code_format", "run_tests"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "Read files with import issues",
            "search_replace to fix order",
            "code_format for consistency",
        ],
    },
    # ─── Full data skills ───────────────────────────────────────────────────────
    "data_cleaning": {
        "description": "Clean data: missing values, outliers, duplicates, validation.",
        "tools": ["read_csv", "read_excel", "dataset_summary", "write_csv", "run_python", "json_schema"],
        "sub_skills": [],
        "execution_steps": [
            "Load with read_csv/read_excel",
            "dataset_summary for quality",
            "run_python for transforms",
            "write_csv for output",
        ],
    },
    "data_export": {
        "description": "Export data to CSV, JSON, or other formats.",
        "tools": ["read_csv", "read_excel", "json_query", "write_csv", "write_file"],
        "sub_skills": [],
        "execution_steps": [
            "Load source data",
            "Transform if needed",
            "write_csv or write_file",
        ],
    },
    "data_validation": {
        "description": "Validate data against schema, constraints, business rules.",
        "tools": ["read_csv", "read_excel", "json_schema", "dataset_summary", "run_python"],
        "sub_skills": [],
        "execution_steps": [
            "Load data and json_schema",
            "dataset_summary for stats",
            "Check constraints",
        ],
    },
    # ─── Full system skills (safety embedded) ────────────────────────────────────
    "system_health_check": {
        "description": "Full system health: disk, memory, processes. Safe, read-only.",
        "tools": ["disk_usage", "process_list", "env_info", "check_port", "tail_file"],
        "sub_skills": [],
        "execution_steps": [
            "disk_usage for space",
            "process_list for load",
            "env_info for runtime",
        ],
    },
    "safe_cleanup": {
        "description": "Safe cleanup: temp files, caches. Requires approval for deletion.",
        "tools": ["list_dir", "file_info", "glob_files", "read_file"],
        "sub_skills": [],
        "execution_steps": [
            "List candidate dirs (.cache, __pycache__, .pytest_cache)",
            "Report sizes with file_info",
            "User approves before any delete",
        ],
    },
    # ─── Creative (procedural, no Gen AI) ────────────────────────────────────────
    "create_diagram": {
        "description": "Create diagrams: flowcharts, sequence, ER. Mermaid or SVG. Procedural, no Gen AI.",
        "tools": ["create_mermaid", "create_svg", "write_file", "read_file"],
        "sub_skills": [],
        "execution_steps": [
            "create_mermaid for flowcharts/sequence",
            "create_svg for custom vector graphics",
            "Write diagram code directly",
        ],
    },
    "create_visualization": {
        "description": "Create charts and visualizations from data. plot_chart, SVG. No image Gen AI.",
        "tools": ["read_csv", "read_excel", "plot_chart", "create_svg", "dataset_summary"],
        "sub_skills": [],
        "execution_steps": [
            "Load data",
            "plot_chart for bar/line/scatter",
            "create_svg for custom graphics",
        ],
    },
    "compose_document": {
        "description": "Compose structured documents: outlines, reports, specs.",
        "tools": ["read_file", "write_file", "summarize_text", "fetch_article", "search_memories"],
        "sub_skills": ["research_topic"],
        "execution_steps": [
            "Gather sources with read_file/fetch_article",
            "summarize_text for key points",
            "write_file for structure",
        ],
    },
    # ─── Full comms (Discord, Slack, etc.) ───────────────────────────────────────
    "discord_notify": {
        "description": "Send notification to Discord. Easy: set discord_webhook_url in config.",
        "tools": ["discord_send", "send_webhook"],
        "sub_skills": [],
        "execution_steps": [
            "discord_send with content or embed",
            "Uses config discord_webhook_url or DISCORD_WEBHOOK_URL env",
        ],
    },
    "send_notification": {
        "description": "Send notification: Discord, Slack, webhook, or email.",
        "tools": ["discord_send", "send_webhook", "send_email"],
        "sub_skills": [],
        "execution_steps": [
            "discord_send for Discord",
            "send_webhook for Slack/custom",
            "send_email for email",
        ],
    },
    # ─── Full calendar ──────────────────────────────────────────────────────────
    "manage_calendar": {
        "description": "Read and add calendar events. .ics files.",
        "tools": ["calendar_read", "calendar_add_event", "read_file", "list_dir"],
        "sub_skills": [],
        "execution_steps": [
            "calendar_read to list events",
            "calendar_add_event to add (approval required)",
        ],
    },
    # ─── Full database ──────────────────────────────────────────────────────────
    "database_workflow": {
        "description": "Database: query, schema, backup, migrate.",
        "tools": ["sql_query", "schema_introspect", "db_backup", "generate_sql", "read_file"],
        "sub_skills": [],
        "execution_steps": [
            "schema_introspect for structure",
            "sql_query or generate_sql",
            "db_backup before changes",
        ],
    },
    # ─── Read any file (everyday task) ───────────────────────────────────────────
    "read_any_file": {
        "description": "Read and understand any file type: code, docs, data, config, media metadata.",
        "tools": ["read_file", "understand_file", "read_pdf", "read_csv", "read_excel", "read_docx", "read_toml", "yaml_read", "parse_gcode", "stl_mesh_info", "file_info"],
        "sub_skills": [],
        "execution_steps": [
            "file_info for type/size",
            "Route to correct reader by extension",
            "understand_file for intent",
        ],
    },
    # ─── Learning and improvement (game-like progression) ─────────────────────────
    "review_past_work": {
        "description": "Review past work: audit log, learnings, what was done. Learn from history.",
        "tools": ["trace_last_run", "search_memories", "git_log", "tool_metrics"],
        "sub_skills": [],
        "execution_steps": [
            "trace_last_run for recent actions",
            "search_memories for learnings",
            "git_log for commits",
        ],
    },
    "optimize_workflow": {
        "description": "Suggest workflow optimizations: tool usage, efficiency, patterns.",
        "tools": ["tool_metrics", "trace_last_run", "code_metrics", "search_memories"],
        "sub_skills": [],
        "execution_steps": [
            "tool_metrics for usage patterns",
            "Identify inefficiencies",
            "Suggest improvements",
        ],
    },
    "practice_skill": {
        "description": "Focused practice on a skill. Reinforces capability. Game-like improvement.",
        "tools": ["run_tests", "code_lint", "read_file", "write_file", "search_memories", "save_note"],
        "sub_skills": [],
        "execution_steps": [
            "Pick a skill area",
            "Run exercises (run_tests, code_lint)",
            "save_note for learnings",
        ],
    },
    # ─── OpenOrca/CLU/Nebulus-inspired skills ─────────────────────────────────
    "network_diagnostics": {
        "description": "Network diagnostics: port check, connectivity, HTTP probe.",
        "tools": ["check_port", "http_request", "fetch_url", "env_info"],
        "sub_skills": [],
        "execution_steps": [
            "check_port for TCP connectivity",
            "http_request or fetch_url for HTTP",
            "Report status",
        ],
    },
    "archive_workflow": {
        "description": "Create, extract, verify archives. Compression and extraction.",
        "tools": ["create_archive", "extract_archive", "hash_file", "list_dir"],
        "sub_skills": [],
        "execution_steps": [
            "create_archive for backup/compress",
            "extract_archive to restore",
            "hash_file for integrity",
        ],
    },
    "github_full_workflow": {
        "description": "Full GitHub workflow: issues, PRs, clone, push.",
        "tools": ["github_issues", "github_pr", "git_clone", "git_push", "git_status", "git_diff"],
        "sub_skills": [],
        "execution_steps": [
            "github_issues to list/create issues",
            "github_pr for pull requests",
            "git_clone, git_push for repo ops",
        ],
    },
    "semantic_code_search": {
        "description": "Semantic code search: vector search, workspace map, grep.",
        "tools": ["vector_search", "workspace_map", "grep_code", "code_symbols", "find_todos"],
        "sub_skills": ["analyze_repo"],
        "execution_steps": [
            "vector_search for semantic matches",
            "workspace_map for structure",
            "grep_code for exact patterns",
        ],
    },
    "multi_step_research": {
        "description": "Multi-step research: search, fetch, summarize, verify.",
        "tools": ["ddg_search", "fetch_article", "wiki_search", "arxiv_search", "summarize_text", "rss_feed"],
        "sub_skills": ["research_topic"],
        "execution_steps": [
            "Search with ddg_search",
            "Fetch and summarize articles",
            "Verify with wiki_search or arxiv",
        ],
    },
    "spawn_background_task": {
        "description": "Schedule a tool to run in background: once or recurring cron.",
        "tools": ["schedule_task", "list_scheduled_tasks", "cancel_task"],
        "sub_skills": [],
        "execution_steps": [
            "schedule_task with tool_name, args, delay or cron",
            "list_scheduled_tasks to check status",
            "cancel_task to stop",
        ],
    },
    "email_workflow": {
        "description": "Send email, optionally with attachments or templates.",
        "tools": ["send_email", "read_file", "write_file", "summarize_text"],
        "sub_skills": [],
        "execution_steps": [
            "send_email for notifications",
            "summarize_text for body content",
        ],
    },
    "webhook_notify": {
        "description": "Send webhook to Slack, Discord, or custom endpoint.",
        "tools": ["send_webhook", "discord_send", "http_request"],
        "sub_skills": [],
        "execution_steps": [
            "discord_send for Discord",
            "send_webhook for Slack/custom",
        ],
    },
    "spaced_repetition_review": {
        "description": "Review learnings due for spaced repetition. Strengthen memory.",
        "tools": ["search_memories", "memory_stats", "save_note"],
        "sub_skills": [],
        "execution_steps": [
            "memory_stats for overview",
            "search_memories for due items",
            "Reinforce with save_note",
        ],
    },
    "contradiction_detection": {
        "description": "Detect contradictions in memories or learnings.",
        "tools": ["search_memories", "memory_stats", "classify_text"],
        "sub_skills": [],
        "execution_steps": [
            "search_memories for related content",
            "Compare for contradictions",
        ],
    },
}

# Skill philosophy: everyday assistant, full coverage, learn & improve.
# - Coding: optimize, migrate, review, fix
# - Data: clean, export, validate
# - System: health check, safe cleanup (approval for delete)
# - Creative: diagrams, SVG, charts — procedural only, no Gen AI
# - Comms: Discord, Slack, webhook, email
# - Calendar, database, read_any_file
# - Learning: review_past_work, optimize_workflow, practice_skill


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
    out = "\n".join(lines) + "\n"
    if cfg is not None:
        try:
            from services.markdown_skills import load_markdown_skills_prompt

            extra = load_markdown_skills_prompt(cfg)
            if extra:
                out += "\n" + extra + "\n"
        except Exception:
            pass
    return out


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
