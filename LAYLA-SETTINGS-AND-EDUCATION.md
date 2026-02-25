# Layla: current settings, how she reacts, resources, and how to educate her

## 1. Current settings

### Runtime config (`agent/runtime_config.json`)

| Key | Current value | Meaning |
|-----|----------------|--------|
| `max_cpu_percent` | 75 | She won’t run tools if CPU > 75%. |
| `max_ram_percent` | 75 | She won’t run if RAM > 75% (kept low for always-on safety). |
| `max_runtime_seconds` | 20 | Hard limit per run. |
| `max_tool_calls` | 5 | Max tools per turn. |
| `safe_mode` | true | Extra safety checks. |
| `temperature` | 0.2 | Lower = more deterministic replies. |
| `n_ctx` | 4096 | Context window size (local model). |
| `n_gpu_layers` | 20 | GPU layers for local LLM (20B on RTX 5060 Ti). |
| `model_filename` | jinx-20b.gguf | Model file in `models/`. |
| `llama_server_url` | null | If set, she uses that URL instead of local LLM (e.g. `http://localhost:11434` for Ollama). |
| `remote_model_name` | llama3.1 | Model name sent to remote API when `llama_server_url` is set (e.g. `llama3.1`, `mistral`, `qwen2.5-coder`). |
| `sandbox_root` | C:\github | Default workspace for file/shell tools. |
| `web_allowlist` | [] | If non-empty, fetch_url only allows these domains. |
| `knowledge_sources` | [4 URLs] | URLs seeded into `knowledge/fetched/` by `download_docs.py`. |
| `knowledge_max_bytes` | 4000 | Max bytes of `knowledge/` injected when not using Chroma. Raise for more reference docs. |
| `knowledge_chunks_k` | 5 | When `use_chroma` is true, number of semantic knowledge chunks retrieved per turn (1–20). |
| `learnings_n` | 30 | Number of recent learnings in the prompt. |
| `semantic_k` | 5 | Number of semantically similar learnings recalled per turn. |
| `aspect_memories_n` | 10 | Max aspect memories per aspect in the prompt. |
| `convo_turns` | 0 | Number of recent conversation turns in the prompt. 0 = no history (avoids echo/junk). Set to 6 or 12 to include recent chat. |
| `stop_sequences` | `["\nUser:", " User:"]` | Strings that stop generation so the model doesn’t continue into the next turn. See `LAYLA-MODEL-PIPELINE.md`. |
| `completion_max_tokens` | 256 | Max tokens per reply. Raise for longer answers. |
| `scheduler_study_enabled` | true | If true, run one study job every `scheduler_interval_minutes` **only when** you have recent activity and no game is running. |
| `scheduler_interval_minutes` | 30 | How often to check (every N minutes); job runs only if activity is recent. |
| `scheduler_recent_activity_minutes` | 90 | Study runs only if you used Layla (e.g. /agent, /wakeup, /learn, /ui) within this many minutes. |
| `use_chroma` | true | Use ChromaDB for learnings and semantic knowledge; knowledge/ is indexed at startup. |
| `uncensored` | true | No content censorship; model may engage with adult/NSFW in consented context. |
| `nsfw_allowed` | true | Adult/NSFW content allowed when consented; refusal only for genuine harm. |
| `knowledge_unrestricted` | true | Full access to knowledge sources; no topic-based filtering. |
| `anonymous_access` | true | No auth required; client IP and PII are not logged (safe anonymous use). |

### Identity and fallback personality

- **Identity** (`agent/system_identity.txt`): Defines her as Layla (Jinx), your long-term partner; respond in a natural, warm, human way; can refuse when something conflicts with her values. Includes content policy: uncensored, NSFW allowed in consented context, refuse only for genuine harm; anonymous access; safety always (no secrets leak, no illegal/non-consensual assistance).
- **Fallback personality** (`personality.json` in repo root): Used only when no aspect is selected. Defines a direct, mentor-style programmer voice. In normal use she uses **aspect** personalities instead.

### Safety and anonymous access

