# Contributing to Layla

Thank you for your interest in contributing. Layla is a local-first AI companion and engineering agent. Contributions of all kinds are welcome: bug fixes, features, docs, tests, and ideas.

**Skill packs:** Add a folder under `skill_packs/<id>/` with `manifest.json` (see existing packs). Optional dynamic install via `POST /skill_packs/install` clones into `.layla/skill_packs_installed/`.

> **License note:** Layla is released under the [Layla Non-Commercial Source License](LICENSE). By contributing you agree your contribution is licensed under the same terms. Commercial use requires explicit written permission from the project maintainer(s).

---

## Development setup

```bash
git clone <YOUR_REPO_URL>
cd layla/agent

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Copy the example config
cp runtime_config.example.json runtime_config.json
# Edit runtime_config.json: set model_filename to your GGUF file path
```

Place your GGUF model under `models/`. See [docs/GETTING_THE_MODEL.md](docs/GETTING_THE_MODEL.md) for model recommendations.

Start the server:

```bash
cd agent
uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000` for the web UI. Interactive API docs: `http://localhost:8000/docs`.

---

## Running tests

```bash
cd agent
pytest tests/ -v
```

Tests mock the LLM — no model required to run the test suite.

---

## Code style

This project uses [ruff](https://github.com/astral-sh/ruff) for linting and formatting.

```bash
pip install ruff
ruff check agent/
ruff format agent/
```

CI will fail if ruff reports errors on changed files.

---

## Commit format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add paginated /learnings endpoint
fix: prevent mission state reset on resume
docs: update RUNBOOKS with Docker section
refactor: replace FAISS dual-write with ChromaDB-only
test: add approval end-to-end lifecycle test
```

---

## Pull request checklist

Before opening a PR:

- [ ] Tests pass: `cd agent && pytest tests/ -v`
- [ ] No new ruff errors: `ruff check agent/`
- [ ] Docs updated if behaviour changed
- [ ] No hardcoded local paths (use `Path.home()` or config)
- [ ] No personal identifiers in code, docs, or comments
- [ ] If adding a new tool: add it to `TOOL_DISPATCH` in `layla/tools/registry.py`
- [ ] If adding a new aspect: add a JSON file to `personalities/`

---

## Project structure

```
agent/              FastAPI server, agent loop, routers
agent/layla/        Core package: memory, tools, file understanding
personalities/      Aspect JSON files (Morrigan, Nyx, Echo, Eris, Lilith, Cassandra)
cursor-layla-mcp/   Cursor MCP server
docs/               Guides and references
knowledge/          Operator-specific knowledge docs (gitignored)
models/             GGUF model files (gitignored)
scripts/            Utility scripts
```

---

## Adding a new aspect

1. Create `personalities/my_aspect.json` with `id`, `name`, `title`, `role`, `voice`, `systemPromptAddition`, `triggers`.
2. Optionally add `nsfw_triggers` and `systemPromptAdditionNsfw` for a NSFW register.
3. The orchestrator will auto-discover and route to it.

---

## Reporting issues

Use the GitHub issue tracker. See `.github/ISSUE_TEMPLATE/` for templates.

For security issues, see [SECURITY.md](SECURITY.md) — do **not** open a public issue.
