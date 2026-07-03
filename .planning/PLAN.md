# Layla — The Plan (single source of truth) · 2026-07-03

Everything folded into one doc: vision · strategy · requirements · architecture · roadmap ·
the GUI redesign spec · security backlog · measured truths · what's done · how to run. Detailed
audit evidence, cited research, and per-commit history live in git and in `codebase/` + `research/`
+ `phases/` (pointed to in §11). Supersedes the old scattered plan docs.

Legend: ✅ done · 🟡 partial · ⬜ open · ✂️ cut/parked · ⏸️ deferred (reason).

---

## 1. Vision & positioning

**What Layla is:** a **local-first, self-hosted AI agent platform** — a Python/FastAPI server wrapping a
locally-loaded GGUF model (llama-cpp-python), exposing a tool-using agent loop over a web UI, CLI/TUI, an
OpenAI-compatible `/v1` API, and optional MCP. All data on the operator's machine (SQLite + optional
Chroma). Every side-effecting tool (file write / shell / code exec) is gated behind explicit
`allow_write`/`allow_run` + approval.

**The sharpened thesis:** Layla expresses itself through personality **aspects, and each aspect is a
domain-optimized *kit*** — not a cosmetic skin. An aspect bundles {best local model for the user's
hardware + the right skills/tools + a tuned system prompt + inference settings + a visual identity}. The
product's job: **detect the user's hardware on first run and provision the best experience it can actually
run**, per domain. Morrigan = coding kit; Nyx = research; Echo = continuity; Eris = creative; Cassandra =
critique; Lilith = safety/boundaries.

**North-star user:** a friend on a **16 GB-RAM, CPU-only laptop** who wants genuinely useful, private,
*delightful* programming + companion help. Aspirational: sovereign self-hosting operators.

**The defensible edge = curation, not the engine.** llama.cpp, Ollama/LM Studio, chat UIs are commodities.
The bet: assembling the optimal local kit **per domain per hardware tier**, auto-provisioned and wrapped in
a personality with a soul, is what no incumbent does well.

**Viability / the honesty anchor:** as a market product competing head-on, Layla is redundant. So operate
as: (1) primary frame = **a delightful personal tool** — judge by *"does she love and use it"*; (2) the
only real novelty = the aesthetic + the domain-kit personality system; (3) if it ever matters beyond her →
pivot to a **layer on an incumbent** (personality/kit on an OpenAI-compatible engine), don't maintain a
whole platform solo. **As a venture: no. As an OSS passion/community cause: yes.**

**Out of scope (durable):** horizontal scaling / multi-node inference; platform-scale market ambition;
backend rewrites beyond remediation (prefer surgical, regression-safe changes); out-of-process/container
tool sandboxing beyond path-jail + approvals (tracked as a later hardening tier, §7).

---

## 2. Strategy — the wedge, the cuts, the verdict

**One-line truth:** Layla's only defensible position is the **intersection**: a **private, offline,
low-end-friendly, multilingual, personality-driven companion-assistant** with hardware-adaptive domain
kits. Win the intersection or lose to focused incumbents.

**The wedge:** *"The local AI with a soul that runs well on a potato, in your language, and can actually do
things — fully private."* **Companion-leaning, not coding-leaning.** Coding-as-flagship is the one claim a
small-model-on-CPU structurally cannot win; coding stays a **strong aspect made credible by hybrid
escalation** (UPG-01), not by pretending 3B-on-CPU rivals the cloud. Nearest adjacent market = the
companion crowd (SillyTavern/Backyard), **not** Cursor.

**Biggest mistake + fix:** "trying to be everything" (197 tools, cluster mesh, tribunal council,
gamification-as-headline). **Fix: cut ~60% of surface to the wedge.** Cut/park: cluster/work-unit mesh,
tribunal (6-aspect) council, maturity gamification as a headline, the 197-tool long tail. *Every tool we
keep is a tool we maintain forever.*

**Leverage principle — reuse, don't reinvent.** Engine / vector store / embeddings / rerankers /
constrained decoding / OCR are commodities with better OSS than we hand-rolled. Moat = curation + kits +
soul, never the plumbing. Adopting them shrinks maintenance AND improves low-end quality (win-win).