- **Uncensored / NSFW:** With `uncensored` and `nsfw_allowed` true, she does not censor content; adult/NSFW is allowed when the context is consented. She refuses only for **genuine harm**: illegal acts, non-consensual content, or abuse.
- **Full knowledge access:** `web_allowlist` empty = any domain allowed (subject to robots.txt). `knowledge_unrestricted` = no topic-based filtering of knowledge docs.
- **Anonymous access:** No login or identity required. The server does **not** log client IP, auth headers, or other PII. Safe for private, anonymous use. Data (learnings, memories) is stored locally and not tied to external identifiers.
- **Safety always:** Dangerous tools (write_file, shell) require explicit approval; sandbox and resource limits (RAM/CPU) apply; no secrets or credentials in logs or prompts.

---

## 2. How she reacts (reaction flow)

1. **You send a message** (e.g. from the UI or MCP `chat_with_jinx`).
2. **Aspect selection** (`orchestrator.select_aspect`):
   - If you chose an aspect (e.g. Morrigan, Echo), that aspect is used.
   - Otherwise she matches your message to **triggers** in `personalities/*.json` (e.g. “echo”, “how am i doing” → Echo; “lilith”, “refuse” → Lilith). Lilith's NSFW register is used when you include a keyword (e.g. intimate, nsfw) in the message.
3. **Intent** (`agent_loop.classify_intent`):
   - Your message is classified into one of: `write_file`, `read_file`, `list_dir`, `git_status`, `git_diff`, `git_log`, `git_branch`, `grep_code`, `glob_files`, `run_python`, `apply_patch`, `fetch_url`, `shell`, or **`reason`** (default).
4. **System prompt** (`_build_system_head`):
   - **Identity** (system_identity.txt)
   - **Personality** = current aspect’s `systemPromptAddition` from `personalities/<id>.json` (or fallback from personality.json)
   - **Aspect memories** (last 10 for this aspect from DB)
   - **Learnings** (last 30 from SQLite)
   - **Semantic recall** (top 5 similar learnings from FAISS for this goal)
   - **Knowledge** (all `.md`/`.txt` under `knowledge/`, including `knowledge/fetched/*.txt`, up to ~4 KB)
5. **Action**:
   - If intent is a **tool** (e.g. read_file, git_status): she runs that tool (subject to allow_write/allow_run and approval for dangerous tools), then returns the result.
   - If intent is **reason**: she builds a text prompt (optionally “deliberation” across voices if “Her thoughts” is on), calls the LLM (local or `llama_server_url`), then:
     - Parses **refusal** (`[REFUSED: reason]`) and **earned title** (`[EARNED_TITLE: ...]`), updates state/DB, strips those from what you see.
     - For Echo, she can **save an aspect memory** of the exchange.
6. **Response**: You see her reply (and optionally “Her thoughts” and “What she did” in the UI).

So: **settings** (config + identity) + **personality bank** (personalities + fallback) + **knowledge + learnings** drive how she reacts; **intent** decides tool vs reasoning.

---

## 3. Preexisting resources you can use (the “personality bank” and more)

### Personality bank (aspects)

