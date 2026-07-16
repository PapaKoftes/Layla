# Phase 13 Context: Castilla repair — plug in what was already built

**Status:** ▶ ACTIVE · **Backlog:** W14 (119 defects) · W15 (29 architecture verdicts) · W16 (instance counts)

## Why this phase, now

The operator drove the actual UI and found it broken in ways a 2,700-test suite could not see. Five parallel
adversarial sweeps and four architectural reviews followed. The finding is not what anyone expected:

> **This was not built badly. It was built well and never plugged in.**
> The defect, at every scale: **callee sets one field, caller inspects another.**
> From `submit_task`/`queue.submit` (a 4,600-LOC courier with no depot) down to
> `record_token_throughput`/`get_token_usage` (5 lines apart, never introduced).

Of ~31 build-vs-adopt verdicts, **zero say "adopt a framework."** Three say CUT. The rest are wiring. The single
highest-leverage change in the whole backlog turned out to be **one decorator** (BL-381, landed).

**Why the tests never caught it:** *"strong behavioral coverage of pure functions, text-matching at every wiring
seam."* Every dead feature died at a seam — and a seam is exactly where the assertions turn into `grep`. The
2,900 green tests measure the parts that were never at risk.

## Goal

Every feature Layla advertises either **works**, or **is deleted**. No third state. Each repair ships with a
guard that **fails when the wiring is removed** — not a grep.

## Success criteria

1. **The learning pipeline runs on a normal turn.** A streamed chat turn writes a learning about the USER.
   Verified by driving a real turn and reading the DB — not by a source match.
2. **Nothing Layla claims is false.** `.identity/capabilities.md` matches reality in both directions; the
   drift test proves it.
3. **Every `getElementById` resolves** — `_KNOWN_DEAD` is empty; the forward sweep is hard-fail with no ratchet.
4. **The three HIGH security items** are fixed or their claims deleted. No user-facing string says "jail" or
   "sandboxed" unless it holds.
5. **Dead subsystems are gone**, not disabled. A "coming soon" toggle is the same lie with a longer fuse.
6. **Green gate + operator confirmation.** `CI_GATE_RESULT exit=0 failed=0` AND the operator confirms in the
   browser. Claude cannot see the UI; "tests pass" is not verification.

## Known facts / constraints

- **Claude cannot see the rendered UI** (preview tooling is banned by the operator). Every UI item needs
  operator confirmation. This is why nothing here is marked ✅ on Claude's say-so.
- **The operator's `.venv` is a THIRD configuration nobody ships** (BL-375). The installer ships `[cpu,llm]`;
  this box is a partial `[core]` — torch present, `model2vec`/`sqlite-vec`/`chromadb` missing. **Any perf
  conclusion drawn from this box is suspect until parity lands.** Do S1 first for this reason.
- **The venv gate must be BIDIRECTIONAL** (BL-385): `cryptography`/`nbformat` are in `.venv-test` only;
  `instructor`/`docstring_parser` are in `.venv` only. Both directions hide bugs.
- `cryptography` is declared in **no extra at all** — hand-installed to turn a `skipif` green. **Encryption is
  unshippable by construction**, in every install path.
- **A skip that fires because a feature is broken is a silent pass.** That is how the dead TTS shipped.
- `run_distill_after_outcome(n=50)` is O(n²) Jaccard, currently per-turn. **Debounce before wiring it to every
  turn** or the fix becomes the bottleneck.
- Do NOT "fix" BL-338 by disabling streaming. Finalize *after* the stream completes.
- Reverse sweeps are **inherently noisy** (computed ids). Triage by hand; never bulk-delete. C3's 99 included
  the aspect switcher.

## Approach (planned slices)

Ordered by leverage. **S1 first** — until the venvs agree, every other test may be lying.

| # | Slice | Items | Size | Why here |
|---|---|---|---|---|
| **S0** | ✅ **DONE** — tool contract + trivial UI | BL-381, 321, 246, 320, 336, 258, 259, 268, 370 | — | One decorator restored 198 signatures + 198 docstrings; 8 dead features live; the element guard has **proven teeth** (reintroduced the bug, it failed) |
| **S1** | **Dependency honesty** | BL-365, 374, 375, 385 | ~2d | Until `.venv` == `.venv-test` == shipped, every verdict rests on tests that may lie. Also closes the **local-first breach**: no `local_files_only` anywhere — the embedder fetches from HuggingFace on first use and an offline first-run silently degrades |
| **S2** | **The learning pipeline** | BL-338, 376 | ~5-6d | 🔴 THE product defect. `commit_turn()` at the 3 done-frames (their triplicated 6 lines ARE the missing abstraction); demote `status` to a safety filter. **Ships WITH the extractor fix** — the seam alone floods the DB with docstrings 8× faster |
| **S3** | **Conversation history** | BL-243, 244, 245 | ~2d | The operator's #1. Async title lands 2s-4min later, nothing re-renders. Plus 7 paths that never persist a turn |
| **S4** | **Security claims** | BL-295, 296, 297, 382, 344 | ~1d | Normalize before matching (the filesystem jail already does — one `splitext` apart); default the allowlist ON; **delete the network-jail claim**; fix the approval-gate test that would pass if the gate were deleted |
| **S5** | **Delete the lies** | BL-349, 350, 367, 384, 380 | ~2d | CUT clustering (−4,600 LOC), the dead SRS (advertised **in chat**), `routing_telemetry` (a 90-day plaintext prompt log **nothing reads** — a liability, not waste), 4 orphan coordinator helpers |
| **S6** | **Learning quality** | BL-264, 265, 266, 377 | ~3d | Source from the USER turn; closed-schema extraction a 3B can do; type-gate at the existing choke point. **No OSS fits** — mem0's telemetry hangs offline, Kuzu is dead |
| **S7** | **The registry smoke test** | BL-346, 347 | ~2d | Unblocked by S0. Needs per-tool `smoke_args` + a timeout — **blind invocation HANGS** (verified) |
| **S8** | **UI seam + i18n** | BL-370(2,3), 261, 335, 249, 337 | ~3d | `$req()`/`$opt()`; ban `onclick=` in JS (40 sites); burn `_KNOWN_DEAD` to zero; 127/162 buttons + `qps` pseudolocale |
| **S9** | **Discoverability + IA** | BL-247, 248, 250, 251, 252, 373 | ~4d | 21 palette-only features; the Growth panel; **the wizard is SKIPPED when the install goes well**; one settings surface, three depths |
| **S10** | **Honesty pass** | BL-306, 257, 289, 290 | ~2d | Manifest ↔ reality; the missing user tutorials; human-readable diagnostics; the lilac theme |

**Deferred, deliberately:** BL-292 (GSD-into-Layla) is **milestone-sized** — its own discovery + spec. Do not
start it inside this phase.

## The rule (non-negotiable)

**Nothing is marked done on Claude's say-so.** Every report states: what changed · what was **PROVED** · what was
**ASSUMED** · what is **unverified**. No ✅, no confidence scores. This rule exists because the same class of bug
was declared fixed three times while the operator was looking at it, still broken — and because four of the ten
worst vacuous tests in the repo were written by Claude, including a guard authored the same morning it was
praised. **A source-grep is not a regression guard. If a test cannot fail when the wiring is removed, it is
documentation.**
