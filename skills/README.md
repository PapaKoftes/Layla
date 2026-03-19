# Optional markdown skills (AgentSkills-style)

Drop `SKILL.md` files in subfolders here. Each file may start with YAML frontmatter (`name`, `description`, optional `requires` with `bins` / `env` lists).

Layla loads them into the planner context when `skills_enabled` is true. Override the scan directory with `markdown_skills_dir` in `agent/runtime_config.json`.

See [docs/OPENCLAW_ALIGNMENT.md](../docs/OPENCLAW_ALIGNMENT.md).
