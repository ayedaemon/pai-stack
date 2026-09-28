---
name: gitops
description: Git safety router — branch topology, .worktrees/ sandboxing, and the user-confirmation gate for mutating git ops. Load for status/log/branch/commit/merge work. Delegates isolation mechanics to using-git-worktrees and merge/PR finish to finishing-a-development-branch.
---

# GitOps (router)

> You own git **safety invariants**. Isolation mechanics and finish flows live upstream.
> Shared Hermes glue is canonical in the `agents` skill.

## Invariants (always apply, upstream has none of these)
1. **Topology**: `dev` (if present) is the integration branch, else `main`/`master`. `feature/*`, `fix/*` branch from it; `hotfix/*` branches from `main` and merges back to both.
2. **Sandbox**: new work goes in `.worktrees/<task-slug>` (`git worktree add .worktrees/<slug> -b <type>/<name> <base>`); switch `EXECUTION_DIR` into it; propose `.gitignore`-ing `.worktrees/` if missing.
3. **Confirmation gate**: NEVER run mutating git commands (`worktree add`, `commit`, `merge`, `push`, `rebase`) without proposing the exact command and waiting for explicit approval. Reads (`status`, `log -n`, `diff`, `branch -a`, plumbing) need no confirmation. Conventional Commits for messages.

## Delegate (load via `skill_view`)
| Need | Load |
|---|---|
| Worktree isolation, setup detection, clean-baseline gate | `using-git-worktrees` (superpowers, plugin) |
| Test-first merge, PR, worktree cleanup | `finishing-a-development-branch` (superpowers, plugin) |