**Positioning:** audience = privacy/offline + low-end + non-English + companion-lovers (**not** pro
coders); compete vs SillyTavern/Backyard/AnythingLLM (**not** Cursor); standards = OpenAI `/v1` + **MCP** +
Ollama API (drop-in, not island); plugin system = **MCP only, never a second one**; engine = abstract
behind one interface (llama.cpp + Ollama + OpenAI-remote); license = non-commercial (an OSS cause).

**Non-negotiables (trust backbone):** local-first · approval-gated mutation · deny-by-default ·
loopback-default · hashed tokens · OS-keyring secrets · verify against implementation not docs · report
measurements honestly even when they contradict prior claims · every install must **prove a real inference
turn** (`scripts/selftest.py`) before declaring success.

---

## 3. Requirements contract (REQ-01…REQ-85)

Stable IDs; phases map to these. Status reconciled to current reality.

- **Trust/foundation (done):** REQ-01 trust boundary / no unauth RCE or config-rewrite ✅ · REQ-02 no AGPL +
  reload-off ✅ · REQ-03 agent-loop core unit-tested without a model ✅ · REQ-04 bounded resident-model
  cache, no OOM ✅.
- **Security finish:** REQ-10 rightmost-trusted-hop XFF over `tunnel_trusted_proxies` ✅ · REQ-11
  `remote_require_auth_always` default-on-when-exposed ✅ · REQ-12 secrets via OS keyring ✅.
- **Verifiable core:** REQ-20 real tiny-model inference-smoke each PR (`stories260K`/SmolLM2) 🟡 (seam
  ready, CI job unwired) · REQ-21 un-`collect_ignore` agent-loop tests ✅ · REQ-22 release gated + thread
  seed/top_k 🟡.
- **Answer quality:** REQ-30 inline RAG grounding (MiniCheck/NLI, CPU, cite-or-abstain, `grounding` block)
  ⬜ · REQ-31 20–50 promptfoo golden set on PR+nightly ⬜.
- **Reliability & data:** REQ-40 remove dead `LLMRequestQueue` / document concurrency ⬜ · REQ-41
  `save_learning` embed outside the write txn + `/health` reports model-load failure 🟡 · REQ-42 backup
  includes Chroma dir + WAL checkpoint + VACUUM 🟡 · REQ-43 erasure removes vectors + log PII/secret
  redaction ✅ (redaction).
- **Maintainability:** REQ-50 one typed config schema, no drift ⬜ (two-file `config.json` vs
  `runtime_config.json` still persists) · REQ-51 decompose `_autonomous_run_impl_core` + services stop
  importing agent_loop privates 🟡 · REQ-52 shared UI data (ASPECTS) defined once + reduce `window.*` 🟡.
- **Then-build:** REQ-60 hardware-aware model browser/downloader in UI 🟡 · REQ-61 `/v1` honors
  temperature/max_tokens(→n_predict)/stop/top_p, never 400 🟡 · REQ-62 prebuilt CPU/CUDA wheels + opt-in ML
  stack ✅ · REQ-63 approval-gating visible/demoable (diff/command previews) 🟡.
- **M2 Track A — daily-driver:** REQ-70 real coding model measured ✅ · REQ-71 `recommend_kit` ✅ · REQ-72
  compiler-free full stack/fallback ✅ (memory; install slice open) · REQ-73 first-run kit provisioning 🟡 ·
  REQ-74 HumanEval/MBPP pass@1 harness ✅ · REQ-75 full-app E2E + one-command install 🟡 · REQ-76 each aspect
  = curated kit 🟡 · REQ-82 coding scaffolding (repo-map, diff-edit, GBNF, codebase RAG, KV-cache) ⬜ ·
  REQ-83 `/v1` hardened as integration seam (Cline/Continue/Aider) 🟡 · REQ-84 aspects import/export as
  portable **SillyTavern-compatible character cards** ⬜ · REQ-85 kit upgrades (embedding-per-tier,
  IQ-quant catalog, benchmark-driven selection) 🟡 (model2vec per-tier landed).
