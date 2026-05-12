# Final System Readiness Audit

**Date:** Pre-launch integration + reliability pass.  
**Scope:** Research lab, research brain, mission state, runtime limits, progress guard, usefulness gate, knowledge/cognitive layers, UI, output, safety.  
**No new systems added; no safety or approval changes.**

---

## 1. Research Lab Sandbox — CONFIRMED

- **`.research_lab/` copy flow:** `_copy_source_to_lab(workspace_root)` in `main.py` creates `RESEARCH_LAB_WORKSPACE` and `RESEARCH_LAB_SOURCE_COPY`, runs `shutil.rmtree(dst)` if `dst` exists then `shutil.copytree(src, dst, ...)`. Repo copy clears and re-copies safely.
- **write_file:** In `agent_loop.py`, when `state.get("research_lab_root")` is set, `write_file` is rejected unless `_path_under_lab(path, lab_root)` is true. Message: "Writes allowed only inside .research_lab".
- **run_python:** When `research_lab_root` is set, `run_python` is rejected unless `_path_under_lab(workspace, lab_root)` (cwd) is true. Message: "run_python allowed only with cwd inside .research_lab".
- **shell:** When `research_lab_root` is set, shell returns `ok: False`, `reason: "not_allowed_in_research"`, "shell not allowed in research missions".
- **apply_patch:** When `research_lab_root` is set, apply_patch returns same not-allowed-in-research response.

**Status:** Working as designed. No code changes.

---

## 2. Research Brain — CONFIRMED

- **Paths:** `agent/.research_brain/` created by `ensure_research_brain_dirs()` in `research_stages.py`. Subdirs include: `maps/`, `investigations/`, `verifications/`, `distilled/`, `strategic/` (plus intelligence subdirs).
- **Stage → file mapping (base 5):**
  - mapping → `maps/system_map.json`
  - investigation → `investigations/notes.md`
  - verification → `verifications/verified.md`
  - distillation → `distilled/knowledge.md`
  - synthesis → `strategic/model.md`
- **`/research_mission`** reads `mission_depth` and `next_stage` from request; uses `stages_for_depth(mission_depth, next_stage)` and `STAGE_RUNNERS`. Staged pipeline only when `mission_depth` is explicitly provided.
- **Continuity:** Each base stage calls `load_research_context(for_stage)` and appends "Previous context:\n" + continuity to the goal. Intelligence stages use `load_intelligence_context(for_stage)` in `research_intelligence.py`.

**Status:** Wired and in use. No fixes.

---

## 3. Mission State / Resume — CONFIRMED

- **`mission_state.json`:** Path `agent/.research_brain/mission_state.json`. `load_mission_state()` / `save_mission_state()` in `research_stages.py` read/write it. Default when missing: `{"stage": None, "progress": {}, "completed": []}`.
- **Per-stage completion:** Every stage runner (base + intelligence) calls `load_mission_state()`, appends its `stage_name` to `completed`, sets `state["stage"]`, calls `save_mission_state(mission)`.
- **Resume:** In `main.py` `/research_mission`, before the stage loop: `state = load_mission_state()`, `completed = state.get("completed") or []`. If `mission_depth is not None` and `completed` is non-empty, `stages_to_run` is filtered to exclude stages in `completed`. Already-completed stages are skipped; remaining stages run in order.
- **After restart:** Same flow: state is persisted on disk; next run loads it and skips completed stages.

**Status:** Working. No code changes.

---

## 4. Runtime Limits — CONFIRMED

- **research_max_tool_calls:** In `runtime_config.json`: `40`. `agent_loop.py` uses `cfg.get("research_max_tool_calls", 20)` when `research_mode` is true → 40.
- **research_max_runtime_seconds:** In `runtime_config.json`: `240`. `agent_loop.py` uses `cfg.get("research_max_runtime_seconds", 120)` when `research_mode` is true → 240.
- **max_mission_runtime_seconds:** In `main.py` `/research_mission`: `14400` (4 hours). Checked before each stage; on exceed: write `strategic/incomplete.md`, set `mission_status = "stopped"`, break.
- **Early conversational exit:** In `agent_loop.py`, when `research_lab_root` is set and not refused and not timeout, if `_research_response_asks_user(text)` is true, the loop does not append the step or set status finished; it updates goal with a reminder and continues.
- **Loop bounds:** Per-run limits (tool_calls, max_runtime) and mission-level 4h cap prevent infinite runs. Missions stop on timeout, tool_limit, or 4h.

