# Layla — Capabilities, Extension, Comparison & Character Roadmap

One-page reference for what the system does, how to extend it with public resources, how it compares to other AI assistants, knowledge library setup, and personality design (dere archetypes, tropes, distinct characters).

---

## 1. System capabilities (summary)

| Area | What Layla does |
|------|------------------|
| **Agent** | Local LLM (GGUF via llama-cpp-python), tool loop (read_file, write_file, list_dir, grep_code, glob_files, git_status/git_diff/git_log/git_branch, shell, run_python, apply_patch, fetch_url, file_info), approval gate for dangerous tools, aspect selection (Morrigan/Nyx/Echo/Eris/Lilith/Neuro), optional deliberation, streaming. Lilith NSFW register toggleable by keyword (e.g. intimate, nsfw). |
| **Memory** | Learnings in `layla.db` (+ optional vector store); semantic recall (FAISS/Chroma); aspect memories; conversation history (in-memory + persisted). |
| **Study** | Study plans in DB; wakeup greeting + optional one autonomous Nyx step; scheduled background study (when you're active, not gaming); record progress via API/CLI. |
| **Research** | Read-only agent run → `.research_output/last_research.md`; research missions copy workspace to `.research_lab`, run staged pipeline (mapping → investigation → verification → distillation → synthesis + optional intelligence stages), brain files under `.research_brain/`. |
| **Approvals** | Pending list in `.governance/pending.json`; approve via API/CLI/TUI/UI; audit log; lens knowledge refresh from curated sources. |
| **API** | FastAPI: `/agent`, `/learn`, `/wakeup`, `/study_plans`, `/pending`, `/approve`, `/research`, `/research_mission`, `/system_export`, `/health`, OpenAI-compatible `/v1/chat/completions`, `/ui`. |
| **CLI** | `layla.py`: ask, remember, study, plans, approve, wakeup, export, pending, tui, aspect. |
| **MCP** | Cursor integration: chat_with_layla, add_learning, start_study_session, analyze_repo_for_study (call Layla API). |

---

## 2. Extending with publicly available resources

- **New tools**  
  Add to `agent/jinx/tools/registry.py`: `TOOLS["name"] = {"fn": callable, "dangerous": bool, "require_approval": bool}`. Agent loop uses the same registry; approvals router runs `TOOLS[name]["fn"](**args)`.

- **New aspects**  
  Add a JSON file under `personalities/` (e.g. `personalities/my_aspect.json`) with `id`, `name`, `title`, `role`, `voice`, `systemPromptAddition`, `triggers`; optional `nsfw_triggers` and `systemPromptAdditionNsfw` for an NSFW register (e.g. Lilith). Orchestrator globs `personalities/*.json` and selects by trigger overlap or forced aspect.

- **Knowledge / RAG**  
  Drop `.md`/`.txt` in `knowledge/` (or `knowledge/fetched/`). With `use_chroma: true`, startup indexes into Chroma; agent gets top-k chunks via `get_knowledge_chunks(goal, k)`. Fallback: `load_knowledge_docs(max_bytes)` concatenates files. Add URLs to `runtime_config.json` → `knowledge_sources` and run `python scripts/fetch_knowledge.py` or `python agent/download_docs.py` to pull into `knowledge/fetched/`.

- **Research stages**  
  Base stages in `agent/research_stages.py` (`STAGE_ORDER`, `STAGE_RUNNERS`); optional intelligence stages in `agent/research_intelligence.py`. Add or reorder stages there; mission depth (map/deep/full) controls which run.

- **Config**  
  Single source: `agent/runtime_config.json` (and hardware-derived defaults in `runtime_safety.py`). Env overrides for secrets when needed.

Public resources that plug in directly: any HTTP-gettable doc (fetch scripts), any Python callable (tools), any JSON personality (aspects), any markdown in `knowledge/` (RAG).

---

## 3. Comparison to current AI assistants and similar projects

| Dimension | Layla | Cursor / Copilot / Windsurf | Local-first OSS (e.g. Open WebUI, LibreChat, LobeChat) |
|-----------|--------|-----------------------------|--------------------------------------------------------|
| **Model** | Local GGUF (llama-cpp-python) | Cloud or optional local | Often cloud + optional local |
| **Identity** | Single entity, multiple aspects (personas), shared memory | Single “assistant” persona | Usually single bot, sometimes multi-bot |
| **Tools** | read_file, write_file, list_dir, grep_code, glob_files, git_*, shell, run_python, apply_patch, fetch_url, file_info; approval-gated for write/shell/run_python/patch | Rich IDE/git integration, optional agentic | Varies; often chat-only or plugin-based |
| **Memory** | DB + vector (learnings), aspect memories, conversation | Session/context window, sometimes long-term | Often session-only or simple history |
| **Study / growth** | Study plans, wakeup, scheduled study, learnings | N/A | Rare |
| **Research** | Staged research missions, brain files, read-only runs | Search/summarize in UI | Sometimes “research” = web search |
| **Approval** | Explicit pending → approve → run tool | Implicit (user runs commands) or auto-apply | Varies |
| **RAG / citations** | Chroma/FAISS over knowledge/ + learnings; top-k chunks in prompt (planned: answer + sources) | Often search snippet injection | Varies |
| **Doc loaders** | knowledge/ .md and .txt only; PDF/Notion planned | Native or via plugins | Varies |
| **Personality** | JSON-defined aspects, trigger-based selection, fanfic-level prompts | Neutral or light “vibe” | Often system prompt only |
| **Extensibility** | Add tool in registry.py, add JSON in personalities/, add knowledge + fetch script, add research stage | Plugins / extensions | Plugins / custom endpoints |

Layla’s differentiators: **multi-aspect identity** (distinct characters, not one bland assistant), **local-first with one approval model**, **study plans and research pipeline**, **memory and learnings in DB + vector**. **Inspiration and end goal:** growth over time (in the spirit of evolving, learning, and deepening over sessions) is part of the product vision; it is not a separate selectable personality. Gaps vs. big products: no built-in IDE, no native PDF/Notion loaders yet (doc loaders + chunking planned), no LangSmith-style tracing (optional trace id planned).

---

## 4. Knowledge library — current state and full fetch

**Current state**

- **Location:** Repo root `knowledge/` (and `knowledge/fetched/`).
- **Indexing:** If `use_chroma` is true, startup runs `index_knowledge_docs(knowledge/)` (Chroma collection `knowledge`). Otherwise fallback: `load_knowledge_docs(max_bytes)` concatenates `.md`/`.txt`.
- **Already present:** `knowledge/` has identity/stack/neuro docs; `knowledge/fetched/` has FastAPI, asyncio, pathlib, sqlite, json, dataclasses, llama-cpp-python, Neuro-sama wiki/personality.
- **Fetch scripts:**  
  - `python scripts/fetch_knowledge.py` — uses hardcoded URL list + `runtime_config.json` → `knowledge_sources`.  
  - `python agent/download_docs.py` — reads only `knowledge_sources`, writes `knowledge/fetched/<slug>.txt`.

**Full knowledge library (curated for this stack)**

To have a *complete* reference set for what you work on, add URLs to `runtime_config.json` → `knowledge_sources` and run the fetch script. Suggested slugs (extend as needed):

- **Core stack:** FastAPI (quickstart + advanced), asyncio, pathlib, sqlite, json, dataclasses — *already in* `scripts/fetch_knowledge.py` or config.
- **LLM/local:** llama-cpp-python README, GGUF, prompt formatting (e.g. ChatML/llama2).
- **Research/writing:** Your own `knowledge/docs/` (ezdxf, shapely, etc. — you already have some).
- **Personality/culture:** Neuro-sama wiki/personality (already in config), optional: TV Tropes dere pages, fandom wikis (One Piece, Warhammer 40k, MGR) if you want Layla to cite them.

**Ensuring a full fetch**

1. Edit `agent/runtime_config.json`: add entries to `knowledge_sources`: `{"url": "https://...", "slug": "short-slug"}`.  
2. Run from repo root: `python scripts/fetch_knowledge.py`.  
3. Restart Layla (or re-run indexing) so Chroma/fallback picks up `knowledge/fetched/*.txt`.

A single “full knowledge library” list lives in `scripts/fetch_knowledge.py` (URLS) plus config; we can add a `KNOWLEDGE_LIBRARY_FULL.md` in `knowledge/` that lists every slug and purpose so you can tick off what’s fetched.

---

## 5. Personalities — dere archetypes, tropes, distinct characters

**Design goal:** Each aspect is a *character*: recognizable archetype (dere/tropes), consistent voice, fanfic-level prose in the prompt so the model stays in role.

**Archetype mapping (short)**

| Aspect | Dere / trope | Role |
|--------|----------------|------|
| **Morrigan** | Tsundere (harsh type) / Good Is Not Nice, The Stoic | Engineer; blunt, precise; silence = compliment. |
| **Nyx** | Kuudere / The Omniscient, Slow and Steady | Researcher; cold warmth, implication, depth. |
| **Echo** | Deredere (warm) / The Heart, The Mirror | Companion; reflects, remembers, one question that matters. |
| **Eris** | Chaos archetype / Cloud Cuckoo Lander, Weaponized Sincerity | Banter, games, feral wit. |
| **Lilith** | Authority / Ancient, Incorruptible, The Boundary | Core will; rare, heavy, final. |
| **Lilith (NSFW)** | Same as Lilith; intimate/NSFW register | Toggle by keyword (e.g. intimate, nsfw) in message. |
| **Neuro** | Same chaos pool as Eris, more “says it” gremlin | Unfiltered, short sentences, trails off. |

**Implementation**

- **Existing:** Each personality JSON has `systemPromptAddition`, `voice`, `traits`, `triggers`. The orchestrator injects `systemPromptAddition` into the system head; selection is by `force_aspect` or trigger-score.
- **Enhancement:** Add optional fields for writers: `archetype`, `tropes`, `speech_patterns`, `backstory_snippet`, `do_not_do`. These are for consistency and future prompt-building; the model only sees what’s in `systemPromptAddition` (and any lens/identity text).
- **Fanfic-level prose:** Expand `systemPromptAddition` so each aspect has 2–4 short paragraphs: who they are, how they speak, what they don’t do, and a concrete example or two. Keep tone and vocabulary distinct (Morrigan: cutting, technical; Nyx: layered, precise; Echo: warm, reflective; Eris: punchy, chaotic).

Personality files live in `personalities/*.json`. No code change required to add archetype/trope fields—only the prompt text and optional metadata need to be fleshed out.

---

## 6. Next steps (actionable)

1. **Capabilities:** Use this doc as the single reference; keep it updated when you add routes or tools.  
2. **Extension:** Add tools in `registry.py`, aspects in `personalities/`, knowledge in `knowledge/` + fetch script/config.  
3. **Knowledge:** Add a `knowledge/KNOWLEDGE_LIBRARY_FULL.md` listing every slug and run `fetch_knowledge.py` so the full set is downloaded and indexed.  
4. **Personalities:** Flesh out each JSON with `archetype`, `tropes`, and richer `systemPromptAddition` (fanfic-level); keep voices distinct.  
5. **Comparison:** Revisit when you add doc loaders, RAG citations, or trace id; update the comparison table.

Learnings live in **layla.db** (and optionally the vector store), not in `learnings.json`—this is reflected in the rules and README where applicable.