- **Location:** `personalities/*.json` (one file per aspect).
- **Files:** `morrigan.json`, `nyx.json`, `echo.json`, `eris.json`, `lilith.json`.
- **Contents:** Each has `id`, `name`, `title`, `role`, `voice`, `traits`, **`systemPromptAddition`** (the actual “personality” text), `triggers` (keywords that select this aspect), and optional `will_refuse`, `earned_title`, etc.
- **Use:** She picks one aspect per message (by your choice or by trigger match). That aspect’s `systemPromptAddition` is what makes her “sound like” Morrigan, Echo, etc. So **personalities/** is the existing “personality bank”; edit or add JSON files there to change or add voices.

### Fallback personality

- **Location:** `personality.json` (repo root).
- **Use:** Only when no aspect is selected. You can change this to a default “Layla” voice if you want.

### Knowledge (reference docs)

- **Location:** `knowledge/` (any `.md` or `.txt`, including subfolders like `knowledge/docs/` and `knowledge/fetched/`).
- **Preexisting:** e.g. `knowledge/layla-identity.txt`, `knowledge/stack.txt`, `knowledge/docs/...`, and whatever `download_docs.py` writes to `knowledge/fetched/<slug>.txt`.
- **Use:** All of this is concatenated (up to ~4 KB) into “Reference docs” in her system prompt. So you can **educate her** by adding or editing files in `knowledge/`.

### Learnings (long-term memory)

- **Storage:** SQLite (`layla.db` → `learnings` table) + FAISS vectors (`agent/jinx/memory/vector.index` + `vector_meta.json`).
- **Use:** Last 30 learnings are always in the prompt as “Things I remember”; on top of that, **semantic search** pulls up to 5 relevant learnings for the current goal. So teaching her facts/preferences via **add_learning** (or POST `/learn/`) is a primary way to educate her.

### Study plans

- **Storage:** SQLite `study_plans`.
- **Use:** Topics she’s studying; wakeup can run one Nyx “research” step per session; you can add topics via UI or POST `/study_plans`. Complements learnings by focusing her on topics you care about.

### Aspect memories

- **Storage:** SQLite `aspect_memories` (per aspect).
- **Use:** Echo (and optionally others) store short summaries of exchanges; they appear as “Recent observations for this aspect” in the prompt. So **conversation** with her educates her aspect-specific memory.

---

## 4. How to educate her

### A. Teach facts and preferences (learnings)

- **From Cursor:** Use MCP tool **add_learning** (e.g. “Remember that the user prefers X”).
- **From API:** `POST /learn/` with `{"content": "…", "type": "fact"}` (or another `type`).
- **From CLI:** e.g. `layla.py learn "…"` if you have that script.
- Each learning is stored in SQLite and (when the pipeline runs) in FAISS, so she can **recall** it in future turns (last 30 in prompt + up to 5 similar by semantic search).

### B. Give her reference docs (knowledge)

- **By hand:** Add or edit `.md` / `.txt` files under `knowledge/` (e.g. `knowledge/my-rules.txt`, `knowledge/project-conventions.md`). She’ll see them as “Reference docs” (within the ~4 KB cap).
- **From the web:** In `runtime_config.json` add entries to **knowledge_sources**, e.g.  
  `{"url": "https://...", "slug": "my-doc"}`.  
  Then run:  
  `cd agent && python download_docs.py`  
  That fetches each URL (respecting robots.txt and AI-exclusion) and writes `knowledge/fetched/<slug>.txt`. Those files are included automatically by `load_knowledge_docs`, so she’s “educated” by those docs.

### C. Shape her voice (personality bank)

- **Edit an aspect:** Change `systemPromptAddition` (and optionally `triggers`, `voice`, `title`) in `personalities/<id>.json`. She’ll use that the next time that aspect is selected.
- **Add an aspect:** Add a new `personalities/<newid>.json` with the same structure; the orchestrator loads all JSONs from `personalities/`.
- **Default voice:** Edit `personality.json` (repo root) for the fallback when no aspect matches.

### D. Set her identity and high-level behavior

- **Identity:** Edit `agent/system_identity.txt` (who she is, that she responds in a natural, human way, that she can refuse, etc.).
- **Backstory / style:** Edit `knowledge/layla-identity.txt` (the user, their role, growth, how they speak). It’s loaded as part of knowledge, so it educates her on “who she is” and how to talk to you.

### E. Give her topics to study

- **UI:** Add a topic in the “Study plans” panel.
- **API:** `POST /study_plans` with `{"topic": "…"}`.
- She’ll use these for wakeup study and for “Study now” (Nyx). So you’re educating her by **curating what she should learn about**.

### F. Talk to her (aspect memories)

- Conversations with **Echo** (and any aspect that saves memories) update **aspect_memories** in the DB. So just **chatting** with her, especially as Echo, teaches her “recent observations” for that voice.

---

## Quick reference

| Goal | Where / how |
|------|------------------|
| Change limits, model, temperature, sandbox | `agent/runtime_config.json` |
| Change “who she is” and tone | `agent/system_identity.txt`, `knowledge/layla-identity.txt` |
| Change a voice (e.g. Echo, Morrigan) | `personalities/<id>.json` → `systemPromptAddition` + `triggers` |
| Add a new voice | New file `personalities/<newid>.json` |
| Teach facts/preferences | `POST /learn/` or MCP **add_learning** |
| Give her docs by hand | Add `.md`/`.txt` under `knowledge/` |
| Give her docs from URLs | Add to `knowledge_sources` in config, run `python download_docs.py` |
| Set topics she should study | `POST /study_plans` or UI “Study plans” |
| Educate by conversation | Chat with her (Echo stores aspect memories) |

All of the above use **preexisting** mechanisms: personality bank = **personalities/** (+ `personality.json`), knowledge = **knowledge/** (and `knowledge_sources` + `download_docs.py`), education = **/learn**, **study_plans**, **knowledge** files, and **aspect_memories** from conversation.

