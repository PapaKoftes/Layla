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

## Built-in skills

| Skill | Description | Sub-skills |
|-------|-------------|------------|
| `analyze_repo` | Tech stack, entry points, structure | — |
| `research_topic` | Web search, articles, Wikipedia | — |
| `write_python_module` | Read, implement, verify | analyze_repo |
| `debug_code` | Locate issues, trace, suggest fixes | analyze_repo |
| `document_codebase` | Summarize structure, key files | analyze_repo |

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

`resolve_skill_chain(skill_name)` returns ordered list: sub_skills first, then the skill. Used by planner to expand dependencies.