- **M2 Track B — UI:** REQ-77 design-token system ✅ (G1 `layla-rebuild.css`) · REQ-78 core chat in new
  aesthetic ⬜ (G2) · REQ-79 aspect creator (name/sigil/sliders/voice/prompt + kit) 🟡 · REQ-80
  S.P.E.C.I.A.L.-style intake quiz 🟡 · REQ-81 per-aspect motion/polish ⬜ (G6).
  **NOTE — superseded framing:** REQ-77/78 originally specified a from-scratch `ui-next/` (Vite+React+TS)
  in a "Warframe-mystic" aesthetic. **Both are dead:** the decision is **expand the existing modular
  ES-module `agent/ui/`** (no `ui-next/` — verified absent), and the aesthetic is the **calm/clean #1** look
  (§6). Carry the *goals* (design tokens, aspect creator, quiz) under G1–G6, not the React/Warframe framing.

---

## 4. Architecture & hard constraints

Full map in `codebase/ARCHITECTURE.md` + `agent/docs/adr/001-006` + `agent/docs/VISION.md`. Load-bearing:

- **ADRs:** 001 agent-loop decomposition (1574→910 lines) · 002 session-context replaces global
  `shared_state` · 003 the shim pattern (**now historical — all 206 shims deleted in R8, refs canonical;
  the boundary test asserts canonical-only**) · 006 **Companion First, Workstation Second** + "no new major
  systems" + "every system must produce felt user impact" + progressive disclosure.
- **Executable boundary budgets** (`codebase/CONVENTIONS.md`, enforced by tests): routers don't import db
  directly; `shared_state` importers ≤15; `memory_router` bypass ≤85; `agent_loop` ≤1000 lines + must
  export its public names; required service sub-packages must exist; license hygiene via `check_copyleft.py`.
- **Hard constraints:** Python **3.11/3.12 only** (3.13+ unvalidated) · **single process, one model, one
  global generation lock** (deliberate; horizontal scale = a separate worker process = a feature, not a
  fix) · approval-gated mutation is the trust backbone, deny-by-default.
- **Known-open architecture concerns** (`codebase/CONCERNS.md`): two config files (`config.json` ≠
  `runtime_config.json`, = REQ-50) · single-process ceiling (by design) · remaining god-modules (§7 R9) ·
  legacy `remote_api_key` (gated off) · eris→11B unenforced.

---

## 5. Roadmap

**Strategic tiers (the top-level shape):**
- **MVP — "the local AI with a soul that runs on a potato, in your language."** ONE soulful aspect on the
  surface (others opt-in kits); engine abstraction (UPG-10) + **sqlite-vec (UPG-02 ✅)** + **model2vec
  (UPG-03 ✅)** + constrained decoding (UPG-05); self-test installer (✅) + Doctor panel (UPG-31) + pairing
  (✅) + honesty card (UPG-24); clean **#1** UI + memory + knowledge ingest; scope cut (UPG-00a) + trap
  installers retired (UPG-00c ✅) + finish R9 (UPG-00b). CUT: cluster mesh, tribunal, gamification-headline,
  tool long-tail.
- **V2 — "credible assistant."** Hybrid escalation (UPG-01) · project-aware coding context (UPG-21) · MCP
  plugins (UPG-12) · Ollama backend (UPG-06) · FlashRank (UPG-04) · DSPy (UPG-08) · self-consistency
  (UPG-20) · multilingual/Castilla flagship (UPG-23) · eval harness in CI (UPG-22) · safe model download
  (UPG-35) · Ollama + `/v1` interop (UPG-40/41).
- **V3 — "platform."** 2–3 opt-in aspect kits · knowledge/memory sync across paired instances (UPG-33) · VS
  Code + CLI + mobile PWA via tunnel (UPG-34) · Tauri shell (UPG-13) · optional GPU path · a11y (UPG-36).
- **Dream — "movement."** Sponsor-funded OSS personal-AI-OS · your instance follows you across devices · a
  community **MCP kit marketplace** (UPG-37). "A cause, not a cap table."

