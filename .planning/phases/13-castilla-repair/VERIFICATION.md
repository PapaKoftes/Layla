# Phase 13 Verification: Castilla repair

**Status:** ~ 1 of 6 criteria done (S0) · **Date:** 2026-07-16 · **Backlog:** W14/W15/W16

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
