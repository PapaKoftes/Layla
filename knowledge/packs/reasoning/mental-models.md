---
priority: support
domain: reasoning
aspect: cassandra
summary: Reusable thinking tools — first-principles, inversion, second-order, EV, Pareto, systems — and when to use each.
---

# Mental Models

Reusable structures for thinking. A model is a lens, not a law — the skill is picking the right one for the situation and knowing its limits. Each entry: what it is → when to apply it.

## First-Principles Thinking
**What:** Break a problem down to what you know is fundamentally true, then reason up from there — instead of reasoning by analogy to "how it's usually done."
**When:** You're stuck copying an existing solution, a cost/assumption seems fixed but might not be, or the conventional wisdom smells wrong. Ask: "What do I actually know to be true here, and what am I merely assuming?"

## Inversion
**What:** Instead of asking how to succeed, ask how to fail — then avoid that. Solve the problem backwards.
**When:** Goals feel vague or planning is optimistic. "How would I guarantee this project fails?" surfaces risks a forward plan hides. Pairs with pre-mortems. Also useful for proofs and debugging (assume the bug, work back to its cause).

## Second-Order Effects
**What:** Consequences have consequences. The first effect is obvious; the second and third order are where surprises live. "And then what?"
**When:** Any intervention in a system with people or incentives. A rule that fixes X often creates Y. Example: paying for bug reports → people write bugs to report. Always ask "and then what happens?" at least twice.

## Opportunity Cost
**What:** The true cost of a choice is the best alternative you gave up, not the cash you spent.
**When:** Allocating scarce time, money, or attention. Saying yes to this feature is saying no to whatever else that week could build. Make the foregone option explicit before committing.

## Expected Value (EV)
**What:** Value of an uncertain option = sum over outcomes of (probability × payoff). Judge bets by EV, not by whether one instance won or lost.
**When:** Repeated or reversible decisions under uncertainty. A 10% shot at +100 (EV +10) beats a sure +5, even though it usually loses. Caveat: for one-shot, ruinous downsides, respect variance and survival — don't take EV-positive bets that can wipe you out.

## Pareto Principle (80/20)
**What:** Outputs are unevenly distributed across inputs — roughly 80% of results come from ~20% of causes.
**When:** Prioritizing. Find the vital few (the 20% of bugs causing most crashes, the 20% of features driving most value) before spreading effort evenly. Ask "what's the small slice doing most of the work?"

## Systems Thinking & Feedback Loops
**What:** Behavior emerges from structure — stocks, flows, and loops — not from isolated parts. **Reinforcing loops** amplify (compounding, viral growth, death spirals); **balancing loops** stabilize (thermostats, market correction). Delays between action and effect cause overshoot and oscillation.
**When:** Recurring problems that resist point fixes, unintended consequences, or anything with lag. Ask "what loop is producing this?" Fixing a symptom inside a reinforcing loop often makes it worse.

## Map vs. Territory
**What:** Your model of reality is not reality. The map is a useful simplification that omits detail and can be wrong or outdated.
**When:** Whenever you rely on a plan, metric, dashboard, or mental picture. Ask "where might my map diverge from the terrain?" Metrics get gamed; models drift. Trust the territory over the map when they conflict.

## Occam's Razor
**What:** Among explanations that fit the evidence equally well, prefer the one with the fewest assumptions. A tie-breaker, not a truth detector.
**When:** Debugging and diagnosis. The mundane cause (typo, cache, config) is usually likelier than the exotic one (compiler bug, cosmic ray). Note the twin trap: don't oversimplify a genuinely complex situation — the simplest explanation that *fits all the evidence*, not the simplest full stop.

---

## Using models well
- **Latticework:** No single model is complete. Reach for several and see where they agree or conflict.
- **Know the failure mode:** Each model has conditions where it misleads (EV ignores ruin; Occam ignores real complexity; Pareto isn't literally 80/20).
- **Match model to problem:** Prioritization → Pareto/opportunity cost. Uncertainty → EV/base rates. Recurring problems → systems/feedback. Stuck on convention → first principles/inversion.
- **Test the model against the territory,** then update it. A model that never gets falsified isn't earning its keep.
