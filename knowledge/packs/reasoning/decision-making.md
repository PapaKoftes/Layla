---
priority: support
domain: reasoning
aspect: cassandra
summary: A usable decision process — reversibility, options, weighted criteria, EV under uncertainty, pre-mortems.
---

# Decision-Making

A process to make good decisions repeatably. A *good decision* is judged by the quality of reasoning given what was knowable at the time — not by the outcome (outcomes have luck in them). Separate decision quality from result quality.

## 1. Define the decision — and its reversibility
State the actual choice in one sentence, and the real deadline. Then classify:

- **Two-way door (reversible):** cheap to undo. Decide *fast*, with less analysis, and learn by doing. Delegating and defaulting to action is correct here.
- **One-way door (irreversible / expensive to reverse):** hiring/firing, public commitments, data deletion, architecture you'll build years on. Slow down, gather more, get more eyes.

Most decisions are two-way doors treated as one-way. The main failure is spending one-way-door caution on two-way-door choices — and vice versa.

## 2. Generate options
The first-offered choice is often a false binary ("do X or don't"). Force at least **three** real options. Techniques:
- Add the "do nothing / status quo" option explicitly and cost it.
- Ask "what would I do if this option were off the table?"
- Combine or split options; look for a both/and.
- Set a floor: never decide between fewer than 2 genuine alternatives.

## 3. Criteria and weights
List what actually matters *before* scoring options (deciding criteria after you see options invites motivated reasoning). Assign rough weights — even 1–5 — to reflect that not all criteria are equal. A simple weighted table:

| Option | Cost (w2) | Speed (w3) | Risk (w3) | Fit (w2) | Total |
|--------|-----------|------------|-----------|----------|-------|
Score each cell, multiply by weight, sum. The number isn't the decision — it exposes hidden trade-offs and forces the weights into the open. If the winner feels wrong, your real weights differ from your stated ones; find out why.

## 4. Expected value under uncertainty
For options with uncertain outcomes, estimate probabilities and payoffs and compute EV (Σ probability × payoff). Rules of thumb:
- Use ranges, not false precision. "60–80% likely" beats a fake "73%."
- Weight the **downside** separately: an EV-positive bet with a ruinous tail can still be a no. Ask "what's the worst case, and can I survive it?"
- Prefer options that keep future options open (optionality) when uncertainty is high.

## 5. Pre-mortem
Before committing, imagine it's a year later and the decision **failed**. Ask each person: "What went wrong?" This is inversion applied to planning — it surfaces risks that optimism suppresses, and it's psychologically easier than predicting failure in advance. Turn the top failure modes into mitigations or kill-criteria.

## 6. Decide, set a review trigger, and record it
- **Commit.** A timely 80% decision usually beats a perfect one too late.
- **Set kill/review criteria in advance:** "If by date X metric Y isn't Z, we stop/revisit." This defeats sunk cost later.
- **Write it down** — the decision, the reasoning, the key assumptions, expected outcome. This decision journal is the only cure for hindsight bias and the only way to actually improve calibration.

## Avoiding analysis paralysis
- **Match rigor to stakes and reversibility.** Reversible + low-stakes → decide now.
- **Set a decision deadline** and a "good enough" bar up front. More information has diminishing and sometimes negative returns.
- **Satisfice, don't maximize** on low-stakes calls: take the first option that clears the bar.
- **The cost of delay is a real cost** — include the status quo's ongoing damage in the ledger.
- If two options are genuinely close after honest analysis, they're close: pick one and move. The agonizing gap is usually tiny.

## Common traps
- Deciding on the outcome you *want* (motivated reasoning) — name it, then argue the other side.
- Anchoring on the first option or number — generate independently first.
- Confusing a bad outcome with a bad decision — review the reasoning, not just the result.
- Skipping the status-quo option — inaction is a choice with its own cost.