**The "truly-ready" definition-of-done gate** (all must hold): (1) `fresh_install.ps1` on a clean box →
working `.venv` + **passes `selftest --server`** (demonstrated, not inferred) [✅ proven 2026-07-02]; (2)
GUI built to the locked "clean #1" look + signed off against the running screen [G1 done; G2–G6 open]; (3)
scope cut to the wedge [⬜ Phase 3]; (4) zero 🟡/⬜ in the UPG backlog (or each explicitly ✂️ with a
reason); (5) full suite green + real install green + one end-to-end human UAT on the friend's tier.

**Execution phases (from MASTER-PLAN, reconciled):** Phase 0 substrate ✅ · Phase 1 GUI lock 🟡 (G1 done,
needs your eyes per pass) · **Phase 2 prove-install ✅** (fixed the never-run installer — non-ASCII PS 5.1
parse failure + `Find-Py312` bug; `.venv` builds; `selftest` PASS) · Phase 3 scope-cut ⬜ (park behind flags,
reversible) · **Phase 4 foundation swaps 🟡** (UPG-02 ✅ + UPG-03 ✅ done; UPG-10 engine abstraction, UPG-11
one-SQLite, UPG-04 FlashRank open; absorbs R9) · Phase 5 quality ⬜ (UPG-05/01/14/20/21) · Phase 6 ecosystem
⬜ (UPG-06/40/41/12/09) · Phase 7 polish ⬜ (UPG-24/31/23/22/35) — **truly-ready gate here** · Phase 8
later/dream. Estimate: ~23 focused passes to the gate. The one irremovable dependency: **Phase 1 GUI needs
your sign-off per pass**; everything else is drivable to green autonomously.

**UPG backlog (canonical IDs; reconcile with §10 done-list):** Tier 0 — UPG-00a scope-cut, UPG-00b R9
splits 🟡, UPG-00c ✅. Tier A (reuse win-wins) — UPG-01 hybrid escalation, **UPG-02 ✅**, **UPG-03 ✅**,
UPG-04 FlashRank, **UPG-05 ✅ constrained decoding** (GBNF native layer built + wired + model-in-loop proven
on real Qwen-7B, Outlines/instructor already present — "biggest small-model correctness win, cheapest"), UPG-06 Ollama backend, UPG-07 RapidOCR/Piper, UPG-08 DSPy, UPG-09 Open WebUI call. Tier B —
UPG-10 engine abstraction, UPG-11 one SQLite memory file, UPG-12 MCP-only plugins 🟡, UPG-13 Tauri, UPG-14
governor auto-cap 🟡. Tier C — UPG-20 self-consistency, UPG-21 project-aware coding, UPG-22 eval-in-CI,
UPG-23 Castilla, UPG-24 honesty card. Tier D — UPG-30 selftest ✅, UPG-31 Doctor panel, UPG-32 pairing ✅,
UPG-33 memory sync, UPG-34 clients, UPG-35 download-hardening 🟡, UPG-36 a11y/palette/recipes, UPG-37 kit
marketplace. Tier E — UPG-40 first-class `/v1` 🟡, UPG-41 Ollama API, UPG-42 HF Hub + ONNX.

**Near-term P0→P6 (the actionable order from here):**
- **P0 quick wins (libs already in the `cpu` extra, just hand-rolled around):** tiktoken token-counting
  **✅ (P0.1, kills the `//4` heuristics — chunker + validator route through `services.llm.token_count`)** ·
  **resumable/checksummed downloads ✅ (P0.2 — `/setup/download` now routes through `model_downloader.download_model`:
  HTTP Range + `.part.meta` resume + sha256 + GGUF-magic + atomic rename, progress_cb drives the SSE bar)** ·
  httpx consolidation ⬜ · tenacity/diskcache/apscheduler replace bespoke retry/cache/scheduler ⬜
  (both deprioritised — replace *working* code, hard to verify in a test-only session).
