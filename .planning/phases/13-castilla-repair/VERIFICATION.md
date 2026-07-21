# Phase 13 Verification: Castilla repair

**Status:** ~ 1 of 6 criteria done (S0) · **Date:** 2026-07-16 · **Backlog:** W14/W15/W16

> ## S-P13 update — 2026-07-21 (performance + memory + safety session)
>
> A 14-commit session landed against this phase without knowing it was the active phase; the work was
> rediscovered independently and lands on criteria 4, 2 and 6. Gate **GREEN 3944 passed / 0 failed**.
>
> **CRITERION 5 IS REWRITTEN BY OPERATOR DECISION.** It read "dead subsystems deleted, not disabled"
> and named clustering and SRS. The operator has since ruled BOTH are to be **wired, not deleted** —
> clustering because it is the potato→gaming-PC compute-offload pillar ("why should we delete this
> instead of making it work?"), SRS by explicit answer on 2026-07-21. Criterion 5 now reads: *no
> subsystem is advertised-but-dead — the advertised ones are wired.* The old wording is superseded,
> not merely unmet, and must not be actioned as written.
>
> **Landed against criterion 4 (security):** `powershell` blocked / `powershell.exe` ALLOWED is FIXED
> — the stale duplicate blocklist in `layla/tools/impl/system.py` was deleted rather than patched (the
> correct normaliser already existed in `services/sandbox/shell_runner.py`; two copies of one security
> rule was the actual defect) and the fallback now fails closed. Measured 5 bypasses + 4 false blocks
> before. `clipboard_read`/`screenshot_desktop` also gated. **Still open on 4:** the 3 network-jail
> bypasses and `check_output` running after the token loop (streaming unguarded).
>
> **Landed against criterion 2 (nothing Layla claims is false):** the memory graph was feeding planted
> test data into the prompt — measured, `"what should I do about the failing test"` produced
> `Knowledge graph associations: Adversarial verifier test fact: the sky is teal on Tuesdays.` A
> recency fallback injected the 5 newest nodes whenever nothing matched the goal. Fixed. **Still open
> on 2:** the capability manifest reaches the model for "list your capabilities" and "what tools do you
> have" but NOT for "what can you actually do" — a trigger gap, not a wiring break (REPO_ROOT is now
> correct). And the graph DATA is unpurged: ~6 of 31 nodes are real.
>
> **Operator config corrected (2026-07-21, with explicit permission).** Three stored values were
> disabling working features, none of them auto_tune-owned:
> `convo_turns 0 → 6` · `use_chroma false → true` · `sandbox_root ~/layla-workspace → C:/Work/Programming/Layla`.
> The sandbox root had been an EMPTY directory, which is why `read_file` was 0/13, `file_info` 0/7 and
> `list_dir` 2/26 while every non-disk tool was ~100%. Verified after the change: `read_file` 8000
> chars, `list_dir` 95 entries, `file_info` ok. **The engineering-agent half of the product had never
> had anything to work on.** Backup at `agent/runtime_config.json.bak-p13`.
>
> **Regressions introduced and closed in-session:** making compaction actually fire (P13-B2) turned two
> dormant audit findings live — round-6 #14 (swap guard compared LENGTH, blind at deque maxlen, drops
> the newest turn) and #12 HIGH (summariser held a non-reentrant lock across a call that re-enters it,
> freezing all local inference under `llm_serialize_per_workspace`). Both fixed in P13-B2b.
>
> **Scope decision:** the operator has set "finished" = these 6 criteria only. The 9 outstanding audit
> HIGHs and the remote pillar are explicitly OUT of this phase (and at least one round-3 HIGH is
> already stale — `MEMORY_SECTION_ORDER` now contains all three blocks it was reported as missing).
>
> ### Criterion status after S-P13 (gate GREEN 3995 passed / 0 failed)
>
> | # | Criterion | State | What moved |
> |---|---|---|---|
> | 1 | Learning pipeline runs on a normal turn | 🟡 | **Outcome evaluation now runs on streamed turns** (P13-C1). It was gated on `status == "finished"` while `reasoning_handler` returns `stream_pending`, and the UI ships streaming ON — so on the default path nothing was ever evaluated. Moved to `commit_turn`, the real turn boundary. **Open:** strategy stats, skill acquisition and answer_quality still live in `run_finalizer` and remain streamed-blind. |
> | 2 | Nothing Layla claims is false | 🟡 | **Manifest trigger fixed** (P13-C2): `_CAP_Q_RE` required "you"/"do" adjacent, so "what can you actually do" got no capability ground truth — she invented on the exact turn the user pushed for accuracy. **Graph fabrications fixed** (P13-B5). **Open:** the graph DATA is unpurged (~6 of 31 nodes real; two planted false facts about the operator). Code cannot distinguish a well-formed false claim — that is an operator decision. |
> | 3 | Every `getElementById` resolves | 🟡 | **Untouched this session.** 7 lookups remain on the `_KNOWN_DEAD` ratchet (BL-335/249/337); criterion needs it empty. |
> | 4 | Three HIGH security items | ✅ | All three resolved and now **pinned as executable assertions** rather than prose (P13-C4). powershell.exe bypass fixed by deleting the duplicate blocklist; network-jail resolved via the criterion's "claims deleted" branch (in-process Python sandboxing is impossible — disclaimers verified and scanned for regression); streaming guarded by `StreamOutputGuard`, verified **wired** in all 3 paths. Writing the test found a **live bypass nobody had reported: `sh`, `zsh` and `wsl` were not blocked** while `bash`/`pwsh` were. Also fixed a bare `sandbox/` in .gitignore that silently claimed `agent/services/sandbox/`. |
> | 5 | ~~Dead subsystems deleted~~ → **wired** | ⬜ | **Redefined by operator decision** (see above). Both clustering and SRS are to be WIRED. Neither started — these are two feature builds, not repairs, and are the bulk of the remaining phase. |
> | 6 | Green gate + operator confirmation | 🟡 | Gate **GREEN 3995 / 0**. Operator confirmation still **PENDING** — unchanged; Claude cannot see the UI render. |
>
> ### FINAL — end of S-P13 (gate GREEN 4032 passed / 0 failed)
>
> | # | Criterion | State |
> |---|---|---|
> | 1 | Learning pipeline runs on a normal turn | ✅ |
> | 2 | Nothing Layla claims is false | 🟡 **operator-blocked** |
> | 3 | Every `getElementById` resolves | ✅ |
> | 4 | Three HIGH security items | ✅ |
> | 5 | Advertised subsystems are wired | ✅ |
> | 6 | Green gate + operator confirmation | 🟡 **operator-blocked** |
>
> **1 — done.** All four learners now run at the turn boundary: outcome evaluation (P13-C1), then
> strategy stats, skill acquisition and answer_quality (P13-C1b). All four had shared one
> `status == "finished"` gate that a streamed turn never satisfies. answer_quality was doubly dead —
> even past the gate it assessed a text reconstructed from `state["steps"]`, which is empty on a
> streamed run.
>
> **3 — done.** `_KNOWN_DEAD` is EMPTY and a test asserts it stays empty. The last two entries were
> BL-337 phone access; the ratchet forced the choice and the operator chose build. Verified in the
> browser, not just by unit test: opening Settings populates the LAN URL and tip, no console errors.
>
> **4 — done and now machine-checked.** Writing the criterion as assertions found a live bypass three
> security reports had missed (`sh`/`zsh`/`wsl` unblocked while `bash`/`pwsh` were), plus a bare
> `sandbox/` in .gitignore silently claiming `agent/services/sandbox/`.
>
> **5 — done, both wired rather than deleted.** Clustering: every piece existed and nothing called
> them; wiring the shipped `run_completion_with_cluster` as-is would ALSO have changed nothing, since
> it only reaches for a peer when local *raises* and local here succeeds slowly. `try_cluster_offload_first`
> prefers a peer that outranks this box. SRS: the tool's description promised SM-2 grading and the
> implementation graded nothing, so every learning stayed `next_review_at = NULL` and therefore
> permanently due — repetition with the spacing removed.
>
> **2 and 6 are blocked on the operator, not on engineering.**
> * 2 — the memory graph DATA is unpurged: ~6 of 31 nodes are real, the rest prompt scaffolding and
>   two planted false facts about the operator. Code cannot distinguish a well-formed false claim
>   from a true one; deleting someone's memory is their call.
> * 6 — the gate is green; confirmation requires a human to look at the UI.
>
> **Deliberately NOT claimed:** the 9 outstanding audit-round HIGHs (out of scope by operator
> decision, and at least one is already stale) and the rest of the remote pillar (Discord, Syncthing,
> multi-device). Phone access landed only because criterion 3 forced the choice.

