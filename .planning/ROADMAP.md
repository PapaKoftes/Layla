<!-- GENERATED 2026-07-22 by an adversarial multi-agent audit (33 + 30 agents).
     Every unit was independently CHALLENGED before inclusion; challenged-out units are
     retained with their refutation because the refutation is usually the useful part. -->

# Layla — Milestone Roadmap
## "Everything we built is finished and reachable"

*Synthesised from ~50 scoped units (17 of which failed adversarial challenge and carry corrected scope), plus the 7 release blockers. Nothing below is re-derived; where I contradict a unit, the contradiction comes from that unit's own challenge record or from a fact I re-verified this session.*

---

## 0. How to read this

**The gate applied at every phase** (from `.planning/PROJECT.md` → Active): *"Every advertised capability is real — nothing claimed in README, UI, or in-chat that does not work."* That is not a phase. It is a **merge condition on every phase**. A phase is not done if it added a surface whose backing data or behaviour is not live.

**Ordering principle: TRUTH BEFORE EXPOSURE.** Within every phase the slices run: *fix the data → make the signal real → prove it live → only then draw it on screen.* Where a unit's own `slice_boundary` inverted that order, I have re-ordered it and said so.

**Effort convention.** Hours = focused solo hours by one person. Calendar is worse than hours here for three reasons that recur below: a warm turn on this box is ~70–115s so any *live* verification loop is slow; anything touching a second machine cannot be verified at all until the gaming PC is up; and the 3B is a weak tool-selector, so "does the model choose it" is a measurement, not an assumption.

**Effort ratings** are `hours` (< 1 day), `days` (2–5 days), `weeks` (> 1 week). I have used the **corrected** effort from each challenge record, not the original unit's.

---

## 1. The sequence at a glance

| # | Phase | Theme | Effort | Blocking unknowns |
|---|---|---|---|---|
| **1** | **Ship it without flinching** | The tag gate + every visible lie deleted | 30–34h | none |
| **2** | **The default turn tells the truth** | P13 residuals; the done-frame whitelist; executor arg binding | 18–22h | none |
| **3** | **Corrections stick** | Feedback loop, decision memory, SRS grading, strategy bucketing | 26–32h | none |
| **4** | **Long conversations survive** | Episodic chain — 5 stores off one dead branch | 16–24h **+ spike** | **SPIKE-A** |
| **5** | **One brain, everywhere** | Remote access (the operator's actual ask) | 40–60h **+ spike** | **SPIKE-B** |
| **6** | **Repeatable work** | Macros you can mint, watchers that watch, rules that fire | 30–40h | none |
| **7** | **Drop-in extensibility** | Plugins/skills load; one skill pack actually executes | 50–70h | product call on pack execution defaults |
| **8** | **Bridges** | Transport identity + status; Discord that connects | 50–70h | **DECISION-1** (discord.py vs py-cord) |
| **9** | **The clustering pillar** | Pairing → auth → paired-only offload → real speedup | 120–160h | **SPIKE-C**, second machine |

**Total ≈ 380–500h.** For one person that is 3–4 months at a sustainable pace. **The natural release line is after Phase 5**: Phases 1–5 deliver "publishable, honest, remembers you, reachable from your phone" — that is a coherent v2.0. Phases 6–9 are a second milestone.

---

## PHASE 1 — Ship it without flinching

**Goal:** The thing you tag is a thing you'd hand to a stranger — installs, runs, and never claims a capability it does not have.

### Units

**1A. The seven release blockers** (already audited — folded, not re-derived)

| Blocker | Corrected note |
|---|---|
| Version coherence | **Verified this session:** `agent/version.py:3` and `pyproject.toml:7` both say `1.5.0`; `git describe` = `v1.5.0`; **HEAD is 81 commits past that tag**. So the version string does not identify the build, and `auto_updater.py:40` compares that stale string against the newest GitHub tag. Fix = bump both + tag the release you actually ship. **1h** |
| `INSTALL.bat` browser promise | as scoped. **1h** |
| Fresh-install `sandbox_root` | **Same work as the "Wizard workspace picker" unit** — do not schedule twice. `wizard.js` `onNext()` at step 2 calls `await saveSetupWorkspaceIfNeeded()` (which already exists and works at `setup.js:31-42`), plus a belt-and-braces retry before the step-5 completion POST. **6–8h** |
| CI green on master | 12 days red, 10 real failures, `prometheus_client` missing from the dev extra. **6–8h** |
| `NO_FILE_ACCESS_DIRECTIVE` dead on stream | Set `state["context_suffix_for_stream"]`; both `routers/agent.py:1193` and `routers/research.py:441` append before `stream_reason`. **Ship with the two rewritten tests in the same commit — the vacuous AST test in `test_no_fabrication_when_tools_fail.py:108` is what let this through.** **4h** |
| Cluster offload below the streaming early-return | **⚠️ RE-SCOPED. The audit's "4h — hoist it" is wrong.** Per the challenge record, hoisting requires a raw-inference peer endpoint that does not exist (`/v1/chat/completions` re-wraps the prompt in the *peer's* persona and memory). That is Phase 9, weeks. **Phase 1 action instead:** make `run_completion_cluster` return `None`/raise on transport failure instead of manufacturing `{"choices":[{"message":{"content":"Cluster offload to X failed: [WinError 10061]..."}}]}`, and fix the caller's "text is non-empty" acceptance test at `inference_router.py:840`. Result: the one config flag that could poison a user's answer with a raw socket error no longer can. **4h** |
| README screenshots of an empty app | **2h** |

**1B. Delete every shipped lie** (all subtractive; a removed control cannot lie)

- `ui/components/chat-render.js:393` — the unconditional `<div>Discord bot integration</div>`. The voice claim directly above it was already deleted for exactly this reason; the comment explaining why is still there.
- `ui/index.html:24` — the remote-key banner telling the user to paste `remote_api_key` from `runtime_config.json`. `check_auth` only honours that key when `allow_legacy_remote_api_key` is true, which is **absent from live config**. Following the on-screen instruction yields 401 forever. **This is the signature defect already shipped in the product.**
- `main.py:420` — gate mDNS start on `cluster_enabled OR an active pairing session`. It defaults **True** while every consumer defaults False, so a standalone install broadcasts hostname + hardware tier to the LAN for nothing. The identical fix was already applied to the drone/queen worker threads at `main.py:537-552`; the reasoning was never carried across.
- `agent/cluster_config.json` — 336KB / **647 fabricated drone peers** written by `tests/test_cluster_e2e.py:490` into the operator's real config. Reset to a clean skeleton; repoint the test fixture at a tmp dir.
- `discord_bot/discord_bot_state.json` — test-fixture guild IDs (1, 2, 3, 50…) in the working tree. Add a path override + fixture; same for `guild_config.py:18`'s hardcoded `_DB_PATH`.
- `index.html` — remove `#idb-cache-toggle` (a checkbox whose only reader restores its own state) and `#km-label` (a field no JS references).
- `runtime_config.json` — `vision_enabled: True` with **both** model paths absent. Either set it False or make `/vision/status` report the truth. (Full vision work is out of this milestone — see Cut list.)
- One explanatory comment at `routers/agent.py:677` recording *why* the fast path passes no state to `commit_turn` — so the next audit does not re-file it as a bug. (Closes claim (b), zero behaviour change.)

**1C. `tui.py` — a README-documented entry point with no memory** *(2h)*
`README.md:351` offers it, `layla.py:291/396` ships it as `layla tui`, and `Start_Layla_Terminal.ps1:47` launches it. It never sends `conversation_id`, so `routers/agent.py:378` mints a fresh UUID every turn: **zero cross-turn memory for anyone who follows the README.** Thread the field. (Note: the "run it once and see if it renders a turn" test the original unit proposed would have *passed* this.)

