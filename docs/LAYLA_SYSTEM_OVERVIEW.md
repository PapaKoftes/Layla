# Layla — System Overview (Easy to Understand)

This document explains **what Layla is**, **how she works**, and **what you can do with her right now**. Use it to evaluate the product, explain it to others, or onboard yourself.

---

## What Is Layla?

**In one sentence:** Layla is a **local AI partner** that runs on your machine, remembers you over time, and helps with real work—code, fabrication, documentation, planning—while staying one consistent “person” with clear safety rules.

**She is not:**  
A generic chatbot. A cloud service. Something that forgets you between sessions.

**She is:**  
A single persistent “being” with different **modes** (aspects), a **memory** that grows, and **guards** so she never changes your files or runs code without your explicit approval.

---

## How Does She Run?

- **One server** on your computer: `agent/main.py` (FastAPI at `localhost:8000`).
- **One database** on your computer: `layla.db` — learnings, study plans, project context, capabilities, audit log. Everything stays local.
- **One AI model** (your own GGUF, via llama-cpp-python). No data is sent to the cloud for the core chat/agent loop.
- **Optional:** A vector store (e.g. FAISS) for semantic search over memories; configurable.

So: **local-first**. Your machine, your data, your model.

---

## The Five “Voices” (Aspects)

Layla has one mind but five **aspects**—different ways she responds, depending on what you need. You don’t have to pick every time; certain words in your message can auto-select an aspect.

| Aspect | When she shows up | What she’s for |
|--------|-------------------|----------------|
| **Morrigan** (default) | Code, debug, implement, fix, refactor, architecture, DXF, automation | **Execution.** Gets things done. Blunt, fast. Prioritizes: planning, docs, Python, DXF→fabrication. |
| **Nyx** | Research, study, explain, analyze, deep dive, parametric, CNC, geometry | **Knowledge.** Learns and explains. Slow, precise. Fabrication and domain learning. |
| **Echo** | “How am I”, “notice”, “remember”, “check in”, “hey”, “hi”, session start | **Patterns.** Tracks how you work, recurring blockers, drift. Greets you on wakeup. |
| **Eris** | Banter, games, music, chaos, “what do you think of” | **Creativity.** Alternative ideas, unconventional angles. Playful. |
| **Lilith** | “Lilith”, “refuse”, “ethics”, “is this wrong”, “tell me the truth” | **Authority.** Final say. Gates file changes, code run, and what gets “learned.” |

You can also **force** an aspect: e.g. “as Nyx, explain…” or by passing `aspect_id` in the API.

**Deliberation:** For bigger decisions you can ask her to “think out loud” with all aspects (feasibility, knowledge, alignment with you, creative option, risk), then she answers **as Morrigan** with one conclusion.

---

## How Can I Talk to Her?

You have **four main ways** to interact:

1. **Web UI**  
   Start the server, open `http://localhost:8000/ui`. Chat in the browser; see study plans and pending approvals.

2. **CLI (terminal)**  
   `python layla.py wakeup` — greeting + study status.  
   `python layla.py ask "your message"` — send a message.  
   `python layla.py study "topic name"` — add a study topic.  
   `python layla.py plans` — list study plans.  
   `python layla.py approve <uuid>` — approve a pending action.  
   `python layla.py export` — full system snapshot.

3. **TUI (terminal app)**  
   `cd agent && python tui.py`. Rich terminal interface: chat, wakeup, approve, switch aspect.

4. **From Cursor (or any MCP client)**  
   Use the **MCP tools** that talk to Layla:
   - **chat_with_layla** — main chat; pass message, context, workspace; set `allow_write` / `allow_run` only when you want her to act.
   - **add_learning** — make her remember something (preferences, facts, corrections).
   - **start_study_session** — start a study session on a topic.
   - **analyze_repo_for_study** — ask her what to study next for this repo.

So: **browser, terminal, or inside your editor**—all hit the same Layla instance.

---

## What Can She Do Right Now? (Capabilities)

Here’s what is **implemented and usable today**.

### 1. **Chat and assist**
- Answer questions, explain code, suggest structure.
- Respond in the right “voice” (aspect) from context or your choice.
- Deliberate (multi-aspect reasoning) when you ask (“show me your thinking”, “what do you think”, long messages).

