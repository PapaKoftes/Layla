---
priority: core
domain: engineering
aspects: Morrigan
difficulty: beginner
related: testing-strategy.md, security-engineering-basics.md
---

# Git workflow practices

## Baseline rules

- Keep commits **small and purposeful**.
- Prefer **branches + PRs** for anything non-trivial.
- If it’s not reviewed, treat it as risky.

## Branching

- **Trunk-based** for small teams: short-lived branches, merge quickly.
- **Release branches** only when you must support multiple versions.

Recommended naming:

- `feature/<short>` for features
- `fix/<short>` for bugfixes
- `chore/<short>` for maintenance

## Commit messages

- Prefer a consistent style. Two common options:
  - **Conventional commits**: `feat: ...`, `fix: ...`, `chore: ...`
  - **Imperative**: `Add X`, `Fix Y`, `Refactor Z`
- Focus on **why** more than **what**.

## PR hygiene

- Keep PRs reviewable (aim for <400 changed lines when possible).
- Include:
  - Summary
  - Test plan
  - Risk / rollback note for risky changes
- Don’t mix unrelated changes (formatting + logic + feature) in one PR.

## Code review behaviors

- Review intent first: “Does this solve the right problem?”
- Then correctness: edge cases, safety, error handling.
- Then maintainability: names, structure, tests, docs.

## Merges

- Prefer **squash merge** if you want a clean history.
- Prefer **merge commits** if you want to preserve a narrative (many contributors).
- Avoid rebasing shared branches unless the team expects it.

## Common footguns

- Don’t commit secrets. Rotate if you do.
- Don’t rewrite public history (force push) unless you know who you’ll break.
- Don’t resolve conflicts without running tests.

---
priority: core
domain: engineering
aspects: morrigan, echo
difficulty: beginner
related: testing-strategy.md, devops-cicd-patterns.md
---

## Git workflow practices (clean history, low drama)

### Branching
- **Short-lived branches**: integrate often; avoid week-long divergence.
- Name branches by intent: `feature/...`, `fix/...`, `docs/...`, `chore/...`.

### Commits
- **Small, coherent commits**: each commit should be reviewable in isolation.
- **Message style**: “why” + “what changed” in one line; add body only when needed.
- Avoid committing secrets, local configs, or private data.

### Pull requests
- Keep PRs tight: aim for a single theme.
- Include:
  - **Summary** (what/why)
  - **Test plan** (what you ran; what to click)
  - **Risk** (what could break)

### Rebasing vs merging
- **Rebase locally** to keep your branch up to date, if your team expects linear history.
- **Merge** if preserving branch history matters (larger teams / long-lived branches).
- Avoid rewriting history of shared branches.

### Review hygiene
- Respond to feedback with either code changes or a short rationale.
- Prefer fixing root cause over patching symptoms.
- If a change is opinionated, document the invariant you’re optimizing for.

