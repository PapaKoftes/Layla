# Architecture Target and Migration

**Status:** proposed, not started. **Scope:** structural only. Individual bugs live in `ENGINEERING_HEALTH.md`; features live in `ROADMAP.md`.

**The operator's brief, binding:** simplicity is the goal (deleting a layer beats adding one); no rewrite (every checkpoint lands on a working product, 4047 tests green); not a bug list; finite and numbered — it must END.

**How to read this document.** Every number below was measured by AST or ripgrep probe against `C:\Work\Programming\Layla\agent`, with the UTF-8 BOM stripped before parse. Where an earlier audit's number was wrong, this document says so and gives the corrected one. Section 4 is executable: a fresh session can run CP-1 from this file alone.

---

## 1. Where we are — the architecture as it actually is

### The runtime path of one turn

One `POST /agent` turn traverses **16 modules / 10,695 LOC**, **8 call frames deep** before a tool executes:

```
routers/agent.py:1040 _dispatch_autonomous_run
  → services/planning/coordinator.py:211 run
    → coordinator.py:101 dispatch_autonomous_run
      → agent_loop.py:559 autonomous_run          (29 params, 126 LOC)
        → agent_loop.py:687 _autonomous_run_impl   (29 params, 92 LOC — forwards 22 POSITIONALLY)
          → agent_loop.py:821 _autonomous_run_impl_core (27 params, 180 LOC — receives 20 POSITIONALLY)
            → run_setup / decision_loop → llm_decision / tool_dispatch
```

Module LOC on that path: `routers/agent.py` 1629, `response_builder.py` 1306, `tool_dispatch.py` 1059, `agent_loop.py` 1000, `run_setup.py` 888, `coordinator.py` 727, `llm_decision.py` 658, `decision_loop.py` 644, `turn_commit.py` 500, `reasoning_handler.py` 439, `stream_handler.py` 404, `tool_dispatch_base.py` 332, `verification_engine.py` 266, `run_finalizer.py` 222, `tool_guards.py` 151.

### The three load-bearing facts of a turn have no owner

**(a) The final user-visible answer is not a value.** There is no `state["answer"]` anywhere. An AST search for a non-test assignment to `answer` / `final_answer` / `reply` returns exactly one hit and it is an error string (`decision_loop.py:95`). The answer is *inferred* from the tail of an append-only log, by two rules that disagree:

- **Rule A** — `routers/agent.py:1325` and `:1477`: `final = steps[-1].get("result","") if steps else ""`
- **Rule B** — `run_finalizer.py:101-102` and `routers/explain.py:86-87`: reverse-scan for `s.get("action") == "reason"`

They return different strings whenever the last step is a tool step — i.e. exactly the multi-step engineering turn, the flagship use case. *Measured, this session:* `steps[-1]` appears in **9 non-test files and 0 test files**. The router has HTTP-level coverage (15 test files reference `routers.agent`, incl. `test_golden_flow_http.py`, `test_e2e_agent.py`), but **nothing anywhere asserts what the answer text is** — because no expression denotes it.

**(b) The step log has 46 writers and zero assignments.** `state["steps"]` is never assigned; it is `.append`-ed at **46 turn-state sites across 6 files** — `tool_dispatch.py` 30, `decision_loop.py` 7, `tool_guards.py` 5, `tool_dispatch_base.py` 3, `reasoning_handler.py` 1, `agent_loop.py` 1. (A further 3 in `routers/settings.py` are an unrelated `out["steps"]`.) Two access conventions coexist: `state['steps']` and `ctx.state['steps']`. This independently reproduces C-1.

**(c) Turn termination is a string convention.** 22 non-test writes to `state["status"]` across 6 modules, producing ≥7 terminal values (`finished`, `parse_failed`, `stream_pending`, `client_abort`, `timeout`, `tool_limit`, `paused_high_load`). Consumers are *equality* gates, not exhaustive matches: `run_finalizer.py:32` gates its entire body on `== "finished"`.

### The turn boundary

`commit_turn` is called at **19 sites** (16 in `routers/agent.py`, 3 in `routers/openai_compat.py`) in **6 argument shapes**. Verified signature (`turn_commit.py:298-308`):

```python
def commit_turn(conversation_id, goal, text, *, aspect_id,
                status="finished", refused=False, learn=True,
                state: dict | None = None) -> str:
```

Per-argument coverage: `aspect_id` 19/19, `status` 16/19, `state` 6/19, `refused` 4/19, `learn` 1/19. `state` gates all learning at `turn_commit.py:363` and `:391`.

**Correction to a prior claim.** Earlier analysis said "13 of 19 exits persist and then silently learn nothing." That is inflated. `turn_commit.py:14-16` documents `state` as optional *by design*: the fast paths never call `agent_loop`, so no run state exists to gate on. Walking the sites, the genuine defect surface is **1-2 sites** (`routers/agent.py:1152` timeout; `:1142` is `system_busy`, already in `_NO_LEARN_STATUSES`). The structural fix is still worth its one-line cost — but it buys ~1/19, not 13/19, and this plan will not claim otherwise.

**Structural constraint discovered this session, and it invalidates one popular proposal.** An AST probe of the enclosing-function chain of all 16 `commit_turn` sites in `routers/agent.py`:

| innermost enclosing function | sites |
|---|---|
| `agen` (nested async generator) | 9 |
| `agen_fast` (nested async generator) | 3 |
| `agent` (the handler body) | 3 — lines 677, 770, 1537 |
| `agen_ma` (nested async generator) | 1 |

`agent()` returns `StreamingResponse(...)` at `:961`, `:1027`, `:1424`. **13 of 16 turn exits execute after `agent()` has already returned.** Any `with turn_scope(...)` wrapped around `agent()` would fire `__exit__` at the moment the StreamingResponse is constructed, committing an empty turn before a single token exists — reproducing the exact `stream_pending` defect it was meant to abolish, on the default streaming path. **The context-manager approach is rejected on measured grounds.** See §6.

### The module graph

