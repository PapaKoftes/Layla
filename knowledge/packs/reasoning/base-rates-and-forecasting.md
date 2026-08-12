---
priority: support
domain: reasoning
aspect: cassandra
summary: Thinking in probabilities — base rates, plain-language Bayes, calibration, reference classes, ranges over points.
---

# Base Rates & Forecasting

Most reasoning errors about the future come from ignoring how common things are and from pretending we know more precisely than we do. This doc is about thinking in probabilities.

## Base rates: start with how common it is
The **base rate** is the prior prevalence of something before you look at any specifics. It's the single most neglected number in judgment.

- **Example:** A "99% accurate" test says you have a rare disease that affects 1 in 10,000. Even with a great test, *most* positives are false, because there are far more healthy people to generate false positives than sick people to generate true ones. The base rate dominates.
- **Rule:** Before weighing the specific evidence, ask "out of 1000 similar cases, how many are X to begin with?" Then adjust from there — don't throw the base rate away because the specific story is vivid.

## Bayesian updating in plain language
New evidence should *shift* your belief in proportion to how much more likely that evidence is under one hypothesis than another — it rarely proves anything outright.

Plain-language recipe:
1. **Start with the prior** — your belief before the new evidence (often the base rate).
2. **Ask the key question:** "How much more likely is this evidence if my hypothesis is true than if it's false?" Strong, surprising, hard-to-fake evidence moves you a lot; weak or expected-either-way evidence moves you little.
3. **Update proportionally.** Big likelihood ratio → big shift. Small → small.

- **Strong evidence is evidence that would be *unlikely* if you were wrong.** "It's consistent with my theory" is weak if it's also consistent with the alternatives.
- Update **incrementally**. Don't lurch from 10% to 90% on one ambiguous data point; don't cling at 10% as contrary evidence piles up. Both extremes are errors.
- A useful gut check: "What would have to be true for the opposite conclusion, and how likely is that?"

## Reference-class forecasting (the outside view)
To forecast a specific case, first find the **reference class** — the set of similar past cases — and use *their* distribution of outcomes as your anchor. Then adjust for what's genuinely special about this case.

- **Why:** The "inside view" (this project's specific plan and optimism) systematically underestimates cost and time — the planning fallacy. The outside view corrects it.
- **Example:** "This renovation will take 6 weeks" (inside view) vs. "renovations like this usually run 3–5 months and 40% over budget" (outside view). Start from the reference class, then adjust.
- **How:** Identify the class → get its actual outcome distribution → place your case in it → adjust modestly for real differences (and distrust "but we're different" — everyone thinks that).

## Calibration
Being calibrated means your confidence matches your hit rate: of the things you call "70% likely," about 70% happen. Most people are **overconfident** — their 90% claims come true ~70% of the time.

- **Train it:** Make explicit probability predictions, write them down, and score them later. Only feedback builds calibration.
- **Confidence intervals:** When asked for a 90% range, make it wider than feels comfortable — genuine 90% intervals are surprisingly wide, and narrow ones get blown through.
- **Track record beats feeling.** How often have your "sure things" been wrong?

## Why point predictions mislead — use ranges
A single number ("revenue will be $2.4M", "done by March 3") hides uncertainty and invites false confidence. It's almost always wrong and gives no sense of *how* wrong.

- **State ranges and probabilities:** "$1.8M–$3.0M, most likely ~$2.3M" carries the uncertainty honestly.
- **Scenarios:** give worst / likely / best, not one line.
- **Beware precision theater:** more decimal places do not mean more accuracy. Round to what you actually know.
- **Widen for the unknown unknowns:** history's ranges were usually too narrow; reality finds the tails.

## Practical checklist
- What's the **base rate** before this specific evidence?
- How **diagnostic** is the evidence — would it look different if I were wrong?
- What's the **reference class**, and what usually happens to it?
- Am I stating a **range**, or a fake point estimate?
- Is my **confidence** backed by a track record, or a feeling?
