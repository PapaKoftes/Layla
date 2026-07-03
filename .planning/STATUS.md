# Layla — Status & Remaining Backlog (2026-07-03)

The single source of truth for "what's done" and "what's left," consolidating the
session's working docs (audit traces, ledgers, plans). Full detail lives in the git
history — every item below maps to a commit or a clearly-scoped next step.

---

## Done — verified, committed, pushed

**GUI truth pass (~24 controls fixed, each proven on the running app):**
- Chat loop: plan-first + think-harder toggles (were dead) · working-notes leak · prompt-history ↑ ·
  context-usage bar (SSE `ctx_pct`) · pipeline-clarify questions · retry "Regenerate" button.
- Endpoints (were 404s): update-check · potato preset · file-checkpoints panel.
- Growth: velocity sparkline (dict→array) · knowledge-watcher (real fields) · **the verify/"it learns"
  loop now has a real UI** (was backend-only) · XP-to-next from the server.
- Voice: TTS volume (GainNode) + speed slider now reach `/voice/speak`; fixed the fake `af_sky` voice.
- Memory: `min_adjusted_confidence` retrieval floor (was inert).
- Startup: the setup wizard only runs on genuine first-run (gated on real readiness, not fragile
  localStorage); study-plan delete button + route type fix.
- Design system layer (`layla-rebuild.css`): our colors (near-black + crimson + wine-rose + violet),
  JetBrains Mono, calm chrome — the G1 reskin over the existing structure.

**Foundation swap — COMPLETE & validated (~250 memory tests green):**
- **model2vec** static embeddings are the low-end default (numpy, **no torch**, ~30k/s CPU, ~92% of
  MiniLM); sentence-transformers is the opt-in quality embedder + fallback.
- **sqlite-vec** SIMD cosine KNN for the fallback store (NumPy fallback for `where` + no-extension boxes).
- The **potato preset keeps semantic memory** now that it's cheap — the wedge ("private + low-end + it
  remembers") holds on a weak box.

**Duplications — the real ones collapsed:**
- Plan stores → deleted the orphaned file-backed `/plan/*` router.
- Client XP thresholds → use the server's single source of truth.
- Aspect data models → identity title/tagline/color derive from `personalities/*.json` (fixed 5/6 title
  divergences, e.g. Lilith).
- Governor + deliberation default-drift bugs fixed (`performance_mode` missing→auto; `deliberation_mode`
  `auto` no longer forces multi-model debate every turn).

**Full end-to-end review:** 2,512 tests pass, 0 regressions. Preview verification workflow + the
foundation-swap validation are in the git log.

---

## Remaining backlog — prioritized, honest

### P0 — quick, safe wins (libraries already installed, just hand-rolled around)
- **tiktoken** for token counting (currently `//4` heuristics in 4+ places → context-budget bugs).
- **httpx** consolidation (urllib scattered across every web tool) + **huggingface_hub** resumable,
  checksummed model downloads (currently `urlretrieve` from byte 0).
- **tenacity** / **diskcache** / **apscheduler** already in the `cpu` extra — replace the bespoke
  retry / cache / scheduler code.

### P1 — small-model quality
- **Constrained decoding** (llama.cpp GBNF / llguidance) — the cheapest correctness win; constrain the
  tool-call/JSON envelope, keep reasoning free.
- Hybrid escalation (bigger-local / BYO-cloud toggle) · self-consistency voting · project-aware coding
  context (repo map + symbol index + `@file`) · eval harness in CI.

### P2 — performance levers (mostly llama.cpp config, tier-adaptive)
- Prefix/prompt **KV caching** · **KV-cache quantization** (q4_0 potato / q8_0 modest, needs flash-attn) ·
  lazy imports of heavy modules · model hot-swap + live-vs-restart param labels · threads = physical
  cores · adaptive per-tier auto-config matrix + honesty card · drop torch entirely from the `cpu` extra
  once model2vec is proven.

### P3 — the GUI redesign (the big one; weeks of work; needs your sign-off per pass)
- **G2** chat surface (bubbles/composer/command palette) · **G3** the one card system for panels ·
  **G4** aspect switching + Character-Lab · **G5** the calm 5-step startup (folds in the onboarding
  dedup + the grouped 8-page Settings + the two-settings-surface collapse) · **G6** responsive + a11y.
- The new IA (64px icon rail + conversations) replaces today's reskinned legacy sidebar.

### P4 — backend-without-UI (build a surface or cut, ~18)
Missions board · spawn-agents + blackboard · skill-packs · **remote access / cloudflared tunnel /
tailscale / syncthing / phone-URL** (a user can't enable remote access from the GUI today) · metrics ·
audit log · tools-history · `/health/trace|deps` · `/doctor/capabilities` · image→vision composer path ·
session-grants list · `cot_stats` · ResourceGovernor surface · autonomous-mode toggle (**a product/safety
decision — it's force-reset off at startup as a gate; enabling it is your call, not a silent flip**).

### P5 — partials / cleanup (each small)
memory_router dead "gatekeeper" path · Elasticsearch (opt-in) · import-chat/codex/rebuild thin UIs ·
learning quality-gate default mismatch · @mention leading-only + silent typo fail · personality-slider
hints coarse · skills two-registry UI (show both) · raw-JSON power panels · Obsidian diff/export ·
Discord/Slack/MCP/governance/admin curated controls · per-aspect model+tool overrides (built, unwired) ·
Character-Lab color→chat + titles · dead chrome (`#file-context-chips`, /ctx_viz raw JSON, reasoning-tree/
chain renderers, diff-viewer stub, legacy localStorage sessions).

### P6 — ecosystem / dream (UPGRADES.md)
Ollama backend + first-class `/v1` + MCP-only plugins · Tauri shell · VS Code/CLI/mobile clients ·
RapidOCR/Piper · DSPy · MCP kit marketplace.

---

## Ground truth / how to work here
- Run the app: `.venv` (py3.12). Run pytest: the separate **`.venv-test`**. Fast UI checks: the static
  preview server (`layla-ui-preview`, :8777) + `preview_inspect`; the live animated app defeats
  `preview_screenshot`.
- Strategy unchanged: the wedge is **private + low-end-friendly + multilingual + personality-driven**;
  reuse-don't-reinvent; coding is a strong aspect, not the headline. (See `STRATEGY.md`, `UPGRADES.md`.)
- Detailed audit evidence (every issue with file:line), the optimization research (cited magnitudes), and
  the dedup survey are preserved in the git history under the `feat(ui)/fix(ui)/refactor` commits and the
  now-removed `.planning/gui-audit/`, `FULL-LIST`, `RESEARCH-DEEP`, `DEDUP-PLAN` docs (recoverable via git).