At **module-load time this is a clean DAG**: 396 internal edges, zero import cycles. Counting function-body imports it is a mesh: **1571 edges, 1175 (75%) lazy-only**, and one strongly-connected component holds **165 of 521 product modules (32%)**.

De-facto core by fan-in: `runtime_safety` 132, `layla.memory.db` 76 (a 311-LOC module whose body is imports and aliases only — zero logic), `db_connection` 49, `time_utils` 45, `tools.registry` 41. `agent_loop.py` is not a layer but a facade: 52 of its 116 top-level imported names are never referenced in its own body, and 9 of its 15 functions are pure `return <call>` delegations — a ~61-name pass-through surface where C-9 estimated 23.

Layering: conforming edges dominate (`routers→services` 179, `services→storage` 116), but **78 genuine upward inversions** exist (`layla→services` 61, `storage→services` 15, `services→routers` 2) and **55 layer-skipping edges across 23 routers** reach past `services/` straight into `layla/`.

### The gates that were supposed to catch all this

`agent/scripts/check_architecture.py` exists and has four caps:

| cap | line | actual | verdict |
|---|---|---|---|
| `agent_loop.py <= 1800 lines` | :95 | 1001 | vestigial |
| `services/ flat files <= 205` | :106 | 1 | vestigial |
| `shared_state importers <= 15` | :150 | **16** | **under-counts → false PASS** |

`STRICT = "--strict" in sys.argv` at `:29`, so every cap emits WARN, not FAIL. **And it is not wired to CI at all** — `grep -rn "check_architecture" .github/` returns nothing across `ci.yml`, `release.yml`, `verify-deep.yml`. `test_scripts_readme_check_coverage.py` states it outright: the script "exists on disk but is not wired."

**Correction to the panel's most-repeated claim.** Three of four judge panels asserted the `shared_state` cap under-counts because "5 importers evade it by indenting the import one level." **That is wrong.** `check_architecture.py:142` uses `ast.walk`, so it *does* see function-body imports. I probed the true cause:

```
FILES SKIPPED by ast.parse (BOM/syntax): 1  →  routers\agent.py
shared_state importers, ast.walk (incl. function bodies): 16
shared_state importers, module-scope only:                10
lazy-only importers: 6  (jobs.py, routers/agent.py, routers/system.py,
                         approval_helpers.py, postchecks.py, route_helpers.py)
Is a SKIPPED file a shared_state importer? ['routers\agent.py']  ← yes
```

The mechanism is a **BOM swallow, not indentation**. `routers/agent.py` begins with U+FEFF; `ast.parse` raises `SyntaxError: invalid non-printable character U+FEFF`; the handler at `:140-141` does `except (SyntaxError, UnicodeDecodeError): continue`. The 1629-line main chat router is dropped, it is a lazy `shared_state` importer, so the count reports **15 — exactly at the cap — and PASSES**. The identical swallow exists in the repo's architecture *test*: `tests/test_architecture_boundaries.py:40-45` `_parse_file` catches `SyntaxError` and returns `None`.

This matters operationally: **stripping the BOM is a one-character fix that flips a green gate red.** That is CP-1.

### Live signature defect, caught alive

`orchestrator.NO_FILE_ACCESS_DIRECTIVE` (defined `orchestrator.py:721`) is the anti-fabrication guard. Measured: `build_standard_prompt` has **3 non-test callers** — `agent_loop.py:952`, `stream_handler.py:259`, `reasoning_handler.py:215` — and the directive is applied at **exactly one**, `agent_loop.py:955`, the non-streamed `parse_failed` fallback. The two streaming-path callers pass raw `context=context`. `tests/test_no_fabrication_when_tools_fail.py:57-60` AST-asserts the one fixed site and never enumerates the others: **a green test certifying partial coverage as complete.**

### State and data

Run state: **94 distinct keys, 198 assignments, 45 mutations, 369 reads, 33 production files.** Durable storage is healthier than its reputation — 52 of 53 `layla.db` tables have 1-2 production writer modules, and retention is both implemented and wired (`layla/scheduler/jobs.py:184-195`). The exception is `learnings`: **13 writer modules, 15 readers**, and the measured consequence is 35 rows against 7 vectors — 80% of learnings are not semantically retrievable.

Conversation history exists in **four copies**: the per-conversation deque, a second *global* deque (`main._history`, no conversation id, flushed to `conversation_history.json`), the `conversation_messages` table, and a `convo_block` prompt string built by two character-identical 28-line functions (`stream_handler.py:164-190`, `reasoning_handler.py:133-161`).

---

## 2. What is structurally wrong — ranked by cost

**1. The single most important output of the product has no owner and no type.** The answer is inferred from a 46-writer log by two disagreeing rules. Cost: any of 46 sites can change what the user sees, at a distance, with no local evidence. The two rules diverge precisely on multi-step engineering turns, where the router shows the user a raw tool result while the finalizer learns from a different string. It is *structurally impossible* to write a test asserting "the answer is correct," which is the root reason 4047 tests never caught any of this.

**2. Gates that report green while measuring nothing.** Three of four caps are calibrated to a shape the code left years ago; the fourth under-counts because of a BOM; `--strict` is opt-in; and the script is not wired to CI. `check_memory_coherence.py:114` resolves the knowledge graph to `agent/.layla/knowledge_graph.graphml` while the owner (`memory_graph.py:13`) writes `agent/layla/memory/knowledge_graph.graphml` — so it has returned a green `SKIP` forever. This is the signature defect *inside the detector*, and per the evidence rules a broken probe is worse than no probe. It ranks second because it makes every other item unverifiable.

**3. A safety directive reaches 1 of 3 sites and a green test certifies it.** The anti-fabrication guard is absent from the majority streaming path in production. This generalises: because prompt assembly has 3 independent construction sites, every future prompt-level guard will land on a subset, and the natural way to test one (assert it appears where I just edited) will keep certifying partial coverage as complete.