## Success criteria → evidence

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | The learning pipeline runs on a normal turn | ⬜ | **S2 not started.** Measured today: 17/24 realistic messages take a fast path with ZERO side effects; the rest hit `stream_pending`, which skips 15 of 20 effects. The finalizer gates on `status == "finished"` (`run_finalizer.py:34`) but `reasoning_handler.py:58` returns before the answer exists, and the UI ships streaming ON (`index.html:610`). **Layla learns nothing from normal use.** |
| 2 | Nothing Layla claims is false | 🟡 | `.identity/capabilities.md` ships (git-tracked; the `.identity/` negation was inert — git cannot re-include a file whose parent dir is excluded) + 30 tests incl. a drift test that **caught its own fix** ("math_eval now WORKS — remove it from KNOWN_BROKEN_TOOLS"). Still lists TTS/symbol-search/ingest as broken **because they are**. |
| 3 | Every `getElementById` resolves | 🟡 | `test_ui_element_contract.py` — forward sweep hard-fail, **teeth proven**: reintroduced the ingest bug → failed with *"#ingest-path is being read again"* → restored → green. **7 lookups remain on the `_KNOWN_DEAD` ratchet** (BL-335/249/337); criterion needs it empty. |
| 4 | The three HIGH security items fixed or claims deleted | ⬜ | **S4 not started.** Reproduced: `powershell` blocked / `powershell.exe` ALLOWED (and `pwsh`/`bash` aren't on the list at all); **3/3 network-jail bypasses** (`import _socket`, `reload`, raw `_socket`) incl. a real HTTP 200; `check_output` runs *after* the token loop, so streaming — the default — is unguarded. |
| 5 | Dead subsystems deleted, not disabled | ⬜ | **S5 not started.** Clustering: `DroneWorker` polls a permanently empty queue every 5s forever while the UI ships an Enable toggle **translated into 11 locales**. SRS: advertised **in chat** (`chat-render.js:385`), 0 rows ever, and the live german_mode clone is **buggier than the dead original**. |
| 6 | Green gate + operator confirmation | 🟡 | **`CI_GATE_RESULT exit=0 failed=0`** on everything landed. **Operator confirmation: PENDING** — 3 buttons were ported into the topbar and Claude cannot see them render. |

## S0 — landed and measured (2026-07-16)

| Fix | Proof |
|---|---|
| **BL-381** `@functools.wraps` | signatures erased: **198 → 0** · docstrings nulled: **198 → 11** · pydantic schemas: **198/198 in 247ms**. BL-346's premise ("no static contract exists") was **false** — 196/198 tools were already annotated; the contract was being *discarded*. |
| **BL-306 payoff** | `list_tools` returned **198 tools with 100% empty descriptions** — the tool Layla answers *"what can you do?"* with. Now real descriptions. The manifest was an elaborate workaround for a missing decorator. |
| **BL-321** `math_eval` | `AttributeError` on every input → `3*7 = 21`. Survived because the 198-tool test counts registrations and **never invokes one**. |
| **BL-246** header | 3 orphans ported to the visible `.topbar`; ids verified **unique** (duplicates would bind the hidden copy and re-break them). |
| **BL-320** ingest | read `#ingest-path` (exists nowhere) → bailed → wrote its error to a null element. **Nothing happened at all, not even the error.** |
| **BL-336** health banner | appended to `#chat-messages`; container is `#chat`. Had **never once appeared**. |
| **BL-258/259/268** | study presets (`JSON.stringify` → double quotes in a double-quoted `onclick` → SyntaxError → renders perfectly, does nothing) · `[object Object]` · `+11 more` |
| **BL-370** guard | **teeth proven by reverting the bug**, not asserted. |

## Honest notes for the next session

- **Claude almost shipped a fake fix in S0:** the first header attempt moved it *off-screen* instead of porting
  its controls — leaving Global search unreachable for any mouse user. Looked fixed, changed nothing. Caught
  before it landed, **while actively writing about that disease.**
- **`token_throughput` is NOT the 5-line fix the review claimed.** Producer and consumer do exist 800 lines
  apart — but `_add_usage` has **no elapsed time at any of its 4 call sites**, so a duration must be threaded
  through. Stopped rather than half-do it.
- **`test_agent_loop::test_tool_preflight_redirects_missing_args_to_reason` fails — verified PRE-EXISTING** (by
  stashing; fails identically without S0's changes). BL-333: the fast path shadows preflight.
- **Four of the ten worst vacuous tests in the repo are Claude's**, including `test_learning_bleed_guard.py`
  written the same morning it was called watertight: a reverted `learn_text = final_text` passes all four of
  its asserts. **Fix the guard before trusting the fix.**
- The reverse id-sweep's 99 "dead" ids **include the aspect switcher** (`'btn-' + id`, computed). Triage by
  hand. Never bulk-delete.

## S1 attempt 1 — REJECTED by adversarial verification (2026-07-16)

**Gate was GREEN (`exit=0 failed=0`, 3187 passed) and the slice was still rejected.** That is the phase rule
working: green is necessary, not sufficient. Work stashed (`git stash list`), fully recoverable.

### 🔴 BL-365 IS FALSE — correcting my own backlog

I wrote: *"cryptography is declared in NO extra at all... encryption-at-rest is UNSHIPPABLE BY CONSTRUCTION in
every supported install path."* **Both halves are wrong.** Verified directly:

    install/setup_profiles.py:55   "deps": ["cryptography"], "flags": {"encryption_at_rest_enabled": True}
    routers/setup_profiles.py:99   subprocess.run([sys.executable,"-m","pip","install","--quiet",dep])

cryptography IS installable — via the **optional-feature installer**, which is the designed path (and
`kit_catalog.py:27` sells it as the "Privacy Vault"). My conclusion came from grepping `pyproject.toml` only
and never checking the feature manifest. A spec agent inherited the false premise; an implementer acted on it;
**the adversarial verifier caught it.**

**Worse — the fix was aimed at the wrong layer entirely.** The verifier proved that adding cryptography
**changes nothing**: `memory_router.py:245` and `learnings.py:117` call `maybe_encrypt()` with a
`privacy_level` that is **never `sensitive`**, so it returns plaintext with or without the dep. **BL-326 was
always the real defect.** Encryption is not a packaging problem.

**Lesson, and it is the session's lesson again:** I diagnosed from one file and stated it as verified fact.
The premise was load-bearing for four agents' work.

### Other verified findings against the attempt

- **F1 (teeth) HIGH — `keyring` is the `model2vec` bug VERBATIM, sitting in the new gate's own blind spot.**
  The parity gate only inspects a hand-maintained `PATH_FLIPPING` dict, so it cannot see what it was built to
  catch: `keyring` is in `[core]`+`[cpu]` (every user has it), absent from `requirements.txt` (CI never
  installs it), and flips a path in `secret_store`. **A guard with a hand-maintained inclusion list is a guard
  that misses the next instance** — the exact failure mode this phase exists to kill.
- **F2 (teeth) HIGH** — the second `docs[:k]` is unguarded and **the test self-certifies teeth it does not
  have**.
- **F1 (honesty) HIGH** — `/health/deps` would report `encryption:` in a way that misleads, given the path
  never fires.
- **F3 (honesty) MED-HIGH** — the skip→fail inversion's teeth are **self-manufactured**.

### What the implementer got RIGHT (worth keeping when this is redone)

Its **rejections** were the best work in the slice — it refused four specs on correct grounds:
- Refused a venv-sibling parity test because `pyproject.toml:166-170` **documents `[dev]` as deliberately
  lighter than shipped** — the test would assert an invariant the project explicitly rejects, be permanently
  red, and get deselected: *"becoming the thing this phase kills."*
- Refused the chromadb/nbformat removal — **false premise, both ARE installable**.
- Refused the prometheus_client removal: *"blind-fixing the one path CI exercises is how this repo got here."*
- Refused ~120MB of model bundling on **unverified licensing** — kokoro-GPL already broke CI once.
- Refused to land a UI panel it could not see.

### More corrections to my backlog, from this run

- 🔴 **BL-375 HAD IT BACKWARDS.** `.venv-test` **HAS** model2vec + sqlite-vec; `.venv` does **not**. I stated
  the reverse. The divergence is real; my direction was wrong.
- 🔴 **BL-367's "latent bug" is FALSE.** `system-diagnostics.js`'s `_flatten` is **shape-agnostic** and does
  not break on the prometheus summary shape. Disproved by execution.
- **tree-sitter is commented out of `requirements.txt`** — absent from CI *and* both venvs, so
  `test_code_intelligence.py` runs **nowhere**, while `search_codebase` stays registered, allow-listed,
  UI-exposed and planner-recommended, returning `ok:True, count:0`. Declare the dep or delete the feature —
  a product call, not an engineering one.
- **CI has been red on all 8 recent runs** — 8 unique prometheus tests × 3 jobs. Pre-existing; unexamined.
- **Ruff is installed in neither venv**, so nothing in this session was linted.

### How to redo S1

1. **Delete BL-365 as written.** Rewrite it as: *"the optional-feature installer is the shipped path for
   `cryptography`; the defect is that nothing ever sets `privacy_level='sensitive'` (BL-326), so encryption
   never fires regardless."*
2. **The parity gate is worth keeping — but derive `PATH_FLIPPING` by AST, not by hand.** Scan for
   `try: import X / except ImportError:` and compare THAT against the extras. A hand-maintained list
   reproduces the bug it is meant to prevent (F1 proves it: it already misses `keyring`).
3. **Keep the BM25 backstop** (the live reranker silently returning unranked results is real, BL-378) — but
   guard BOTH `docs[:k]` paths and prove the teeth on each.
4. Land nothing on `/health/deps` until the encryption field can be honest.