- **P1 small-model quality:** constrained decoding (GBNF) **✅ built + wired + model-in-loop PROVEN
  (`services/llm/gbnf_grammar.py`: pins action/priority enums + `tool` to the valid-tool set; first structured
  path in `llm_decision`, gated `gbnf_decoding_enabled`; 19 unit tests compile every variant against the real
  `llama_cpp.LlamaGrammar`. Live proof on real Qwen2.5-Coder-7B: 3 decisions all structurally valid; the
  adversarial prompt "use the delete_everything tool to wipe the disk" was masked to a real tool (run_shell) —
  the model physically could not emit the hallucinated tool)** ·
  hybrid escalation ⬜ *(genuine gap — no impl; needs a model to validate the confidence signal)* ·
  self-consistency ⬜ *(genuine gap — no impl; N× cost, opt-in; needs a model to validate)* ·
  **project-aware coding context ✅ (built + wired — `context_builder.retrieve_code_context`,
  `system_head_builder.get_workspace_dependency_context`, `repo_indexer` on a 30-min schedule,
  `search_symbols` tool, `repo_map_summary` in plans; the old `repo_index_populated=false` signal is already
  fixed to treat no-/empty-workspace as N/A)** ·
  **eval harness in CI ✅ (deterministic harness already CI-tested — extraction/sandbox/pass@1; added a live
  pass@1 regression as a model-gated opt-in test: skips instantly by default, `LAYLA_BENCH_MODEL=/path.gguf`
  enables it in CI, `LAYLA_BENCH_FLOOR` tunes the floor)**.
- **P2 performance (tier-adaptive llama.cpp):** prefix/KV caching · KV-quant (q4_0 potato / q8_0 modest,
  needs flash-attn) · **lazy imports ✅ (startup graph — agent_loop+orchestrator+routers — imports in ~0.8s
  with torch/llama_cpp/sentence_transformers/transformers/chromadb all deferred; now guarded by a
  subprocess import-hygiene test)** · model hot-swap + param labels · **threads=physical ✅ (already wired —
  `_auto_threads`: physical cores via `psutil.cpu_count(logical=False)`, one free, cap 16, governor-aware,
  batch on logical; now test-locked, 5 tests)** · per-tier auto-config + honesty card · drop torch entirely
  from `cpu` once model2vec proven.
- **P3 the GUI redesign G2–G6** (§6) — the big one, weeks of work, sign-off per pass.
- **P4 backend-without-UI (build a surface or cut, ~18):** missions board · spawn-agents + blackboard ·
  skill-packs · **remote access / cloudflared / tailscale / syncthing / phone-URL** (unreachable from the
  GUI today) · metrics · audit log · tools-history · `/health/trace|deps` · `/doctor/capabilities` ·
  image→vision composer · session-grants list · `cot_stats` · ResourceGovernor surface · **autonomous-mode
  toggle (product/safety decision — it's force-reset off at startup as a gate; enabling it is a deliberate
  call, not a silent flip)**.
- **P5 partials/cleanup:** memory_router dead "gatekeeper" path · Elasticsearch (opt-in) · import-chat/
  codex/rebuild thin UIs · **learning + output quality-gate default mismatch ✅ (both fallbacks now default
  True to match config_schema/DEFAULTS; 4 regression tests)** · @mention leading-only + silent typo
  fail · personality-slider hints coarse · skills two-registry UI (show both) · raw-JSON power panels ·
  Obsidian diff/export · Discord/Slack/MCP/governance/admin curated controls · **per-aspect model overrides
  (built + tested — `model_router.route_model`/`_resolve_aspect_model` + `aspect_model_overrides`; the
  specific unwired gap is that `llm_gateway.run_completion` never receives/reads the *active* aspect, so
  overrides don't fire in the live single-aspect chat path — deferred: hot-path ContextVar wiring best
  verified with a real generation)** · Character-Lab color→chat + titles · dead chrome (`#file-context-chips`,
  /ctx_viz raw JSON, reasoning-tree/chain renderers, diff-viewer stub, legacy localStorage sessions).
- **P6 ecosystem/dream:** Ollama backend + `/v1` + MCP-only plugins · Tauri · clients · RapidOCR/Piper ·
  DSPy · MCP kit marketplace.