**Status:** Configured and enforced. No code changes.

---

## 5. Progress Guard — CONFIRMED

- **No-progress detection:** `_run_stage` in `research_stages.py` and `research_intelligence.py` returns `status = "no_progress"` when `len(text) < 500`, else `"ok"`.
- **Abort after 2:** In `main.py` staged loop, if `status == "no_progress"` then `consecutive_no_progress += 1`; else reset to 0. If `consecutive_no_progress >= 2`, set `mission_status = "partial"` and break. Mission stops cleanly; state and outputs already written by completed stages.

**Status:** Working. No code changes.

---

## 6. Usefulness Gate — CONFIRMED

- **`is_useful_output(text)`** in `research_stages.py`: returns True if text (lowercased) contains any of: recommend, should, risk, improve, replace, refactor, adopt, avoid, opportunity, tradeoff.
- **Synthesis stage:** After `_run_stage`, if `not is_useful_output(md or "")`, appends `"\n\nINSUFFICIENT_ACTIONABLE_INSIGHT"` to `md`. Then writes to `strategic/model.md` and returns. Output is always saved.

**Status:** Working. No code changes.

---

## 7. Knowledge Layer — CONFIRMED

- **knowledge/:** `runtime_safety.load_knowledge_docs()` walks `REPO_ROOT / "knowledge"` for .md/.txt; used in `agent_loop.py` when building the prompt. Chroma fallback: `get_knowledge_chunks(goal, k)` from vector_store (indexed from `knowledge_dir` at startup in `main.py`).
- **knowledge/fetched/:** Under `knowledge/`; included in the same walk and in Chroma index when present.
- **lens_knowledge/:** `runtime_safety.load_lens_knowledge()` reads `lens_knowledge/*.md`. Injected when `cfg.get("enable_lens_knowledge")` is true in `agent_loop.py` prompt build.
- **Research:** Staged and single-pass missions use `autonomous_run` → `_llm_decision`, which includes knowledge (Chroma chunks + load_knowledge_docs) and lens_knowledge when enabled. No separate research-only path; same prompt assembly.

**Status:** Indexed and injected. Usable during research. No code changes.

---

## 8. Cognitive Layers — CONFIRMED

- **Order in prompt** (`agent_loop.py`): identity → cognitive_lens → lens_knowledge → behavioral_rhythm → ui_reflection → operational_guidance → personality_expression → workspace → memories → learnings → semantic → knowledge.
- **Flags:** `enable_cognitive_lens`, `enable_behavioral_rhythm`, `enable_ui_reflection`, `enable_lens_knowledge`, `enable_operational_guidance` read from config; each block appended only when enabled and non-empty.

**Status:** Loaded when enabled; order correct. No code changes.

---

## 9. UI Wiring — FIXED / EXPOSED

- **Before:** UI had workspace path, "Research repo (read-only)" (→ `/research`). No control for `/research_mission`, `mission_depth`, or `next_stage`.
- **Added (minimal, no redesign):**
  - **Mission depth selector:** `<select id="mission-depth">` with options `map`, `deep`, `full` (default `deep`).
  - **Next stage toggle:** `<input type="checkbox" id="next-stage">` label "Next stage".
  - **Research mission (staged) button:** "Research mission (staged)" calls `startResearchMission()` which POSTs to `/research_mission` with `workspace_root`, `mission_depth`, `next_stage`, `mission_type: 'repo_analysis'`, shows typing indicator, then displays `data.response` and optional mission depth / stages run line via `addMsg`.
- **Existing:** Workspace path input (used for both Research and Research mission). Stream toggle applies to `/research` only. Output visibility: response shown in chat; note "Output also saved to agent/.research_output/last_research.md" already present.

**Status:** Staged mission trigger, depth selector, next-stage toggle, and workspace path are exposed. Output visible in chat and on disk.

---

## 10. Output Confidence — CONFIRMED + FIXED

- **last_research.md:** Written in `main.py` when `response_text` is non-empty. Staged path sets `response_text` from `combined_md`; on resume when all stages already completed, `combined_md` was empty so nothing was written.
- **Fix:** When staged path runs but after resume filter there are no stages to run, `response_text` is set to: "Mission resume: all stages already completed. No new stages run this session. See .research_brain/ for prior outputs." Write condition changed from `if response_text and result.get("status") not in (...)` to `if response_text` so that this message and any other non-empty response always produce `last_research.md` (and timestamped copy).
- **Stage outputs:** Each stage runner writes to its `.research_brain/` path before returning. On timeout or no-progress abort, stages that already ran have written their outputs; `strategic/incomplete.md` is written on 4h timeout.