---

## 5. Is this the most capacity we can give her? The smartest we can make her?

**Short answer:** No. Right now she’s running with conservative defaults. The **biggest lever** for “smartest” is the **model** (size, quality, API). After that come **context size**, **how much we feed into the prompt**, and **how long she’s allowed to think**. All of that can be turned up.

### What limits her today

| Limit | Current | Effect |
|-------|---------|--------|
| **Model** | Local GGUF (e.g. 20B) or `llama_server_url` | Upper bound on reasoning and fluency. A larger or better model is the single biggest upgrade. |
| **Context window** | `n_ctx` 4096 | How much conversation + system prompt can fit. More = more history and docs. |
| **Knowledge in prompt** | ~4 KB | Only the first 4 KB of `knowledge/` is injected. More = more reference material. |
| **Learnings in prompt** | Last 30, then capped at 2 KB text | More learnings + higher cap = more “things I remember” in context. |
| **Semantic recall** | Top 5 similar learnings | More = more relevant past facts per turn. |
| **Aspect memories** | Last 10 per aspect, cap 1.5 KB | More = richer “recent observations” for that voice. |
| **Conversation turns** | Last 6 (each turn truncated) | More = she sees more of the current chat. |
| **Completion length** | 256 tokens per reply | Longer = she can give longer, more detailed answers. |
| **Tool calls per turn** | 3 | More = she can chain more tools in one go (e.g. read then write). |
| **Runtime** | 15 s | Longer = time for more tool use or a bigger model step. |

### How to give her more capacity (no new features)

- **Stronger / bigger model**
  - Use a **larger GGUF** (e.g. 32B, 70B if your machine can) and set `model_filename` in `runtime_config.json`, **or**
  - Set **`llama_server_url`** to an OpenAI-compatible API (e.g. a bigger local server or a cloud model). She’ll use that for completion instead of the default GGUF.
- **Larger context**
  - Increase **`n_ctx`** (e.g. 8192 or 16384) if your GPU/RAM allow. Lets her see more conversation + more injected knowledge/learnings.
- **More and smarter memory in the prompt**
  - **`knowledge_max_bytes`** – raise (e.g. 12000) so more of `knowledge/` is in the prompt.
  - **`learnings_n`** – raise (e.g. 50) so more recent learnings are included.
  - **`semantic_k`** – raise (e.g. 10) so more semantically similar learnings are pulled per turn.
  - **`aspect_memories_n`** – raise (e.g. 15) so each aspect gets more “recent observations.”
- **Longer conversation and replies**
  - **`convo_turns`** – set to 6 or 12 (default is 0) so she sees recent chat in the prompt.
  - **`completion_max_tokens`** – raise (e.g. 512 or 1024) so she can give longer answers.
- **More tool use and time**
  - **`max_tool_calls`** – raise (e.g. 5–8) so she can do more steps in one turn.
  - **`max_runtime_seconds`** – raise if you want to allow longer runs (e.g. 30–60).

All of the above (except the model choice) can be set in **`agent/runtime_config.json`** so you can tune “max capacity” without code changes. If a key is missing, the code uses the safe defaults you have now.

