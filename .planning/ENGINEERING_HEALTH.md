<!-- GENERATED 2026-07-22 by an adversarial multi-agent audit (33 + 30 agents).
     Every unit was independently CHALLENGED before inclusion; challenged-out units are
     retained with their refutation because the refutation is usually the useful part. -->

# Engineering Health Plan — Layla

**Scope:** one maintainer, 4-core/16 GB Windows, CPU-only, local-first, no frontend build step.
**Method:** every claim below was AST- or measurement-verified and then adversarially challenged. Where a challenge overturned the original recommendation, the corrected version is what appears here.

---

## ⚠️ GATE 0 — Do this before anything else (15 min)

**There are 430 uncommitted lines in a git worktree that exist in no commit on any branch.** Every cleanup item below is downstream of rescuing them. I re-verified this at plan time:

```
git -C .claude/worktrees/mystifying-kapitsa-58fd21 status --porcelain
# 22 modified (21 agent/ui/components/*.js + agent/ui/sw.js)
# ?? agent/tests/test_overlay_escape.py
# ?? agent/ui/tools/test_overlay_escape.mjs
# diff --stat: 22 files, 428 insertions(+), 1 deletion(-)
```

This is the BL-386 fix (document-level capture listener so Escape actually dismisses overlays when focus is on `<body>`) **plus 248 lines of new tests**. The two test files are *untracked* — no reflog, no stash, no dangling object. `git worktree remove --force` or `rm -rf` destroys them permanently.

```bash
cd C:/Work/Programming/Layla/.claude/worktrees/mystifying-kapitsa-58fd21
git checkout -b rescue/bl-386-overlay-escape
git add -A && git commit -m "rescue(BL-386): overlay Escape capture listener + tests (was uncommitted in worktree)"
```

Review and merge on its own merits afterward. **Do not touch `.claude/worktrees/` until this commit exists.**

Also note: `git worktree list` shows a *third* worktree under the Claude scratchpad (`.../ef81daf0-.../BASE_HEAD`, detached at 73d7e69). That one is tooling scaffolding and is safe to ignore, but do not blanket-prune worktrees by pattern.

---

## 1. QUICK WINS

Ranked by (visible benefit × certainty) ÷ effort. Each ≤ ~2h. Do them in this order.

### QW-1 — `write_file`, `shell`, `fetch_url` still discard the model's args
**Effort: ~2h · Risk: MEDIUM (destructive tools) · Benefit: closes a live fabrication bug**

The P13-E1 fix ("dispatch discards the model's args") was applied to `read_file`, `list_dir`, `grep_code`, `apply_patch`, `understand_file` via `_arg_or_goal_path` — and **not** to the three most consequential handlers. All three still re-parse the goal *string*:

| Handler | How it gets its args today |
|---|---|
| `_handle_write_file` | `al._extract_file_and_content` — requires the literal substring `"with content"` **and** a token containing `:`, `\` or `/` (`intent_classifier.py:65`) |
| `_handle_shell` | `al._extract_shell_argv` — a quoted substring of the goal (`intent_classifier.py:81`) |
| `_handle_fetch_url` | `next((w for w in goal.split() if w.startswith('http')), '')` (`tool_dispatch.py:583`) |

A correct model emission `{"tool":"write_file","args":{"path":"README.md","content":"..."}}` returns `(None, None)` → `status="parse_failed"` → `break` → the prose fallback fabricates the file's contents. **That is the exact symptom class the P13-E commits declared closed.**

Fix: route all three through the same args-first helper as `_arg_or_goal_path` (`tool_dispatch.py:205`).

- **Test to land with it:** a bare-filename `write_file` emits a *tool* step, not a *reason* step.
- **What breaks if wrong:** `write_file` and `shell` are the destructive pair. Honouring model-supplied paths reaches paths the goal-text heuristic could never name. Land behind the existing sandbox + approval gates unchanged, and port `_handle_shell` **last** — its `status="finished"` + `break` after `al._write_pending` is what stops an unapproved command from proceeding, and it must stay fail-closed.

### QW-2 — Strip the UTF-8 BOM, and make the parse-failure gates loud
**Effort: 20 min · Risk: NONE · Benefit: unblocks every AST tool, including the repo's own CI gates**

Verified at plan time: `agent/routers/agent.py` and `agent/tests/test_phase7_knowledge_loading.py` both begin `b'\xef\xbb\xbf'`. Python's importer strips it, so the app runs — but `ast.parse(read_text(encoding="utf-8"))` raises `SyntaxError: invalid non-printable character U+FEFF`, and the repo's own gates swallow it:

- `agent/scripts/check_architecture.py:139` → `except (SyntaxError, UnicodeDecodeError): continue`
- `agent/scripts/check_imports.py:82` → `except SyntaxError: return []`

So the `shared_state`-importer ceiling check and the import-policy check **have never examined the 1629-line main chat router**. This also broke my first import graph and produced three false orphans.

```bash
python - <<'EOF'
import pathlib
for p in ["agent/routers/agent.py","agent/tests/test_phase7_knowledge_loading.py"]:
    f = pathlib.Path(p); b = f.read_bytes()
    assert b[:3] == b"\xef\xbb\xbf", f"PROBE BROKEN: no BOM on {p}"
    f.write_bytes(b[3:]); print("stripped", p)
EOF
```

**Part (b) matters more than part (a):** make both checkers count parse failures and exit non-zero if the count is > 0. This is "verify the probe before the result" encoded into CI. Budget 20 extra minutes to triage whatever it surfaces.

### QW-3 — The application has no log file
**Effort: 20 min · Risk: NONE (additive) · Benefit: precondition for every other observability item**

`grep -rn FileHandler --include=*.py agent/ --exclude-dir=tests` → **zero matches**. `agent/main.py:123` and `:132` both do `_logging.getLogger().handlers = [h]` with a single `StreamHandler`, which *replaces* all handlers, so no other module can add a sink. Every diagnostic this system has ever produced went to the stderr of a console window that closed.

Add a `logging.handlers.RotatingFileHandler` alongside the existing StreamHandler. Stdlib, no dependency, no network.

- Set `maxBytes` and `backupCount` explicitly (5 MB × 3). The repo already proves it can rotate — `db_backup.py` keeps 7.
- Resolve the log path through `LAYLA_DATA_DIR` the way `_default_db_path()` does, or a packaged install writes into its install dir.
- **Promoting log levels (QW-6, ST-4) is pointless until this lands.** Do it first.

### QW-4 — Repair and wire the API-contract gate that has been drifting 45% past its own baseline
**Effort: 30 min · Risk: LOW · Benefit: stops the uncovered-route count growing; fixes a gate that is itself an instance of the signature defect**

`agent/scripts/check_api_contracts.py` works correctly, exits 1 today, and **is wired into no CI workflow** (`rg check_api_contracts .github/` → 0 hits, while `check_copyleft.py` appears at `ci.yml:48` and `:112`). Its own constant says the number "must only go DOWN":

```
agent/scripts/check_api_contracts.py:46   MAX_UNCOVERED_ROUTES = 125
actual today: 181 uncovered routes — 56 above limit
```

It has been breached since ~2026-05-13 and nobody noticed, because `run_all_checks.py` registers it as severity `WARN` and `run_all_checks` is itself in no workflow.

1. Set `MAX_UNCOVERED_ROUTES = 181` (today's honest number) **in the same commit** as the CI step.
2. Flip its severity in `run_all_checks.py` from WARN to FAIL.
3. Add one step to `.github/workflows/ci.yml`.

**Do NOT set it to 125 first** — a permanently-red gate gets deselected, which the parity test's own docstring warns is worse than an honest limit. Ratchet down afterward.

### QW-5 — Pin ruff in CI
**Effort: 5 min · Risk: NONE · Benefit: reproducible lint**

`.github/workflows/ci.yml:208` is literally `pip install ruff` — unbounded. Every run resolves whatever ruff published most recently; a minor release can silently *stop* enforcing something. Local resolves 0.15.20. `requirements.txt`'s `ruff>=0.4` is commented out and constrains nothing.

```yaml
run: pip install "ruff==0.15.20"   # pin to the version that is green today
```

### QW-6 — Make the sqlite-vec index stop silently self-disabling forever
**Effort: 20 min · Risk: NONE · Benefit: turns invisible permanent degradation into a logged event**

`agent/layla/memory/fallback_store.py`: `_vec_ok = True` appears **once** (line 74). It is set `False` at `:67, :76, :86, :151, :159, :307` — every one inside a bare `except Exception:` with **no log call at all** — and nothing ever sets it back. One transient error (locked DB, malformed vector, dim mismatch during an embedder swap) permanently downgrades semantic recall to brute force for the whole process lifetime.

Search correctness survives (line 303 falls through), which is exactly why nobody would ever notice: memory just gets quietly worse. The comment `# never let the index break a write` is the right *intent*, implemented as silence instead of as logged, recoverable degradation.

