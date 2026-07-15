# Skills

Skills are named workflows that combine tools. Stored in `agent/layla/skills/`. The planner injects skill hints so the LLM prefers skills over raw tools. See also [CAPABILITIES.md](CAPABILITIES.md) for capability implementations (vector_search, embedding, etc.) and dynamic backend selection.

---

## Skill structure

Skills can call other skills (sub_skills). Each skill defines:

| Field | Description |
|-------|-------------|
| `description` | Shown in planner prompt |
| `tools` | Tool names from registry |
| `sub_skills` | Skills to run first (dependency order) |
| `execution_steps` | Hints for the agent |

---

## Built-in skills (42)

| Skill | Description | Sub-skills |
|-------|-------------|------------|
| `analyze_repo` | Tech stack, entry points, structure | — |
| `research_topic` | Web search, articles, Wikipedia | — |
| `write_python_module` | Read, implement, verify | analyze_repo |
| `debug_code` | Locate issues, trace, suggest fixes | analyze_repo |
| `document_codebase` | Summarize structure, key files | analyze_repo |
| `fabrication_workflow` | DXF/G-code/STL analysis, geometry→fabrication | — |
| `run_test_suite` | Run tests, summarize, suggest fixes | analyze_repo |
| `setup_project` | Install deps, run first test | — |
| `create_pr` | Stage, commit, push, open PR | — |
| `investigate_bug` | Blame, grep, audit log, context | analyze_repo |
| `code_review` | Structure, style, security, best practices | analyze_repo |
| `generate_tests` | Unit tests from code | analyze_repo |
| `generate_docs` | README, docstrings, API docs | analyze_repo |
| `data_analysis` | Load, summarize, visualize data | — |
| `refactor_code` | Rename, extract, format | analyze_repo |
| `performance_audit` | Complexity, bottlenecks | analyze_repo |
| `security_audit` | Vulnerabilities, secrets scan | analyze_repo |
| `create_presentation` | Outline, slides, speaker notes | research_topic |
| `compare_versions` | Diff across branches/versions | — |
| `extract_insights` | Summarize, classify, extract entities | — |
| `api_exploration` | Fetch, parse, document APIs | — |
| `backup_and_restore` | Create/extract archives | — |
| `optimize_code` | Performance, complexity, efficiency | analyze_repo, performance_audit |
| `migrate_codebase` | Framework upgrade, deprecations | analyze_repo |
| `review_pull_request` | Full PR: diff, security, style | — |
| `fix_imports` | Organize imports | analyze_repo |
| `data_cleaning` | Missing, outliers, validation | — |
| `data_export` | Export to CSV/JSON | — |
| `data_validation` | Schema, constraints | — |
| `system_health_check` | Disk, memory, processes (read-only) | — |
| `safe_cleanup` | Temp/cache report (approval for delete) | — |
| `create_diagram` | Mermaid, SVG (no Gen AI) | — |
| `create_visualization` | Charts from data (no Gen AI) | — |
| `compose_document` | Outlines, reports, specs | research_topic |
| `discord_notify` | Send to Discord | — |
| `send_notification` | Discord/Slack/webhook/email | — |
| `manage_calendar` | Read/add .ics events | — |
| `database_workflow` | Query, schema, backup | — |
| `read_any_file` | Any file type: code, docs, data | — |
| `review_past_work` | Audit log, learnings, history | — |
| `optimize_workflow` | Suggest efficiency improvements | — |
| `practice_skill` | Focused practice, game-like improvement | — |

---

## Adding a skill

Edit `agent/layla/skills/registry.py`:

```python
SKILLS["my_skill"] = {
    "description": "What this skill does",
    "tools": ["tool1", "tool2"],
    "sub_skills": ["analyze_repo"],  # optional
    "execution_steps": ["Step 1", "Step 2"],
}
```

Ensure all tools exist in `layla/tools/registry.TOOLS`. Skills are injected when `skills_enabled: true` in config.

---

## Skill chains

`resolve_skill_chain(skill_name)` returns an ordered list: sub_skills first, then the skill. **Note:** this helper is available but is *not* currently invoked by the planner — `sub_skills` are surfaced to the model as a `[calls: …]` hint in the skill prompt block (`get_skills_prompt_hint`), not auto-expanded/executed. Treat `sub_skills` as documentation for the model, not an execution guarantee.
