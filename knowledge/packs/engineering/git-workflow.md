---
priority: support
domain: engineering
aspect: morrigan
summary: Practical git: atomic commits, good messages, rebase vs merge, bisect, reflog safety net, conflicts, safe undo.
---

# Git Workflow

Git is a safety net and a communication tool. Commit history is documentation your future self and teammates read to understand *why*.

## Atomic commits

One commit = one logical, self-contained change that builds and passes tests.

- Don't mix refactor + feature + formatting in one commit — reviewers can't separate signal from noise, and reverts drag unrelated changes.
- Separate mechanical changes (rename, reformat) from behavioral changes into different commits.
- Stage selectively: `git add -p` (patch mode) picks hunks so unrelated edits in the same file land in different commits.
- Each commit should be revertable on its own without breaking the build.

## Good commit messages

```
<type>: <imperative summary, <=50 chars, no period>

Why the change is needed and what it does. Wrap ~72 cols.
Explain intent and trade-offs, not the diff (the diff shows what).

Fixes #123
```

- Subject in imperative mood: "Add retry to uploader," not "Added"/"Adds." (Completes "If applied, this commit will ___.")
- The body answers **why**, and why *this* way — the code shows what and how.
- `type:` prefixes (feat, fix, refactor, docs, test, chore) aid scanning and tooling (Conventional Commits).
- A message like "fix stuff" or "wip" costs you an hour during a future bisect. Spend the 20 seconds now.

## Branching

- Short-lived feature branches off `main`; merge/rebase back quickly. Long-lived branches drift and rot into conflict hell.
- Keep branches focused and small — easier review, faster merge, fewer conflicts.
- Name descriptively: `fix/upload-retry`, `feat/oauth-login`.
- Pull/rebase `main` frequently to stay current and surface conflicts early while they're small.

## Rebase vs merge

**Merge** preserves true history, creates a merge commit joining two branches. Non-destructive.
**Rebase** replays your commits on top of a new base — linear history, no merge commit, but *rewrites* commit SHAs.

Practical rules:
- **Rebase your local/unpushed work** onto latest `main` before opening/updating a PR → clean linear history: `git rebase main`.
- **Merge** (or squash-merge) to integrate a finished PR into `main`.
- **NEVER rebase commits that others have pulled** (shared/pushed branches) — rewriting shared history forces everyone into conflicts. Golden rule: don't rewrite public history.
- `git pull --rebase` avoids noisy "Merge branch main" commits on sync.

## Interactive rebase — clean up before sharing

`git rebase -i HEAD~5` opens an editor to rewrite the last 5 commits:

- `pick` keep, `reword` edit message, `squash`/`fixup` combine into previous (fixup discards the message), `edit` pause to amend, `drop` delete, reorder lines to reorder commits.
- Use it to: squash "wip"/"fix typo" commits into their parent, split a fat commit (`edit` then `git reset HEAD^` and re-commit in pieces), reorder, fix messages.
- `git commit --fixup <sha>` + `git rebase -i --autosquash` automates fixup placement.
- Do this on your branch *before* others pull it. Not on `main`.

## git bisect — find the commit that broke it

```
git bisect start
git bisect bad                 # current is broken
git bisect good v1.2.0         # this old tag worked
# git checks out a midpoint; test it, then:
git bisect good   (or)   git bisect bad
# repeat log2(n) times → names the first bad commit
git bisect reset
```

Automate: `git bisect run pytest tests/test_thing.py` — git drives the whole search using the test's exit code. This is why atomic, buildable commits matter.

## reflog — the safety net

`git reflog` records where HEAD has been (commits, resets, rebases, checkouts) for ~90 days, even for "lost" commits.

- Botched a rebase/reset and think work is gone? It usually isn't. `git reflog`, find the SHA before the mistake, `git reset --hard <sha>` or `git checkout -b rescue <sha>`.
- Deleted a branch? Its tip is in the reflog — recover it.
- This is why git is safe to experiment with: almost nothing committed is truly lost.

## Resolving conflicts

Conflicts happen when two branches change the same lines. Git marks them:
```
<<<<<<< HEAD
your side
=======
their side
>>>>>>> other-branch
```
- Edit to the correct *combined* result, remove all markers, `git add` the file, then `git rebase --continue` / `git merge --continue`.
- Understand *both* sides' intent before choosing — don't blindly keep yours. `git log`/`git blame` on the region if unsure.
- Reduce conflicts: small frequent merges, rebase often, agree on formatting to avoid whitespace noise.
- Escape hatch: `git merge --abort` / `git rebase --abort` returns to the pre-attempt state.
- `git checkout --ours <file>` / `--theirs <file>` to take one side wholesale when appropriate.

## Undoing safely

| Situation | Command | Note |
|---|---|---|
| Unstage a file | `git restore --staged <f>` | keeps edits |
| Discard working changes | `git restore <f>` | **destroys** uncommitted edits |
| Fix last commit message/content | `git commit --amend` | rewrites; only if unpushed |
| Undo commit, keep changes staged | `git reset --soft HEAD~1` | safe |
| Undo commit, keep changes unstaged | `git reset HEAD~1` | mixed (default) |
| Undo commit, discard changes | `git reset --hard HEAD~1` | **destructive** |
| Undo a *pushed* commit | `git revert <sha>` | new inverse commit, safe on shared |

- **Prefer `revert` over `reset` on anything pushed** — revert adds a new commit that undoes the change without rewriting history.
- Stash work-in-progress to switch context: `git stash` / `git stash pop`; `git stash -u` includes untracked.
- Before any `--hard` or force-push, know that reflog can save you — but pause and confirm the target SHA.
- `git push --force-with-lease` instead of `--force`: refuses to overwrite if someone else pushed in the meantime.
