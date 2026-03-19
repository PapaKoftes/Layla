# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] — 2026-02-22

### Major — The Character Update

#### Aspects
- Renamed Neuro → **Cassandra** (unfiltered oracle; no filter between perception and output)
- All six aspects rewritten with 300–600-word `systemPromptAddition` character definitions
- Fixed critical bug: `systemPromptAddition` was silently truncated to 80 chars — now fully injected
- Added per-aspect symbols: ⚔ Morrigan, ✦ Nyx, ◎ Echo, ⚡ Eris, ⌖ Cassandra, ⊛ Lilith
- Deliberation prompt rewritten with per-aspect voice cues so the model knows the register
- `build_standard_prompt` now includes a character anchor line
- `system_identity.txt` rewritten as a deep foundational Layla identity document
- `.identity/self_model.md` created — Lilith's self-model, injected only when Lilith is active

#### Capabilities
- Added 8 new tools: `json_query`, `diff_files`, `env_info`, `regex_test`, `git_add`, `git_commit`, `save_note`, `search_memories`
- Echo now accumulates session-pattern summaries every 5 turns across all aspects
- Memory bundle export/import: `/memory/export` (ZIP), `/memory/import` (merge)
- Model download wizard in `first_run.py`: interactive picker, progress bar, 5 recommended models
- `Download-Model.ps1` rewritten: interactive model picker with real HuggingFace open model links

#### Knowledge Base
- Added 6 aspect-specific knowledge docs: `morrigan-engineering.md`, `nyx-research.md`,
  `echo-behavioral-patterns.md`, `eris-creative-thinking.md`,
  `lilith-ethics-autonomy.md`, `cassandra-pattern-perception.md`

#### UI
- Aspect buttons now show symbols (⚔ ✦ ◎ ⚡ ⌖ ⊛) instead of raw HTML codes
- Header aspect badge updates symbol on aspect switch
- Improved aspect descriptions for all six

#### Infrastructure
- Fixed `start-layla.ps1`: `cursor-jinx-mcp` → `cursor-layla-mcp`
- Fixed `IMPLEMENTATION_STATUS.md`: stale `agent/jinx/` path → `agent/layla/`
- `SETUP-AND-TEST.ps1` and `PASTE-AND-RUN.ps1` rewritten: no stale refs, cleaner output
- `/memory/stats` endpoint for memory state inspection
- Memory router wired into `main.py`

---

## [Unreleased]

### Added
- First-run onboarding (4-step guided tour)
- Model readiness banner
- Keyboard shortcut reference in Help panel
- Improved error messages (`formatAgentError` for 500/503/network)
- Empty state copy for study plans and approvals panels
- Loading skeletons for Health, Models, Knowledge panels
- Focus management (input after send, restore on modal close)
- Responsive layout (sticky header, mobile sidebar with hamburger)
- Accessibility (aria-label on icon buttons, focus-visible styles)
- Typography scale (--text-xs/sm/base/lg, --heading)
- Try-this suggestions (quantum entanglement, Python hello world chips)
- Destructive action confirmations (clear chat, delete session)
- Undo toast for approvals (write_file, apply_patch)
- Input affordances hint (attach, paste, Ctrl+K)
- Aspect switching feedback toast
- Inline docs mount (`/docs`), Config Reference link in Settings
- Troubleshooting section in Help panel and README
- ChromaDB FTS fallback when vector store fails
- TTS degradation (speakReply wrapped in try/catch)
- Health dashboard (db_ok, chroma_ok, uptime)
- Logging (LOG_LEVEL, LAYLA_LOG_JSON env)
- Saved workspaces (localStorage presets)
- Custom prompt prefixes (config + UI)
- PWA manifest
- ChromaDB as sole vector store (FAISS dual-write removed); learnings now linked via `embedding_id`
- `instructor` integration for grammar-constrained JSON output in agent loop
- Embedding-based aspect routing via cosine similarity (replaces keyword substring scoring)
- Overlap-aware document chunking via `langchain-text-splitters`
- `nomic-embed-text` as default embedding model (768 dim, replaces `all-MiniLM-L6-v2`)
- Tool dispatch table replacing 700-line if-elif chain
- Paginated `/learnings` and `/audit` API endpoints
- `Dockerfile` and `docker-compose.yml`
- GitHub Actions CI workflow
- `pyproject.toml` with ruff config
- Knowledge graph edges via cosine-similarity linking
- Open WebUI integration documentation

### Fixed
- `migrate()` called on every DB function; now runs once at startup with version guard
- Mission state reset on every `/research_mission` call (broken resume); state is now preserved for `next_stage=True`
- `copy_source_to_lab` now excludes `.git`, `.venv`, `node_modules`, `__pycache__`, and files over 5 MB
- `allow_write=True` in research intelligence stages changed to `allow_write=False`
- Sandbox path check uses `Path.relative_to()` consistently (was string prefix match)
- Wikipedia slug construction now uses full topic name with proper URL encoding
- `apply_patch` now uses pure-Python `unidiff` library (no system `patch` binary required on Windows)
- Distillation re-embeds merged learnings into Chroma (previously vector store diverged from DB)
- `C:\github` hardcoded default paths replaced with `Path.home()`

### Changed
- Internal package renamed from `agent/jinx/` to `agent/layla/`
- MCP server renamed from `cursor-jinx-mcp/` to `cursor-layla-mcp/`; tool renamed `chat_with_jinx` -> `chat_with_layla`
- All identity references anonymized for public release
- Dependency pins tightened: `llama-cpp-python`, `chromadb`, `apscheduler`, `sentence-transformers`
- Removed unused `httpx` and `requests` dependencies

### Removed
- `personalities/ishtar.json` (NSFW merged into Lilith with keyword-toggle)
- `faiss-cpu` dependency
- Hardcoded personal paths and identifiers throughout codebase

---

## [0.1.0] - 2024-01-01

### Added
- Initial public release
- FastAPI agent server with GGUF/llama-cpp-python backend
- Multi-aspect personality system (Morrigan, Nyx, Echo, Eris, Lilith, Cassandra)
- Tool loop: read_file, write_file, list_dir, grep_code, glob_files, git_*, shell, run_python, apply_patch, fetch_url
- Approval-gate for dangerous tools
- SQLite memory (learnings, study plans, audit, aspect memories, capability tracking)
- FAISS/ChromaDB vector search over learnings and knowledge docs
- Research lab with staged pipeline (mapping, investigation, verification, distillation, synthesis)
- Study plans with autonomous study steps and wakeup greeting
- Cursor MCP server
- Web UI (dark occult aesthetic, streaming, aspects panel, approvals, study plans)
- OpenAI-compatible `/v1/chat/completions` endpoint