### Hard dependencies
None. Every item is independently shippable; 1B can ship the day it starts.

### What a user can do at the end that they could not before
Install Layla from the documented path and have `read_file` / `list_dir` / `file_info` work on **their own code** without hand-editing JSON — the single biggest gap between what she claims to be and what she can do. And nothing on screen tells them about a capability that isn't there.

### Exit criteria (measurable)
1. `python -c "import version; print(version.__version__)"` equals `git describe --tags --abbrev=0`, and `git rev-list <tag>..HEAD --count` == 0 at tag time.
2. `INSTALL.bat` on a clean VM: exit code 0 **and** a browser process observed spawned (assert the process, not the log line).
3. **Scripted wizard completion → probe reads the live config back and asserts `sandbox_root == chosen_dir` AND `list_dir(".")` returns > 0 entries.** Probe must assert its own precondition (`assert resolved_config_path == <printed path>`) and fail loudly.
4. Full `workflow_dispatch` on master: every non-nightly job green.
5. **Live** `stream=true` request with a tool forced to fail → the reply contains the "could not read" phrasing and **not** an invented heading. (Non-streamed path already passes; the point is the default path.)
6. `rg -n "Discord bot integration" agent/ui/` → 0 hits. `rg -n "remote_api_key" agent/ui/index.html` → 0 hits.
7. `python -c "import json;print(len(json.load(open('agent/cluster_config.json'))['peers']))"` → `0`.
8. With `cluster_enabled=False`, a startup probe asserts `mdns.start_service` was **not** called.
9. TUI: two consecutive turns; probe asserts the same `conversation_id` in both request bodies.

### Effort
**30–34h.** ~5–7 working days.

---

## PHASE 2 — The default turn tells the truth

**Goal:** Every enrichment the turn already computes actually reaches the user, and a hallucinated argument name stops destroying the turn.

### Units

**2A. Housekeeping deletion** *(4h — invisible to users, do it first while the head is cold)*
One commit, provably no behaviour change (nothing imports any of it):
- `services/llm/llm_decision.py` (282 LOC — its own docstring says it "can be adopted incrementally"; it never was)
- `services/retrieval/reranker.py` (191 LOC — already ported to `vector_store_rerank.py:69`)
- `services/workspace/code_intelligence.py` (103 LOC — BL-302 rewired `search_codebase` away from it)
- `services/infrastructure/config_migrator.py` + its 9 tests — **a probe proved it 100% redundant**: 0 of 40 keys missing from `load_config`, 0 value mismatches, `_RENAMES` is an empty dict. It is a hand-synced second source of truth for 40 defaults.
- The 5 phantom `capabilities.impl.*` registry entries + `vector_backend` + `reranker_backend` config keys (see Cut list for the argument).
- `layla/memory/vector_qdrant.py` goes with them — its only claimed consumer was the phantom registry entry.

**2B. The done-frame whitelist — one root cause, two dead features** *(6h)*
`routers/agent.py:1297` is an **explicit literal whitelist of ~12 keys, not a passthrough**. The non-streaming branch (`:1553`) does whole-state passthrough, so anything set on `state` works there and silently dies on the default streaming path. Confirmed casualties: `explanation` **and** `answer_quality` (the latter has **zero consumers repo-wide** despite being written at two sites). Add both keys; add a regression test that asserts a *live* `stream=true` done-frame carries them.

**2C. Explainable reasoning — flag + placement** *(6h)*
`explainable_reasoning_enabled` is **absent from all 437 keys** of the live config, so `run_finalizer.py:146` has never fired. Default it on, mirror `explain_state` to the turn boundary (`commit_turn`) as skill acquisition and learning extraction already were, and **return `None` when thoughts and tools are both empty** — on the fast path `build_explanation` degenerates to restating the answer, and a collapsible that says nothing is worse than absent. **UI rendering is deliberately NOT in this phase** (see Phase 3).

**2D. `core.executor.run_tool` argument binding** *(4h)*
P13-E1 fixed `invoke_tool` (7 tools). `core/executor.py:118,140` still does `fn = TOOLS[...]["fn"]` then `fn(**clean_args)` — so **every approval-gated tool** still raises `TypeError` on an invented parameter name. It fails *closed*, so this is reliability, not the security regression the audit described. Route through `invoke_tool` (or lift the binding into a shared helper). **Widen the AST guard in `test_tool_args_are_untrusted_input.py:108` to walk both files and match the bind-to-local form** — it currently cannot see this file, and would not match the pattern even if pointed at it.

**2E. `git_add` scope-widening** *(minutes, same touch as 2D)*
`git_add(repo=..., files=[...])` → `files` is dropped, `path` falls back to `'.'`, **"stage these two files" becomes "stage everything"**. Rule: when `invoke_tool` drops args for a tool with a defaulted *scope* parameter, return `ok=False` naming the accepted parameters instead of running with the default. *(For the record: no case of this on an approval-gated tool exists — that half of audit claim (d) is refuted.)*

**2F. Bucket `strategy_stats` by task type** *(4h)*
Both writers store the **verbatim goal** (`_g.replace("\n"," ")[:120]`). Live table: 65 rows, every one a distinct sentence, max `success_count` 2, against a reader demanding `min_samples=5` on exact match — **mathematically cannot fire**. `classify_task` already exists and is already used for exactly this bucketing at `turn_commit.py:141`. Existing rows are unaggregatable by construction; leave them for the retention cap.