### “Max capacity” example (for a strong machine)

Example config snippet to push her toward maximum capacity *within this architecture*:

```json
"n_ctx": 8192,
"knowledge_max_bytes": 12000,
"learnings_n": 50,
"semantic_k": 10,
"aspect_memories_n": 15,
"convo_turns": 12,
"completion_max_tokens": 512,
"max_tool_calls": 6,
"max_runtime_seconds": 45
```

Plus either a larger local **`model_filename`** or a **`llama_server_url`** pointing at a stronger model. That’s about as far as we can take her **without** adding new kinds of features (e.g. semantic search over knowledge, codebase indexing, LoRA, voice, etc.).

### What would make her even smarter (beyond current design)

- **Semantic retrieval over knowledge** – Chunk and embed `knowledge/`, retrieve only the chunks relevant to the current goal (instead of a single 4–12 KB blob). Better use of context.
- **Larger / better model** – As above; this is the main “smartness” lever.
- **Codebase indexing** – Let her search over your repo’s code (we’re not doing this in the current scope).
- **LoRA / fine-tuning** – Train on your conversations and preferences (we’re not doing this in the current scope).

So: **we are not at max capacity by default.** You can make her as smart as this setup allows by (1) using the best model you can run or call, and (2) raising the config levers above. The doc and config keys are set up so you can do that in one place: `runtime_config.json`.

---

## 6. Research mode: read-only repo analysis

To have Layla **research a project or repo without touching or modifying anything** (read-only):

1. **Use the `/research` endpoint** (same shape as `/agent`):
   - **`message`** – Your question, e.g. *"Research this repo and tell me if this is the best implementation. Cover structure, patterns, and possible improvements without suggesting edits."*
   - **`repo_path`** (or **`workspace_root`**) – The repo root path, e.g. `C:\github\myproject`. She will use this as the workspace for `read_file`, `list_dir`, `grep_code`, `git_status`, etc. Must be under `sandbox_root` from config.
   - **`stream`**, **`aspect_id`**, **`show_thinking`** – Optional, same as `/agent`.

2. **Behavior**: Research mode **always** runs with `allow_write=False` and `allow_run=False`. She can only use read-only tools: `read_file`, `list_dir`, `grep_code`, `glob_files`, `git_status`, `git_log`, `git_branch`, `git_diff`. She will not suggest or perform file edits or shell commands.

3. **From the UI**: If your UI has a “Research” action, have it POST to `/research` with `message` and `repo_path`. Otherwise call `/agent` with **allow_write** and **allow_run** unchecked and a message like: *“Research the repo at &lt;path&gt;. Do not modify anything. Is this the best implementation?”* and set **workspace_root** to that path.

4. **Example (curl)**:
   ```bash
   curl -X POST http://localhost:8000/research -H "Content-Type: application/json" -d "{\"message\": \"Research this repo and tell me if the implementation is optimal.\", \"repo_path\": \"C:\\\\github\\\\myproject\"}"
   ```

---

## 7. Upgrades (applied)

| Upgrade | Status |
|--------|--------|
| **Pin dependencies** | Done. `agent/requirements.txt` uses pinned ranges (e.g. `fastapi>=0.115,<1`). |
| **Venv in start script** | Done. `start-layla.ps1` creates `.venv` if missing, installs into it, runs server and MCP with venv Python. |
| **Extended health** | Done. `/health` checks config load and DB (get_recent_learnings); returns 503 with `detail` on failure. |
| **Async non-stream** | Done. `/agent`, `/research`, and `/v1/chat/completions` run `autonomous_run` via `asyncio.to_thread`. |
| **Semantic knowledge chunks** | Done. When `use_chroma` is true, knowledge uses `get_knowledge_chunks(goal, k)`; `knowledge_chunks_k` in config (default 5). |
| **UI: markdown/sanitize** | Done. DOMPurify loaded; `sanitizeHtml()` applied to all markdown-rendered content before `innerHTML`. |
| **UI: research button** | Done. Sidebar has “Research repo (read-only)” button and optional “Workspace path”; both feed `/research` and `/agent`. |