**Status:** Every mission run now produces `.research_output/last_research.md`. Stage outputs remain in `.research_brain/` per stage. Fixed: resume-all-complete and unconditional write when `response_text` is set.

---

## 11. Final Safety Check — CONFIRMED

- **Approval flow:** Unchanged. `require_approval(tool_name)` and pending approvals used as before for write_file, run_python, apply_patch, shell when not in research.
- **Refusal logic:** Unchanged. Refusal parsing and handling in agent_loop unchanged.
- **SAFE_TOOLS / DANGEROUS_TOOLS:** Unchanged in `runtime_safety.py`. No new tools; no permission changes.
- **Sandbox:** No bypass. Research-mode restrictions (write_file/run_python under lab only; shell/apply_patch blocked) remain in place.

**Status:** No changes to approval, refusal, tool lists, or sandbox. Safety intact.

---

## What Was Confirmed Working

- Research lab copy, write_file/run_python restriction to lab, shell/apply_patch blocked in research.
- Research brain dirs and stage → file mapping; mission_depth and next_stage in `/research_mission`; load_research_context / load_intelligence_context for continuity.
- Mission state load/save; each stage marks completion; resume skips completed stages.
- research_max_tool_calls (40), research_max_runtime_seconds (240), max_mission_runtime_seconds (14400); early-question prevention; loop limits.
- Progress guard (no_progress when output < 500 chars; abort after 2 consecutive).
- Usefulness gate in synthesis (INSUFFICIENT_ACTIONABLE_INSIGHT append; output still saved).
- Knowledge and lens_knowledge indexing and injection; cognitive/behavioral/UI/operational layers when enabled.
- Safety: approval flow, refusal, SAFE_TOOLS/DANGEROUS_TOOLS, sandbox unchanged.

---

## What Was Wired

- Staged pipeline uses mission_state for resume and final status.
- Staged loop uses runner return (md, data, status) for progress guard and always writes last_research when response_text is set.

---

## What Was Fixed

- **Output:** When mission_depth is set but all stages are skipped (resume with nothing to run), `response_text` is set to a short resume message and `last_research.md` is written.
- **Write condition:** `last_research.md` (and timestamped copy) written whenever `response_text` is non-empty, not gated on status.

---

## What Was Exposed in UI

- Mission depth selector: map | deep | full.
- Next stage checkbox.
- "Research mission (staged)" button: POSTs to `/research_mission` with workspace_root, mission_depth, next_stage; shows response and mission depth/stages run in chat.

---

## What Will Happen During a 24h Unattended Run

- **Start:** Client (or scheduler) POSTs `/research_mission` with e.g. `mission_depth: "full"`, `workspace_root`, optional `next_stage`. Repo is copied to `.research_lab/.../source_copy`. Mission state is loaded; completed stages are skipped (resume).
- **Per stage:** Each remaining stage runs in order. Goal includes previous stage context from `.research_brain/`. Stage runs in research_mode (write/run only under .research_lab; shell/apply_patch blocked). Per-stage limits: 40 tool calls, 240 s runtime. If output < 500 chars, status is no_progress; after 2 consecutive no_progress, mission stops with status "partial". Before each stage, if elapsed time > 4 h, mission writes `strategic/incomplete.md` and stops with status "stopped".
- **After each stage:** Output is written to the correct `.research_brain/` path; mission_state is updated (stage appended to completed, stage set).
- **Synthesis:** If output lacks usefulness signals, "INSUFFICIENT_ACTIONABLE_INSIGHT" is appended; output is still saved.
- **End:** Mission state is saved with `last_run`, `completed`, `status` (complete | partial | stopped). Combined stage output is written to `agent/.research_output/last_research.md` and a timestamped copy. If all stages were already completed (resume), a short resume message is written to `last_research.md`.
- **Safety:** No approval or sandbox changes; no writes outside .research_lab; no shell/apply_patch in research. Missions stop on 4h cap, tool/timeout limits, or 2× no_progress.

---

**Audit complete. No speculation; no redesign.**