**Backlog reconciliation (2026-07-03, test-only session).** Probing each item against the live code found
the codebase far more complete than this backlog implied. **Verified done + committed this session:** P0.1
tiktoken, P0.2 resumable downloads, P1 GBNF (layer + wiring + **model-in-loop proof on real Qwen-7B**, incl. the
adversarial hallucinated-tool case), P1 eval-harness CI half, P2 threads=physical (locked), P2 lazy imports
(locked), P5 quality-gate mismatch (fixed), project-aware coding context (built+wired), repo_index_populated
signal (already fixed). **Genuine remaining gaps that need an app + a loaded model to build *and verify*
(can't be proven in a pytest-only venv):** hybrid escalation · self-consistency · per-aspect override
hot-path wiring · KV cache/quant · model hot-swap · the whole GUI G2–G6 · all P4 backend surfaces. Net: the
test-only-verifiable lane is drained; the substantive rest is app-running work (the box is RAM-tight —
verification loads touch swap).

---

## 6. GUI redesign spec (G1 done; G2–G6 open)

**5 principles:** (1) calm not busy — one accent, one ornament, generous space, content is hero; (2) soul
through restraint — near-black + a single refined crimson/violet + the aspect re-theme, carried by color +
one whisper-subtle damask; (3) professional defaults — Linear/Claude-grade craft dressed in Layla; (4)
**the aspects ARE the navigation** — switching personality is the primary gesture; (5) honest onboarding —
tell the truth about the machine, prove it works before "ready."

**Design system (LOCKED):**
- Palette: `--bg #0a0710` · `--surface #130f1a` · `--surface-2 #1b1526` · `--surface-3 #241d31` ·
  `--border #241d30` · `--border-2 #372c48` · `--text #ece7f3`/`--text-dim #9a8fa8`/`--text-faint #665d73` ·
  `--accent #c0395e` (refined rose-crimson — the soul color) · `--accent-2 #7d5bb8` (violet). Per-aspect
  `--asp`: morrigan #c0395e · nyx #7d5bb8 · echo #3f6fb0 · eris #b5763a · cassandra #2f8f86 · lilith
  #a33b52. `--success #3fae6b · --danger #d0454e`. *(The shipped `layla-rebuild.css` uses the same family;
  reconcile exact values to this spec when doing G2+.)*
- Type: **mono everywhere** — `'JetBrains Mono'` for all UI, `'Cinzel'` for the `∴ LAYLA` wordmark only.
  Readability by craft (line-height 1.5–1.65, tuned tracking, lowercase labels). Scale 11/12/13/14/20/28.
- Space 4·8·12·16·24·32·48 · Radius 6/10/14 · Motion 120ms hover / 200ms panels, **no glows** · Ornament =
  damask ~4% on empty states + rail foot + a 2px accent hairline for active (the whole ornament budget) ·
  Icons = one line set (Tabler/Lucide), 18–20px, currentColor.
- **Locked calls:** mono not system-sans; scope cut to the wedge (cluster/tribunal/gamification/HUD-chips
  parked); colors = ours (the black+dark-purple alternative was considered and rejected).

**IA:** Aspect rail (64px) | Conversations (280, collapsible) | Main (slim header: title · aspect · one
**system dot** · … menu; messages; composer) + a right context panel (320, slide-in, off by default). Kept
surfaces: Chat · Aspects · Memory/Knowledge · Models & Kits · Settings · Doctor. The status-chip row
collapses to the one system dot (governor/health/uptime popover).

**Settings (from the feature-map work):** every config key + control has a home in **8 grouped Settings
pages** with progressive disclosure (common controls visible, advanced collapsed), so nothing is lost and
nothing overwhelms; the aspect creator lives in Settings, not the rail. *(The exhaustive config-key→page
"nothing-lost" ledger was written as `GUI-FEATURE-MAP.md`; it's in git history — recover it when building
G3/Settings if the per-key detail is needed. Latent wedge win to surface: language-learning UI.)*

**Startup (calm, honest, 5 steps):** (1) Welcome `∴ LAYLA` — "A private AI that's yours — runs on your
machine, remembers what matters." (2) Your machine (honesty card) — "16 GB · CPU → Qwen2.5-Coder-3B, fast
for edits and chat." (3) Get the model — one resumable bar / "Found it ✓". (4) Your space — a workspace
folder. (5) Ready — **proof not a promise:** run the self-test live (`model loads ✓ · a real reply ✓ ·
memory ✓`) → Start chatting. Personality/voice = optional "make it yours," not forced.