Add a warn-once log at each transition. Gate any retry on reopen or a time interval, not on every call.

### QW-7 — Delete the three tracked accidents and close the gitignore hole
**Effort: 20 min · Risk: NONE · Reclaims: ~20 KB tracked (and one real class of future accident)**

All three re-verified as tracked at plan time. See §5 for exact commands. The `.bak-p13` one carries a required addendum: `.gitignore:33` names `agent/runtime_config.json` *exactly*, with no trailing `*` — the same mistake the file's own post-mortem at `:197-200` records having already made once with `.graphml`. Deleting the file without widening the rule re-arms the trap for `.bak-p14`.

### QW-8 — Delete the two dead CDN fallbacks in `agent/ui/index.html`
**Effort: 20 min · Risk: NONE · Benefit: local-first integrity**

`index.html:14-16` load marked/highlight/purify as vendored local files via plain synchronous `<script>`, so `window.marked` and `window.hljs` are always defined before the IIFE at `:25` runs its `needMarked`/`needHl` checks. The cdnjs fallbacks at `:56-58` are unreachable in the normal path — and in the abnormal path they silently fetch from `cdnjs.cloudflare.com`.

Stronger than the original finding: `agent/main.py:688-700` sets a default CSP of `script-src 'self'`, so those fetches are **browser-blocked** in the default configuration anyway. They are zero-value dead code that can only fire when `security_headers_enabled: false` or under the dev preview server — precisely the cases where a silent internet fetch is most surprising.

`_loadScript`/`_loadCss` have exactly 5 references repo-wide, all in this file, so both helpers go with them (~34 lines total).

**Required addendum:** bump `agent/ui/sw.js:37` from `const CACHE = "layla-ui-v34"` to `"layla-ui-v35"`, or existing PWA installs keep serving the cached old `index.html` and the change appears not to have taken.

### QW-9 — Delete three genuinely dead modules
**Effort: ~1h total · Risk: NONE at runtime · Benefit: removes three documented lies**

