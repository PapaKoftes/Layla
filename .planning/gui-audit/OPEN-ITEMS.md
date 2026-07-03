# Layla — Complete Open-Items Ledger (every issue, deferral, and unbuilt thing) — 2026-07-03

Exhaustive. Compiled from the six audit docs (01–06), the fix passes, and the broader plan.
Legend: ✅ fixed+verified this session · ⏸️ deferred with a stated reason · ❌ open (untouched) ·
🔁 duplication · 🏗️ never built · ⚠️ risk · 🅿️ intentionally parked.

---

## A. FIXED & VERIFIED this session (14)
1. ✅ Plan-first toggle — was dead; now sends `plan_mode`.
2. ✅ Think-harder toggle — was dead; now sends `reasoning_effort:'high'`.
3. ✅ Working-notes context leak — now cleared after each turn.
4. ✅ Prompt-history ↑ — was 404; now `/history` + shape-mapped.
5. ✅ Context-usage bar — was permanent `Ctx: —`; now live from SSE `ctx_pct`.
6. ✅ Pipeline-clarify — questions now render (both SSE + JSON paths).
7. ✅ Update-check — was 404 (`/version/check_update` → `/update/check`).
8. ✅ Potato preset button — was 404 (path → body).
9. ✅ File-checkpoints panel — was 404 (`/file_checkpoints` → `/memory/file_checkpoints`).
10. ✅ Growth velocity sparkline — dict→array normalized.
11. ✅ Growth knowledge-watcher — mapped to real server fields.
12. ✅ TTS volume slider — was no-op; now a GainNode.
13. ✅ TTS speed slider — now reaches `/voice/speak`.
14. ✅ `min_adjusted_confidence` — was inert; now a retrieval floor.
15. ✅ Verify/"it learns" loop — was NO UI; now a working review flow in Growth.
16. ✅ Startup wizard re-run — now gated on real readiness, not fragile localStorage.
   *(also: color streamline; the 6-doc deep audit; the preview-server "set-up" canned state)*

## B. DEFERRED with a stated reason (7)
17. ⏸️ Compact conversation-scoping — server compacts one global buffer; needs a conversation-aware history model.
18. ⏸️ Rail "Load more" pagination — server ignores `offset`; default `limit=200` suffices for now.
19. ⏸️ "Save appearance & lite" — reads nonexistent DOM ids + posts non-schema keys; needs real controls wired to `/settings/appearance`.
20. ⏸️ Character-Lab pitch/warmth/formality sliders — kokoro-onnx TTS has no such params; remove or repurpose in the Character-Lab rework.
21. ⏸️ Potato + semantic memory (`use_chroma=False`) — defensible low-end tradeoff; real fix is cheap embeddings (Phase 4).
22. ⏸️ `min_adjusted_confidence` real-data test — logic verified; effect not exercised (no live memory in preview).
23. ⏸️ Autonomous mode toggle — HELD: it's force-reset to False at startup as a **safety gate**; enabling it is your product/safety call, not a silent flip.

## C. OPEN — audit found, I did NOT touch

### C1. Dead controls / dead chrome (chat) [01]
24. ✅ Retry "↻ Regenerate" composer button — FSM now un-hides it when idle with a prior turn (verified).
25. ❌ `#file-context-chips` element — defined, no writer → dead chrome.
26. ❌ URL-detect "Fetch content" chip — only rewrites the prompt; doesn't actually fetch (label over-promises).
27. ❌ `/ctx_viz` "Context visualizer" — opens raw JSON, no visual view.
28. ❌ `/usage` endpoint — orphaned (header uses `/session/stats` instead).
29. ❌ Reasoning-tree summary render — renderer exists but `send()` never feeds it.
30. ❌ Reasoning-chain append — function exists, no caller.
31. ❌ Diff-viewer apply / batch-apply — stub (toasts only, no real binding).
32. ❌ Legacy localStorage sessions (`layla_sessions`) — dead code, vestigial.
33. ❌ `triggerSend` minimal fallback (bootstrap.js:83–122) — dead but harmless.
34. ❌ Image attach → vision — server supports `image_base64`; composer has no image path (backend-without-ui).

