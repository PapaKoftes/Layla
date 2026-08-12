---
priority: core
domain: reasoning
aspect: cassandra
summary: High-impact cognitive biases with definition, concrete example, and a counter-move for each.
---

# Cognitive Biases Catalog

A bias is a systematic error in judgment — predictable, not random. Knowing the name is not enough; each entry gives a **counter-move** you can actually run. Format: definition → example → counter-move.

## Confirmation Bias
**Definition:** Seeking, favoring, and remembering evidence that fits what you already believe; discounting what doesn't.
**Example:** You think a library is buggy, so every failure "confirms" it while your own misuse goes unexamined.
**Counter-move:** Before concluding, write the single piece of evidence that would change your mind, then go look for it. Ask "what would I expect to see if I'm wrong?"

## Anchoring
**Definition:** Over-relying on the first number or frame you encounter, adjusting insufficiently from it.
**Example:** A vendor quotes $50k; your "negotiated" $42k feels like a win, though the job is worth $20k.
**Counter-move:** Generate your own estimate *before* seeing theirs. When given an anchor, deliberately produce a value from an independent method and compare.

## Availability Heuristic
**Definition:** Judging how likely or common something is by how easily examples come to mind.
**Example:** After a plane crash in the news you overrate flying risk; vivid, recent, emotional events dominate memory.
**Counter-move:** Ask "am I estimating frequency, or just recall?" Seek base rates and counts, not anecdotes. Vividness is not probability.

## Sunk Cost Fallacy
**Definition:** Continuing a course because of what you've already invested, not because of expected future value.
**Example:** Ploughing another month into a failing rewrite "because we've spent six already."
**Counter-move:** Decide only on *marginal* future cost vs. benefit. Ask "if I were starting fresh today, knowing what I know, would I choose this?" Past spend is gone regardless.

## Survivorship Bias
**Definition:** Drawing conclusions only from the cases that made it through, ignoring the invisible failures.
**Example:** "Dropouts get rich" — you see the few founders, not the thousands who dropped out and failed.
**Counter-move:** Ask "where are the ones that didn't survive, and would they show up in my data?" Actively hunt the missing denominator.

## Hindsight Bias
**Definition:** After an outcome is known, believing it was predictable all along ("I knew it").
**Example:** After an outage, the root cause seems obvious; you judge the on-call engineer harshly.
**Counter-move:** Record predictions *before* outcomes (decision journal). Judge decisions by the information available at the time, not by results.

## Dunning-Kruger Effect
**Definition:** Low competence in a domain comes with low ability to recognize that incompetence — confidence outruns skill at the bottom; genuine experts often underrate themselves.
**Example:** After one tutorial you feel you "get" security; you can't yet see what you're missing.
**Counter-move:** Calibrate against external checks: tests, peer review, teaching it aloud. Treat early confidence in a new domain as a warning, not a signal.

## Motivated Reasoning
**Definition:** Reasoning steered by what you *want* to be true; you become a lawyer for a preferred conclusion, not a judge.
**Example:** You want to buy the tool, so you weigh its pros heavily and rationalize away the cost.
**Counter-move:** Name your preferred outcome out loud first. Then argue the opposite side as if paid to. Ask a disinterested party what they see.

## Base-Rate Neglect
**Definition:** Ignoring the general prevalence of something in favor of specific, vivid detail.
**Example:** A test is "95% accurate" and positive, so you assume ~95% chance of disease — but if the disease affects 1 in 1000, most positives are false.
**Counter-move:** Always ask "how common is this in the population *before* the evidence?" Combine base rate with the evidence (see base-rates doc), don't replace it.

## Recency Bias
**Definition:** Overweighting the most recent events or data relative to the fuller history.
**Example:** Two good sprints and you declare the team "fixed," forgetting six months of the same problem.
**Counter-move:** Widen the window. Look at trends over the full period, not the last data point. Ask "is this a change or noise?"

## Authority Bias
**Definition:** Accepting a claim because of *who* said it rather than the merits of the claim itself.
**Example:** A senior engineer asserts an approach; nobody checks because of their title, and it's wrong.
**Counter-move:** Separate the claim from the source. Ask "what's the actual argument/evidence?" Expertise raises a prior; it doesn't settle the question. (See argument-analysis: appeal to authority.)

---

## Meta counter-moves (work against most biases)
- **Pre-commit predictions.** A decision journal makes hindsight and confirmation bias visible.
- **Consider the opposite.** Deliberately construct the strongest case against your view.
- **Outside view.** Ask how similar cases *usually* go, not how special this one feels.
- **Slow down on high-stakes, irreversible calls.** Biases exploit speed and emotion.
- **Get an independent second opinion** before you've anchored someone to your framing.

Biases are not stupidity — they are efficient shortcuts that misfire in specific, knowable conditions. The goal is not to feel unbiased (a bias itself), but to install checks at the points where errors are costly.