| Target | Why | Same-commit companions |
|---|---|---|
| `agent/services/llm/llm_decision.py` (282 LOC) | Zero importers, prod or test. The live path is `services/agent/llm_decision.py` (658 LOC), which implements GBNF → outlines → instructor → plain — a strict **superset**. Delete on redundancy. | `docs/design/03-llm-and-reasoning.md:416-435` presents the dead module's strategy table as the real architecture; it omits GBNF entirely, so this is a rewrite, not a pointer swap. Also kill the stale comment at `services/agent/llm_decision.py:202-203`. |
| `agent/layla/memory/vector_qdrant.py` (151 LOC) + its test | Zero importers by AST across 946 non-build files; `qdrant_client` not installed; `vector_store.py:310-315,543-548` hardcodes fallback-or-chromadb and never reads `vector_backend`. | Remove `vector_backend` from both defaults dicts **and** add it to `config_migrator.py:30-33 _DEPRECATED` (otherwise it survives forever in the operator's live `agent/runtime_config.json:403`). Fix `agent/tests/integration/test_full_pipeline.py:39,59`, which asserts the key exists. Fix `docs/design/02-memory-and-knowledge.md:38,373`. |
| `AgentRunRequest` + `autonomous_run_from_request` (`agent_loop.py:479,519`) | 29-field dataclass + wrapper, zero callsites in prod **and** tests. Survives only because a test asserts the *names* exist. | Remove the two strings from `_REQUIRED_AGENT_LOOP_ATTRS` (`test_architecture_boundaries.py:404-405`); fix `docs/design/01-core-agent-loop.md:19,425` and `ENGINEERING_BLUEPRINT.md:1004`. |

**Note:** the vector_qdrant commit does *not* fully de-qdrant the repo — `agent/capabilities/registry.py:49-53` registers a second impl at `capabilities.impl.qdrant_vector`, a directory that does not exist, and that registry is live via `routers/workspace.py:75`. Out of scope; don't claim otherwise in the commit message.

### QW-10 — Delete the unreachable compression/optimization tiers
**Effort: ~1h · Risk: LOW · Removes: 217 LOC of tier-selection machinery guarding code that cannot execute**

`prompt_compressor.py` advertises a 4-tier ladder (selective-context → LLMLingua → LongLLMLingua → heuristic); `prompt_optimizer.py` offers DSPy and guidance. **All four packages are absent from the venv AND absent from `requirements.txt` and `pyproject.toml` entirely** — there is no documented install path, so `get_available_tier()` can only ever return heuristic.

They are also wrong in principle here: LLMLingua and selective-context work by running a *second* small LM to score token salience. On a box already spending ~70 s per warm turn, that costs more than the context it saves.

Delete the unreachable branches (157 LOC in the compressor, 60 in the optimizer), keep the heuristic TF-IDF + redundancy-penalty compressor (decent, dependency-free), and make `get_info()` honest about having one tier. If you want to hedge for a future GPU box: delete the DSPy/guidance paths outright and merely *document* the LLMLingua tier as unsupported.

---

## 2. CONSOLIDATIONS

Ranked by pain removed per hour.

### C-1 — Funnel all 45 `state["steps"].append` sites through one `record_step()`
**Effort: ~4h · Risk: LOW (mechanical, wide) · Highest simplification-per-risk change available**

45 append sites across 6 files (`tool_dispatch.py` 29, `decision_loop.py` 7, `tool_guards.py` 5, `tool_dispatch_base.py` 2, `agent_loop.py` 1, `reasoning_handler.py` 1). Status is written independently at 20 sites in 5 files — **the two facts about a turn are maintained by disjoint code**, which is the mechanical reason a run can report `status="finished"` with `steps=[]`.

One function that appends the step *and* updates `last_tool_used`/`tool_calls`/`blocked_calls` together makes that state unreachable, and gives you one place to instrument. This is exactly what smolagents does with `ActionStep`.

- Day one: pure move, zero behaviour change, one commit.
- **What breaks if wrong:** some appends carry extra keys (`deliberated`, `aspect`). `record_step` must accept `**extra` or the step shape changes silently and the UI step renderer drops fields.

### C-2 — Collapse the three divergent SM-2 implementations
**Effort: ~3h · Risk: LOW for the shared function · Benefit: three answers become one**

`layla/tools/impl/memory.py:122`, `services/infrastructure/german_mode.py:417`, `services/infrastructure/language_tutor.py:218`. Differential run on identical input (ease 2.5, interval 10, reps 5):

| | q=3 | q=0 (failure) |
|---|---|---|
| `memory.py` | (2.36, 25, 6) | ease **2.3** |
| `german_mode.py` | (2.36, 24, 6) | ease **2.5** |
| canonical SM-2 | — | ease **1.7** |

None is correct on failure. Worse: the *newest* copy (`memory.py`) computes the next interval from the **pre-update** ease — the exact defect `german_mode.py:429-431` documents as already found and fixed. Three copies means a fix in one silently persists in the others; that has demonstrably already happened.

- Extract one shared pure function with the canonical formula. That alone removes the divergence at near-zero risk.
- **Do not unify the storage in the same pass.** The three call sites persist to different schemas (`learnings.review_ease/review_interval_days/review_reps`, `german_mode.ease_factor/interval`, `lang_card.ease/interval_days` as REAL). Storage unification is a migration.
- **What breaks:** correcting the failure branch lengthens intervals for previously-failed items — acceptable, but user-visible scheduling changes.

### C-3 — Collapse the two rerankers; the dead one is the good one
**Effort: ~4h · Risk: MEDIUM (retrieval feeds the system prompt) · Removes: ~190 LOC of literal duplication**

Two implementations, 391 LOC, duplicating each other function-for-function — both define `_bm25_rerank`, `_tokenize`, `_get_cross_encoder`.

- `layla/memory/vector_store_rerank.py` (200 LOC) — **live**, wired via `search_memories_full(use_rerank=True)`, called from `services/prompts/system_head_builder.py:273`. Torch-dependent (CrossEncoder).
- `services/retrieval/reranker.py` (191 LOC) — **zero production callers**, yet it is the better fit: FlashRank ONNX backend documented as "the potato-path default, BL-103, no torch", module-level model caching, config-driven via `reranker_backend`.

So the CPU-only box runs the torch reranker while the torch-free one sits unused. Make `services/retrieval/reranker.py` the single owner; have `vector_store_rerank` delegate (keeping `mmr_rerank`, which is genuinely unique); delete the duplicated BM25/tokenize/cross-encoder code.

- **What breaks:** retrieval quality shifts, and retrieval feeds the prompt — a regression shows up as *worse memory recall*, not an exception. FlashRank downloads a small ONNX model on first use; verify the `_backend_order` BM25 fallback with the model absent before flipping the default. Gate behind the existing `reranker_backend` config and compare on real queries.

### C-4 — Collapse `autonomous_run` → `_autonomous_run_impl` → `_autonomous_run_impl_core`
**Effort: ~2h · Risk: LOW-MEDIUM · Removes: 2 frames and 2 hand-synced 31-argument lists**

`agent_loop.py:559` (31 params) → `:687` (31 params — body is *nothing but* `set_model_override` / `set_reasoning_effort` / `set_tool_permissions` + try/finally) → `:821` (the real body). The middle layer is a hand-rolled decorator. Replace with one `with _run_scope(...)` contextmanager wrapping the core.

- **What breaks:** the finally-blocks clear thread-local tool permissions and model overrides. A botched contextmanager leaks `allow_run` into the next turn. Keep try/finally semantics byte-identical and assert clear-on-exception in a test.

### C-5 — Extract one `_terminate()` helper in `routers/agent.py`
**Effort: ~3h · Risk: MEDIUM (hottest path, no test coverage) · Benefit: removes 5 near-identical blocks**

This is the **corrected** version of "split the 1281-line `agent()`". The original framing was wrong on the facts: only 3 of the 18 top-level returns commit; the other 13 `commit_turn` calls live inside the three generators and would move *with* them, removing zero call sites. Exactly-once is already enforced by `_committed = {"done": False}` (`agent.py:825, 1074`).

What is real: `agent.py:1132-1177` contains five near-identical 5-line commit+append+append+yield blocks. Extract `_terminate(reply, status, **extra) -> str` that commits, appends history, and returns the SSE frame.

- **Do NOT route persistence through "one exit that takes (reply, status, result)".** `commit_turn` for client-abort lives in `finally` (`agent.py:936-952`) because uvicorn throws `GeneratorExit` (a BaseException) into the generator on tab-close. A generator being torn down has no return value. On a box where a warm turn is ~70 s, that abort path is the *most frequent* persistence event — and it is the bug BL-245 was written to fix.
- **What breaks:** per-status done-frames differ in shape (`questions[]`, `artifacts[]`, `blocked`, `deliberation`, `ux_states`, `reasoning_mode`). `rg` found **no test file importing `routers.agent`**, so there is no safety net. Diff emitted SSE frames before/after, manually.

### C-6 — Merge `coordinator.dispatch_autonomous_run` into `coordinator.run`
**Effort: ~2h · Risk: MEDIUM · Removes: one layer and redundant classification work**

`dispatch_autonomous_run` has exactly **1** prod callsite: `coordinator.py:317`, inside `coordinator.run`. It defensively *re-builds* the coordinator trace (`coordinator.py:123-133`, when `complexity_score is None`) because it cannot know whether its single caller already built one — and `coordinator.py:245` already set `kw['coordinator_trace'] = trace` two frames up. On this CPU box that re-classification is not free.

- **What breaks:** `dispatch_` also owns persistent-task create/update and the session execution snapshot. Those must land *inside* the retry loop exactly as now or a retried turn double-creates task rows.

### C-7 — Extract one `_sse()` helper (and explicitly do NOT adopt sse-starlette)
**Effort: ~2h · Risk: LOW-MEDIUM (touches the streaming hot path) · Collapses: 54 duplicated f-strings**

54 hand-formatted `data: ` frame sites across 5 files (`routers/agent.py` 30, `openai_compat.py` 8, `inference_router.py` 6, `settings.py` 6, `research.py` 4).

**The hand-rolled SSE is correct.** I expected to find a broken implementation and did not: correct framing (`data:` + blank line), `media_type="text/event-stream"`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, a keepalive pulse at `agent.py:877` reading `ui_stream_keepalive_seconds`, and — critically — every payload goes through `json.dumps`, so newlines are escaped and the classic multi-line frame-corruption bug **cannot occur**. One local helper, no dependency. One isolated commit, zero behaviour change.

### C-8 — Adopt `retry_util` in the genuine I/O sites only — or delete it
**Effort: ~3h · Risk: LOW per-site · Confidence: MEDIUM**

`services/infrastructure/retry_util.py` was written explicitly so that "ad-hoc `for attempt in range(...)` loops can standardise on it" (its own docstring), and acquired exactly **one** production caller (`routers/settings.py`). Eight hand-rolled attempt loops exist. The signature defect, in the very module meant to fix duplication.

**But do not blanket-merge.** Several of those eight are not retries: `services/agent/llm_decision.py:633` and `services/planning/planner.py:530` are **LLM reprompt loops** — they retry because the model returned unparseable JSON, and typically need to *mutate the prompt* between attempts. Forcing those through a `fn()`-with-backoff contract is a worse design and adds pointless sleep latency to an already slow turn. Others (`node_sync`, `background_job_worker`) are polling drains, not retries.

Expect 2-5 genuine I/O candidates. **If the honest count is 2-3, delete `retry_util` and drop tenacity instead** — that is the more honest consolidation. Convert one site, confirm, then proceed. Never batch-convert.

- **What breaks:** `retry_call` defaults to `exceptions=(Exception,)`, broader than most of these loops. It would start retrying genuine logic errors while adding backoff delay to a fast failure. Preserve each site's existing exception filter.

### C-9 — Redirect the 23 `agent_loop` pass-throughs (NOT a ring-breaking refactor)
**Effort: ~3h · Risk: LOW if scoped correctly, HIGH if done as originally proposed**

The original recommendation — "move shared leaf helpers into a dependency-free module both sides import" — **is already implemented**. `agent/services/agent/step_formatting.py` exports `VALID_TOOLS`, `format_steps`, `summarize_steps_deterministic` and imports `TOOLS` directly; `_extract_*` live in `intent_classifier.py`. AST over 10 leaf modules shows **zero** imports of `agent_loop`. Nothing is left to move.

What *is* real: of the 37 distinct `_al.<attr>` reads from services, **24 are pure pass-throughs to sibling `services.agent.*` modules** — services importing `agent_loop` to reach their own siblings. Redirect those 23 (one collides), then delete the dead `_imports()` cache at `tool_dispatch_base.py:73`. No code movement, no new module, no import-order risk.

- **What breaks if you overreach:** `_al.X` is late-bound module attribute lookup, and that is the interception point the test suite depends on — **85 `monkeypatch.setattr(agent_loop, ...)` sites across 129 test files**, including 12 on `_llm_decision`. "Let `decision_loop` call `llm_decision` directly" silently severs all 12: tests stop controlling the code path while still asserting on outputs. The proposed green-gate (`test_startup_imports`, `test_architecture_boundaries`) is AST-only and would not catch it. **Keep the seam on the three DI wrappers and the agent_loop-owned attrs.** The 23 pass-throughs have zero overlap with the monkeypatch set — that is the safe scope, and the only scope.

### C-10 — Reconcile `[core]` vs `[cpu]` extras
**Effort: ~3h · Risk: MEDIUM (changes what install commands resolve to) · Confidence: MEDIUM**

`pyproject.toml:31-63` `[core]` (21 entries) vs `:69-97` `[cpu]` (22 entries) are hand-maintained near-duplicates — right down to a verbatim-duplicated 3-line prometheus_client comment block at both `:60-62` and `:94-96`. `[cpu]` is documented as "`[core]` but WITHOUT chromadb", yet it silently also adds `model2vec` and `sqlite-vec`. That undocumented divergence is exactly what makes the fast embedder path unreachable (see O-1).

Declare the shared set once via a `[base]` extra that both reference as `layla[base]` — the same self-reference mechanism `[all]` already uses and that `test_dependency_parity.py::_extra_to_dists` already expands to a fixed point.

- **What breaks:** `install/fresh_install.ps1` depends on the `[cpu]` profile (`pyproject.toml:68`, REQ-72). Installer and docs must move in lockstep or the laptop install path breaks.

### C-11 — Config defaults: pin the schema/runtime seam (do NOT invert authority)
**Effort: ~1 week, sequenced · Risk: HIGH (startup path) · Confidence: MEDIUM**

Three sources: `runtime_safety.load_config`'s literal `defaults = {...}` (427 keys), `config_schema.EDITABLE_SCHEMA` (98 entries, 89 with a `default`), `runtime_config.example.json` (529 keys). Overlap 79, **6 disagreements** including `max_tool_calls` (20 vs 5) and `tool_call_timeout_seconds` (180 vs 60).

**Reject the obvious fix.** "Make config_schema the single source of default values" misreads what `EDITABLE_SCHEMA` is: it is primarily a **write allowlist** enforced at the API boundary — `route_helpers.py:280` refuses any POST /settings key not in it, and it drives the settings UI via `get_schema_for_api`. Moving the 427 runtime keys under it would make `autonomous_allow_network`, `shell_allowlist_extra`, `remote_require_auth_always`, `sandbox_python_memory_limit_mb` and every API-key field **remotely writable**, and render ~350 internal knobs in the settings UI. Authority is also already the other way: the clamp loop at `runtime_safety.py:1035-1038` runs only `if _k in data`, so a fresh install with no `runtime_config.json` **never consults a schema default**.

Correct sequence:
1. **Extend the existing guard first.** `tests/test_example_config_matches_shipped_defaults.py` is genuinely well-built but compares exactly one pair of sources. Make it iterate the **union** of all three key sets. It will fail immediately on 20 findings — that is the point, and the work is "triage 20 config decisions", not "write a test."
2. Resolve the 6 schema-vs-runtime disagreements by explicit decision.
3. Strip the duplicate `default` from the 79 overlapping schema entries, or pin them equal with a new schema-vs-runtime test.
4. **Never touch the allowlist boundary.**

**Real bug surfaced en route:** that test justifies a divergence as "the schema default stays False so the feature is opt-in for anyone assembling a config from scratch" — but the runtime dict ships `deterministic_tool_routes_enabled = True`, so a from-scratch install gets True. The recorded rationale is defeated by the merge order.

---

## 3. REPLACE WITH OSS

**Headline finding: Layla reinvents far less than expected.** APScheduler, zeroconf, tenacity, rank-bm25, networkx and langchain-text-splitters are genuinely adopted. The SSE code and the SQLite migration runner are correct, not naive. The real defect is not reinvention — **it is that the good library choices are DECLARED BUT NOT INSTALLED**, so the runtime silently falls onto its own worst path.

### ADOPT

| # | Library | Licence | Why | Effort / Risk |
|---|---|---|---|---|
| **O-1** | **model2vec** + `potion-base-8M` | MIT (MinishLab, active 2026) | The adapter is **already written and complete** (`vector_store.py:112 _Model2VecAdapter`) and `_get_embedder()` already tries it *first*. `find_spec('model2vec')` is `None`, so that branch has **never executed**. Pure NumPy, no torch, ~30k sentences/s CPU, ~92% MiniLM quality. Declared in `[cpu]`, which `[all]` never references — so no documented install command can obtain it. | days / **MEDIUM** |
| **O-2** | **Pre-fetch the embedder in the installer** | — | Not a library choice; a missing last mile on the headline feature. `rg -ni "potion\|model2vec\|snapshot_download\|huggingface\|prefetch"` over `install/*`, `install.ps1`, `install.sh`, `installer/*`, `scripts/setup_layla.py` → **ZERO matches**. The installer ships the GGUF and nothing else. `vector_store.py:88-95` documents the breach verbatim (BL-374). **On a genuinely offline first run, semantic memory degrades to keyword-only — on the one product whose thesis is working offline.** ~30 MB into the payload, point `HF_HOME` at it. | hours / LOW |
| **O-3** | **ddgs** | MIT (deedy5) | Upstream renamed the project **and** the PyPI distribution from `duckduckgo-search`; the old line is frozen and emits a migration RuntimeWarning. `ddgs` 9.14.4 is API-compatible with the existing call site (`DDGS` still defines `__enter__`/`__exit__`; `text(query, **kwargs)` unchanged). Windows-safe (primp ships prebuilt win_amd64 wheels). | hours / LOW |
| **O-4** | **FlashRank** | Apache-2.0 | ONNX cross-encoder, **no torch**. Not a new dependency to evaluate — the integration is already written inside the dead `services/retrieval/reranker.py:51,67`. It needs a caller. See C-3. | hours / MEDIUM |
| **O-5** | **python-zeroconf** | LGPL-2.1-or-later | mDNS discovery is already correctly written against the real library (470 lines, proper `ServiceInfo`/`ServiceBrowser`, graceful degradation); `mdns_discovery.py:260` literally logs "Run: pip install zeroconf". Licence explicitly permitted by the repo's own gate — `scripts/check_copyleft.py:18` allows LGPL/MPL and blocks only AGPL/GPL/SSPL (which is why Kokoro was rejected). Cheapest possible progress on the remote pillar. | minutes / **see below** |
| **O-6** | **py-fsrs** | MIT (open-spaced-repetition) | FSRS-6, the scheduler Anki ships. Materially better retention-per-review than SM-2. Pure Python, offline, vendorable. **Phase 2 only** — it needs difficulty/stability/retrievability columns, so it is a behaviour change, not a drop-in. Do C-2 first. | days / MEDIUM |
| **O-7** | **llama-cpp-python's own tokenizer** | MIT — already a dependency | `services/llm/token_count.py:17` hardcodes `tiktoken.get_encoding('cl100k_base')` to budget prompts for **Qwen2.5**. I parsed the GGUF header directly (no model load): `tokenizer.ggml.model=gpt2`, `pre=qwen2`, vocab **151,936** vs cl100k's 100,277. Measured divergence: English 0%, Python 0%, Spanish +10%, Russian +41%, Japanese +72%, Arabic +94%, **Chinese +100%** — against a shipped 11-language i18n. It over-counts, so it over-truncates: a Chinese user silently loses roughly half the context she could have kept. `Llama.tokenize()` is exact and free at inference time. Keep tiktoken as the no-model-loaded fallback. | hours / LOW |

**O-1 / O-5 preconditions — read before acting:**

- **O-1 does NOT remove torch, and the migration is the real work.** `pyproject.toml [cpu]` also declares `sentence-transformers` and `torchao`, both of which hard-require torch — `pip install .[cpu]` pulls all 493 MB regardless. Torch also has live consumers that would go dark (`prompt_compressor.py:93`, `reranker.py:91`, `vector_store_rerank.py:33`, BLIP captioning at `analysis.py:513-668`). More importantly: **live data is 590 knowledge vectors + 7 learnings, all at dim 384. potion-base-8M is 256-dim.** `fallback_store.py:333` filters brute-force search to `int(v.shape[0]) == target_dim` — every one of the 590 existing vectors would be **silently skipped at query time**. No error, no log, no health signal. And nothing re-embeds them: the only reindex trigger (`refresh_knowledge_if_changed`) fingerprints the knowledge *directory contents*, not the embedder model or dim.
  **Minimum honest scope:** (1) install model2vec; (2) write a one-shot re-embed, or make the fingerprint include `_current_model_name` + `_embedder_dim`; (3) **make a dim mismatch LOUD — worth doing on its own merits regardless**; (4) only then, separately, consider dropping sentence-transformers/torchao from `[cpu]` and accept losing cross-encoder rerank, BLIP captioning and llmlingua compression on that profile.
- **O-5 changes your privacy posture.** Installing zeroconf makes the box start *broadcasting a service on the LAN*. Config-gate it **off by default, opt-in** — not enabled by installation. And verify discovery actually moves work before declaring the pillar wired; this repo's signature defect is precisely a correct component with nothing consuming it.
- **O-3 has a gate trap.** `requires` in the tool registry holds a *single* module string with no any-of semantics (`domains/web.py:23`). The proposed try-ddgs/except-duckduckgo_search dual import means a box with only `ddgs` gets a working tool **withheld from the model** — a silent false-negative. Go single-name, or teach the gate a tuple. Migrate all of: `impl/web.py:203,216`, `domains/web.py:23`, `pyproject.toml:133`, `requirements.txt:88`, **`dependency_recovery.py:33 _PIP_ALLOWLIST`** (a stale entry silently breaks auto-recovery), `test_capability_sources_honesty.py:244`, plus two doc files.

### REJECTED — checked, and not worth it

| Candidate | Verdict |
|---|---|
| **LangGraph** | **No.** The loop here is already ReAct, depth-capped at 5, with essentially one branch (tool vs reason). LangGraph's value — branching, durable checkpointing, concurrent reducers — buys nothing at that scale and costs a graph compiler, channel/reducer semantics and a checkpointer for one person to own. Published guidance says a direct call is simpler below ~3 steps with no branching, and its default state reducers are a documented token-leak footgun in long-running loops. Cloud/LangSmith gravity also conflicts with local-first. |
| **smolagents** (as a dependency) | **No** — but **copy its shape.** Apache-2.0, genuinely small, but swapping the loop is a rewrite. Adopt the *patterns* dependency-free: one typed step record appended at exactly one place (C-1), and only the model ends the turn. Zero new supply chain. |
| **sse-starlette** | **No.** BSD-3 and maintained, but its main draws are auto-ping and disconnect handling — the ping already exists at `agent.py:877`, and the framing is already correct. It would add a dependency to replace code that works. |
| **Alembic / yoyo-migrations** | **No.** Both healthy (MIT / Apache-2.0), both built for team + multi-environment coordination. A PRAGMA-style versioned runner over idempotent DDL is the *right* design for a single-file local SQLite app with one maintainer. See ST-2 for what the real defect in that file actually is. |
| **FAISS / LanceDB / Chroma / Qdrant** | **No.** Measured NumPy brute-force cosine @384-dim on the live corpus: 590 vectors → **0.78 ms/query**; 5,900 → 1.51 ms; 59,000 → 7.24 ms. ANN indexing is unwarranted below ~100K vectors, and `sqlite-vec` is *itself* brute-force — it buys SIMD, not an algorithm, and NumPy already goes through BLAS. Each of these adds a native build or a server this box cannot absorb. **The hand-rolled version is correct.** |
| **RestrictedPython / wasmtime / containers** | **No.** `skill_sandbox.py` does not claim to be a security boundary — it says so at `:162-163` — and delivers what it does claim: per-pack venv, filtered env, path confinement, wall-clock timeout, output truncation. That is an honest, correctly-scoped mitigation. RestrictedPython is not a real boundary either; WASM/containers break arbitrary-Python skill packs and add a heavy runtime. The actual control is the install-time consent gate; the sandbox is correctly defence-in-depth. |
| **HF `tokenizers`** | **No.** Would add a second source of truth for tokenization when llama-cpp-python already exposes the exact one. See O-7. |
| **rank_bm25** | **No.** Apache-2.0 and fine, but the local BM25 is short and dependency-free. Adopt FlashRank only; keep local BM25. |
| **LLMLingua / selective-context / DSPy / guidance** | **No** — delete the branches. See QW-10. |
| **Removing torchao** | **No — keep it.** I expected torchao to be dragging the tensor stack in and measured otherwise: **torchao is 5.8 MB**; torch's 493 MB arrives via sentence-transformers, which `[core]` and `[cpu]` both declare independently. Removing torchao saves ~6 MB and gives up genuine int8 dynamic quantization of the embedder on CPU. It is try/except-guarded and degrades cleanly. **The lever on the 493 MB is model2vec, not torchao.** Recorded so nobody "optimizes" the wrong package. |

---

## 4. STRENGTHEN

Ranked by blast radius — what can lose or corrupt operator data.

### ST-1 — Embedder dim mismatch silently deletes your knowledge base from every query
**Blast radius: TOTAL knowledge/RAG retrieval, silently · Effort: ~1h for the loud version · Risk: LOW**

`fallback_store.py:134` rebuilds the sqlite-vec index at whatever dim it is handed; `:333` filters brute-force search to `int(v.shape[0]) == target_dim`. Any embedder change makes **all 590 existing knowledge vectors invisible at query time with no error, no log, no health signal** — retrieval just returns empty. This is this repo's signature failure mode in its purest form, and `sqlite_vec` is missing from the venv, so the store is running the brute-force path where the filter lives.

Do this **independently of** whether you ever adopt model2vec: log loudly + mark degraded on a dim mismatch, and make `_knowledge_dir_fingerprint` (`vector_store.py:1318`) include `_current_model_name` and `_embedder_dim` so a model swap forces a reindex.

### ST-2 — `migrate()` swallows failures and proceeds on a half-built schema
**Blast radius: the live user DB, at every startup · Effort: ~2h · Risk: MEDIUM (see caveat)**

`agent/layla/memory/migrations.py:69-70`: `except Exception as e: logger.warning("DB migrate failed: %s", e)` — a failed migration is swallowed and the app continues. Twenty-five lines above, the *downgrade* guard correctly calls `mark_degraded('database', ...)`. AST also finds 6 pass-only exception handlers inside `_migrate_impl`.

Fix the failure path to `mark_degraded` (or re-raise). This is hours, and it addresses what actually bites the operator.

**Explicitly do NOT split `_migrate_impl` (898 lines).** AST shows it is long but **flat**: 46 top-level statements, 36 of them Try wrappers around ALTERs — straight-line append-only DDL with near-zero cyclomatic complexity. Splitting into ~37 per-table functions replaces one ordered block with 37 call sites in a *mandatory* order; the reading burden moves rather than drops, and the ALTER-after-CREATE ordering plus `IF NOT EXISTS` idempotence are load-bearing and easy to break. Git history shows an extraction pass already happened (`e30ca67`); what remains is the DDL core deliberately kept together. **Wrong allocation of a maintainer's highest-risk hours.**

- **Caveat before tightening:** check that the 6 pass-only handlers guard genuinely-optional DDL (already-applied ALTERs), or a benign duplicate-column error becomes a boot failure.

### ST-3 — Derived-memory writes are on unjoined daemon threads
**Blast radius: every turn's learnings, entities, skills, title, capability practice · Effort: ~3h · Risk: LOW**

`turn_commit.py` fires title synthesis (`:271`), skill acquisition (`:428`), learning extraction (`:469`) and capability practice (`:491`) onto `daemon=True` threads that **nothing joins**. Daemon threads are killed instantly at interpreter exit. Close the window shortly after a turn — the common case on a laptop — and that turn's derived memory is gone with no error, no queue entry, no record. All four are wrapped in `logger.debug` handlers, i.e. invisible at the default level.

The core message write is synchronous, so the *conversation* is safe. What is lost is everything that makes the conversation useful later.

- Register the threads and join with a short timeout (2-3 s) in the existing shutdown hook (`agent/main.py:671` already calls `close_thread_connection()`).
- **Keep `daemon=True`** so a hung LLM call can still never block exit permanently.
- **Do NOT convert to synchronous** — that puts LLM calls on the response path and regresses latency badly on this box.

### ST-4 — 632 broad-except handlers report only at DEBUG, under a default-INFO root
**Blast radius: this is the mechanism by which every other defect stayed invisible · Effort: hours, file by file · Risk: LOW (log noise)**

A handler that reports at DEBUG under an INFO root logger is functionally `except: pass`. Full classification of non-test broad-excepts by first log call: **debug 632**, warning 291, exception 42, error 37, critical 3, info 2. And 1620 of 3479 handlers (47%) swallow with no log at all (617 `pass`, 626 `return`, 347 log-less, 30 `continue`).

**Do not bulk-promote all 632** — that drowns the console and trains the operator to ignore warnings. Triage by blast radius; promote only handlers on paths where a failure changes **what the model sees** or **what gets persisted**:

| File | debug-only handlers | What a silent failure costs |
|---|---|---|
| `services/prompts/system_head_builder.py` | 49 | drops a **section of the system prompt** (`:172` load_learnings, `:289` mem0 recall, `:580` knowledge_refresh, `:588` project_domains_knowledge) |
| `services/memory/memory_router.py` | 21 | retrieval |
| `layla/memory/vector_store.py` | 19 | retrieval |
| `install/run_setup.py` | 19 | install |
| `services/agent/llm_decision.py` | 16 | decision |
| `services/agent/turn_commit.py` | 14 | persistence |

~138 handlers across six files covering prompt assembly, retrieval and turn persistence. WARNING is the right level for "a prompt section was dropped." **This is mechanically how the capability manifest never reached the model, and how the agent executed zero tools for 16 days with nobody noticing.** Go one file at a time, watch one real session's output between files, and use rate-limited/warn-once logging on per-turn paths.

### ST-5 — Enable ruff `BLE001` + `S110` + `S112` as a ratchet
**Effort: ~2h · Risk: LOW · Benefit: stops the 1620-handler population growing**

`pyproject.toml:214` is `select = ["E", "F", "W", "I"]` — no BLE, no S. The rules that detect exactly this problem are simply unselected, and ruff is already installed and already in CI.

Enable the rules, generate a baseline via `per-file-ignores` (the pattern already exists at `pyproject.toml:222`), and let CI block only **new** offenders. That converts an open-ended cleanup into a ratchet one person can hold.

- **Do NOT attempt a repo-wide fix** — many swallows are deliberate best-effort paths (`db_connection.py:79-81`'s `try: existing.close() except: pass` is correct).
- **Honest cost:** the ignore block will be ~100 files and will look alarming. It also masks whole files — new blind-excepts *in a baselined file* are not caught. Accept that; the alternative is no ratchet.

### ST-6 — Wire the answer-feedback write path
**Blast radius: a prompt section that is structurally guaranteed to be empty forever · Effort: ~3h · Risk: NONE (additive)**

`services/prompts/system_head_builder.py:1331` calls `feedback_hint_for_prompt()` and injects it into `memory_sections["answer_feedback"]` **on every turn**. The read path is fully wired into the prompt. `record_feedback` — the write path — has no producer anywhere in the repo except the orphaned `routers/feedback.py` and its tests. So that prompt section can never contain anything.

Add a thumbs up/down control that POSTs `/feedback`. No build step, endpoint and service already exist and are tested (`test_answer_feedback.py`), and the prompt-side consumer already handles empty via try/except.

**Correction to a related finding:** of the five "fully orphaned" routers, only `learning_verification.py` (19 lines) is genuinely inert. `automation.py` has a **live producer** — `services/memory/knowledge_watcher.py:277` calls `dispatch_event("file_modified", ...)` on every ingest, so the rules engine runs today; only rule *authoring* lacks a surface. `vision.py` duplicates a capability already exposed via the tool registry (`analyze_image`, covered by `test_vision.py`). `plugins.py` is operator-ruled WANTED. **Do not "decide the fate" of automation.py — it works.**

### ST-7 — Fix the 7 personality flags that ship False to fresh installs
**Blast radius: every new install gets a quieter product than the code intends · Effort: hours (triage, not code) · Risk: LOW**

The config guard compares one seam and structurally cannot reach keys present in `example.json` but absent from `EDITABLE_SCHEMA`. Sixteen disagreements live there, including seven `enable_*` flags — `cognitive_lens`, `personality_expression`, `behavioral_rhythm`, `ui_reflection`, `operational_guidance`, `lens_knowledge`, `lens_refresh` — **True in code, False in the example that seeds a fresh install** (`install/setup_existing_model.py:14`, `scripts/setup_layla.py:146`). Also `write_file_max_bytes` 5,000,000 vs 500,000 — a **10× difference in a safety limit**.

Your live `agent/runtime_config.json` has all 7 True, so this box is unaffected. **Exposure is fresh installs only** — i.e. every user who is not you.

This needs a product decision, not a fix: if the example deliberately ships a quiet persona for new users, that is legitimate and should be **written down** rather than "corrected." Either way, extend the guard (C-11 step 1) so it can never drift again.

### ST-8 — Trace what creates the two zero-byte stray databases
**Blast radius: unknown, and that is the problem · Effort: ~1h · Risk: NONE (investigation)**

Confirmed on disk: `agent/layla.db` (0 B) and `agent/layla/layla.db` (0 B). `db_connection.py:21` resolves four `.parent` hops to the **repo-root** `layla.db`, so no code path should ever create either. Their existence is a symptom of a wrong path resolution somewhere — the exact miswiring class this codebase produces.

Related and confirmed: `german_mode.db` (24 KB) and `language_tutor.db` (24 KB) sit at the repo root because `german_mode.py:83-89` and `language_tutor.py:54-57` resolve their paths at runtime with a CWD-relative fallback. **These two hold the operator's actual vocabulary and SRS decks.** That is a path-resolution bug to fix, not clutter to sweep — and they must be shielded from any `*.db` glob.

**Do not delete the evidence before understanding it.**

### ST-9 — Decide what crash-resume means
**Blast radius: a resumed run re-spends budget and can re-run guarded tools · Effort: hours (the decision is the work) · Risk: LOW**

`services/agent/run_setup.py:418-420` restores an 8-name hardcoded tuple against a **106-key live surface**. One of the eight (`retries`) has zero prod consumers by any variable name. Everything else resets — including `blocked_calls`, the backstop counter, and `packed_context`, `policy_caps`, `no_op_steps`, `tool_loop_history`, `used_learning_ids`.

The fix is a list; the decision (exact vs best-effort resume) is yours. Probably: steps + all counters.

- **What breaks:** restoring more counters makes resumed runs terminate *sooner* — correct, but it changes any test that resumes and expects a full budget.

### ST-10 — Declare the 60 undeclared ExecutionState keys; delete the 3 dead ones
**Effort: ~3h · Risk: LOW**

`ExecutionState.create_initial` declares 46 keys; the true live surface is **106** (80 touched by loop modules). Sixty are runtime-grown and declared nowhere, which is why resume and serialization are guesswork. `retries`, `memory_hits`, `last_reasoning_mode` have zero prod consumers; `current_step`'s three consumers are on a different dict in `missions_db` and `execution_state.py:87` already admits it is "reserved."

- **What breaks:** declaring keys with defaults changes `state.get(k)` from None-by-absence to a declared default. Grep for `in state` before landing — a handful of `if 'k' in state` checks could flip.

### ST-11 — `rl_preferences` has no time column, so no retention policy can ever be written
**Effort: ~2h (a migration) · Risk: LOW · Urgency: LOW, and I will not dress it up**

30 live tables have no retention policy, but **most are correctly excluded** — `learnings`, `entities`, `user_identity`, `capabilities`, `goals`, `project_context` are the operator's actual memory and auto-deleting them would be a bug, not a fix. The live DB is **4.08 MB total** after months of use. This is a "decide the policy before it matters" item.

The actionable part: `rl_preferences` (156 rows) has **no `created_at`/`ts` at all**, so age-based retention is not even expressible. Same for `capability_dependencies` and `style_profile`. Adding the column is cheap but is a schema change on the live DB.

- **The real risk here is over-correcting.** Any new policy must be argued per-table. Retention is genuinely wired and working (22 policies + hard caps, called from `layla/scheduler/jobs.py:195`).

### ST-12 — Make `pip-audit` blocking, or record why it is not
**Effort: ~2h · Risk: MEDIUM (CI could go red on unfixable transitives) · Confidence: MEDIUM**

`.github/workflows/ci.yml:50-54` ends `|| echo "::warning::pip-audit reported advisories (non-blocking; review)"` — the step **always succeeds**. Contrast `ci.yml:47-48`, the copyleft gate, which correctly blocks.

This may well be a deliberate call — pip-audit is noisy and a solo maintainer cannot chase every transitive advisory in the torch/transformers stack. If so, make the choice **explicit and bounded** (fail on HIGH/CRITICAL only, or an ignore list with dated review) rather than decorative. A permanently-red gate gets bypassed. Smaller concern than it looks precisely because the licence gate next to it is correct.

### ST-13 — Close test coverage on UI-wired routers (behind the QW-4 ratchet)
**Effort: hours, not weeks — if scoped correctly · Risk: LOW to product, high in maintainer time**

Eighteen routers have zero tested endpoints, and several are **fully UI-wired**: `onboarding` 7/7, `macros` 5/5, `obsidian` 6/6, `learn` 7/8, `improvements` 4/4, `goals` 4/5, `learned_skills` 4/5, `decisions` 3/4. These are live user-reachable surfaces with no regression protection — materially worse than dead code, because dead code cannot break a session.

**But do not hand-write 181 bespoke endpoint tests.** AST on `routers/onboarding.py`: 7 endpoints, **median body 2 statements, max 2** — every one a pure pass-through. `goals` median 2/max 3. A single parametrized sweep (iterate `app.routes`, GET every read-only route, assert status not in {404, 500}) covers the large majority in one file in hours. Hand-write only where there is real logic in the handler (`learn` max 8, `obsidian` max 5).

Also: "no regression protection whatsoever" is overstated — the *service layers* under these routers are tested (`test_obsidian_sync.py`, `test_skill_acquisition.py`, `test_first_run_tour.py`). The uncovered surface is the thin wrapper.

- **What breaks:** restrict the sweep to **GET** and exclude anything side-effectful or slow — several of these front the model, the filesystem, or the live DB. Path-parameter routes (`{aspect_id}`, `{task_id}`) need fixture IDs or seed/exclude them explicitly; do not weaken the assertion to "not 500," which would let genuine routing breakage pass.

### ST-14 — Add `prometheus_client` to `[dev]` and cover the branch that actually ships
**Effort: ~2h · Risk: LOW**

I could not reproduce the claim that a missing `prometheus_client` breaks 8 CI tests, and I am reporting that rather than confirming it — every CI job installs `agent/requirements.txt`, which declares it.

The genuine defect is the mirror image: `prometheus_client` is in `[core]` and `[cpu]`, so **every real user** gets `text/plain` Prometheus output — but the only tests that exist (`test_observability.py`, 14 tests) deliberately exercise the **absent** branch, and the package is installed in neither local venv. **The branch that ships is the branch nothing tests.**

- **What breaks:** installing it flips `PROMETHEUS_AVAILABLE` to True, so the 14 fallback tests must `monkeypatch` it False explicitly rather than relying on absence — same commit, or the suite goes red.

### ST-15 — Add upper bounds to the highest-churn dependencies
**Effort: ~3h · Risk: MEDIUM (over-pinning has real cost) · Confidence: MEDIUM**

52 of 65 declared dists carry a lower bound only. The `duckduckgo-search` rename is concrete proof this already bit. The project clearly knows the pattern — `fastapi>=0.115,<1`, `sentence-transformers>=3.0,<4`, `chromadb>=0.6.0,<1`, `numpy`, `apscheduler`, `outlines` all carry proper `<` bounds. It just was not applied uniformly.

**Do not bound all 52.** Bound the ones with a history of breaking majors and real blast radius: `litellm` (very high cadence, gateway-critical), `playwright`, `trafilatura`, `matplotlib`, `scikit-learn`, `scipy`, `yfinance`, `textual`, and the pytest plugin trio.

- **Check first:** `agent/requirements-lock.txt` already exists and may be the better mechanism for reproducibility. Don't duplicate that job in pyproject.

### ST-16 — Remove the 4 dead dependency declarations (parity, not size)
**Effort: 30 min · Risk: LOW · Confidence: HIGH**

`requests`, `orjson`, `diskcache` are **already annotated** `FINDING (dead dep)` at `test_dependency_parity.py:82-88` and were never removed — the gate records the debt instead of clearing it. `hypothesis` is a fourth the gate structurally cannot catch (`[dev]` is out of its direction-B scope). Zero import sites across 2436 files; zero literal-string matches in docs/JSON/PowerShell either.

**Correction to the usual rationale: nobody's install shrinks.** All three survive transitively regardless — `diskcache` is an unconditional requirement of `llama-cpp-python`; `requests` of `huggingface_hub`/`instructor`/`tiktoken`; `orjson` arrives via `langchain-text-splitters → langchain-core → langsmith`. The benefit is **declaration parity and licence-accounting honesty** (`THIRD_PARTY.md:51` credits diskcache as a direct dep).

- **What breaks:** an incomplete edit goes red. Delete from `pyproject.toml` **and** `agent/requirements.txt` (direction A: `test_ci_installed_dists_are_reachable_from_an_extra`) **and** the three `_NOT_IMPORTED_OK` annotations (`test_resolution_allowlist_burns_down`) in one commit. Also fix stale prose: `retry_util.py:3` claims diskcache is "already adopted" (it is not), the `requests` comment in `requirements.txt`, `INSTALL_PROFILES.md:33,50,100,116,137`, `THIRD_PARTY.md:51`.
- **Keep** `python-multipart` (FastAPI imports it internally as `multipart`) and `bandit` (invoked as `[sys.executable, '-m', 'bandit', ...]` at `layla/tools/impl/code.py:379`). Both correctly annotated already.

---

## 5. REPO CLEANUP

**Context first, because it is counterintuitive: this repo is not bloated in git terms.** `git count-objects -vH` → `size-pack 11.44 MiB` across 1532 tracked files. `git ls-files -z | xargs -0 git check-ignore` returns **zero rows** — not one tracked file matches a .gitignore rule. No build output, no venv, no models, no `*.db`, no coverage. **Only ~20 KB is genuinely committed by accident.**

### 5a. Tracked files to delete (~20 KB, all verified tracked at plan time)

```bash
cd C:/Work/Programming/Layla

# 1. logs/audit.log — 920 B, 4 JSON lines frozen at 2026-02-19, arrived in the
#    initial commit 71a6500 from the author's old "C:\Github" workspace.
#    The REAL audit writer resolves to agent/.governance/audit.log
#    (main.py:776, scheduler/jobs.py:21, tools/impl/general.py:684) — correctly ignored.
#    No writer, no reader, no test, no CI job references logs/audit.log.
git rm logs/audit.log
#    No .gitignore edit needed: `*.log` and `logs/` already match once untracked.

# 2. agent/scripts/last_report.json — 2580 B, generated output overwritten by
#    run_all_checks.py:318 on EVERY run, frozen at 2026-05-13. Zero readers.
git rm agent/scripts/last_report.json
echo "agent/scripts/last_report.json" >> .gitignore   # REQUIRED — not currently ignored

# 3. agent/runtime_config.json.bak-p13 — 16,475 B, a near-byte-identical copy of
#    your LIVE machine config (437 keys, incl. models_dir and the full
#    secret-shaped surface: discord/slack/telegram tokens, tailscale_auth_key,
#    remote_api_key, langfuse_secret_key — all null in this snapshot, but that is
#    luck, not design).
git rm agent/runtime_config.json.bak-p13

# 4. Two empty scaffolding dirs, 0 bytes, zero references anywhere in the repo.
git rm -r agent/tests/performance_baselines agent/tests/regression_snapshots
```

**Required same-commit companions — do not skip these:**

- **Widen the gitignore rule.** `.gitignore:33` is `agent/runtime_config.json` **exact**. That is precisely the mistake the file's own post-mortem at `:197-200` records having already made with `.graphml` ("the rule used to name the .graphml exactly, so the .bak sibling was left untracked but NOT ignored"). Change to `agent/runtime_config.json*` to match the `graphml*` pattern, and add one assertion beside the existing `.graphml.bak` assertion in `agent/tests/test_release_hygiene.py:58-61`. **Deleting the file alone re-arms the trap for `.bak-p14`.**
- **Fix the six stale citations in `agent/docs/audit/subsystem_audit.md`** (lines 19, 30, 89, 158, 177, 194). Deleting `last_report.json` **orphans** them, it does not fix them — and they are provably wrong against the file they cite: the doc asserts `confidence_pct 100` / `real_assertions_pass 1/3` / `repo_index_populated=false` / `854 tests` where the file says **91 / 3/3 / true / 1445**. The doc is generating fabricated remediation work items from a snapshot that already contradicts it. Strike the numeric claims; do not re-derive them.
- One prose reference at `.planning/phases/13-castilla-repair/VERIFICATION.md:38` points at the `.bak-p13`. One-word edit.

### 5b. Untracked disk — safe subset only (~7 MiB, verified at plan time)

```bash
cd C:/Work/Programming/Layla
rm -rf build dist layla.egg-info .ruff_cache .pytest_cache agent/.pytest_cache
find . -name __pycache__ -type d -not -path './.venv*' -not -path './.claude/*' -exec rm -rf {} +
```

Measured: `build` 5.3M, `dist` 1.2M, `layla.egg-info` 62K, `.ruff_cache` 152K, `.pytest_cache` 5K, `agent/.pytest_cache` 352K, **58** `__pycache__` dirs. All regenerable, all already gitignored.

`layla.egg-info` is safe: the venv uses a PEP-660 editable install (`__editable__.layla-1.4.0.pth` + finder), which never reads `.egg-info`, so the `layla` CLI entry point is unaffected.

**The "~49 MiB reclaim" figure is wrong and dangerous — it collapses to ~7 MiB.** See §6 for the 42 MiB that must not be touched.

### 5c. Documentation archive (~259 KB, `git mv` only)

27 markdown files at the repo root, ~470 KiB. Measured last-commit date and inbound reference count for each. **Zero inbound references from anywhere in the repo:**

| File | Size | Last commit |
|---|---|---|
| `DESIGN-DISTRIBUTED-INFRASTRUCTURE.md` | 52 KiB | 2026-05-24 (1 commit) |
| `repo_state/MASTER_ANALYSIS.md` | 44 KiB | 2026-03-23 (sole occupant of its top-level dir) |
| `HANDOFF.md` | 9 KiB | — |
| `CLIENTS.md` | 2 KiB | — |

Superseded-in-place: `COMPLETION_PLAN.md` (52 KiB) and `SYSTEM_PLAN.md` (29 KiB) both predate `.planning/PLAN.md`, which opens "Supersedes the old scattered plan docs" — yet both still cite `last_report.json` features as future work. `AUDIT_REPORT.md` (12 KiB) is a point-in-time report. `docs/archive/` already exists with 21 files and a README, so destination and convention are established.

```bash
# Order ascending by inbound-ref count: the zero-ref four move first and prove the pattern.
git mv CLIENTS.md HANDOFF.md DESIGN-DISTRIBUTED-INFRASTRUCTURE.md docs/archive/
git mv repo_state/MASTER_ANALYSIS.md docs/archive/
# Then, after reading them:
git mv COMPLETION_PLAN.md SYSTEM_PLAN.md AUDIT_REPORT.md docs/archive/
```

- **Never `git rm`** — `git mv` preserves history and is reversible.
- **Read `ENGINEERING_BLUEPRINT.md` (55 KiB, 1 inbound ref) before moving it** — it is titled as a blueprint and may hold design intent nothing else records.
- Update inbound links in `ROADMAP.md` and `docs/README.md` in the same commit.
- **Keep at root:** `ARCHITECTURE.md` (39 inbound refs), `LAYLA_NORTH_STAR.md` (14), `PROJECT_BRAIN.md` (14).

### 5d. Branches — after Gate 0 only

```bash
git worktree remove .claude/worktrees/mystifying-kapitsa-58fd21   # ONLY after the rescue commit
git branch -d claude/affectionate-raman-8ff02a integration        # lowercase -d refuses unmerged
```

**The naming is a trap.** The *directory* is `mystifying-kapitsa-58fd21`, but the branch checked out inside it is `claude/affectionate-raman-8ff02a` (0 commits ahead of master). The similarly-named *branch* `claude/mystifying-kapitsa-58fd21` has **no worktree and 2 commits not in master**. Name-matched deletion destroys unmerged work. **Never `-D`. Never `--force`.** `remote/friend-ready-session` and `remote/unite-integration` are 0-unmerged but are a separate judgement call.

### 5e. Open decisions (not deletions)

- `.planning/CASTILLA_RELEASE_PLAN.md` (34 KiB, still `Status: DRAFT for review`) and `.planning/REMEDIATION_PLAN.md` (6 KiB) both have **zero inbound references** — including from `PLAN.md`, the doc claiming to supersede scattered plans. **Do not archive REMEDIATION_PLAN.md blind:** it records the operator's explicit voice calibration (EDGE~6, NERVE~7, SIGNAL~4, IRON~4, "direct but keep some warmth") and the non-negotiables list. That is live design intent. Sequence: (1) add a "Superseded plans" section to `PLAN.md` linking both so they stop being orphans; (2) lift the voice-calibration block into `PLAN.md` proper; (3) *then* archive the Castilla plan if phase-13 is confirmed shipped.
- `.planning/PROJECT.md` is currently **untracked and created today**, after being deliberately deleted in `59f24b4` ("fold all planning docs into one canonical PLAN.md; clean .planning/"). The consolidation is quietly being undone. It is one `git add -A` from re-entering the repo against that decision. **Decide deliberately whether it should exist.**

---

## 6. DO NOT TOUCH

Each of these pattern-matches as bloat and each is load-bearing. Recorded so a future cleanup session — human or agent — does not remove it.

### Files and directories

| Item | Size | Why it stays |
|---|---|---|
| `.claude/worktrees/mystifying-kapitsa-58fd21` | 17 MiB | **428 uncommitted lines + 2 untracked test files that exist in no commit anywhere.** See Gate 0. `git worktree prune` does NOT clear it (that only handles directories that no longer exist), which is exactly what pushes someone toward `--force`. |
| `backups/` | 25 MiB | The **only** snapshots of the operator's conversation and memory data (`layla_20260718_213249.db` 3.5 MB, `layla_20260705_200424.db` 675 KB) against a live `layla.db` of 4.07 MB. At most drop the older one, and that is the operator's call. |
| `agent/.governance/` | 2.4 MiB | Holds the **live** audit log the running app appends to (`main.py:776 AUDIT_LOG = GOV_PATH / "audit.log"`), plus the only readers (`trace_last_run`, `tool_metrics`) hardcode that path. |
| `agent/layla/memory/knowledge_graph.graphml.bak` | — | **The knowledge graph's only crash-recovery copy.** `memory_graph.py:115` writes it; `:43-48` restores from it when the primary graphml is unparseable. Deleting it means the next corrupt read returns an **empty DiGraph** — total loss of graph memory reaching the prompt, announced only by a warning-level log on a rare path. |
| `german_mode.db`, `language_tutor.db` | 24 KB each | **Live user vocabulary and SRS decks.** `german_mode.py:83-89` and `language_tutor.py:54-57` resolve and read them at runtime. They are at the repo root because of a CWD path-resolution fallback (ST-8) — a bug to fix, not clutter to sweep. Shield from any `*.db` glob. |
| `agent/tools/nssm.exe` | 368 KiB | MIT-licensed, invoked by four real installer scripts (`uninstall.ps1:68`, `agent/install-autostart.ps1:22`, `install/uninstall_service.ps1:9`, `install/install_service.ps1:1`). **Vendoring it is what makes offline Windows service install work.** No test would catch its removal. |
| `desktop/dist/index.html` | 1031 B | Despite the `dist/` path, a **hand-written Tauri fallback page**, not generated output. `.gitignore` uses anchored `/dist/` specifically so it is not swallowed. |
| `benchmarks/scorecard_qwen2.5-coder-*.json` | 1.4 KiB × 4 | Deliberate tracked pass@1 baselines (REQ-74), documented in `benchmarks/README.md` with a results table. The scorecard that *does* churn (`scorecard_live.json`) is already gitignored — the split is intentional. |
| `readme-assets/` | 1.6 MiB | Largest tracked asset group, but it is what makes the README legible for a public repo. The only defensible action is compressing `demo.gif` (754 KiB). |
| `.gitignore` | 200+ lines | Unusually well-reasoned; carries written post-mortems on the `.identity/` negation trap, the `/sandbox/` anchoring bug, and the `.graphml.bak` near-miss. **Whoever wrote it already fought this battle.** Widen rules (5a), never simplify. |
| `.planning/BACKLOG.md` | 190 KiB | **Live, not historical** — 113 commits, the most-edited planning doc in the repo. I parsed per-item markers: 125 of 128 status-marked BL items are still open, which its own header explains as externally-blocked or deliberately parked. |

### Code and dependencies

| Item | Why it stays |
|---|---|
| **`routers/automation.py`** | Has a **live producer** — `services/memory/knowledge_watcher.py:277` calls `dispatch_event("file_modified", ...)` on every ingest. Only rule *authoring* lacks a UI. Not an orphan. |
| **`routers/plugins.py`, clustering, multi-device, phone, skill-packs, Discord** | Operator ruling: this pillar is **WANTED and must be WIRED, not deleted.** Recommend how to finish them cheaply (O-5), never how to cut them. |
| **`routers/learn.py`** | Not dead — self-included via `agent/routers/agent.py:67` (`from .learn import router`) and `:69`. The BOM made this look orphaned in my first AST pass. |
| **`layla/tools/domains/*.py`** | Not dead — reached via its `__init__.py` re-exports from `layla/tools/registry.py:24`. |
| **`torchao`** | 5.8 MB, not the 493 MB culprit. Buys real int8 dynamic quantization of the embedder on CPU. Try/except-guarded, degrades cleanly. See the rejection table. |
| **`python-multipart`, `bandit`** | Both used non-obviously (internal FastAPI import; subprocess invocation at `code.py:379`). Both correctly annotated in the parity gate already. |
| **The `_al.X` late-bound attribute seam** | 85 `monkeypatch.setattr(agent_loop, ...)` sites across 129 test files depend on it as the interception point. Keep it for the three DI wrappers and the agent_loop-owned attrs (C-9). |
| **The hand-rolled SSE framing** | Correct. `json.dumps` on every payload makes the classic multi-line corruption bug impossible. Keepalive already exists. |
| **The hand-rolled SQLite migration runner** | Correct design for a single-file local app with one maintainer. Alembic solves coordination problems you do not have. Fix its silent-failure path (ST-2), do not restructure it. |
| **NumPy brute-force vector search / `fallback_store`** | Correct at 590 vectors — 0.78 ms/query, and still 7.24 ms at 100× the corpus. The "fallback" has quietly been the real store all along; promote it in name and docs and stop logging the normal case as a degradation. **No vector database is warranted.** |
| **The local BM25** | Short, dependency-free, correct. Adopt FlashRank only. |
| **`skill_sandbox.py`** | Honestly scoped and does not claim to be a security boundary. Every available "upgrade" is a worse trade on CPU-only Windows. The real control is the install-time consent gate. |
| **The ReAct decision loop (`run_decision_loop`)** | One `while`, depth < 5, six top-level breaks. **It is genuinely the simplest thing that works.** The complexity is in `tool_dispatch` and `routers/agent.py`, not here. Do not adopt a framework; adopt smolagents' *shape* (C-1). |
| **`DispatchResult` / the tool-dispatch control flow** | The premise "tools terminate the run" is **factually inverted** — `DispatchResult` is a returned dataclass with exactly **one** production consumer (`decision_loop.py:474`); the loop already owns every break on the tool path. The `_handle_shell` approval path (`tool_dispatch.py:601-652`) that writes a pending record, sets `status="finished"` and breaks is **currently correct and fail-closed.** A refactor risks converting it fail-open for what amounts to a field rename. |
| **`tests/test_example_config_matches_shipped_defaults.py`** | Genuinely excellent — pins divergences *with reasons* and fails on both new and stale ones. Extend its scope (C-11); do not replace it. |

---

## Sequencing for one maintainer

| Block | Items | Cumulative |
|---|---|---|
| **Day 0** | Gate 0 (rescue BL-386) | 15 min |
| **Week 1 — quick wins** | QW-1 … QW-10 | ~10-12 h |
| **Week 2 — data safety** | ST-1, ST-2, ST-3, ST-5 | ~8 h |
| **Week 3 — observability + cleanup** | ST-4 (six files), §5a-5c cleanup | ~10 h |
| **Week 4+ — consolidations** | C-1, C-2, C-3, then C-4/C-5/C-6 | ~15 h |
| **Ongoing / gated** | C-11 (behind the extended guard), O-1 (behind ST-1), ST-13 (behind QW-4) | — |

**One methodological note, because it cost me twice and will cost the next session too:** every measurement error in this audit was a **broken probe**, not broken code. `rg -rn` silently rewrote matches (`-r` is `--replace`) and fabricated a convincing "source file is corrupted" finding. An unbounded `rglob('*.py')` returned 31,982 files — 29,546 of them from the two venvs — and inflated every caller count. A `git status --porcelain` in the main worktree said "clean" while a linked worktree held 428 uncommitted lines. **Make probes assert their own preconditions and fail loudly**, print the path they actually resolved, and never scan source as text to decide what code *does*.