---
priority: core
domain: engineering
aspect: morrigan
summary: Systematic debugging: reproduce, isolate, hypothesize, instrument, fix, verify, prevent — and the traps to avoid.
---

# Debugging Methodology

Debugging is not luck or staring harder. It is a loop that converts a vague symptom into a proven cause. Work the loop; do not skip steps.

## The loop

1. **Reproduce** — make the bug happen on demand.
2. **Isolate** — shrink the search space (minimal repro, bisection).
3. **Hypothesize** — form ONE falsifiable guess about the cause.
4. **Instrument** — add observation to confirm or kill the hypothesis.
5. **Fix** — change the actual cause.
6. **Verify** — prove the fix works and nothing else broke.
7. **Prevent** — regression test + note so it never returns silently.

If you're not currently on a named step, you're guessing. Stop and name the step.

## 1. Reproduce

A bug you can't reproduce, you can't fix — you can only hope. Invest here first.

- Nail the exact inputs, environment, versions, timing, and sequence.
- Reduce nondeterminism: pin seeds, freeze the clock, fix ordering, single-thread it.
- If it only happens in prod: capture the request, payload, config, and data snapshot; replay locally.
- "Works on my machine" → the difference IS the bug. Diff the two environments.
- Intermittent? Loop it: `for i in range(1000): run()`; log the failing case. Flakiness is a reproduction problem, not a mystery.

## 2. Isolate

Cut the search space in half repeatedly instead of reading everything.

**Minimal reproduction** — delete code/inputs until removing more makes the bug vanish. What's left points at the cause. A good minimal repro often reveals the fix by itself.

**Binary search (bisection)** on anything ordered:
- *Commits*: `git bisect start; git bisect bad; git bisect good <sha>` — it checkouts midpoints; you mark good/bad; log(n) steps find the culprit commit. Automate with `git bisect run pytest test_x.py`.
- *Data*: does it fail on the first half of the rows? Recurse.
- *Code path*: comment out / early-return halves of a function to find which side triggers it.

**"What changed?"** — the highest-yield question. Bugs rarely appear in untouched code. Check recent commits, dependency bumps, config/env changes, data shape changes, upstream API changes. `git log --since`, `git diff`, lockfile diffs.

## 3. Read the traceback (Python)

- **Read bottom-up**: the last line is the exception + message; the frame directly above it is where it was raised. The top frames are the outer call chain.
- The message is data — read it literally. `KeyError: 'user_id'` means that exact key is absent, not "something about users."
- `NoneType has no attribute X` → something returned `None` you expected to be an object; find *which* call.
- Look for the last frame in *your* code before it enters a library — usually where you misused the API.
- `raise ... from e` chains ("During handling of the above exception...") — the *original* cause is the first block.
- Use `traceback.print_exc()` / `logging.exception()` to capture full stacks; never swallow with bare `except: pass`.

## 4. Hypothesize + instrument

Write the hypothesis as a sentence you can prove false: "The list is empty because the filter runs before the data loads." Then observe *that specific thing*.

**Print vs debugger:**
- **Print / logging**: best for loops, async, timing, multi-process, prod, "which branch ran," value-over-time. Fast, no ceremony. Log the variable AND a label: `print(f"after filter: {rows=}")` (the `=` shows name and value).
- **Debugger** (`breakpoint()` → pdb, or IDE): best for inspecting rich state at one point, stepping through unfamiliar code, examining the call stack live. pdb: `n` next, `s` step in, `c` continue, `p expr` print, `l` list, `w` where, `pp` pretty-print.
- Post-mortem: `python -m pdb script.py` or `pdb.post_mortem()` in an except block drops you at the crash site.

**Rubber-ducking**: explain the code line-by-line aloud to a duck/person. You'll hear the false assumption yourself. The bug is almost always a gap between what you *think* the code does and what it does.

## 5–6. Fix and verify

- Fix the **cause**, not the symptom. Wrapping in try/except or adding an `if x is not None` guard often hides the real defect (why was it None?).
- Change **one** thing. Re-run. If it fixed it, you learned the cause. If not, revert and try the next hypothesis — don't stack speculative edits.
- Verify: the original repro now passes, AND the surrounding tests still pass. Confirm you fixed *this* bug, not a similar-looking one.

## 7. Prevent

- Write a **regression test** that fails before the fix and passes after. This is the only proof the bug is truly dead and stays dead.
- If the class of bug is likely elsewhere, grep for the pattern and fix siblings.
- Add an assertion/type/validation at the boundary where the bad value entered.

## Traps (anti-patterns)

- **Shotgun debugging** — changing many things hoping one helps. You lose causality and add new bugs. One change at a time.
- **Fixing symptoms** — silencing the error instead of removing its cause.
- **Assuming instead of checking** — "it can't be that" is where the bug is. Verify assumptions with observation, especially the "obviously correct" ones.
- **Editing without reproducing** — you can't tell if you fixed anything.
- **Trusting the wrong layer** — blaming the library/OS/compiler before your own code. It's your code ~99% of the time.
- **Not reading the error** — the message frequently states the answer.
- **Debugging tired** — fresh eyes solve in minutes what exhausted eyes miss for hours. Sleep is a debugging tool.

## Quick checklist

- [ ] Can I reproduce it on demand?
- [ ] What changed recently?
- [ ] What's the minimal repro?
- [ ] What's my one falsifiable hypothesis?
- [ ] What observation confirms/kills it?
- [ ] Did I fix the cause or the symptom?
- [ ] Does a regression test now guard it?
