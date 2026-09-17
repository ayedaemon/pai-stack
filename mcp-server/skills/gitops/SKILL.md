---
name: gitops
description: Full Git lifecycle management (dev, feature, fix, hotfix, prod), worktree sandboxing, and read/write/plumbing operations. No mutating git changes are to be made without explicit user confirmation.
---
# GitOps

> Full Git lifecycle management (dev, feature, fix, hotfix, prod), worktree sandboxing, and read/write/plumbing operations. No mutating git changes are to be made without explicit user confirmation.

## When to use
- Trigger phrases / intents: "check git status", "start feature", "fix issue", "what changed in git", "git log", "gitops", "commit changes", "create branch", "merge"
- Preconditions: project under `/opt/data/workspace/...` with a `.git` directory.

## Inputs
- Required: project root path.
- Optional: task type (feature, fix, hotfix), branch name, file path, commit hash.

## Steps

### 1. Project Management & Workflow Lifecycle
Follow standard Git workflow topologies based on the base branch. **Check if a `dev` branch exists.** If it exists, use it as the primary integration branch. If it does not exist, use `main` or `master`.
- `main` / `prod`: The stable, production-ready branch.
- `dev`: Primary integration branch (if present).
- `feature/<name>`: Branched from `dev` (or `main`) for new capabilities.
- `fix/<name>`: Branched from `dev` (or `main`) for standard bug fixes.
- `hotfix/<name>`: Branched from `main` for critical production issues (must be merged back to both `main` and `dev`).

### 2. Worktree Sandboxing (The Smart Execution)
To avoid dirtying the active workspace, you MUST sandbox your execution context using Git worktrees when working on new tasks (features, fixes, hotfixes).

1. **Initialization**:
   - Check if `.worktrees/` is ignored in the project's `.gitignore`. If not, **explicitly propose that the user updates their `.gitignore` to ignore `.worktrees/`**.
   - Propose creating a new worktree for the task inside the hidden `.worktrees/` directory at the project root.
   - Command pattern: `git worktree add .worktrees/<task-slug> -b <branch-type>/<name> <base-branch>`
   - Example: `git worktree add .worktrees/feature-auth -b feature/auth dev`
2. **Execution Context**:
   - Once the user confirms and the worktree is created, change your `EXECUTION_DIR` to `.worktrees/<task-slug>`.
   - Perform all code edits, linting, tests, and plumbing operations inside this sandbox.

### 3. Read & Plumbing Operations
- Use efficient read-only commands (`git status`, `git log -n <N> --oneline`, `git diff`, `git branch -a`).
- Use low-level plumbing operations (`git rev-parse`, `git ls-tree`, etc.) for diagnosis when necessary.
- Read and read-only plumbing operations can be run without confirmation.

### 4. Write Operations & Commit Discipline
- You are fully capable of mutating git state (`git commit`, `git merge`, `git push`, etc.).
- Use Conventional Commits format when proposing commits (e.g., `feat: ...`, `fix: ...`, `chore: ...`).
- **CRITICAL INSTRUCTION FOR WRITES**: Do not execute ANY write or mutating git commands (including `git worktree add`, `git commit`, `git merge`, `git push`, `git rebase`) without explicit user confirmation. You must first propose the exact git command(s) you intend to run and wait for approval.

### 5. Merge & Cleanup
- Once the task in the worktree is complete and tested, propose merging the branch back into its base branch (`dev` or `main`).
- Propose removing the worktree and deleting the local branch: `git worktree remove .worktrees/<task-slug>` and `git branch -d <branch-type>/<name>`.

## Outputs
- Primary: Safe, sandboxed execution of features and fixes, with a clear trace of branch lifecycle and atomic commits.

## Notes for Hermes
- You are the custodian of the repository's hygiene. Always isolate your work using `.worktrees/`.
- Propose updating `.gitignore` if `.worktrees/` is not present.
- NEVER execute mutative git changes without explicit user confirmation. ALWAYS propose the git command and wait for the user to approve before executing.