### Hard dependencies
Phase 1 (2B's regression test needs the stream handoff of 1A already correct).

### What a user can do at the end
Nothing new on screen — **and that is the point.** This phase makes three signals real so Phase 3 can show them. What the user *feels* is that a tool call with one wrong parameter name no longer nukes the turn.

### Exit criteria
1. `rg -l "config_migrator|services.retrieval.reranker|services.workspace.code_intelligence|capabilities.impl" agent/ --glob '!**/tests/**'` → 0 hits; full suite still green.
2. **Live** `stream=true` turn → the done frame JSON contains keys `explanation` and `answer_quality`. Assert on the wire, not on `state`.
3. An 8-turn session with tools → `SELECT COUNT(DISTINCT task_type) FROM strategy_stats WHERE created_at > '<phase-start>'` returns ≤ ~12 buckets, and `SELECT task_type FROM strategy_stats WHERE created_at > '<start>' AND length(task_type) > 40` returns 0 rows.
4. AST guard walks both `tool_dispatch.py` and `core/executor.py`; a live call to an approval-gated tool with one invented kwarg returns `ok=False` with a named-parameter message, **not** a `TypeError` traceback.
5. `git_add(repo=X, files=[...])` returns `ok=False` naming accepted params; `git status` shows nothing staged.

### Effort
**18–22h.**

---

## PHASE 3 — Corrections stick

**Goal:** What she learns from a turn actually persists and changes the next one — and you can finally tell her she's wrong.

### Units

**3A. The thumbs (BL-242) — highest value-per-hour in the entire audit** *(4–6h)*
The **read side already reaches the model**: `system_head_builder.py:1330` folds `feedback_hint_for_prompt()` into `memory_sections`. `answer_feedback.py` + `routers/feedback.py` are complete and mounted. Missing: **the write door.** Zero hits for `thumb` / `/feedback` / 👍 / 👎 anywhere in `agent/ui`. Add 👍/👎 per assistant message in `chat-render.js`; 👎 opens a one-line "what should it have said"; POST `/feedback`. **The first correction a user types takes effect on the very next turn.**

**3B. Decision memory (BL-235)** *(4h)*
Two independent starvations, and the second is the signature defect: the **live** thinking path is `services/planning/debate_engine.run_deliberation` (called from `reasoning_handler.py:174`, `stream_handler.py:203`) — a *different function of the same name* from `cognitive_workspace.run_deliberation`, which is the only one that calls `record_decision`. Add the call to the path users actually reach, reusing the identical payload shape from `cognitive_workspace.py:118`. **Do not relax the 100-char/keyword gate in the same slice** — you would not be able to attribute the change.

**3C. SRS grading gets a caller that is not the 3B** *(days, 12–16h)*
All 35 learnings are **permanently due**: 0 with `next_review_at`, 0 with `review_reps > 0`, ease 2.5 across the board. "What should I review" returns the same items forever.
- **⚠️ The unit's proposed host is dead.** `verify.js` → `/verify/answer` → `verification_queue.py` has **0 rows**, `submit_for_verification` has zero non-test callers, and it keys on a TEXT `fact_id` in its own table — answering it **INSERTs a new learning** (`verification_queue.py:270`) rather than grading an existing one. Wiring SM-2 there is a no-op for all 35 rows.
- **Corrected slice 1 (truth, no UI):** fix `registry.py:553` (the skill literally named `spaced_repetition_review` whose tools list omits the real tool), fix the stale docstring at `learnings.py:572` ("There is no adaptive SM-2 path for learnings" — now false), and anchor an implicit grade on a surface that **carries `learnings.id`**: either `routers/memory.py:59-60` (the memory browser, already user-reachable) or grade-on-retrieval at `system_head_builder.py:163`. Retrieved-and-uncorrected grades 4; corrected grades 2.
- Slice 2 (exposure, later): an explicit 0–5 review view. **Never first** — a due-list UI over an all-NULL table is the exact half-wired surface the ordering rule forbids.

**3D. Render the explanation** *(4h)*
Now that 2B/2C made the value real and it arrives on the wire, render `state['explanation']` as a collapsible under the reply. **Reuse the collapsible POV-trace affordance from the thinking-mode work** — do not invent a new one. Budget strings across all 11 `ui/locales/*.json`.

### Hard dependencies
Phase 2 (3D needs the done-frame whitelist).

### What a user can do at the end
Mark an answer wrong, say what it should have said, and **see the correction land on the next turn.** Ask "why did we decide that?" about a real past deliberation and get an answer. Stop being shown the same five review items forever.

### Exit criteria
1. Click 👎 + type a correction → `SELECT COUNT(*) FROM answer_feedback` ≥ 1, **and** a probe on the next turn's *assembled prompt* asserts the correction substring is present. (Probe asserts the prompt it captured is the one that was sent.)
2. One deliberation on the live path → `SELECT COUNT(*) FROM decisions WHERE created_at > '<start>'` ≥ 1.
3. After one review interaction: `SELECT COUNT(*) FROM learnings WHERE next_review_at IS NOT NULL` ≥ 1 **and** `SELECT COUNT(*) FROM learnings WHERE review_reps > 0` ≥ 1. Re-query the due list and assert the graded item is **absent**.
4. Live `stream=true` turn with ≥1 tool step → collapsible renders non-empty; fast-path "ok" turn → collapsible **absent**, not empty.

### Effort
**26–32h.**

---

## PHASE 4 — Long conversations survive

**Goal:** Turn the one dead branch that starves five memory stores, and light the Timeline tab honestly.

### ⚠️ Record correction, first
`.planning/PROJECT.md` lists *"Conversation survives past the in-memory window (summaries + timeline + relationship memory) — P13-B2"* under **Validated**. Live data says `conversation_summaries` **0**, `episodes` **0**, `episode_events` **0**, `relationship_memory` **0**, and the only 2 `timeline_events` are both `onboarding_complete`. The honest status is **UNPROVEN, not validated** — the occupancy fix landed 2026-07-21 and *every* conversation since has exactly 2 messages, so the gate has never been approached. **Move that line out of Validated before anything else in this phase.**

### SPIKE-A (do this before writing any fix) — 4–6h
Five stores hang off one choke point: `context_manager.py:126`, the `if _persisted_kind:` branch. It has never fired. Two candidate causes, and the unit could not distinguish them:
- (a) the ring never reaches occupancy 16 in-process;
- (b) **the LLM-lock admission race** — `_compress_to_summary` does a **non-blocking** acquire on `llm_serialize_lock`, which is a plain `RLock` (reentrant only for its own holder). The compaction daemon is a **different thread**, spawned at the tail of an assistant turn, on a box where turns take 70–115s. If the streaming generator has not released, it raises `RuntimeError("llm busy")`, degrades to `[Earlier conversation (truncated)]`, and the force path bails **every time** — while every component looks healthy.

**The spike is not "add a counter and wait."** At the observed 2-messages-per-conversation rate that is an indefinite wait. **Drive a scripted 8-turn conversation deterministically** with instrumentation at `context_manager.py:110` recording `(snap_len, summary_prefix, _persisted_kind, lock_acquired)`. The probe must assert `snap_len >= 16` was actually observed, or it proves nothing.

*(Two claims already refuted and not worth re-testing: `is_memory_junk` does **not** reject the summary, and `add_timeline_event`/`create_episode` signatures match their call sites.)*

### Units
- Fix whichever cause the spike names. If (b): the compaction daemon needs a blocking-with-timeout acquire, or compaction must run inside the turn's own lock holder.
- Everything downstream is already wired: `routers/timeline.py` is mounted and **already consumed** by `intelligence.js:64`. **No UI work required** — the tab lights up on its own.
- *(`intelligence.js:106` already renders an honest empty state, so this is not currently a TRUTH-BEFORE-EXPOSURE violation — it is a truthful blank. Don't let that be an excuse to leave it blank.)*

### Hard dependencies
None technically, but **schedule it after Phase 3** — Phase 3 is what makes people have long conversations worth summarising.

### What a user can do at the end
Have a conversation longer than 20 messages and find that Layla still knows what happened at the start of it — and see the Timeline tab populated with real events rather than one onboarding marker.

### Exit criteria
After one scripted 8-turn conversation:
1. `SELECT COUNT(*) FROM conversation_summaries` ≥ 1
2. `SELECT COUNT(*) FROM episodes` ≥ 1 **and** `episode_events` ≥ 1
3. `SELECT COUNT(*) FROM timeline_events WHERE kind != 'onboarding_complete'` ≥ 1
4. `SELECT COUNT(*) FROM relationship_memory` ≥ 1
5. Turn 9 references a fact stated in turn 1 (live, human-checked — this one is qualitative and I am labelling it as such).

### Effort
**16–24h + the 4–6h spike.** Confidence MEDIUM until SPIKE-A returns.

---

## PHASE 5 — One brain, everywhere

**Goal:** Open Layla from your phone on the sofa and continue the same conversation, same memory, mid-thread. One brain, one writer — no replication, no conflicts.

**This is what the operator actually asked for, and it sidesteps the distributed-systems problem entirely.** It is the highest value-per-hour unit in the whole multi-device territory.

### SPIKE-B (must run first; can start during Phase 2) — 4h
Turn `remote_enabled` on behind a token, reach `/agent` from a second device, and **record what actually breaks.** The challenge already found five things that will:
1. **`GET /` is not in the interactive allowlist** (`main.py:1150-1203`) though the UI is served there — a phone hitting the bare host 403s.
2. A probe of the UI's real call graph (68 JS files, 109 endpoints, evaluated with `main.py`'s own matcher) shows **63 of 109 denied even in the most permissive built-in mode** — `/history`, `/memory/*`, `/operator/profile`, `/onboarding/*`, `/platform/*`, `/search`, `/skills`. Chat works; the app around it does not.
3. Default `remote_mode="observe"` allows only `/wakeup`, `/project_discovery`, `/health` — so `/agent` is denied **at defaults**. The unit's open question resolves to *"on-paper only."*
4. **No credential can exist.** `tunnel_token_hash=None`, `remote_api_key=None`, and **zero UI files** reference `/remote/token/rotate` or `/remote/tailscale/*`.
5. **`EventSource` cannot carry an `Authorization` header** — `models.js` (model download) and `setup.js` (setup progress) are *structurally* unreachable remotely regardless of allowlist or token.

### Units (ordered)
1. **Credential minting in the UI** — a rotate/reveal flow for the remote token. Without this the feature has no front door. *(The `index.html:24` banner was already deleted in Phase 1; this is what replaces it, honestly.)*
2. **Curate the allowlist against the UI's actual call graph** — or invert it to a deny-list. **This is the real work of the phase**, and it is a security decision, not a config toggle. Tailscale itself (`routers/system.py:743-790`) is genuinely real and is *not* the hard part.
3. **A query-token or WebSocket path for the two `EventSource` consumers**, or an explicit "not available remotely" state for them. Do not leave them silently broken.
4. **Phone-width UI pass** — verify, don't assume.
5. **Only then**: a "Remote access" panel with setup steps.

### Hard dependencies
SPIKE-B. Phases 1–4 (they are what makes remote access worth having).

### What a user can do at the end
Pick up their phone anywhere on their tailnet, open Layla, and continue the exact conversation they left on the desktop — with the same memory, the same aspect, the same thread.

### Exit criteria
1. From a **second physical device** on the tailnet: `GET /` returns 200 and the UI renders.
2. `POST /agent` with the token **streams** a reply that appears in the desktop's history for the same `conversation_id`.
3. **A scripted crawl of all 109 endpoints under the shipped remote mode reports 0 unexpected 403s for the interactive set** — and the probe asserts it enumerated 109, not 12.
4. The two `EventSource` consumers either work or display an explicit unavailable state (assert the DOM node, not the absence of an error).
5. With `remote_enabled=False` (the default), every one of the above returns 403. Verify the off state, not just the on state.

### Effort
**40–60h + 4h spike.** Confidence MEDIUM — the allowlist curation is the unknown.

**Consequence:** if this phase succeeds, **conversation sync becomes largely unnecessary** for a single-user product. See Cut/Defer list.

---

## PHASE 6 — Repeatable work

**Goal:** Do something once, save it, and have it happen again — by hand or on an event.

### Units

**6A. `knowledge_watcher` — the watcher that watches nothing** *(minutes, do first)*
`_load_config` (`knowledge_watcher.py:171`) does `Path(d)` over `watch_folders` **with no `expanduser()`**. The live value is `["~/Documents"]`. `Path("~/Documents").is_dir()` is False, so every scan loop silently skips every directory — **while logging `"Knowledge watcher started (watchdog mode, 1 dirs)"`.** Net: **0 of 5 automation event types are live**, not 1 of 5.
Also: `on_created` passes `kind="file_created"` into `_on_file_change`, which **ignores the parameter** and hardcodes `dispatch_event("file_modified")` at line 277. Classic callee-sets / caller-ignores. One-line fix.

**6B. Macros you can actually mint** *(6h)*
`macros.js` implements list, replay, delete — **but no create.** The only way a macro can exist today is auto-acquisition, which needs ≥3 successful tool steps in one run, and *no evidence exists that a single real 3-tool user run has ever completed* (`tool_calls` has 16 rows, newest are literally `run_id='probe'`). Add a **"Save as workflow"** action on a finished multi-step run — `extract_steps_from_run` (`macros.py:72`) already produces exactly the right shape. This makes the existing overlay non-empty for the first time and is **independent of whether auto-acquisition ever fires.** Leave `min_steps=3` alone until real runs exist to measure against. Separately: add a nav button (it is command-palette-only today).

**6C. Automation: repair, then a door** *(days)*
**⚠️ The unit's slice order is wrong.** Its slice 1 (add `schedule` + `git_commit` emitters, leave rule creation curl-only) ships **no user-observable change at all** — real events firing into an empty rule table. TRUTH BEFORE EXPOSURE forbids surfacing dead features; it does not require shipping a stage with no surface.
**Corrected single slice:** 6A's repairs + a `schedule` emitter from the already-running scheduler (`create_scheduler` genuinely is called at `main.py:358`) + **expose `add_rule`/`list_rules` as an agent tool** so the user can say *"when a file in Documents changes, re-index it"* and have it work end to end.
*(Two corrections: `layla/tools/impl/automation.py` is a **different subsystem** — desktop control, its own apscheduler — and is not an existing door. And `git_commit` cannot come from `system_head_builder`'s git block, which is a per-turn prompt snapshot, not a change detector; a scheduler job diffing HEAD is the honest emitter.)*

**6D. Proactive goals** *(days)*
**⚠️ "Data, not wiring" is wrong — the proactive half is effectively unreachable.** Three compounding gates: goal hints are appended **last** in `collect_initiative_hints` while the sole consumer (`initiative_inline.py:52`) takes only `eng_hints[0]`; the whole path requires `len(tool_steps) >= 1`, so **zero-tool companion turns — exactly where an unprompted nudge belongs — never reach it**; and both `initiative_engine_enabled` and `inline_initiative_enabled` ship **false** in `runtime_config.example.json:276-278` (they are true only in this operator's local config). Plus `GET /goals/suggestions` has **no frontend caller**, and `intelligence.js:80` reads `g.progress` against the API's `progress_pct`.
**Order:** (1) give goal hints their own priority slot + a goals-aware idle/wakeup path, turn the shipped defaults on, fix `progress`/`progress_pct`; (2) *then* add create/complete controls to the Intelligence panel; (3) separately, constrain `add_goal` tool selection — there is no classifier at fault, the 3B simply called `add_goal` on a math query, which is why the one goal in the DB is titled **`1+1`**. Purge that row.

### Hard dependencies
Phase 3 (macros need real multi-step runs to save; feedback + tool reliability from Phase 2 make those happen).

### What a user can do at the end
Finish a multi-step task, click **Save as workflow**, and replay it. Say *"when a file in this folder changes, re-index it"* and have it actually happen. See a real goal, mark progress on it, and be nudged about it when it stalls.

### Exit criteria
1. Probe asserts the watcher's **resolved** directory list is non-empty and every entry `.is_dir()` is True; touch a file in it → `SELECT COUNT(*) FROM automation.rule_fires` (or the dispatch log) increments, and `kind` is `file_created` for a new file.
2. Save a run as a workflow → `SELECT COUNT(*) FROM macros` ≥ 1; replay it → all steps report `ok=True`.
3. `SELECT COUNT(*) FROM rule` ≥ 1 created **through the agent tool, not curl**; a `run_macro` action executes and its macro's steps appear in the execution log.
4. A zero-tool companion turn on a stalled goal produces a goal nudge in the reply (live, and assert the goal id appears in the assembled hint).
5. `SELECT * FROM goals WHERE title='1+1'` → 0 rows.

### Effort
**30–40h.**

---

## PHASE 7 — Drop-in extensibility

**Goal:** Put a file in a folder, or install a pack, and Layla can actually use it.

### Units

**7A. The two off-by-one directory roots** *(4h — do this first, it is nearly free)*
Both compute `REPO_ROOT` **one directory short**. `markdown_skills.py:16-17` names a constant `AGENT_DIR` that resolves to `agent/services`, making the scan base `agent/skills` (empty) instead of repo-root `skills/` — **which contains the README telling users to put files there.** Probed prompt length: **0**. `plugin_loader.py:11` has the same shape, scanning `agent/plugins` (a cookiecutter `_template`) instead of repo-root `plugins/` where `plugins/example/plugin.yaml` lives. Probed: **0 skills / 0 tools / 0 capabilities.**
**The regression test must assert the resolved scan directory equals the repo root** — not merely that loading succeeded. Asserting success is what let this survive.

**7B. Resolve the bundled-packs contradiction, then make one pack execute** *(days)*
**⚠️ Two scoped units conflict and both are partly wrong.** One says "add `install_from_path` and list the 5 bundled packs day one"; the other says all 5 **fail `validate_manifest`** on two counts (no `entry_point`; a `name` with spaces/slashes violating `^[a-zA-Z0-9_-]+$`). The second is correct — I am treating the five as **manifest-only stubs with no code**, which cannot be surfaced as-is.
**Resolution, in order:**
1. **Delete the five stubs.** They are one JSON file each; there is nothing to salvage.
2. **Fix the venv precondition.** `run_entry_point` (`skill_sandbox.py:169-171`) hard-requires a per-pack venv interpreter with **no `sys.executable` fallback**, but `create_venv` has exactly **one** production caller — inside `install_from_git`, guarded by `skill_venv_enabled` (default **False**). So a *copied/seeded* pack can never run. Either provision on any install path, or **fall back to the host interpreter for a pack declaring zero dependencies** (defensible — the module docstring is explicit that the venv is *not* a security boundary). The second is the smaller change and lets bundled packs be dependency-free by design, which they should be on a CPU-only box.
3. **Make `runnable` mean runnable.** Today it is literally `bool(isinstance(entry_point, str) and entry_point.strip())` — it echoes a manifest string and never checks the file exists, the venv exists, or the flag is on. **The originally-proposed acceptance criterion (`assert runnable == true`) would pass on two packs that cannot run.**
4. **Ship two real, dependency-free packs** + a seed-on-first-run step.
5. **Add a skill-pack intent rule.** `rg "skill"` across `intent_router.py`, `tool_policy.py`, `toolchain_graph.py` returns **zero hits**. A live probe shows *"what can you do with pdfs"* → `run_skill_pack` **False**; *"can you summarize a csv"* → **False**; only the literal words *"skill pack"* admit them. Without this, the prompt hint at `llm_decision.py:408-419` advertises a tool that `llm_decision.py:624` then **silently discards** — advertised, obeyed, dropped.
6. **Couple the hint to `valid_tools`** — compute `valid_tools` first and suppress the hint when the tool was filtered out.

**7C. Registry becomes readable** *(4h)*
`list_packs()` / `get_pack()` have **zero production callers**. `GET /skill_packs` reads the filesystem (and `mkdir`s as a side effect of a read) and returns raw manifests with no `runnable` field — **diverging from what the tool reports.** Rewrite it to join registry rows (health, last_run, git_url, provenance) with `list_installed_readonly()`.

**7D. Marketplace entries + a run endpoint** *(days)*
`install_kit` **already** has a `git_url` branch calling `install_from_git`, but **zero of the 7 `KIT_CATALOG` entries carry a `git_url`**, so it has never executed. Add pack entries + teach `installed_status()` to consult the registry.
**⚠️ Also required and missed by the original UI unit: there is no `POST /skill_packs/run`.** `run_skill_pack` is a *model-facing tool only*; `rg dispatch_tool|execute_tool|run_tool` across all routers returns **zero hits**, so no router can dispatch any tool. A UI "Run" button would have to route through the 3B choosing the tool — unreliable on this box. Add the thin endpoint.

**7E. Plugin SDK → developer CLI, not app UI** *(4h)*
Expose `scaffold_plugin`/`validate_manifest` through the already-shipping `layla` CLI as `layla plugin new` / `layla plugin validate`. **Do not build a UI for it** — scaffolding a plugin from a chat window is not a coherent user action. Explicitly *not* a cut: this is the authoring end of the skill-pack pillar.

**7F. Pack UI — last** *(days)*
One overlay reusing the marketplace shell, wired to install/list/run/remove. **Only after 7B–7D.** It needs an honest warning that the runner is dependency isolation, **not a security jail** — the module docstring says so and the UI must repeat it. And it must surface **both** gates (`skill_packs_execute_enabled` *and* `skill_venv_enabled`), or a user who flips one installs a pack and gets `"venv Python not found"` on every run.

### Hard dependencies
7A is independent. 7B → 7C → 7D → 7F is a strict chain.

### What a user can do at the end
Drop a `SKILL.md` into `skills/` and have it take effect. Install a skill pack in one click from the marketplace they already have, ask a capability-shaped question, and have Layla name the pack and run it.

### Exit criteria
1. **Probe asserts the resolved scan directory `== repo root`** (not that loading succeeded); `plugins/example` loads and `example_skill` is present in `SKILLS`; markdown-skills prompt length > 0.
2. `list_skill_packs` returns ≥ 2 rows where `runnable` was computed from **file existence + interpreter availability**, not a manifest string.
3. **`run_skill_pack` end-to-end returns `exit_code == 0` with non-empty stdout** — the only acceptance criterion that means anything here.
4. A probe on the assembled decision prompt for *"what can you do with pdfs"* asserts `run_skill_pack ∈ valid_tools` **and** the pack id appears in `prompt_context`; `SELECT COUNT(*) FROM tool_outcomes WHERE tool='list_skill_packs'` > 0 (it is 0 today).
5. Install a pack from the marketplace → it badges installed, and `GET /skill_packs` reports the same `runnable` value the tool reports.

### Effort
**50–70h.**

---

## PHASE 8 — Bridges

**Goal:** The Slack/Telegram/Discord bridges are startable, observable, and honest — and the Discord bot actually connects.

### DECISION-1 (blocking; make it before planning the phase)
**`bot.py` is a hybrid that no single library satisfies.** 20 slash commands use `bot.tree` + `discord.app_commands` (**discord.py only**), while `/listen` and `/stop_listen` at `bot.py:595-617` use `discord.sinks.WaveSink()` / `vc.start_recording()` — **voice receive, which exists only in py-cord**. Picking discord.py ships two registered slash commands that `AttributeError` at runtime; picking py-cord means porting 20 commands to `slash_command`/`ApplicationContext`, which is a rewrite, not a fix.
**The test stub is why this was never caught:** `test_discord_bot.py:33` stubs `discord.app_commands` and `:44` stubs `discord.sinks`, side by side.
**Recommendation: commit to discord.py, drop voice-receive** (or feature-gate it so it is *not registered* when unavailable). Voice receive on a CPU-only box with a 3B was never going to be good.

### Units
1. **Settle the library** — requirements + **3 docs** + `setup_profiles.py`. Note the product already contradicts itself: `feature_installer.py:40` maps `"discord.py": "discord"` and `setup_profiles.py:38` lists `discord.py`, while `requirements.txt` and the docs say py-cord. **`setup_profiles.py:38` is the one place already correct.** And `agent/docs/DISCORD_SETUP.md:228-238` has a troubleshooting entry that walks the user **in a closed loop back into the broken state** — fix it or delete it.
2. **Fix the autostart import** — `main.py:378` does `from bot import _create_bot` after inserting `discord_bot/` on `sys.path`, but `bot.py:61-90` uses **relative** imports. Reproduced: `ImportError: attempted relative import with no known parent package`, swallowed into a `logger.warning` at `:404`. Needs **repo root** on path (`transports/` is at repo root, not under `agent/`) and `from discord_bot.bot import _create_bot`. Remove `discord_bot` from the exclusion set at `check_imports.py:31`; raise the swallowed warning to a visible startup error.
3. **Transport identity + last-seen** *(before any status panel)* — all three transports are **outbound-only clients with no listening port**, so the app cannot probe them; and `transports/base.py:249` sends only `Content-Type` while `AgentRequest` has no `source`/`transport` field, so a stamped value would be dropped by Pydantic. **Stamp identity in `transports/base.py`, accept it on `AgentRequest`, record last-seen server-side.** This is the truth layer and it ships no UI.
4. **Close the `/learn/` hole in the same touch** — `routers/learn.py:72` takes **no `request: Request` object at all**, so it structurally cannot do an origin check, yet `bot.py:190` → `transports/base.py:304` POSTs to it, writing into `save_learning`, `vector_store` and **the memory graph that reaches the prompt**. `is_direct_local` is wired into six routers but **not** `learn.py`. Same for `/learn/correct`. Force `allow_write`/`allow_run` False on transport-marked requests across `/agent` *and* gate the learn routes. *(Today's posture is caller-enforced only: the bot calls localhost, so `is_direct_local` returns True for it.)*
5. **Add the three missing credential keys to `EDITABLE_SCHEMA`** — only `discord_bot_token` is there; `slack_bot_token`, `slack_app_token`, `telegram_bot_token` are **not settable in-app at all**.
6. **Then** the read-only Connections panel (configured? / last seen), **then** supervised start/stop.
7. `discord_bot_autostart` gets a `config_schema.py` entry + `runtime_config.example.json` line — **only after 1 and 2**.
8. **`setup_error_handler(bot)` is never called** — `_create_bot` returns at `bot.py:801` without invoking it, so unhandled command errors produce *nothing* in Discord. One call site.
9. `guild_config.py` (195 LOC, tested, **zero callers**, DB file never created) — ship the **read side first**: channel allowlist in `on_message` (which today only checks the single bound channel and ignores `allowed_channels`) and `default_aspect` into `_call_layla` (which hardcodes `aspect_id='morrigan'`). The module's defaults make an empty DB behave exactly like today.
10. **Per-user rate limiting** before any guild with more than the operator in it — today's 2s debounce is per-*channel* and slash commands bypass it entirely. On single-model CPU inference two concurrent users queue silently.

### Hard dependencies
DECISION-1. Items 1→2 gate everything else. Item 3 gates the status panel.

### What a user can do at the end
Run `python -m discord_bot.run` **or** flip the in-app toggle and get a bot that connects, answers `/ask`, respects channel restrictions, and reports errors instead of going silent — and see in the app whether their Slack/Telegram/Discord bridges are configured and alive.

### Exit criteria
1. `python -m discord_bot.run` against a **real test guild**: `/ask` returns an answer.
2. **Autostart path** with the toggle on: log shows `on_ready` (assert the log line, and assert the import did not fall into the warning branch).
3. `check_imports.py` no longer excludes `discord_bot` and passes.
4. A transport-originated `POST /agent` is observed with `allow_write=False`, `allow_run=False` **forced server-side** (assert in the handler, not in the caller); a transport-originated `POST /learn/` is rejected or downgraded.
5. Connections panel shows `configured: true/false` per transport from `EDITABLE_SCHEMA`, and `last_seen` updates within one message of a live bridge.
6. Two rapid `/ask` calls from the same user → the second gets a visible "still working" reply, not silence.
7. `rg -n "py-cord" docs/ agent/docs/ discord_bot/` → 0 hits (or the inverse if DECISION-1 goes the other way).

### Effort
**50–70h.**

---

## PHASE 9 — The clustering pillar

**Goal:** Anchor this box to the gaming PC and get an answer that is actually faster.

**This is the most expensive phase in the milestone and the only one that cannot be verified on one machine.** It is also explicitly WANTED (`PROJECT.md`: *"The remote pillar is WIRED, not deleted"*), so nothing here is a cut. But sequence it last and go in with eyes open.

### The finding that reprices this whole phase
**There is no raw-inference endpoint on a peer.** The only inference entry a Layla instance exposes is `/v1/chat/completions`, which runs the **entire agent pipeline** — content guard, quick-reply short-circuit, the peer's *own* persona/aspect/memory via `stream_reason`, junk-stripping, and history writes to the peer's DB. The local path being replaced is `llm.create_completion(prompt, ...)`: a raw completion over an **already fully-rendered** prompt. So today's offload hands a finished prompt to a peer as a bare user message and the peer **re-wraps it in its own brain.** The user would not see the same answer faster — they would see a *different, double-wrapped* answer, plus 400s when an internal prompt trips the content guard.
**A new authenticated raw-inference peer endpoint (`prompt`, `max_tokens`, `temperature`, `stop` → raw tokens, no pipeline) is a hard prerequisite**, and it applies retroactively to the already-shipped non-streaming hook (masked only by being default-off).

### Ordered units

1. **Discovery that says so when it cannot work** *(hours — cheapest, protects everything above it from blind debugging)*. **`zeroconf` is not installed in `.venv`** — it is only in the optional `network` extra. mDNS gates **both** the pairing UI and `_get_cluster_peers()`, so no peer is pairable or offloadable on a default install regardless of anything else. Install it, cover it in the clustering install profile, and propagate the unavailable/failed reason into `/pairing/status` and the cluster panel.
2. **Fix the cluster auth handshake — the keystone.** Sender transmits the stored SHA-256 hash; receiver hashes it **again** before comparing. Mismatch by construction. The tunnel fallback has the identical bug. **Not a one-line fix:** `request_pairing` (`cluster_pairing.py:255-257`) discards the raw secret and persists only `sha256(raw)`, so the drone has no raw credential to send even after fixing the header — this is a storage-format change plus a config migration for any box that already has a `cluster_secret_hash`. **Every test passes today because they all run against one localhost `TestClient` and take the localhost bypass at `cluster.py:104-106`.** The new test must use a non-localhost client IP.
3. **Stop rotating the secret on every pair.** `accept_drone` (`cluster_pairing.py:143-146`) regenerates `cluster_secret_hash` unconditionally — **pairing a second device silently invalidates the first.** Needs a per-peer credential, not one global cluster secret.
4. **Address resolution.** `request_pairing` derives `drone_address` **solely** from Tailscale and records `""` without it (and `cluster_network` early-returns on empty addresses). Worse, the drone stores `result.get("queen_address", queen_address)` — `.get` with a default only fires when the key is **absent**, and it is always present, so **the address the user typed is discarded in favour of the queen's self-reported `http://127.0.0.1:8000`. The drone ends up pointed at itself.** Needs a LAN-IP fallback and user-input precedence.
5. **A drone-join button that works.** `request_pairing` has **zero callers**; `cluster.js:301` posts `{queen_address, token}` to an endpoint expecting `{pairing_token, instance_id, name, address, hardware_tier}` → **422**. Add `POST /cluster/join`, fix the UI shape. **Ship 2–5 as ONE slice** — shipping the join endpoint alone paints "Paired successfully!" over a cluster that 401s on its next call, which is *worse than today's 422 because today's 422 tells the truth.*
6. **Advertise only what you bind.** ⚠️ Larger than scoped: **the app process cannot currently observe its own bind address** — there is no `host` key anywhere in config, and `LAYLA_HOST` is local to `serve.py:93`, while `Dockerfile:31` and ~15 docs launch `--host 0.0.0.0` without it. Deriving the advertised address from env/config would **silence advertising on every correctly-configured remote deployment** — inverting the bug. Needs uvicorn socket introspection (or an explicit export from `serve.py`) with a Docker-safe fallback. **Same slice must carry the effective port** — mDNS advertises `cfg["port"]` while `port_guard` relocates to a free port, the common Windows case.
7. **Hardware tier truth.** `mdns_discovery.py:89` uses `.total_mem`; torch's attribute is `.total_memory`, so the probe always raises and is swallowed — **the beefy machine advertises itself as `cpu` and the potato correctly refuses to offload to an apparent equal.** Also `:270` prefers `cfg["hardware_tier"]`, which defaults to `"cpu"`, so detection never runs. Reconcile with `setup_wizard.py:181-199`'s separate, correct VRAM detector rather than keeping two.
8. **Paired-only selection.** `try_cluster_offload_first` calls `get_best_peer_for_inference()`, which **filters by tier alone**. `_get_cluster_peers` — which correctly intersects discovered peers with paired devices *and* requires `permissions.inference_offload` — is reached only from a zero-caller function. **Enabling one config flag today sends full prompts to any LAN device advertising a GPU tier.** Pure caller-swap. **This must land before any UI toggle exists.**
9. **Enforce the pairing permissions that are already written and shown.** Of five permissions, **exactly one** (`inference_offload`) has a reader. `read_learnings` / `write_learnings` / `sync_knowledge` / `remote_tools` have **no reader anywhere** — `/cluster/sync/push`, `/sync/pull`, `/task/submit` call only `_require_auth` and never consult the caller's record. Have `_require_auth` return the identified peer; gate each endpoint; fail closed. **No UI change needed — the controls already exist and finally do something.**
10. **Collapse the two pairing systems.** ⚠️ **Inverted claim in the original unit:** `inference_router.py:600-601` **already reads the PIN store** and filters on `permissions.inference_offload` — offload is the PIN store's **only working consumer**. A collapse that makes `cluster_network` the registry must explicitly migrate `_get_cluster_peers()` or it relocates the store **out from under the one thing that works.**
11. **The raw-inference peer endpoint** (see above) — the actual prerequisite for any speedup.
12. **Streaming offload with first-token fallback.** Hoist the peer attempt above the streaming early-return; return the peer's generator when the first token arrives in time. **First-token timeout, not total** — a slow peer is worse than no peer. Liveness cannot key off the peer's first SSE frame (role-delta and `layla_progress` frames carry no content). Preserve `_add_usage` and the `_routing_prompt_var.reset()` currently in `_counting_gen`'s `finally`, or an early return leaks the contextvar.
13. **Expose it, last.** `cluster_offload_enabled` has **zero occurrences under `agent/ui`**. Toggle + a status line naming the serving peer (`try_cluster_offload_first` logs which node served and throws the fact away).
14. **Reframe Syncthing** *(hours, independent, do it any time)* — the setup guide currently instructs the user to **file-sync a live SQLite database** and hand-delete `.sync-conflict` files. That is a path to silently losing memory. Repoint at the knowledge-watcher folder and sandbox workspace; add an explicit "never sync `layla.db`" warning. Guide-and-copy only. **Do not cut the module — the code is sound.**

### SPIKE-C (before unit 11–12, the expensive half) — 8h, needs both machines
**Measure whether this is worth building at all.** Stand up the 3B on the gaming PC, hit it over LAN with a fully-rendered prompt, and compare **first-token** and **total** latency against local.
**Measurement protocol is non-negotiable** (`PROJECT.md` → Constraints): **alternate conditions, ≥3 samples.** Sequential run order on this laptop once reported +136% where the truth was +12.7%, twice nearly inverting a correct decision. If LAN round-trip + peer prefill does not beat the local floor by a wide margin, units 11–13 are not worth the weeks.

### Exit criteria
1. `python -c "import zeroconf"` succeeds in `.venv`; `/pairing/status` reports an explicit unavailable reason when it does not.
2. **From the OTHER machine**: the drone's heartbeat appears in the queen's `GET /cluster/peers` with a fresh `last_heartbeat`. This is the first moment "genuinely paired" is true — not a green toast.
3. Pair a **second** device; assert the **first** still authenticates (guards the secret-rotation bug).
4. `GET /cluster/status` on the gaming PC reports `hardware_tier != "cpu"`.
5. A probe asserts the offload peer list came from `_get_cluster_peers` (paired ∩ discovered ∩ permission), and that an *unpaired* LAN peer advertising `gpu_high` is **not** selected.
6. `/cluster/sync/push` from a peer with `write_learnings=false` returns 403 (fail closed).
7. Advertised address+port **equal the actually-bound socket** — assert against the live socket, not against config.
8. SPIKE-C: alternating-order, ≥3-sample first-token comparison with the delta and variance recorded.
9. Streaming offload: kill the peer mid-stream → the user gets a **local** answer, never `""` and never an error string.

### Effort
**120–160h + 8h spike, and a second physical machine.** Confidence MEDIUM.

---

## 2. Cut list — with the argument

| Cut | Argument |
|---|---|
| **The 5 phantom `capabilities.impl.*` entries** (`faiss_vector`, `qdrant_vector`, `openai_embed`, `cohere_rerank`, `bs4_scraper`) + `vector_backend` + `reranker_backend` config keys + `layla/memory/vector_qdrant.py` | `agent/capabilities/impl/` **does not exist**. But the deeper reason is that fixing it would change nothing: `get_active_implementation()` is only ever called with `llm_model_coding` (two call sites, both `model_router.py`). `vector_search` / `embedding` / `reranker` / `web_scraper` have **zero selection callers**; `vector_store.py` hardwires `chromadb.PersistentClient`. Two of the phantoms are **cloud APIs**, which contradict the product's first line. `vector_backend` has **no reader at all**. The only surface publishing the lie is documentation. Delete the entries, the keys, the adapter, and correct 4 doc passages. |
| **`config_migrator.py` + its 9 tests** | A direct probe (temp config, cleared caches, asserted precondition) proved it **100% redundant**: 0 of 40 keys missing from `load_config`, 0 value mismatches, `_RENAMES` empty, and the 2 "deprecated" keys it strips have **zero readers repo-wide**. Worse, the WIRE branch was inert by construction — `load_config` never writes back to disk. It is a hand-synced second source of truth for 40 defaults, flagged as such by its own comment. |
| **The 3 other dead duplicates** (`services/llm/llm_decision.py`, `services/retrieval/reranker.py`, `services/workspace/code_intelligence.py`) | Each has a live replacement already in the call path, and each *says so in its own docstring*. `PROJECT.md`: *"One owner per rule, never two copies."* |
| **Skill-pack permission *enforcement*** | Not "hard on Windows" — **undefined**. A pack subprocess has **no IPC channel back into Layla** (`env_extra` has zero production callers), so `read_memory`/`write_memory`/`voice`/`browser` name capabilities Layla never grants; the rest are ambient OS privileges it cannot revoke without a container. And install-time consent **already exists and is stronger** than the proposed replacement (two default-off flags, dangerous-tool approval, a plan-then-confirm dialog, and blunt "this is a downloaded script" copy). Rendering the permission strings in that dialog would surface a list that constrains nothing — *less* truthful than today. **Residue (hours, keep):** relabel the field as *advisory metadata* in docs + registry display, and drop the "Permission allow-list" bullet from `SKILL_PACKS.md:341` where it reads as a runtime control. |
| **The 5 bundled skill-pack stubs** | One `manifest.json` each, no code, no knowledge files, and **all five fail `validate_manifest` on two counts**. Nothing to salvage. Replace with two real dependency-free packs (Phase 7). |
| **`#idb-cache-toggle`, `#km-label`** | A checkbox whose only reader restores its own state; a field no JS references. A removed control cannot lie. |
| **Fast-path `state` to `commit_turn` (claim (b))** | Refuted. The fast path fires only on `ok/yes/no`, the `how are you` family, and test hooks — no run, no tools, no outcome to evaluate, and `_practice_domain_for_turn` already anticipates `state=None`. **Action: one comment**, so the next audit does not re-file it. |

### Deferred, not cut (keep the code, revisit later)

| Deferred | Why, and what would revive it |
|---|---|
| **Conversation/DB sync between nodes** | **Phase 5 likely makes it unnecessary** for a single-user product. If it is still wanted, the honest first slice is a **read-only mirror** — and note it currently has **no mechanism to be read-only**: no provenance column on `conversations`, no composer lock, no "mirrored from `<node>`, read-only" banner. A replicated thread would render as ordinary and writable, and the two nodes would diverge silently. *(Better news than scoped: message IDs are already globally-unique UUIDs, FTS is maintained by triggers so a plain INSERT reindexes for free, and messages are immutable — zero `UPDATE conversation_messages` repo-wide. The hard parts are pre-solved; the missing part is the read-only affordance.)* |
| **Cross-project reasoning (BL-232)** | Code is genuinely good; the universe is empty (`layla_projects` 0 rows). **The precondition is stronger than "two project rows"** — `_load_terms_for` returns empty unless each project has a non-blank `workspace_root` **and** an indexed `.layla/project_memory.json`, so you need **two indexed workspaces** or you get isolated nodes and zero edges. Worth noting `layla_projects` is *not* an orphan table — `world_state.py:36` reads it and world state reaches the prompt, so making projects real pays off independently. |
| **Rich Discord embeds** | 237 LOC, complete, tested, zero callers. Do not wire it until the bridge has carried real conversations for a while. It will keep. |
| **Batch/work-queue offload** | ⚠️ The receive side is **hollow**, contrary to how it was scoped: `process_file` has **zero definitions** (the real API is `ingest_file(Path, *, topic="") -> IngestResult`, a dataclass), `autonomous_wiki_entry` has **zero definitions**, and `_handle_study` silently returns the raw OpenAI envelope as a success. Only backup and consolidation resolve. Wiring a submitter first would produce a paired drone whose first act is to accept a job and fail it. |
| **Vision / VLM (BL-230)** | The investigation is **discharged and the answer is "nothing works"**: `pytesseract` and `easyocr` both fail to import, no `tesseract` on PATH (native Windows installer, not a pip package), BLIP absent from the HF cache, **and there is no image-ingress endpoint at all** — `/vision/analyze` takes a filesystem path; the only byte ingress is a private data-URI decoder reachable solely via `/v1`. This is a *build*, not a wiring job: one offline describer + a multipart upload route + a truthful `/vision/status`, in that order. Out of this milestone; Phase 1 only makes the config stop claiming it. |
| **`multi_agent`** | See SPIKE-D below. Leaning DEFER permanently. |

---

## 3. Where the honest answer is "we do not know enough yet"

| Spike | Question | Method (must assert its own preconditions) | Cost | Gates |
|---|---|---|---|---|
| **SPIKE-A** | Why has `context_manager.py:126` never fired — ring occupancy, or the LLM-lock admission race? | Scripted **8-turn** conversation with instrumentation at `:110` recording `(snap_len, summary_prefix, _persisted_kind, lock_acquired)`. **Assert `snap_len >= 16` was observed** or the run proves nothing. Do **not** "add a counter and wait" — post-fix conversations are all 2 messages, so that is an indefinite wait. | 4–6h | Phase 4 |
| **SPIKE-B** | Can a second device actually hold a conversation, and what does the allowlist deny? | Enable behind a token; from a real second device, walk the UI and log every 403. **Assert the crawl enumerated all 109 endpoints.** | 4h | Phase 5 |
| **SPIKE-C** | Does LAN offload to the gaming PC beat the local CPU floor by enough to justify weeks? | Both machines; **alternating conditions, ≥3 samples**, first-token and total. Sequential order once reported +136% where truth was +12.7%. | 8h | Phase 9 units 11–13 |
| **SPIKE-D** | Is `auto_tune`'s CPU-tier refusal of `multi_agent` a correct performance judgement or an over-broad default? | ⚠️ **The originally proposed probe is broken** — "force the flag on and send a 2-part compound prompt" would go down the **fast path**, never invoke `multi_agent`, and report "decomposition didn't help." Any probe **must first assert `is_self_contained_question(prompt) is False` AND `should_use_multi_agent(prompt, cfg) is True`.** Note the deeper finding: the fast path shadows `multi_agent` on **all** tiers including GPU (`is_self_contained_question` defaults to `return True`), and `is_decomposable`'s regex **rejects the path-bearing prompts that are the only ones surviving the fast path** — the two gates are anti-correlated. With `_SUBTASK_TIMEOUT_S=120` against a ~70s warm turn, `auto_tune`'s refusal looks correct. **Leaning: DEFER permanently.** Also for the record: there is **no "council marketplace kit"** — `council` is a `deliberation_mode` of `debate_engine`, unrelated; and the "advertises a refused capability" defect is **already fixed** (`feature_status.py` re-reads `load_config()` and attributes the OFF to auto_tune by name). | 4h | nothing — run it when curious |
| **DECISION-1** | discord.py (drop voice receive) or py-cord (port 20 commands)? | Not a spike — a product call. Recommendation above. | — | Phase 8 |
| **`answer_quality` / `grounding_enabled`** | Is a retrieval pass per answer affordable on this box? | Run the existing product benchmark with `grounding_enabled=True`; compare **latency and false-abstain rate**, alternating order. If affordable, flip the default in `runtime_safety.py` **and** the example config together. If not, **say so in a config comment** so the next audit does not re-file it as a bug. | 4h | fold into Phase 2 |

---

## 4. Things I want on the record

1. **`PROJECT.md` claims a Validated requirement that the live database contradicts.** *"Conversation survives past the in-memory window — P13-B2"* sits under Validated while `conversation_summaries`, `episodes`, `episode_events`, and `relationship_memory` all hold **0 rows**. The occupancy fix may well be correct — it has simply never been exercised, because every conversation since it landed is 2 messages long. **Move the line to Active before Phase 4 starts.** This is exactly the failure mode the project's own constraint names: *"Tests are not evidence of product health here."*

2. **One release blocker's stated fix is wrong.** Blocker (6) — *"cluster offload after the streaming early-return [4h]"* — is estimated as a hoist. The hoist requires a raw-inference peer endpoint that does not exist, and is weeks. Phase 1 ships the honest 4h version (stop the error envelope reaching the user); the hoist is Phase 9.

3. **Blocker (3) and the "Wizard workspace picker" unit are the same work.** Do not schedule them twice.

4. **Two scoped units contradict each other on bundled skill packs.** Reconciled in Phase 7B: the five stubs cannot be surfaced, because they fail their own validator on two counts.

5. **17 of ~50 units failed adversarial challenge**, and the failure mode was almost always the same: the unit named the missing wire but not the *second* gate behind it — a default-off flag, an intent-router filter, a whitelist, a missing endpoint, an uninstalled dependency. **Budget for this.** When a phase says "one call site," assume one more gate exists until a live probe says otherwise.

6. **Every "acceptance criterion" that reads a field rather than exercising a path should be treated as suspect.** The clearest example: `runnable` in `list_installed_readonly` is `bool(entry_point.strip())` — it echoes a manifest string. Asserting `runnable == true` would have passed on two packs that cannot run. `PROJECT.md`: *"Verify the probe before the result."*