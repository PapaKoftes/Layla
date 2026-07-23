# STATE — where the work actually stands

*Updated 2026-07-23. This is the resume point for a fresh session. Read PROJECT.md for the why,
ARCHITECTURE_TARGET.md for the checkpoint sequence, this file for what is done.*

## Architecture sequence (ARCHITECTURE_TARGET.md) — 3 of 12 checkpoints done

The foundation layer is complete: the gates are now honest, enforced in CI, and there is a runtime
signal for the defect class. Per the plan, these three are what make every later checkpoint safe to
attempt.

| CP | Name | State | Commit |
|----|------|-------|--------|
| 1 | Detector sees whole codebase | ✅ done | `056f628` |
| 2 | Baseline gates to reality + wire to CI | ✅ done | `c610615` |
| 3 | Runtime liveness registry | ✅ done | `aab0600` |
| 4 | Answer characterization test | ✅ done | `05d3bfe` |
| 5 | The answer becomes a value | ⬜ **next — highest risk** | — |
| 6 | One step writer (`state["steps"].append` → 0 outside turn.py) | ⬜ | — |
| 7 | `state` required at the turn boundary | ⬜ | — |
| 8 | Exhaustive status | ⬜ | — |
| 9 | One prompt builder | ⬜ | — |
| 10 | Collapse pass-through frames | ⬜ | — |
| 11 | One conversation cache | ⬜ | — |
| 12 | Delete corpses, close gates, freeze | ⬜ | — |

**Stop-early line: after CP-9.** CP-10–12 buy legibility, not correctness.

### What the foundation now enforces (CI-gated, `check_architecture.py`, strict by default)
- `state["steps"].append` sites ≤ **49** (CP-6 drives to 1 in `turn.py`)
- `commit_turn` call sites ≤ **19** (CP-7/8 collapse the shapes)
- `shared_state` importers ≤ **16** — the honest count; was 15 only because a BOM hid `routers/agent.py`
- `agent_loop.py` ≤ **1000** lines
- **0** source files unparseable by the AST gates (was 1: the main chat router)

### Runtime liveness dashboard (`check_liveness.py`, report-only)
`tool_executed`, `turn_committed`, `outcome_evaluated`, `conversation_compacted`. Run it after real
use; a named effect stuck at 0 is a load-bearing path that has gone dark.

## Next: CP-5 — The answer becomes a value (~1 day, 3 revertible commits) ⚠️ HIGHEST USER-VISIBLE RISK

Give the final user-visible text one owner (`set_answer`/`answer_of` in a new `turn.py`) and delete
both extraction rules. CP-4's `test_answer_extraction_characterization.py` is the safety net.

**Do NOT rush this on depleted context.** A live ambiguity to resolve BEFORE writing code:
CP-5 commit 1 says "repoint the 4 readers to `answer_of`, zero behaviour change." But the 4 readers
use *different* rules today — Rule A readers (agent.py:1325/:1477) take `steps[-1]`, Rule B readers
(run_finalizer.py:101) take the last reason. A single `answer_of` that does "Rule B then Rule A"
changes what Rule A's readers return on a **tool-last turn** (the flagship multi-step case): the user
would see the last reason instead of the raw tool result. Whether that is the intended unification-at-
commit-1 or a regression must be settled by **driving the real app** on a tool-last goal through BOTH
`/agent` (streamed + non-streamed) and `/v1`, comparing the answer text before/after. The
characterization test passing is necessary but NOT sufficient — it tests the isolated rule helpers,
not the readers. Verify live, per turn shape, per path.

commit 1 = add turn.py + repoint readers (must be provably behaviour-neutral, verified live).
commit 2 = call set_answer at the 3 producers (stream_handler close, reasoning_handler, agent_loop
           parse_failed fallback) — POST-polish, since commit_turn's `text` is already cleaned/floored.
commit 3 = delete both fallbacks + Rule A + Rule B; update the characterization test ONCE (that diff
           is the reviewable record). Add the `steps[-1] outside diagnostics = 0` gate.

## Other live tracks (not the architecture sequence)
- **Release blockers** (`ENGINEERING_HEALTH.md` / the release audit): 7 items, ~25–35h. Highest:
  version-tag mismatch (1h, unrecoverable if a v1.6.0 tag ships against version.py 1.5.0), fresh-install
  empty sandbox_root, the `write_file`/`shell`/`fetch_url` handlers that STILL discard model args
  (QW-1 — same class as P13-E1, applied to 5 of 8 handlers).
- **Feature roadmap** (`ROADMAP.md`): 9 phases, natural release line after Phase 5.
- **Rescued, awaiting review:** branch `rescue/bl-386-overlay-escape` (428 lines that existed in no
  commit — overlay-Escape fix + tests). Merge on its own merits.

## Ground rules for whoever picks this up
`AGENTS.md` → "Engineering discipline" section. The short version: existence is not evidence (prove a
caller by AST); the 4054-test suite mocks the model (drive the real app); verify the probe before the
result; one owner per rule. Every trap in this session was one of those.
