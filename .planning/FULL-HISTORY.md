# Full Git History — complete commit record (drop nothing)

Generated 2026-06-29. Root: 71a6500 (2026-02-25). 204 distinct commits across two lines that diverged at `26a37ef03aec8b3f1b59112dd1d018d672affeb8` (2026-05-17).

- Shared foundation: 138 commits (root → divergence)
- Refactor line (origin/master): 10 commits since divergence
- This session (friend-ready-session): 56 commits since divergence

---
## A. THIS SESSION's line — 56 commits since divergence (origin/friend-ready-session)
```
9edd9ed 2026-06-30  docs(planning): unified roadmap reconciling refactor + this session; position ~5/15
13161ff 2026-06-30  docs(handoff): scope the master-integration task (25 conflicts, resolution strategy)
0535c1a 2026-06-30  feat(install): fresh-laptop installer + remote-tunnel connect + session HANDOFF
b087312 2026-06-29  docs(planning): Phase 12 criterion 3 done — first benchmark scorecard recorded (2/3)
b4beb4d 2026-06-29  feat(benchmark): first scorecard — Qwen-Coder-7B 100% pass@1; fix Windows console crash
25b9d62 2026-06-29  feat(benchmark): HumanEval-style pass@1 coding benchmark harness (Phase 12, REQ-74)
601bea9 2026-06-29  docs(planning): Phase 12 criterion 1 done — suite green on real stack (1734 pass)
d512dca 2026-06-29  fix(tests): suite green on the real model stack (Phase 12, criterion 1)
9a4ce9c 2026-06-29  docs(planning): formalize Friend-Ready as GSD phases 11-19 + verification/context artifacts
8f2b989 2026-06-29  docs(planning): A3 memory-fallback shipped; record full-suite-hang finding
2fe7e18 2026-06-29  feat(memory): compiler-free vector store fallback — memory works without chromadb (A3, REQ-72)
cca84aa 2026-06-29  docs(planning): absorb the coding-quality + ecosystem layer (A8-A10, REQ-82..85)
600bd60 2026-06-29  docs(planning): integrate Friend-Ready milestone into the full GSD plan
42d5769 2026-06-29  fix(installer): don't overclaim speculative decoding — measured unhelpful on CPU
b306047 2026-06-29  feat(installer): hardware+domain+priority aware coding-kit recommender (Friend-Ready, Track A)
aaaac97 2026-06-29  test(security): harden REQ-11 autonomous-allowlist test + plan Friend-Ready milestone
12e7420 2026-06-29  docs(planning): Phase 6 log-redaction shipped; mark partial progress
4c68804 2026-06-29  feat(privacy): redact secrets/PII from audit log at the chokepoint (Phase 6, REQ-42/43)
fd830d9 2026-06-29  docs(planning): Phase 2 complete — VERIFICATION + ROADMAP/STATE updated
7d45082 2026-06-29  feat(legal): copyleft-license CI guard + THIRD_PARTY accounting (Phase 2, REQ-02)
7128991 2026-06-29  docs(planning): Phase 1 complete — VERIFICATION + ROADMAP/STATE updated
77335b4 2026-06-29  feat(security): OS-keyring secret store (Phase 1, REQ-12)
b1968ad 2026-06-29  feat(security): auth-required-when-exposed by default (Phase 1, REQ-11)
4f05229 2026-06-29  feat(security): rightmost-trusted-hop forwarded-IP derivation (Phase 1, REQ-10)
f0c2cd5 2026-06-29  docs(planning): validated ROADMAP (10 phases, REQ coverage) + STATE.md — GSD init complete
4deaf78 2026-06-29  docs(planning): research SUMMARY + REQUIREMENTS (REQ IDs)
eb80bcc 2026-06-29  docs(research): ecosystem, CI/LLM-testing, eval, security findings
fe5cc59 2026-06-29  docs: initialize GSD project (config + PROJECT.md)
32cf9dd 2026-06-29  docs(planning): GSD codebase map + remediation roadmap
dc0b9c0 2026-06-04  fix: bound model cache (F9 OOM SPOF) + test the agent loop's core (C5)
44cc3b0 2026-06-04  fix(security): eliminate the trust-boundary class (post-remediation re-review)
b6bb9aa 2026-06-04  fix(security): remediate the critical trust-boundary class (C1-C3) + C6/F28
4ca6968 2026-06-04  fix(security): block sandbox-escaping docker_run flags (audit item)
f521536 2026-06-04  chore(dev): one-command 3.12 test env + lite `dev` extra (no GPU/model build)
9ffc5bb 2026-06-04  fix(security): block tar symlink sandbox-escape in extract_archive + tool tests
f6653ad 2026-06-04  feat(memory): show cited knowledge sources under replies (RAG provenance)
bed20c6 2026-06-04  feat(memory): forget identity facts from "About you" + fix latent Row.get bug
2af402c 2026-06-04  feat(memory): "What Layla knows about you" view + aggregation endpoint
2f65317 2026-06-04  feat(council): configure per-aspect models from the Settings → Models panel
b611a69 2026-06-04  feat(council): heterogeneous multi-model deliberation
9d07db6 2026-06-04  fix(ui): never-silent "no model" banner + make first-run quiz skippable
3150e38 2026-06-04  fix(security): block remote writes to security-critical settings (audit HIGH)
38d7455 2026-06-04  fix(security): enforce sql_query read-only contract (audit HIGH)
8b0c440 2026-06-04  fix(security): hardened SSRF guard + apply to the web tool family (audit HIGH)
a38904a 2026-06-04  docs: fix 12 broken internal links
95c6533 2026-06-04  fix(ui): two buttons called non-existent endpoints (found via endpoint sweep)
8ce979b 2026-06-03  fix(ui): remove broken background glyph wall
68a6fee 2026-06-03  fix(security): redact secrets from GET /settings; share redaction logic
fae074f 2026-06-03  fix(transfer): untrack dead llama.cpp gitlink + machine-specific runtime cache
eabff31 2026-06-03  ui: quiet-confident redesign — calm the loudness, real header + ⋯ menu
ce34c53 2026-06-03  feat: port-conflict guard so Layla never collides on :8000
ffab35a 2026-06-03  ui: add palette-preserving polish layer; tidy the header junk drawer
df816e4 2026-06-03  fix: guard file-lock registry race (B7); dedupe httpx requirement
55528db 2026-06-03  fix: greedy JSON extraction (B6) and bounded model-download timeout (B9)
b38a177 2026-06-03  fix(security): stop /system_export secret leak and /setup/download SSRF
14d08ea 2026-06-03  fix: repair 8 confirmed audit bugs + add one-click Council UI
```
## B. REFACTOR line — 10 commits since divergence (origin/master)
```
6a58e12 2026-05-26  docs: add vision roadmap, ADR-006, update README with current architecture
031713b 2026-05-26  chore: remove accidentally tracked __pycache__ from sandbox
c37054e 2026-05-26  refactor: complete frontend rearchitecture, service reorganization, and agent loop decomposition
b7d4ccb 2026-05-24  refactor: Tier 5 centralization — constants, API key safety, dead import
93dfcb5 2026-05-24  refactor: Tier 4 items 3-4 — tool args validation + setup consolidation
1f9d2d6 2026-05-24  feat: Tier 4 items 1-2 — capability decay scheduler + PPTX/notebook extractors
ffd586f 2026-05-24  refactor: Tier 3 module consolidation — delete/inline 7 incomplete modules
68d9582 2026-05-24  refactor: Tier 2 mega-function extraction + exception logging upgrade
b122229 2026-05-24  fix: Tier 1 security and correctness hardening
4adcc87 2026-05-24  chore: Tier 0 dead code removal + full design documentation
```
## C. SHARED FOUNDATION — 138 commits (root 71a6500 → divergence 26a37ef)
```
26a37ef 2026-05-17  fix: skip sandbox default-path tests on CI (explicit config present)
740ddc5 2026-05-17  fix: add global CI safety net to block llama_cpp.Llama SIGILL
cb633cb 2026-05-17  fix: mock run_completion in research_topic pipeline tests
679d78d 2026-05-17  fix: mock run_completion in research tests to prevent SIGILL
a37c5f4 2026-05-17  fix: exclude all llama_cpp-dependent tests from CI collection
02796ce 2026-05-17  fix: skip llama_cpp tests in CI, disable LLM prewarm, fix pool shutdown
5dc2dba 2026-05-16  fix: resolve SIGILL + timeout CI failures via lazy numpy/torch imports
7ff65da 2026-05-16  fix: resolve all CI/CD failures — lint, TestClient hangs, task_ctx crash
e4fa349 2026-05-13  ﻿feat: plan execution — Phase 0 quick wins, Phase 1A agent loop decomposition, Phase 2 dependency diet, Phase 6 test gaps
faced34 2026-05-13  ﻿fix: comprehensive audit — 18 bugs, dead code, and test fixes across Phase 1-8 modules
cec0eea 2026-05-13  ﻿fix: rework config defaults - secrets use None, opt-in booleans default False
6062ff6 2026-05-13  feat: Phase 8 — hardening with integration tests and config migration
54da6a9 2026-05-13  feat: Phase 7 — WebSocket support and multi-agent task delegation
49f0cb5 2026-05-13  feat: Phase 6 — open-source integrations (web crawler, Docling, Qdrant, Mem0)
96f5800 2026-05-13  feat: Phase 3 — remote access promotion with tunnel auth, audit logging, Tailscale
9646a04 2026-05-13  feat: product build-out Phases 1,2,4,5 — LLM gateway, Discord polish, skill packs, search router
5509dbb 2026-05-13  feat: engineering blueprint complete — safety, expertise retrieval, privacy separation
fec0bfe 2026-05-13  feat: Phase 8 — scaffold promotion, tool descriptions, service test depth
dbbbe09 2026-05-13  feat: Phase 7 — knowledge loading, spaced repetition, people codex
93e701b 2026-05-13  feat: Phase 6 — autonomy engine enhancements
80a9056 2026-05-13  feat: Phase 5 — advanced token management
41ce7f0 2026-05-13  feat: Phase 4 — research orchestrator, ingestion pipeline, reranker
72a7884 2026-05-13  feat: Phase 3 — observability stack (metrics, crash handler, structured logging)
13ae2a1 2026-05-13  feat: Phase 2 — debate engine, aspect model routing, streaming wiring
aa6bd85 2026-05-13  feat: Phase 1 structural integrity — codex, scheduler, confidence, original_goal
927f447 2026-05-12  docs: add git history regression sweep — zero regressions found
151d8ea 2026-05-12  feat: flip cognitive layer defaults to maximal, enrich model catalog
64fc7bf 2026-05-12  docs(plan): update SYSTEM_PLAN.md and ROADMAP.md with audit-backed status markers
5a9ffcd 2026-05-12  docs: consolidate scattered documentation, archive stale files, update hub index
7b343c6 2026-05-12  feat(memory): enforce memory_router as canonical write path (partial migration + lint check)
cdbd787 2026-05-12  fix(agent_loop): preserve original_goal alongside optimized_goal in state
0bc4e74 2026-05-12  fix(config): make config_cache importable assertion truly pass
ac67964 2026-05-12  Audit fixes #1-#10: wiring, config cache, degraded mode, honesty
4184fe5 2026-05-02  Phase B: repo indexer, watertight test infrastructure, 100% confidence
0a2be45 2026-04-29  Add Phase A memory coherence: entity schema, memory router, SQLite tables, check scripts
4120ded 2026-04-29  Add Phase 6 intelligence layer: AirLLM, LLMLingua, prompt optimizer, KB builder, Syncthing sync, WCAG AA
d7378c8 2026-04-29  feat(artifacts): server-side artifact extraction in /agent response (Item #11)
f0bc4b1 2026-04-29  feat(german): add German language learning mode (Item #10)
96fc112 2026-04-29  feat(tool-tracing): wire request_tracer into executor + 38 tool tracing tests
c39a51e 2026-04-29  feat(observability): per-request trace -- tokens, phase timings, /health/trace
c92ede9 2026-04-28  feat(aspects): real behavioral separation -- reasoning depth, length, step limits
2c03494 2026-04-28  feat(frame): extract FRAME calibration into frame_modifier.py
dd6a647 2026-04-28  feat(memory): add inline memory command system + cross-session working memory
42e41ee 2026-04-28  feat: comprehensive smoke test suite (41 tests) + fix check_config duplicate key detection
ffb5f8a 2026-04-28  fix: repair CRLF-in-string-literal and BOM in agent_loop.py
8ba34e4 2026-04-27  feat: dynamic hardware-aware auto-config + capability self-awareness
3291373 2026-04-27  fix: small-model context guard — stop injecting 18 sections into 4096-token window
5d70484 2026-04-27  feat: add repeatable bug pattern + config health scanners
dfe4a82 2026-04-22  fix: harden echo stripping, stop sequences, and completion gate contamination
3678284 2026-04-22  fix: resolve KV cache overflow crashing every LLM completion after first
cfc0cc8 2026-04-22  fix: Layla now responds correctly to chat messages
8cc0e00 2026-04-22  fix: 6 bugs from second audit pass
aeaecf7 2026-04-22  fix: stream_reason TypeError + missing laylaAgentTimeoutMs
38e2167 2026-04-22  fix: 8 bugs found in comprehensive post-v0.3 audit
473834f 2026-04-21  feat(phase5): Obsidian vault sync, Phase 1-4 test suite, onboarding polish
cc0a9f2 2026-04-21  feat(phase4): concurrent context isolation, retrieval confidence, dual-model CoT
c53eeae 2026-04-21  feat(phase3): performance polish, Warframe CSS, accessibility, voice/perf settings
9296b03 2026-04-21  feat(phase2): plan Gantt viz, autonomous monitor, similar plans, outcome display
9ef186f 2026-04-21  feat(phase1): UI redesign — artifacts panel, global search, memory browser, voice personalities, stream stats
e99b7ca 2026-04-20  feat(phase0): backend observability — context budget, tool tracing, workspace invalidation, model routing
9d5bb16 2026-04-20  refactor: consolidate context builder and fix critical system issues
cd259da 2026-04-18  fix: pending.json lock + lite mode overrides for PR #1 tests
22a4b36 2026-04-18  merge: PR #1 claude/xenodochial-feistel (solidification) into master
e6cc1c8 2026-04-18  feat: onboarding doc, installer resilience, CI and agent updates
bfcf8d0 2026-04-18  feat(autonomous): prefetch reuse/wiki, wiki export flag, source/reused API
b9ab86c 2026-04-16  Fix Windows bundling and make unit tests LLM-free
020f21f 2026-04-16  Fix Windows packaging scripts and PyInstaller spec
8c4cf2f 2026-04-16  Fix prompt assembly: reserve budget for goal and workspace context
ccf3528 2026-04-16  Fix prompt budgeting: prioritize workspace context and avoid negative remaining
7113bcc 2026-04-16  Fix CI: preserve current goal in budgets; support POSIX paths; cleanup cgroup leaf
fca414c 2026-04-16  Ship unified intent routing with tool preflight + telemetry
2a62a6f 2026-04-16  docs: link documentation hub from PROJECT_BRAIN
c22b5da 2026-04-16  chore: document GitHub README refresh; align quality defaults in load_config
8eb6249 2026-04-16  docs: professional GitHub README and documentation hub
2ac8bdd 2026-04-15  chore: restore Cursor rules and MCP config
91063b5 2026-04-15  Merge remote-tracking branch 'origin/master'
8ec58be 2026-04-15  feat: enforce deterministic quality gates and polish repo
75229a4 2026-04-13  consolidation: outcome_writer, SQLite barrel+migrations, engineering pipeline kwargs, codex/study/sandbox/UI fixes, docs archive
5f39170 2026-04-05  Delete .cursor directory
60d9064 2026-04-05  feat: planning-first agent, project memory, checkpoints, Elasticsearch, parity CI
1c434ef 2026-03-23  fix: rl_feedback.py wrong function name add_capability_event → insert_capability_event
073d633 2026-03-23  fix: resolve all three CI failures
012ae94 2026-03-23  fix: wire cancellation, remove LLM lock bottleneck, fix STT blocking
e1b6282 2026-03-23  fix: cursor MCP — venv path, 4 new tools, timeout bump, rules update
aa290c1 2026-03-23  docs: update MASTER_ANALYSIS — milestone solidification complete
e9ec2b6 2026-03-23  fix: curly quotes in main.py voice/stream, ruff import order
79fa242 2026-03-23  perf+fix: async LLM queue, cancellation, lite mode, sandbox, pending lock, UI improvements
7591006 2026-03-23  feat: RL feedback loop, DXF fabrication runner, streaming STT WebSocket
2e10258 2026-03-23  feat: discord bot — fully working slash commands, voice/TTS, music, error handling, reconnection
036b1ab 2026-03-23  docs: add repo_state/MASTER_ANALYSIS.md — canonical deep analysis
d937bd7 2026-03-21  feat: non-clinical psychology integration + operator sources catalog
68c2396 2026-03-21  ci: ruff (incl. imports), Playwright UI e2e; cross-tab health sync
ed22931 2026-03-21  feat: production hardening, geometry, fabrication assist, multi-surface UX
aa3c3bf 2026-03-20  feat: implement full platform upgrade foundation
75eeda2 2026-03-20  feat: expand model catalog + full Cursor MCP integration
59dd1da 2026-03-19  feat: finalize power-user upgrade and repo repair pass
4298a19 2026-03-19  Power-user upgrade: sandbox runners, code intelligence, retrieval, safety hygiene
5502d53 2026-03-19  feat(agent): harden LLM routing, setup UX, and context assembly
290f027 2026-03-19  feat: OpenClaw core alignment, transports, tool governance, audit hardening
67c4b90 2026-03-18  fix: chat response handling and load thresholds
669f5f3 2026-03-18  fix(ui): chat send/enter and all buttons work via bootstrap + window handlers
0bb2d86 2026-03-17  Module second sweeps: XSS, SSRF, path traversal, null safety, logging
a5155e9 2026-03-14  feat: config schema, dynamic settings UI, install flow improvements
0f99ab5 2026-03-14  fix(ui): remove dead _origRefreshApprovals — follow-up to Kai's send() fix
737fced 2026-03-14  fix(ui): avoid recursion when wrapping send(); ignore .zed folder
2b4a97c 2026-03-14  fix: cannot send message — model pre-check, error handling, troubleshooting
bb52de3 2026-03-14  test: add startup import smoke tests (catches ModuleNotFoundError in CI)
26ae64b 2026-03-14  fix: add failure_recovery, decision_engine, reflection_engine (prevents runtime ModuleNotFoundError)
e0a3923 2026-03-14  fix: add missing context_manager, context_budget, token_count (fixes ModuleNotFoundError on Linux)
d0780bd 2026-03-14  feat: add cognitive workspace (tree-of-thought deliberation)
2819960 2026-03-14  Installation improvements + lint fixes
3c7c4c8 2026-03-13  fix: resolve ruff lint errors for CI (F401, F541)
947b251 2026-03-13  feat: v1.1 mission system — long-running tasks with persistence
2b0350e 2026-03-13  chore: finalize milestone v1 stabilization
af0761a 2026-03-13  fix: add python-multipart to requirements for FastAPI form tests
f407a30 2026-03-13  fix: CI - write lightweight runtime_config before tests, skip slow marker, add timeout
682f78e 2026-03-13  feat: auto-learning extraction, study learnings persistence, fix scheduler gate
114fad8 2026-03-13  fix: CI - add pytest/httpx to requirements, fix 106 ruff lint violations
7a748ba 2026-03-13  feat: sprint 2 - session history, diff viewer, URL fetch chip, warmup bar, study plans, memory search
015abc0 2026-03-13  feat: mature product UX - setup overlay, example prompts, settings panel, inline approvals, file upload, tool status
6017432 2026-03-13  feat: Tier 3 complete - 74 to 109 tools (+35 new tools across all domains)
4dc6c71 2026-03-13  feat: 74 tools (Tier 2 complete)  NLP, code intel, science, ML, feeds, image utils
d2ebbde 2026-03-13  feat: 59 tools  semantic memory, workspace map, crawl, schema, self-reflection, context mgmt
8516bb4 2026-03-13  feat: 49 tools  symbolic math, NLP, OCR, charts, docs, DB, finance, security
add3607 2026-03-13  feat: 40 tools (+11 new), library expansion, all audit gaps closed
b914499 2026-03-13  ﻿fix: TUI Cassandra, tools-reference update, memory export UI button
3c6da03 2026-03-13  ﻿feat: @mention syntax + aspect lock for direct aspect addressing
98d8a3f 2026-03-13  ﻿v2.1 - full technical reference knowledge base for all 6 aspects
9ec0693 2026-03-13  ﻿v2.0 - skillset expansion, character depth, knowledge base, UI polish
a92c336 2026-03-13  v2.0  Character depth pass, cohesion layer, critical systemPromptAddition bug fix
8e98a47 2026-03-13  docs: AI-friendly cleanup - AGENTS.md, archive stale docs, fix paths, update rules
f108ecc 2026-03-13  fix: critical gaps - lilith.json, neuro.json, sandbox bug, knowledge base, MCP, TTS, config
61a069c 2026-03-13  feat: installer, launchers, model guide, vision, friendly README
d719041 2026-03-13  polish: UI overhaul — aspect theming, animations, copy buttons, empty state
bf66387 2026-03-13  feat: major capability upgrade — RAG, reasoning, browser, voice
46ebbe2 2026-03-13  perf: maximize inference speed + replace MIT with Non-Commercial Source License
d857e3c 2026-03-13  feat: full overhaul — anonymize, OSS foundations, critical fixes, arch upgrades, features
71a6500 2026-02-25  Initial commit: Layla — local AI companion (multi-aspect, approval-gated)
```