### C2. Backend-without-UI — built, powerful, unreachable
35. ❌ Missions board / horizon / lifecycle (`missions.py`) — full product, zero UI callers. [04]
36. ❌ Spawn tiny agents (`/agents/spawn`) — no UI. [05]
37. ❌ Agent blackboard (`/agents/blackboard`) — no viewer. [05]
38. ❌ Skill-packs / rollback / rl-preferences — code-complete, unsurfaced. [05]
39. ✅ Study-plan delete — added a delete button (data-action) + fixed the route type (`int`→`str`, ids are hex). [05]
40. ❌ File-backed plans `/plan/*` — orphaned duplicate of the SQLite `/plans/*` path. [04]
41. ❌ `cot_stats` — no UI caller. [04]
42. ❌ ResourceGovernor (whisper/breathe/sprint) — not surfaced anywhere. [04]
43. ❌ Mission verify / debug diagnostics — no UI. [04]
44. ❌ Session-grants list — clear-all only; no per-grant revoke, no panel. [04]
45. ❌ Remote access — full backend, no reachable GUI to enable it. [06]
46. ❌ Cloudflared tunnel — backend only, no GUI. [06]
47. ❌ Tailscale / funnel — backend only, no GUI. [06]
48. ❌ Syncthing sync — backend only, no GUI. [06]
49. ❌ Phone-access URL — handler unregistered, no DOM element (dead UI / backend-without-ui). [06]
50. ❌ Metrics (summary/security/observability) — no UI. [06]
51. ❌ Audit log — no UI. [06]
52. ❌ Tools history / analysis — no UI. [06]
53. ❌ `/health/trace`, `/health/deps` — no UI. [06]
54. ❌ `/doctor/capabilities` — no UI consumer. [06]

### C3. UI-without-backend / inert / cosmetic
55. ❌ Per-aspect MODEL override — built + tested, never called in the live loop (dormant/dead). [02]
56. ❌ Per-aspect TOOL boost/suppress (`ASPECT_TOOL_PREFERENCES`) — referenced only by tests. [02]
57. ❌ Character-Lab color picker → chat UI — chat rail uses a separate hardcoded palette, not the Lab's color. [02]
58. ❌ Character-Lab titles — persists `active_title`, but runtime uses a separate earned-title path. [02]
59. ❌ `ui_theme_preset` — inert (no loader in the UI). [06]
60. ❌ `syncthing_*` keys — not even in the schema (config-file only). [06]
61. ❌ `ui_font_size` / `ui_animation_level` — not schema keys (dead reference). [06]
62. ✅ TTS voice list — replaced the fake `af_sky` with the 9 real kokoro voices. [05]
63. ❌ "Agents" panel is a misnomer — it's a CPU/RAM gauge, not agents. [05]

### C4. Partial / half-wired
64. ❌ `memory_router.query` semantic path (the documented "gatekeeper") — calls a nonexistent function; dead; real retrieval bypasses it. [03]
65. ❌ Elasticsearch mirror/search — inert unless the user runs ES + installs the package. [03]
66. ❌ Import-chat (WhatsApp→knowledge) — backend solid, thin UI entry. [03]
67. ❌ Relationship-codex proposals — backend works, UI surface limited. [03]
68. ❌ Memory rebuild — works, minimal UI. [03]
69. ❌ Learning quality-gate default mismatch — schema says True, `distill.py:47` defaults False on missing key. [03]
70. ❌ Model download — non-resumable (`urlretrieve` from byte 0, no Range). [04]
71. ❌ Switch active model — persists but doesn't hot-swap the loaded model. [04]
72. ❌ Model params — structural (n_ctx/gpu/batch/threads) are load-time only; no live-vs-restart labeling. [04]
73. ❌ Rail switch of aspect — client-only; reverts on reload; only "Set as Main" persists. [02]
74. ❌ Deliberation dropdown — no boot-time sync to the saved value (markup hardcodes `auto`). [02]
75. ❌ @mention — leading-token only; silent no-op on typos; no multi-word names. [02]
76. ❌ Personality-slider hints — coarse: only fire at ≥8/≤2 and for the primary aspect. [02]
77. ❌ Project-preset picker — lives in Prefs, not the workspace panel (fragmented). [05]
78. ❌ Skills — two disjoint registries (Python dict vs markdown files); UI shows the emptier one. [05]
79. ❌ Power panels (symbol search / exec trace / tasks) — dump raw JSON. [05]
80. ❌ Obsidian — connect/sync/suggest work; diff/export unwired in UI. [06]
81. ❌ Discord / Slack / MCP-client / plan-governance / engineering-pipeline / admin keys — reachable ONLY via the raw schema modal, no curated controls. [06]
82. ❌ Non-solo deliberation ⚠️ — silently skips tools/plans/approvals (advisory text only). [02]