**Build approach:** rebuild design + structure from scratch, **reuse the working plumbing** (API layer,
state bus, endpoint wiring). One stylesheet system (`tokens → base → components → screens`). **Stay vanilla
ES modules** (zero build, offline-trivial; Svelte noted as optional-future). Order, shippable each step:
**G1 design system ✅** (tokens + shell + empty state — `layla-rebuild.css`) · G2 chat 🟡 (**⌘K command
palette ✅** — `components/command-palette.js`: 20 commands in Aspect/Go-to/Chat/View, substring filter,
keyboard nav with wrap, token-styled [surface-2 panel, wine-rose accent hairline, JetBrains Mono], repurposes
the old ⌘K spotlight; verified live on the preview: open/filter/nav/run/close all green, 0 console errors;
**messages ✅** [you = accent-soft bubble, Layla = bare flush text, facet chip carries --asp, wine-rose
brand], **composer ✅** [G1-styled, verified borderless], **streaming ✅** [typing dots → --asp]) · **G3 🟡**
one form/card system (inputs/selects/textarea/buttons/cards tokenized — border/font/radius/padding; some
legacy bg's kept a darker on-brand value, not fought) · **G4 ✅** aspect retheme verified (--asp flips per
aspect live; exact per-aspect hues still need reconciling — the JS color source ≠ the CSS spec tokens, e.g.
cassandra renders violet not teal) · G5 startup (5-step + live self-test; onboarding-dedup) ⬜ · **G6 ✅**
a11y + motion (focus-visible accent rings on all controls, prefers-reduced-motion kill-switch) → SIGN-OFF.
Each Gx reactable against the running app; **check_ui_symbols ✅** (now scans the real module tree) + e2e-ui.

---

## 7. Security & sandbox hardening backlog

- **R9 (open) — remaining god-modules** (MEDIUM/LARGE, opportunistic): `vector_store.py` (~1410),
  `migrations.py` (~1362 hand-rolled ladder), `tool_dispatch.py`, `cursor-layla-mcp/server.py` (~1296). =
  UPG-00b. Absorbed into Phase-4 foundation swaps where `vector_store` is rewritten (don't split-then-
  replace). *(Done: R1–R8 + R10 — CI inference seam, legal/copyleft guard, config-cache single loader,
  two-store backup/erasure, `remote_api_key` gated off, TestClient suite un-skipped + 12 bugs fixed, all
  206 shims deleted → canonical refs (a0441f9), inference-backend audit.)*
- **Sandbox hardening (later tier — mostly NOT done; the gap between "safe for a trusted operator" [true
  today] and "safe to expose to untrusted work through a tunnel"):** shell deny-by-default + allowlist when
  remote · subprocess rlimits / cgroups / Windows job-object for code exec · ephemeral-container (E2B) tier ·
  per-invocation approvals · egress control / network jail · audit-by-default when remote. (Source:
  `research/security-patterns.md` P0–P3.)
- **Durable "won't-fix" notes:** single-process/one-lock inference ceiling (inherent; horizontal scale is a
  separate feature) · non-commercial license (intentional) · root-entrypoint sprawl (collapse
  opportunistically).

---

## 8. Measured truths (honest CPU/coding numbers — these drive decisions)

- On a 16 GB CPU box the recommender picks **Qwen2.5-Coder-3B** (loads + completes, selftest-verified);
  **Qwen2.5-Coder-7B-Q4_K_M (~4.7 GB) ≈ 5 tok/s** — usable for focused edits, not from-scratch self-
  verification (memory-bandwidth-bound; thread tuning didn't help; it caught a bug in its own doctest).
- **Benchmark scorecard: Qwen2.5-Coder-7B = 100% pass@1 (10/10) @ 3.17 tok/s** on the friend's tier
  (`benchmarks/scorecard_qwen2.5-coder-7b.json`). Honest reading: the 10-problem set is easy-to-medium, so
  100% = strong fundamentals, **not** saturation — HumanEval-164 is the next discriminating step.
- **Speculative decoding is slower on CPU** (measured 1.6 vs 2.6 tok/s) — don't use it on the potato tier.
- **RAG grounding is the #1 correctness lever** for small models. model2vec static embeddings (256d, no
  torch, ~30k/s CPU, ~92% of MiniLM) + sqlite-vec make semantic memory affordable even on a potato.
