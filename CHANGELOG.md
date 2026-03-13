# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
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