**4. Turn termination is a string with 22 writers and no exhaustive dispatch.** A new status value costs nothing to introduce and silently disables every downstream gate that did not enumerate it. Because the gates are equality checks, adding a value can never fail loudly — it can only make work quietly stop. `turn_commit.py:348-362` is a written confession of exactly this.

**5. Three stacked frames re-declare ~29 parameters and forward 20-22 POSITIONALLY.** Insert or reorder one parameter mid-signature and every argument after it shifts silently. The types are mostly `str`/`bool`/`list`, so a shifted argument is still type-valid and the 4047 tests cannot catch it.

**6. The turn boundary is 19 hand-copied calls in 6 argument shapes.** The corrected genuine surface is small (~1-2 sites), but the *shape* is the problem: the shortest call is the degraded one, so each new exit path defaults to it and the compiler, type checker and test suite are all satisfied.

**7. `learnings` has 13 writers and no owning module** — no single place to couple the row-write to the vector-index write. Measured cost: 35 rows, 7 vectors.

**8. 75% of the dependency graph is invisible to module-scope tooling**, and one SCC holds 32% of the product. This is real, and it is why the graph looks clean while behaving as a mesh. It ranks last deliberately: it makes the defect hard to **see**, not easy to **write**. Unwinding it is a rewrite.

---

## 3. The target architecture

### The one organising idea

> **The three load-bearing facts of a turn — its answer, its steps, its end — become values with exactly one owner each. Then delete the layers that existed only to forward arguments between them.**

Everything else in this plan is deletion or instrumentation. This is the winning design (`minimal-diff`, panel 29.3/40) with three grafts the panel named, and four corrections my probes forced.

**Grafted from the runners-up, as the panel directed:**

