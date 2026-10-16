---
name: change-impact
description: Blast-radius analysis for uncommitted or branch changes — maps changed files to their dependents through the Terrain index, cross-checks ADR drift, and produces an ordered read-before-merge list. Load before commit or PR on an indexed repo, or on "what breaks if I change this", "what's the blast radius".
---

# Change Impact

> A changed file is not the blast radius — its **dependents** are. This skill walks outward
> from a diff through the index, then reports who else is affected and what is worth reading
> before the change lands.

## Gate first

Run `skill_view(name="index-health")`. A blast radius computed against a stale index is worse
than no blast radius, because it looks authoritative. If the corpus is stale, say so **before**
presenting any numbers, and offer `refresh` (free) over `init` (LLM) as the fix.

## Step 1 — Get the actual change set

```bash
cd <EXECUTION_DIR> && git status --porcelain
cd <EXECUTION_DIR> && git diff --name-only           # unstaged
cd <EXECUTION_DIR> && git diff --cached --name-only  # staged
cd <EXECUTION_DIR> && git diff --name-only <base>...HEAD   # branch vs base
```

Read the diff, not just the filenames. A rename, a moved constant, and a signature change
have different radii:

| Change | Radius |
|---|---|
| Body-only edit inside a function | local |
| New export added | additive, near-zero |
| Signature / return type changed | every caller |
| Constant or config value changed | every consumer of that value |
| Deleted or renamed symbol | every referrer, **including strings** — config, docs, tests |
| Public interface / port / mount changed | cross-service; check `docker-compose.yaml` too |

## Step 2 — Walk outward

For each changed file, find dependents through the index:

```
pai_terrain_ops(action="search", query="<symbol or path>", project="<slug>", limit=50)
pai_terrain_ops(action="source", file="<candidate>", project="<slug>")
```

`search` finds names; `source` confirms the call site is real before you claim a dependency.
**Never report a dependent you have not read.** A search hit is a lead, not a finding.

For changes that cross a service boundary, read the compose file directly — the index will
not tell you that `TERRAIN_ALLOW_LLM` is read by `server.mjs` in a different container.

## Step 3 — Cross-check ADR drift

```
pai_adr_ops(action="list_adrs")
pai_adr_ops(action="check_drift")
```

A changed symbol with a living ADR is an **escalation**, not a footnote — either the code or
the ADR is now wrong, and the repo says which one is supposed to win. Surface it separately
from mechanical dependents.

## Step 4 — Report

| Changed file | Dependents | Layer | ADR? |
|---|---|---|---|
| `<file>` | `<n> — <list the important ones>` | `<layer>` | `<adr-id>` / — |

Then the ordered list:

```
Read before merge
  1. <path> — <why it matters, in one line>
  2. <path> — <why>

Cross-service
  - <change> affects <service> via <mechanism> — not visible to the index

ADR drift
  - <symbol> contradicts ADR-<id>
```

## Invariants

1. **Staleness before numbers.** Index health is stated first, not last.
2. **No unverified dependents.** Every claim is a file you opened. Search hits are leads.
3. **Bounded scope.** The diff is the blast radius's origin, never its boundary — but the
   report lists what was *not* checked when the walk hits the edge of the index.
4. **ADR drift escalates.** Never bury it under mechanical dependents.
5. **Reads need no confirmation.** This skill never mutates; it runs `git diff`,
   `pai_terrain_ops`, and `pai_adr_ops` only. Applying a fix is `gitops` territory.
6. **Terrain is optional.** Unindexed or stale → fall back to `grep` for dependents and say
   the result is grep-derived, not index-derived.