### C5. Architectural duplications (collapse to one each)
83. 🔁 Two aspect data models — `character_creator.ASPECT_DEFAULTS` (SQLite) vs `personalities/*.json` (divergent facts). [02]
84. 🔁 Two onboarding systems — setup.js 3-step tour vs onboarding.js interview, sharing `#onboarding-overlay`. [startup]
85. 🔁 Two "governor" systems — `performance_mode` vs idle `ResourceGovernor` (overlapping names). [04]
86. 🔁 Two deliberation systems — debate engine vs single-model "inner voices". [02]
87. 🔁 Two skill registries — Python `SKILLS` dict vs markdown `SKILL.md`. [05]
88. 🔁 Two plan stores — SQLite `/plans/*` (UI) vs file `/plan/*` (orphaned). [04]
89. 🔁 Two settings surfaces — flat schema modal vs curated right-panel (overlapping subsets). [06]
90. 🔁 Duplicated XP thresholds / phase names client-side (`growth.js`) vs server (F7). [03]

## D. NEVER BUILT — the redesign + product scope
91. 🏗️ GUI rebuild **G2** (chat surface: bubbles/composer/palette) — only G1 (design-system layer) exists.
92. 🏗️ GUI rebuild **G3** (the one card system for panels).
93. 🏗️ GUI rebuild **G4** (aspect switching + retheme + Character Lab in the new system).
94. 🏗️ GUI rebuild **G5** (the calm 5-step startup redesign).
95. 🏗️ GUI rebuild **G6** (responsive + a11y + motion polish + sign-off).
96. 🏗️ The new **IA** (64px icon rail + conversations column) — today it's the *reskinned legacy* sidebar.
97. 🏗️ Command palette (⌘/Ctrl-K) — proposed, unbuilt.
98. 🏗️ Language-learning surface (German/Castilla) — backend-complete, still no UI.
99. 🏗️ Self-improvement UI — backend-only, unbuilt.
100. 🏗️ Grouped 8-page Settings architecture — still the flat modal + accordions.
101. 🏗️ Legible unified safety surface (bypass/approvals/safe-mode/governor).
102. 🏗️ Collapse of every §C5 duplication.
103. 🅿️ Cluster (queen/drone mesh) — intentionally parked/experimental.

## E. Broader plan not done (from MASTER-PLAN / UPGRADES)
104. 🏗️ Phase 3 — scope cut (park cluster/tribunal/gamification behind flags).
105. 🟡 Phase 4 — foundation swaps: **model2vec embedder + sqlite-vec store BOTH DONE** (validated: 230 memory tests + 12 fallback-store tests green, sqlite-vec KNN with NumPy fallback); one-SQLite-memory consolidation + FlashRank rerank still open.
106. 🏗️ Phase 5 — quality (constrained decoding, hybrid escalation, governor auto-cap, self-consistency, project-aware coding context).
107. 🏗️ Phase 6 — ecosystem (Ollama backend, first-class `/v1`, MCP-only plugins).
108. 🏗️ Phase 7 — polish (honesty card, Doctor panel, Castilla flagship, eval harness in CI, download robustness).
109. 🏗️ Phase 8 — dream (RapidOCR/Piper, DSPy, Tauri shell, memory sync, VS Code/CLI/mobile clients, MCP marketplace).
110. 🏗️ ~32 of 37 UPGRADES still open.

## F. My own over-claims / corrections (honesty)
111. The earlier `GUI-FEATURE-MAP.md` described a *proposed* IA that isn't built and never verified controls work — it was wiring-level, not truth-level. This ledger + the audit supersede it.
112. I earlier called "potato disables semantic memory" a wedge *bug*; on tracing it's a defensible hardware tradeoff (corrected in FIX-PLAN).
113. "G1 done" = a reskin layer over the OLD structure. The *look* is set; the *structure* is not rebuilt.
114. The live animated app defeats `preview_screenshot` (times out); all my UI verification is via computed-style/DOM reads + the static preview, not visual screenshots of the real app.

---

### Scale summary
- **Fixed + verified:** 16 (incl. startup, color).
- **Deferred with reasons:** 7.
- **Open audit issues I did not touch:** ~67 (C1–C5).
- **Never-built (redesign + scope):** ~20 (D–E).
- The audit's own status tables total ~200 rows across the six docs; the not-`working` subset is enumerated above.