### 2. **Read and understand your workspace**
- **Project context:** She knows the current project name, lifecycle stage (idea / planning / prototype / iteration / execution / reflection), key files, and goals—if you set them (e.g. via `POST /project_context` or DB). She uses this to tailor help.
- **File understanding:** She can **interpret intent** (not edit) for many file types:
  - **Geometry:** .3dm, .gh, .dxf, .dwg, .step, .stp, .iges, .igs, .stl, .obj  
  - **Fabrication:** .nc, .gcode, .tap, .sbp, and similar  
  - **Code/config:** .py, .ipynb, .json, .yaml, .toml  
  - **Docs:** .md (and type hints for .pdf, .docx)  
  - **Images:** .png, .jpg, .svg  
  For DXF she can list layers/entities; for Python she can use docstrings/imports; for Markdown, headings. Rest get format + intent from context.

### 3. **Act on your machine (only with approval)**
- **Tools she can use** when you allow it: read file, list directory, write file, run Python, grep, git-related actions, etc.
- She **never** writes or runs code without **approval**. If she wants to do something that changes things, she returns an `approval_id`; you run `layla approve <uuid>` (or use Web UI / API). Only then does the action run.
- **Lilith** is the internal gate: file modification, autonomous execution, and what gets reinforced in memory are all gated.

### 4. **Remember and learn**
- **Learnings:** You (or she, via tools) can add **persistent** facts, preferences, and corrections (`add_learning`). She uses these in every conversation.
- **Study plans:** She has a list of topics she’s “studying” (e.g. fabrication, Python, writing). On **wakeup** she can run one study step (e.g. research a topic and summarize). Optional **scheduler** can do one study step in the background while you’re active.
- **Capabilities:** Her growth is tracked by **domain** (e.g. coding, fabrication, writing). When she completes a study session, the outcome is scored for **usefulness**. Only high-usefulness outcomes strongly reinforce her “level” in that domain; low usefulness doesn’t spread. So she gets better where it matters, and doesn’t fill up on noise.

### 5. **Project awareness**
- You can set **project name**, **lifecycle stage**, **domains**, **key files**, **goals** (API: `GET/POST /project_context`). She sees this in context and can tailor planning, documentation, and fabrication help.

### 6. **Safety and control**
- **Approval flow** for any write/run/patch.
- **Refusals:** She can refuse requests that conflict with her values (ethics, harm, etc.).
- **No cloud dependency** for the core loop; your data stays local.

---

## What’s “Finalized” vs “Future”?

**Finalized (in place and usable):**
- North Star vision doc and implementation status map.
- Five aspects (Morrigan, Nyx, Echo, Eris, Lilith) and structured deliberation.
- Project context + lifecycle + GET/POST API.
- File ecosystem (intent understanding for all North Star file types).
- Learning with usefulness scoring and selective reinforcement.
- Study plans, wakeup, scheduler (optional).
- Approval flow and Lilith as gate.
- Local-first server and DB.
- CLI, TUI, Web UI, and MCP (Cursor) integration.

**Future (designed, not built yet):**
- **Remote command:** Architecture is local-first; “remote” could be added later without changing identity or safety.
- **Project discovery:** Her proactively detecting opportunities or suggesting new projects (would still be gated).
- **Initiative:** Her suggesting improvements or next steps on her own—always through approval.

---

## How to Explain the Product to Others

You can say:

- **“Layla is a local AI partner that runs on my machine. She has one persistent identity and memory, and five ‘modes’—execution, knowledge, patterns, creativity, and authority. She helps with code, fabrication, docs, and planning, and she never touches my files or runs code without my approval. She gets better over time in areas that actually matter, and she’s built to stay aligned with my workflow and grow with me over years.”**

For technical listeners:

- **“Single FastAPI server, one SQLite DB, local GGUF model. Project context and lifecycle, file-intent understanding for geometry/fabrication/code/docs. Capability domains with usefulness-weighted learning. Approval-gated tools. MCP for Cursor, plus CLI/TUI/Web UI.”**

---

## Quick Reference: Start and Daily Use

1. **Start:** `cd agent && uvicorn main:app --host 127.0.0.1 --port 8000`
2. **Open:** `http://localhost:8000/ui` or run `python layla.py wakeup`
3. **Set project (optional):** `POST http://localhost:8000/project_context` with `{"project_name": "MyProject", "lifecycle_stage": "planning", "goals": "..."}`
4. **Chat:** In UI, or `python layla.py ask "your message"`, or in Cursor via MCP `chat_with_layla`
5. **When she asks for approval:** `python layla.py approve <uuid>` or use the Web UI Approvals panel

That’s the system you have today: a **local, persistent, multi-aspect partner** with project awareness, file understanding, selective learning, and strict safety—ready to use and to evolve with you.