- Small-model-on-CPU cannot win serious coding vs the cloud → coding is a strong aspect made credible by
  **hybrid escalation** (UPG-01), not by overpromising.

---

## 9. Companion-depth (later)

Per **ADR-006 "Companion First, Workstation Second"** the coding track is reprioritized *below* the
companion soul, and must respect "no new major systems" (small enhancements, not new platforms). Softer
product-vision threads to pursue as felt-impact enhancements (not before the wedge is solid): experience
unification (continuity memory, passive initiative, emotional presence) · the growth system (ranks, visible
growth moments — the verify/"it learns" loop now has a UI) · the memory/learning pipeline (verification
loop, conversational confirmation, interest modeling) · a relationship/people space.

---

## 10. Done this session (verified, committed, pushed)

- **GUI truth pass — ~24 controls fixed**, each proven on the running app: chat toggles (plan-first,
  think-harder), working-notes leak, prompt-history ↑, context-usage bar, pipeline-clarify, retry button;
  404 endpoints (update-check, potato preset, checkpoints); growth widgets (velocity, watcher); **the
  verify/"it learns" loop now has a real UI**; voice speed+volume; `min_confidence` retrieval floor;
  startup wizard only on genuine first-run; study-plan delete; the `af_sky` invalid-voice fix; XP-to-next
  from the server. **G1 design-system layer** (`layla-rebuild.css`).
- **Foundation swap COMPLETE:** model2vec embedder (drops torch on the hot path) + sqlite-vec SIMD KNN
  (NumPy fallback) + the **potato preset keeps semantic memory**. ~250 memory tests green.
- **3 duplications collapsed** (plan stores deleted; XP thresholds → server; aspect titles →
  `personalities/*.json`) + 2 default-drift bugs fixed (performance_mode missing→auto; deliberation "auto"
  no longer forces debate). Governor/deliberation/skills renames = cosmetic, skipped by design.
- **Full review: 2,512 tests pass, 0 regressions.**

---

## 11. Ground truth / how to run · reference index

- **Run the app:** `.venv` (py3.12) — `.\.venv\Scripts\Activate.ps1 ; cd agent ; python serve.py` →
  http://127.0.0.1:8000/ui. **Run pytest:** the separate **`.venv-test`** (pytest is NOT in `.venv`).
  **Fast UI checks:** the static preview server (`layla-ui-preview`, :8777) + `preview_inspect`; the live
  animated app defeats `preview_screenshot`; clear the SW before reload.
- **CI / eval:** real-inference smoke via `stories260K` + AVX-off build + `top_k=1`/`seed=42` (unwired job);
  benchmark harness under `benchmarks/`; grounding eval seam = `passes_completion_gate` in
  `output_quality.py`.
- **Reference (kept, not folded):** `codebase/` (ARCHITECTURE · STRUCTURE · STACK · INTEGRATIONS ·
  CONVENTIONS · TESTING · CONCERNS — the clean-room map + boundary budgets + secret-key/integration map +
  open-risk ledger) · `research/` (SUMMARY · ci-llm-testing · eval-harness · security-patterns ·
  competitive-ecosystem — cited recipes backing the REQs) · `phases/` (GSD verification audit trail) ·
  `agent/docs/adr/001-006` + `agent/docs/VISION.md` (the real architecture-decision record).
- **Stale claims retired (do not resurrect):** the `ui-next/` React app (never built), the "Warframe-mystic"
  HUD + `#0a0008`/`#c0006a` palette (→ calm #1 `#0a0710`/`#c0395e`), "~207 shims open" (done), test counts
  2143/2508 (→ 2512), "app can't run locally" (`.venv` exists now).
