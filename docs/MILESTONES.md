# Milestones (M1–M6)

Target shape for stabilize, research docs, study docs, approval docs, extensibility, and optional enhancements.

---

## M1 — Stabilize and document

- **DB path**: Documented. Database is **repo root** `layla.db` (see README, ARCHITECTURE, RUNBOOKS).
- **Python**: 3.11–3.12 documented in README and ARCHITECTURE; deps in `agent/requirements.txt`.
- **Smoke**: GET /health and POST /agent (with mock) covered by existing e2e tests.
- **Runbook**: First run procedure in docs/RUNBOOKS.md.

---

## M2 — Research pipeline clarity

- **Docs**: Research usage and stages are in RESEARCH_MISSION_UI_GUIDE.md and agent/research_stages.py (STAGE_ORDER, load_research_context, mission_state).
- **When to use**: Use **research_mission** for multi-stage investigations (mapping → investigation → verification → distillation → synthesis). Use **/research** or single-step flows for lighter tasks.
- **Tests**: Optional minimal research stage test (e.g. load_mission_state, is_useful_output); full pipeline tests can mock LLM.
- **Stop/retry**: Refined in research_stages and router (max steps, timeout, partial vs no_progress behavior). Add tests for mission state and stage transitions.

---

## M3 — Study and memory

- **Docs**: Study plans and wakeup in README, ARCHITECTURE, and .cursor/rules (wakeup, study_plans, scheduler). Learnings and aspect memories used in agent_loop head (see agent_loop._build_system_head).
- **Tests**: test_study_integration.py and test_north_star.py cover study plans, wakeup, initiative.
- **Runbook**: “Add a learning” / “add a study plan” summarized in RUNBOOKS (add knowledge, study CLI/API).

---

## M4 — Approval and safety

- **Docs**: Approval flow (pending → approve → audit) in README “Approvals”, ARCHITECTURE “Request flow”, and runtime_safety (PROTECTED_FILES, DANGEROUS_TOOLS).
- **Tests**: Approval flow test: trigger a write/run that requires approval, then POST /approve with the returned id; assert tool runs or result applied.
- **Policy**: PROTECTED_FILES and DANGEROUS_TOOLS in runtime_safety.py; keep aligned with intended safety.

---

## M5 — Extensibility runbooks

- **Add a tool**: docs/RUNBOOKS.md § “Add a tool”.
- **Add an aspect**: docs/RUNBOOKS.md § “Add an aspect”.
- **Add knowledge**: docs/RUNBOOKS.md § “Add knowledge”.
- **Refs**: CAPABILITIES_AND_CHARACTER_ROADMAP.md, EXTENSION_IMPLEMENTATION_SUMMARY (if present).

---

## M6 — Optional enhancements

- **Loaders**: PDF loader implemented (optional dep `pypdf`); `.pdf` under `knowledge/` are indexed when pypdf is installed. Notion: export to Markdown and add under `knowledge/` (or future Notion API loader).
- **Trace ID**: Optional `trace_id_enabled` in config; X-Trace-Id on responses (see RUNBOOKS).
- **RAG citations**: When using knowledge chunks, return `cited_sources` (or equivalent) with the answer so clients can show sources.
- **Research**: Extra stages or depth options as product needs emerge.

---

## Status summary

| Milestone | Focus | Status |
|-----------|--------|--------|
| M1 | Stabilize, DB path, Python, runbook | Done (docs + RUNBOOKS) |
| M2 | Research docs, stages, tests | Docs present; tests optional |
| M3 | Study/memory docs and tests | Done (tests exist) |
| M4 | Approval docs and test | Docs present; approval test to add |
| M5 | Extensibility runbooks | Done (RUNBOOKS) |
| M6 | Loaders, trace id, RAG, research | Trace id done; rest optional |