1. **Repair the detector before trusting any measurement, and sequence it first.** Named as the top graft by 5 of 12 judges across 3 of 4 designs. Refined here: the cause is the BOM swallow, not lazy imports.
2. **Make the degraded call shape unrepresentable, not discouraged** (`delete-first`, `contracts`). When a gate reads `if x is not None`, the fix is not to check harder at the gate — it is to make the caller unable to construct the call without `x`.
3. **Runtime liveness assertions, not only import-graph orphan gates** (`contracts` judge #3). This is the piece the winning design lacks, and it is decisive — see below.

**Why the liveness graft is not optional.** Judge #3 tested the winning design against the five confirmed historical instances and found its orphan gate catches zero of them, because all five are *runtime* no-ops with valid callers. I verified the sharpest case: `_sm2` at `layla/tools/impl/memory.py:122` **is called**, at `:172`, in a module imported by `layla/tools/registry_body.py`. A module-level orphan gate reports it healthy. `layla/memory/learnings.py:574` records the real state — the SM-2 columns hold 0 rows. Structure makes code singular; it does not make anything *fire*. Import-graph gates cannot detect absence.

### The new seam: `agent/services/agent/turn.py` (~150 LOC, the only new module)

Exports five names and nothing else:

```python
KNOWN_ACTIONS: frozenset[str]        # derived from measurement, enforced in log-only mode first
TERMINAL_STATUSES: frozenset[str]

def record_step(state, *, action: str, result: str, **extra) -> dict
def set_answer(state, text: str) -> None
def answer_of(state) -> str
def should_learn(status: str) -> bool   # exhaustive; unknown status raises
```

**`state` stays a plain `dict`.** This is a deliberate reversal of two runner-up designs, forced by measurement — see §6. `turn.py` owns three keys by convention plus a CI gate, not by wrapping the object.

### What ceases to exist

| Concept | Where it lives today | Fate |
|---|---|---|
| "The answer is the tail of the steps log" | `routers/agent.py:1325`, `:1477`; `run_finalizer.py:101`; `explain.py:86` | **deleted** — both rules, ~40 LOC. The *question* "which rule is right?" ceases to exist. |
| Direct `state["steps"].append` | 46 sites / 6 files | **deleted** — replaced by one writer + a gate asserting zero appends outside `turn.py` |
| `_autonomous_run_impl` | `agent_loop.py:687` (29 params, 92 LOC) | **deleted** — and with it both 20+-positional boundaries |
| The two pass-through coordinator frames + inert retry loop | `coordinator.py:101`, `:211`, `:303-326` | **deleted** (~120 LOC). **The module survives** — see §6. |
| Directive applied selectively | `agent_loop.py:955` | **deleted** — moves *inside* `build_standard_prompt`; 1-of-3 coverage becomes unrepresentable |
| One of two `convo_block` builders | `reasoning_handler.py:133-161` | **deleted** (~28 LOC) |
| The global `main._history` deque + `conversation_history.json` | `main.py:773-825` | **deleted** — but only after its 4 reader modules are repointed (CP-11) |
| `services/llm/llm_decision.py` | 283 LOC, zero importers, name-collides with the live `services/agent/llm_decision.py` | **deleted** |
| Three vestigial CI caps + `--strict`-is-opt-in | `check_architecture.py:95`, `:106`, `:29` | **deleted**, replaced by a downward-only ratchet that can fail |
| Two zero-byte orphan DBs | `agent/layla.db`, `agent/layla/layla.db` | **deleted** |

**Net LOC: roughly −300 to −500.** Honest accounting: ~410 added (`turn.py` ~150, liveness registry ~80, gate rewrite ~120, characterization tests ~60) against ~700-900 deleted. This is far below the −600 to −2,700 the four designs advertised, because their headline numbers were inflated by three deletions the judges falsified: `coordinator.py` (470), the `layla.memory.db` facade (311), and the `agent_loop` facade (~120). None of those are deleted here.

### Reused wholesale: the wiring-test template the repo already proved

`tunnel_audit.purge_old` was an orphan; it is now called from `layla/scheduler/jobs.py:267` and pinned by `tests/test_tunnel_audit.py:164`, which asserts **the call happened with the right argument** — not that the function works. Every checkpoint below pins its seam with that shape. It is the only test form that catches "built well and never plugged in."

---

## 4. The checkpoint sequence

Twelve checkpoints. Each lands on a working product with 4047 tests green. Checkpoints 1-4 are pure safety infrastructure and make everything after them verifiable.

Throughout, **"suite green"** means: `C:/Work/Programming/Layla/.venv-test/Scripts/python.exe -m pytest agent/tests -q` with a clean stub config and `CI=true` (per `local-ci-reproduction` — the ~7 local failures are operator-config artifacts, not regressions).

---

### CP-1 — Make the detector see the whole codebase

**Goal:** the repo's architecture gate and architecture test stop silently skipping the 1629-line main chat router.

**Why it is better:** today `check_architecture.py` reports `shared_state importers <= 15 (current: 15) PASS` while the true count is 16, because it drops `routers/agent.py` on a BOM `SyntaxError` and that file is one of the importers. After CP-1 the same gate reports 16 and FAILS. **One character of fix flips a green gate red** — which is the proof it now measures what it names. Nothing downstream in this plan is verifiable until this lands.

**Changes:**
- `agent/scripts/check_architecture.py:139` — `ast.parse(py_file.read_text(...).lstrip("\ufeff"))`. **Write the escape `"\ufeff"`, never a literal BOM character** — a literal renders as an empty-looking string and the fix silently does nothing.
- `agent/scripts/check_architecture.py:140-141` — replace `except (SyntaxError, UnicodeDecodeError): continue` with a loud failure that records the file and marks the run failed. A parse error must never be silent.
- `agent/tests/test_architecture_boundaries.py:40-45` — same BOM strip in `_parse_file`; `return None` becomes a test failure naming the file.

**Proof it did not break the product:** zero product code touched. Two assertions:
```bash
# BEFORE: prints 15 and PASSes. AFTER: prints 16 and FAILs.
python agent/scripts/check_architecture.py 2>&1 | grep shared_state
# must report zero unparseable files:
python agent/scripts/check_architecture.py --strict 2>&1 | grep -i "parse\|skip"
```
Plus suite green. The gate *failing* is the success condition here; CP-2 baselines it.

**Effort:** ~1 hour. **If it goes wrong:** nothing — no runtime code is touched. Worst case the gate is noisy and CP-2 is needed sooner.

**Depends on:** nothing. **This is the entry point.**

---

### CP-2 — Baseline the gates to reality, then wire them to CI

**Goal:** replace three caps that constrain nothing with a downward-only ratchet, and actually run it in CI.

**Why it is better:** a gate that has never failed is evidentially identical to no gate, and this one has never *run* — `grep -rn "check_architecture" .github/` returns nothing. After CP-2 every structural number in this plan is a CI-enforced ceiling that may fall and may never rise, which is what converts "when is the architecture done" from a judgement call into arithmetic (§5).

**Changes:**
- Delete the vestigial caps at `check_architecture.py:95` (`agent_loop <= 1800`, actual 1001) and `:106` (`services/ flat <= 205`, actual 1).
- New `.planning/arch-baseline.json` with today's measured counts: `steps_append_sites: 46`, `commit_turn_sites: 19`, `commit_turn_arg_shapes: 6`, `status_write_sites: 22`, `prompt_build_sites: 3`, `terminal_emission_sites: 21`, `shared_state_importers: 16`, `routers_to_storage_edges: 55`, `scc_size: 165`, `orphan_modules: 67`. Gate fails if any rises.
- `check_architecture.py:29` — `STRICT` becomes the default.
- Fix `agent/scripts/check_memory_coherence.py:114` — resolve to `agent/layla/memory/knowledge_graph.graphml` (owner path, `memory_graph.py:13`), not `AGENT_DIR/.layla/`.
- Wire to `.github/workflows/ci.yml`.

**Ordering discipline, mandatory:** run the gate locally and record every failure *before* wiring it. Do not discover the failure count in CI. Baseline to measured reality so it is green on day one — a ratchet whose baseline is wrong is the fifth decorative gate.

**Proof:** the gate must self-assert. It fails loudly if any baseline number does not match at authoring time (`assert measured == baseline, "PROBE BROKEN: ..."`), and fails if any file fails to parse. Then: `python agent/scripts/check_architecture.py` exits 0 locally, CI run exits 0, `check_memory_coherence.py` reports a real node/edge count (31 nodes / 45 edges) rather than `SKIP`.

**Effort:** ~1 day. **If it goes wrong:** CI blocks on a miscalibrated number. Mitigation: baseline is generated from a probe run, not typed by hand.

**Depends on:** CP-1.

---

### CP-3 — A runtime liveness registry

**Goal:** make "a correct component that nobody drives" detectable at all.

**Why it is better:** this is the only checkpoint that addresses the actual historical failures. Four of the five confirmed instances — the agent executing zero tools for 16 days, zero conversation summaries ever, clustering moving no work, the SM-2 that produced 0 rows — are runtime no-ops with valid callers and live import edges. No static gate in any proposal catches them; I verified `_sm2` (`layla/tools/impl/memory.py:122`) is called at `:172` inside an imported module, so an orphan gate reports it healthy while `learnings.py:574` records 0 rows. After CP-3, a load-bearing effect that stops firing is visible in a counter instead of being discovered 16 days later.

**Changes:**
- New `agent/services/observability/liveness.py` (~80 LOC): a small registry of named load-bearing effects with monotonic counters, persisted alongside existing telemetry. Generalises the proven `tunnel_audit` template from a unit test to a runtime signal.
- Instrument existing call sites only — no behaviour change: `tool_dispatch` (a tool actually executed), `turn_commit` (a turn was committed), `run_finalizer` (an outcome was evaluated), conversation compaction, vector-index write.
- New `agent/scripts/check_liveness.py`: reports any registered effect with zero fires in the retention window. **Report-only.** It is a dashboard, not a gate — this box is a single-user machine and a zero count may legitimately mean "not used this week."

**Proof:** suite green. Then a single live turn through the running app (`.venv`, per `layla-no-local-run`) must increment `turn_committed` and, for a tool-requiring goal, `tool_executed`. That measurement is itself the acceptance criterion: if `tool_executed` stays 0 on a goal that requires a tool, CP-3 has found a live instance of the signature defect on its first run.

**Effort:** ~1 day. **If it goes wrong:** counters are wrong and mislead. Mitigation: counters are additive and read-only to the turn; a broken counter cannot break a turn.

**Depends on:** CP-2 (so the new script is registered in the gate inventory).

---

### CP-4 — Characterization test: pin what the user sees today

**Goal:** capture current answer-extraction behaviour before changing it.

**Why it is better:** `steps[-1]` appears in **9 non-test files and 0 test files**. The suite has HTTP-level coverage of the router but asserts nothing about the answer text, so "the suite stayed green" is worthless evidence precisely where CP-5 operates. This checkpoint creates the evidence.

**Changes:**
- New `agent/tests/test_answer_extraction_characterization.py`: pins the answer string for (a) a reason-last turn and (b) a tool-last turn, through both the router path (Rule A) and the finalizer path (Rule B). It asserts *today's* behaviour, including the divergence — the two paths returning different strings for a tool-last turn is recorded as fact, not fixed.

**Proof:** the new tests pass against unmodified product code. If they do not, the model of the two rules in §1 is wrong and CP-5 must be re-planned before any code changes.

**Effort:** ~half a day. **If it goes wrong:** nothing — test-only.

**Depends on:** nothing (parallelisable with CP-1..CP-3).

---

### CP-5 — The answer becomes a value

**Goal:** one field holds the final user-visible text; both extraction rules die.

**Why it is better:** for the first time an expression in this codebase *denotes the answer*, so "assert the answer is correct" becomes a writable test. It also ends a live divergence: on multi-step engineering turns the router currently shows the user a raw tool result while the finalizer evaluates and learns from a different string.

**Changes, in three commits so each is revertible:**
1. Add `set_answer` / `answer_of` to new `agent/services/agent/turn.py`. `answer_of` falls back to Rule B then Rule A. Repoint the 4 readers. **Zero behaviour change** — the characterization test must still pass unmodified.
2. Call `set_answer` at the three producers: `stream_handler.py` at stream close, `reasoning_handler.py`, and the `agent_loop.py:955` parse_failed fallback. Note `commit_turn`'s `text` is a required positional carrying the *already-cleaned, floored* reply (`turn_commit.py:311-312`), so `set_answer` must be called post-polish, not on the raw model output.
3. Delete both fallbacks in `answer_of`, and delete Rule A (`routers/agent.py:1325`, `:1477`) and Rule B (`run_finalizer.py:101`, `explain.py:86`).

**Proof:** CP-4's characterization test, updated *once* at commit 3 with the divergence deliberately removed — the diff to that test file is the human-readable record of the behaviour change, and is the thing to review. Suite green at each of the three commits. Ratchet: `prompt_build_sites` unchanged, and a new gate asserts zero `steps[-1]` reads outside diagnostics.

**Effort:** ~1 day. **If it goes wrong:** users see the wrong text on multi-step turns. This is the highest user-visible risk in the plan, which is why CP-4 exists and why commit 1 is behaviour-neutral.

**Depends on:** CP-4 (hard — do not start without it), CP-2.

---

### CP-6 — One step writer

**Goal:** `state["steps"]` gets exactly one writer.

**Why it is better:** 46 sites across 6 files can currently change what gets recorded, with two access conventions and no validation. After CP-6 there is one function, one convention, and a typo'd action raises instead of appending a step nobody reads.

**Changes:**
1. Add `record_step` to `turn.py`; mechanically convert the 30 sites in `tool_dispatch.py`.
2. Convert the remaining 16 (`decision_loop.py` 7, `tool_guards.py` 5, `tool_dispatch_base.py` 3, `reasoning_handler.py` 1, `agent_loop.py` 1). Leave `routers/settings.py`'s 3 alone — different object.
3. Enable `KNOWN_ACTIONS` validation **in log-only mode**. It raises only after one full release cycle with a clean log.

**Proof:** AST gate — zero `["steps"].append` on turn state outside `turn.py`; ratchet `steps_append_sites: 46 → 1`. Suite green. CP-3's `tool_executed` counter must still increment on a live tool turn — this is the wiring assertion that the conversion did not sever recording.

**Effort:** ~1 day (mechanical but concentrated in the two hottest files). **If it goes wrong:** steps stop being recorded, which degrades the answer and learning. CP-3's counter catches it in one turn instead of 16 days.

**Depends on:** CP-3 (needs the counter as the safety net), CP-5 (the answer must already be a field, or converting the log destabilises extraction).

---

### CP-7 — `state` becomes required at the turn boundary

**Goal:** the degraded `commit_turn` shape stops being expressible.

**Why it is better:** the shortest call is currently the one that skips learning, so every new exit path defaults to the broken shape and the compiler, type checker and 4047 tests are all satisfied. After CP-7 "I forgot" becomes "I declared." **Scoped honestly:** the genuine defect surface is 1-2 sites, not 13 — this buys a small correctness win and a large *shape* win, and is worth exactly its one-line cost.

**Changes:**
- `turn_commit.py:307` — `state: dict | None = None` becomes required `state: dict`.
- The fast paths that genuinely have no run pass an explicit `trivial_state()` — **a plain-dict factory in `turn.py`, not a new type** (`{"steps": [], "status": "finished", "trivial": True}`). Explicitly not a class: see §6.
- Collapse the 6 argument shapes to one at all 19 sites.

**Proof:** AST gate asserts every `commit_turn` call passes `state`; ratchet `commit_turn_arg_shapes: 6 → 1`. `tests/test_turn_persistence_and_title_refresh.py` and `test_streamed_turns_are_evaluated.py` green. CP-3's `turn_committed` counter unchanged across a live turn.

**Effort:** ~half a day. **If it goes wrong:** a turn exit raises `TypeError` at runtime. Caught by the 15 test files that reference `routers.agent`, including `test_golden_flow_http.py` and `test_e2e_agent.py` which drive it over HTTP.

**Depends on:** CP-2.

---

### CP-8 — Exhaustive status

**Goal:** an unenumerated terminal status fails loudly instead of quietly disabling a downstream stage.

**Why it is better:** this is the exact mechanism that severed learning — `status="stream_pending"` meeting a gate testing `== "finished"` at `run_finalizer.py:32`, with `turn_commit.py:348-362` as the written confession. An equality check can only fail silently; a predicate with an exhaustive body cannot.

**Changes:**
- `TERMINAL_STATUSES` frozenset + `should_learn(status)` in `turn.py`, with an explicit unknown-status branch that raises.
- Replace the `== "finished"` gates (`run_finalizer.py:32`, `turn_commit.py:363`/`:391`) and the `_NO_LEARN_STATUSES` denylist (`turn_commit.py:88`) with `should_learn(...)`.
- **Log-only for one full release**, then raise. Non-negotiable: `TERMINAL_STATUSES` was derived from measurement, not requirements, so an incomplete set turns a quiet degradation into a dead user turn on a box with no staging tier. `turn_commit.py:56-70` already warns against deriving this list from reachability — honour that reasoning.
- Leave the 22 `status` *write* sites alone. They keep writing strings.

**Proof:** suite green. A test enumerating all 22 write sites by AST and asserting each written literal is in `TERMINAL_STATUSES` — this is the enumeration form, not the pin-the-site-I-edited form. CP-3's `outcome_evaluated` counter must be non-zero after a live streamed turn; that is the direct regression test for the original defect.

**Effort:** ~half a day. **If it goes wrong:** learning silently stops again (log-only mode) or turns die (raise mode). The log-only release is the entire mitigation.

**Depends on:** CP-7.

---

### CP-9 — One prompt builder

**Goal:** the anti-fabrication directive cannot land on a subset of prompt sites.

**Why it is better:** the guard currently reaches 1 of 3 callers while a green test reports it present — worse than no test, because it converts an open question into a false answer. After CP-9 selective application has no spelling.

**Changes:**
- Move `NO_FILE_ACCESS_DIRECTIVE` (`orchestrator.py:721`) **inside** `build_standard_prompt` (`orchestrator.py:637`); delete the caller-side concat at `agent_loop.py:955`. The two streaming callers (`stream_handler.py:259`, `reasoning_handler.py:215`) get it for free.
- Merge the two character-identical `convo_block` builders (`stream_handler.py:164-190`, `reasoning_handler.py:133-161`) into one function.
- **Rewrite** `tests/test_no_fabrication_when_tools_fail.py:57-60`: instead of AST-asserting the `agent_loop` site, *enumerate every `build_standard_prompt` call site and assert the count of directive-applying sites is 1 — the function itself.*

**Proof:** the rewritten enumeration test. Ratchet `prompt_build_sites: 3 → 1` (one builder, 3 callers). Suite green. A live streamed turn with a failing tool must not fabricate file contents — this is a manual one-turn check, and it is the point of the whole checkpoint.

**Effort:** ~half a day. **If it goes wrong:** prompts change shape and answer quality shifts. Caught by golden eval (`test_golden_flow_http.py`).

**Depends on:** CP-5 (the answer must be a field before prompt assembly moves).

---

### CP-10 — Collapse the pass-through frames

**Goal:** 8 call frames become 5; both 20+-positional boundaries cease to exist.

**Why it is better:** 20+ positional arguments across a boundary is a silent-corruption machine — reorder one parameter and every argument after it shifts to the wrong slot with no error, swapping `allow_write` for `allow_run`. The types are mostly `str`/`bool`, so the 4047 tests cannot catch it. And the cure is already written and unplugged: `AgentRunRequest` (`agent_loop.py:479`) is a complete dataclass mirroring every parameter, and I verified it has **zero non-test callers** — referenced only by a name list at `tests/test_architecture_boundaries.py:404-405`. This is the signature defect sitting on top of its own cure.

**Changes:**
- `autonomous_run(**kwargs)` builds an `AgentRunRequest` and calls one impl taking `(req)`.
- Delete `_autonomous_run_impl` (`agent_loop.py:687`, 29 params, 92 LOC). `_autonomous_run_impl_core` takes `req`.
- Inline the two coordinator pass-through frames — `dispatch_autonomous_run` (`coordinator.py:101`) and `run` (`:211`) — whose own `if not coordinator_enabled: return run_fn(goal, **kwargs)` at `:116` proves them optional to the turn.
- Delete the inert retry loop at `coordinator.py:303-326`. `coordinator_dispatch_max_attempts` is clamped to 1, and `commit_turn`'s docstring states it is not self-deduplicating, so at n>1 it would replay every non-idempotent side effect.
- **`services/planning/coordinator.py` is NOT deleted.** See §6.

**Proof:** suite green, especially `test_architecture_boundaries.py` (which names both symbols). Ratchet: a new `max_positional_args` cap set to 8. Add the wiring test that was missing: assert `autonomous_run` constructs an `AgentRunRequest` — the `tunnel_audit` shape, which is what would have caught this dataclass being unplugged for however long it has been.

**Effort:** ~1 day. **If it goes wrong:** an argument lands in the wrong slot. Mitigated by making the surviving signature keyword-only, which converts this entire failure class into a `TypeError`.

**Depends on:** CP-2. Independent of CP-5..CP-9.

---

### CP-11 — One conversation cache

**Goal:** four copies of a turn become three; the global no-conversation-id store dies.

**Why it is better:** `main._history` is a *global* `maxlen=20` deque with no conversation id, predating conversation IDs entirely, flushed to `conversation_history.json`. It is a whole redundant store.

**Critical ordering — this is a migration, not a deletion.** I probed the readers: `get_history()` has **4 live reader modules** — `routers/session.py:18,47,71,157`, `routers/research.py:30,76,407`, `services/infrastructure/route_helpers.py:547,552` (lazy). `research.py` feeds it to the model as `conversation_history=`. Deleting the deque without repointing does not raise — **research turns silently lose all conversation context and answer confidently from nothing**, which is the signature defect reintroduced on the one path where a fabrication and a correct answer are the same shape on the wire.

**Changes, strictly in order:**
1. Repoint all 4 reader modules to the per-conversation cache. Ship. Verify.
2. Only then delete `main._history` + `conversation_history.json` + the flush at `main.py:773-825`.
3. Move `append_conv_history` inside `commit_turn`, closing the 16-vs-7 durable/cache exit gap.

**Proof:** between step 1 and step 2, an AST gate asserting **zero non-test callers of `get_history`** — the deletion is blocked until that gate is green. A live research turn must still carry prior context (manual, one turn). Suite green.

**Effort:** ~1 day. **If it goes wrong:** silent context loss on research turns. The zero-callers gate is what makes this safe; without it, do not attempt this checkpoint. **This is the checkpoint to drop if budget runs short** — it is the lowest architectural value in the plan and the only one with a silent-degradation failure mode.

**Depends on:** CP-7.

---

### CP-12 — Delete the corpses, close the gates, freeze

**Goal:** remove what nothing calls, turn the ratchet into hard caps, declare the architecture done.

**Why it is better:** two modules named `llm_decision` currently exist, one dead — anyone navigating by filename has a 50% chance of editing the corpse, and the edit will pass tests because nothing covers it. After CP-12 the ratchet has no scheduled decrements left and §5's finish line is arithmetic.

**Changes:**
- Delete `services/llm/llm_decision.py` (283 LOC, zero product and zero test importers, name-collides with the live `services/agent/llm_decision.py`).
- Delete the zero-byte `agent/layla.db` and `agent/layla/layla.db`, and fix the resolver ambiguity at `layla/memory/db_connection.py:20-21` that created them. Remove the stray `agent/services/.governance` and `.screenshots` directories.
- Give `learnings` an owner: route the 13 writer modules through `layla/memory/learnings.py`, coupling the row-write and the vector-index write in one call. This is the missing coupling behind 35 rows vs 7 vectors.
- Add the `ENTRY_POINTS` allowlist so a module with zero importers in the *combined* (function-body-inclusive) graph that is not declared fails CI. **Scoped honestly:** this catches the import-orphan class only — roughly 1 of the 5 historical instances. CP-3 is what covers the rest.
- Ratchet numbers become hard caps. Write the ADR.

**Proof:** full gate suite green with `--strict` in CI. `learnings` row count and vector count converge (a probe asserting `abs(rows - vectors) == 0` after a write). Ratchet shows every target number at its floor.

**Effort:** ~2 days (the `learnings` rerouting is most of it). **If it goes wrong:** a learning write path breaks. Covered by existing memory tests; the vector/row equality probe is the new assertion.

**Depends on:** CP-2, CP-3.

---

### Sequence summary

| CP | Name | Effort | Depends on | Net LOC |
|---|---|---|---|---|
| 1 | Detector sees whole codebase | 1h | — | ~0 |
| 2 | Baseline + wire gates to CI | 1d | 1 | +120 |
| 3 | Runtime liveness registry | 1d | 2 | +80 |
| 4 | Answer characterization test | 0.5d | — | +60 |
| 5 | Answer becomes a value | 1d | 4, 2 | −40 |
| 6 | One step writer | 1d | 3, 5 | +40 |
| 7 | `state` required at boundary | 0.5d | 2 | −20 |
| 8 | Exhaustive status | 0.5d | 7 | −10 |
| 9 | One prompt builder | 0.5d | 5 | −40 |
| 10 | Collapse pass-through frames | 1d | 2 | −220 |
| 11 | One conversation cache | 1d | 7 | −90 |
| 12 | Corpses, gates, freeze | 2d | 2, 3 | −380 |

**Total ≈ 10 working days.** CP-1 through CP-8 carry the great majority of the defect-prevention value. **If you stop early, stop after CP-9** — CP-10 is a safe deletion but buys legibility rather than correctness, CP-11 is droppable, and CP-12's `learnings` work could migrate to `ENGINEERING_HEALTH.md`.

---

## 5. When this is DONE

The architecture is finished when all of the following hold simultaneously in CI with `--strict`. These are counts, not judgements.

**One owner per load-bearing fact:**
1. `state["steps"]` append sites outside `turn.py`: **0** (from 46)
2. Expressions that extract the final answer other than `answer_of`: **0** (from 2 rules at 4 sites)
3. `commit_turn` argument shapes: **1** (from 6); calls omitting `state`: **0** (from 13)
4. Terminal-status gates that are equality checks: **0**; unenumerated statuses: **0**
5. Prompt-construction sites that apply the safety directive selectively: **0** (from 2 of 3)
6. Modules writing `learnings` other than `layla/memory/learnings.py`: **0** (from 13)

**The detector works:**
7. Files skipped by any architecture gate due to parse failure: **0** (from 1 — and that one was the main chat router)
8. `check_architecture.py` runs in `.github/workflows/ci.yml` with `--strict` and exits 0
9. Every gate in `.planning/arch-baseline.json` self-asserts its baseline and fails on mismatch
10. `check_memory_coherence.py` reports real node/edge counts, never `SKIP`
11. Every registered load-bearing effect in `liveness.py` has fired at least once on a real turn

**Deletion is real:**
12. Call frames from HTTP handler to tool execution: **≤5** (from 8)
13. Maximum positional arguments across any internal boundary: **≤8** (from 22)
14. Modules with zero importers in the combined graph and not on `ENTRY_POINTS`: **0**
15. Net LOC change across CP-1..CP-12 is **negative**

**Then stop.** When those 15 conditions hold, no further architectural work is warranted on this codebase. Everything remaining is a feature (`ROADMAP.md`) or a bug (`ENGINEERING_HEALTH.md`). Specifically: the 165-module SCC, the 78 upward layer inversions, the 55 router→storage layer-skips, the `layla.memory.db` facade and the `agent_loop.py` pass-through surface will all still exist. They are ratcheted so they cannot grow. **That is the intended end state, not an unfinished one** — see §6.

**The honest limit of this plan, stated plainly so the operator can judge it before approving:** this attacks *writability* — how easy it is to create the signature defect — and only ratchets *readability* — how hard it is to see one. If the operator's real complaint turns out to be "I cannot navigate this codebase," this plan underdelivers, and the honest answer would be a larger, non-incremental project that the current brief forbids.

---

## 6. Explicitly NOT doing

Each of these was proposed by at least one design and rejected on measured grounds. **Do not re-propose without new evidence that overturns the cited measurement.**

**1. Wrapping `agent()` in a `with turn_scope(...)` context manager.**
*Rejected on measurement.* An AST probe of the enclosing-function chain of all 16 `commit_turn` sites in `routers/agent.py`: only 3 (`:677`, `:770`, `:1537`) are in `agent()`'s body. Nine are in `agen`, three in `agen_fast`, one in `agen_ma` — all nested async generators handed to FastAPI via `return StreamingResponse(...)` at `:961`/`:1027`/`:1424`. `__exit__` would fire before a single token exists, committing an empty turn on the default streaming path. This reimplements the `stream_pending` defect inside the mechanism designed to abolish it. A correct version needs `async with` inside each of ~4 generators, which restores the multi-site convention the idea existed to remove.

**2. Replacing the run-state dict with a `RunState`/`TurnState` class.**
*Rejected on measurement.* A `MutableMapping` subclass is not a `dict`, and `isinstance(state, dict)` gates real behaviour at 5 non-test sites: `turn_commit.py:136` (route_decision silently becomes `None` on every turn), `llm_decision.py:62`, `:68`, `:329`, `multi_agent.py:58` (every subtask reply returns `""`). None of them raise; all take a fallback path that still "works." Also live: `{**state}` spreads at `turn_commit.py:379`, `initiative_inline.py:62`, `initiative_engine.py:36`, and 12 non-test `state.setdefault` sites. Subclassing `dict` instead dodges the `isinstance` problem but defeats the purpose — `**unpacking`, `dict.get` and `dict.update` do not dispatch through an overridden `__setitem__` in CPython, so the unknown-key check would not fire on the paths it exists to police. **The 94-key dict stays a plain dict.** `turn.py` owns three keys by convention plus a CI gate. Typing the other 91 is the overengineering trap the brief names, and it cannot land incrementally.

**3. Deleting `services/planning/coordinator.py`.**
*Rejected on measurement.* Two designs proposed deleting the whole 470-LOC module; one named a path that does not exist (`services/agent/coordinator.py`). It has **9 public functions**, of which only `run` and `dispatch_autonomous_run` are the optional turn wrapper. `run_with_plan_graph` is imported by `planner.py:904`; `run` by `routers/agent_tasks.py:74` and `routers/agent.py:40`; and `run_parallel_subtasks`, `merge_outputs`, `resume_from_task`, `spawn_subtasks` are the multi-agent pillar, which standing project findings classify as **WIRE, not delete**. CP-10 deletes ~120 LOC of pass-through frames and the inert retry loop. The module survives.

**4. Deleting `main._history` as a simple deletion.**
*Rejected on measurement, downgraded to a migration.* `get_history()` has 4 live reader modules (`session.py`, `research.py`, `route_helpers.py`), and `research.py` feeds it to the model. Deleting it does not raise; it silently strips conversation context from research turns. Retained as CP-11 with a mandatory repoint-first ordering and a zero-callers gate, and flagged as the first checkpoint to drop.

**5. Dissolving the `layla.memory.db` re-export facade (311 LOC, fan-in 76).**
*Rejected on cost/benefit.* Repointing 76 importers to `db_connection`/`migrations`/`vector_store` is a week of mechanical import churn with zero behaviour change, inside a 165-module SCC that makes the blast radius unbounded. The panel independently called this the item most likely to end the migration with a red suite and a stalled maintainer. The facade is ratcheted, not dissolved.

**6. Dissolving the `agent_loop.py` facade (~61 pass-throughs, 51 importers).**
*Rejected on value-per-line.* Zero behaviour change for 51 repointed importers. Every design that proposed it also named it the first checkpoint to drop. Note for the record that C-9 sized this at 23 pass-throughs and the measured surface is ~61 — any future plan scoped to C-9's number will under-deliver by more than half.

**7. Fixing the 78 upward layer inversions and the 165-module SCC.**
*Rejected as a rewrite.* These 78 edges are *why* the imports are lazy — a module-scope version would be a genuine circular import and crash at startup. Fixing them means either surfacing 78 import errors or building a dependency-inversion scaffold, and a scaffold is an added abstraction, which fails constraint 1. All four designs declined this. Ratcheted so it cannot grow.

**8. Fixing the 55 router→storage layer-skips.**
*Rejected as a rewrite in disguise*, same reasoning. Ratcheted at 55.

**9. An import-graph orphan gate as the answer to "built well and never plugged in."**
*Rejected as the primary mechanism; retained as a secondary one.* I verified the decisive counter-example: `_sm2` at `layla/tools/impl/memory.py:122` is **called** at `:172`, inside a module imported by `registry_body.py` — an import-graph gate reports it healthy, while `learnings.py:574` records that its columns hold 0 rows. Four of the five confirmed historical instances are runtime no-ops with valid callers and live import edges. The gate ships in CP-12 for the one class it does catch; **CP-3's runtime liveness registry is the mechanism that covers the rest**, and CP-12 must not be sold as covering them.

**10. "13 of 19 `commit_turn` exits silently learn nothing."**
*Retired as a claim.* `turn_commit.py:14-16` documents `state` as optional by design — fast paths never call `agent_loop`, so no run state exists. The genuine surface is 1-2 sites. CP-7 still ships because the one-line signature change is nearly free and fixes the *shape*, but no future plan should cite the 13/19 figure.

**11. Enabling `KNOWN_ACTIONS` / `TERMINAL_STATUSES` assertions in raise mode on first ship.**
*Rejected.* Both sets are derived from measurement, not requirements. An incomplete set converts a quiet degradation into a dead user turn, on a single-maintainer box with no staging tier. Log-only for one full release is mandatory in CP-6 and CP-8, not advisory.
