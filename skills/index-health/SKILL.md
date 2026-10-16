---
name: index-health
description: Pre-flight check on the Terrain index before trusting any terrain answer. Reports index staleness, registry loss, and missing corpora honestly, and names the exact remediation without running it. Load before codebase-tour or change-impact, or on "why doesn't terrain know about X", "is my index stale", "why is this answer wrong".
---

# Index Health

> Terrain indexes a repo into `<repo>/.terrain/` and tracks its own staleness in
> `.terrain/.meta/freshness.json`. This skill reads that ledger **before** you spend a call
> on it, and reports what is actually true — including when the answer is "don't trust it".

You do not fix anything here. You diagnose, and you name the command. The operator decides.

## Why this exists

Terrain's `ask` is **reactive**: when its preloaded context is stale it notices mid-answer,
emits `⚠️ outdated-knowledge notice — index is stale (overall_score N/100)`, and silently
re-verifies with `grep` instead. The answer still looks authoritative. So a stale index does
not fail loudly — it degrades invisibly, and you never learn your index was useless.

This skill is the **pre-flight**. Run it first, so the number is known up front.

## Step 1 — Three states, checked in order

```bash
# a. registry
pai_terrain_ops(action="projects")
# b. artifacts on disk
ls <project>/.terrain/ 2>/dev/null
```

| Registry | `.terrain/` on disk | State | Action |
|---|---|---|---|
| has project | present | **indexed** — go to Step 2 | — |
| has project | absent | **index never ran / wiped** | `index` |
| **empty** | **present** | **registry lost** — see below | `refresh` |
| empty | absent | **not indexed** | `index` (free, no LLM) |

### Registry lost is its own state

`registry.json` lives in the `terrain_data` volume; `.terrain/` lives **inside the indexed
repo** on the workspace bind mount. Different mounts, different lifetimes. Recreating the
volume (`docker compose down -v`, a changed project name, a manual `docker volume rm`)
drops the registry while every index artifact survives intact.

The symptom is `projects` returning `[]` while `<repo>/.terrain/` is fully populated. Project-
scoped `search`, `overview`, and `ask --project` all fail against it. The index is fine; only
its address book is gone. `refresh` re-registers — it is free, idempotent, and reuses the
index already on disk. Do not run `index` here; there is nothing to rebuild.

## Step 2 — Read the ledger

`.terrain/.meta/freshness.json`, or `pai_terrain_ops(action="overview", project="<slug>")`.

```jsonc
{
  "assets": {
    "agent_pack":     { "stale": false, "freshness_score": 95 },
    "agent_context":  { "stale": false, "freshness_score": 85 },
    "human_docs":     { "stale": true, "stale_reason": "repo_advanced_5_commits",
                        "freshness_score": 79 }
  },
  "drift": { "commits_since_baseline": 5, "changed_files_since_baseline": 0 },
  "summary": { "overall_score": 79 }
}
```

`pai_terrain_ops(action="overview")` also reports `doc_counts` — `human`, `modules`,
`interfaces`, `routes`, `events`. The last four staying at `0` is **normal for repos with no
application source** (compose YAML, Markdown, skills). It is not a terrain failure and not
something to fix. Same for `index.md` reading `Tech stack: _Not detected_` on such a repo —
that is an accurate answer, not a broken collector.

### The `stale_reason` vocabulary

Terrain emits one of these, and each implies a different fix:

| `stale_reason` | Meaning | Fix |
|---|---|---|
| `repo_advanced_N_commits` | the repo moved N commits past the corpus baseline | `init` |
| `working_tree_dirty` | uncommitted source changes the corpus can't reflect | commit, or `init` if they matter |
| `baseline_unreachable` | terrain could **not** compare against the baseline — usually its git collector failed inside the container | not a staleness verdict at all; fix git access first |

`baseline_unreachable` is the dangerous one, because it is a *measurement failure wearing a
staleness verdict's clothes*. It does not mean the corpus is old; it means terrain does not
know how old it is. If you see it, check the git collector before drawing any conclusion:

```bash
docker exec terrain sh -c 'cd /repo/path && git rev-parse HEAD'   # "dubious ownership" = broken
```

`server.mjs` injects `safe.directory` into every spawned child's environment for exactly
this reason. If that regresses, `stale_reason` will silently degrade to
`baseline_unreachable` while the ledger keeps reporting `commits_since_baseline: 0` —
which reads as "nothing changed", the most dangerous possible lie.

Terrain's `overview` also returns a `drift_factors` array naming each deduction in prose
(`dirty_tree`, `context_lineage`, `overall_driver`). Quote those in the report; they are more
useful than the bare score.

## Step 3 — Report, then name the fix. Do not run it.

| Asset | State | Fix | Cost |
|---|---|---|---|
| `agent_pack`, `agent_context` | stale | `pai_terrain_ops(action="refresh", path=...)` | free |
| `human_docs` | missing (no `human/` dir) | `pai_terrain_ops(action="init", path=...)` | LLM (keyless Zen) |
| `human_docs` | stale | `pai_terrain_ops(action="init", path=...)` — **`refresh` will not fix this** | LLM (keyless Zen) |

**`refresh` skips Litho.** Terrain's doc generator only runs under `init`. A stale
`human_docs` asset therefore survives any number of `refresh` calls — the 6-chapter corpus in
`.terrain/human/` stays frozen at its original generation date until someone runs `init`.

That makes `init` the expensive action in this stack. It regenerates a whole corpus via the
ACP agent. So:

- **Default to reporting, not repairing.** Present the score, name the command, let the
  operator decide. A stale index is a legitimate state — the operator may prefer `grep` over
  paying for a regen.
- **Never run `init` unprompted.** `index` and `refresh` are free and safe to suggest as
  defaults; `init` needs an explicit go-ahead.
- **Pass staleness forward.** Any skill that consumes this report carries it into its own
  output. A tour built on a stale corpus says so at the top, not in a footnote.

## Report format

```
Index health: <project>
  registry:  ok (slug=<slug>)
  overall:   79/100
  agent_pack     fresh   (95)
  agent_context  fresh   (85)
  human_docs     STALE   (79)  repo_advanced_5_commits — generated 2026-10-04
  drift: 5 commits since baseline

Impact: code search/read are trustworthy. The 6-chapter human corpus predates
5 commits — treat architectural claims from it as dated, and verify before acting.
Fix:    make terrain-index d=<path>   (or ask me to run init — it costs an LLM pass)
```

## Invariants

1. **Diagnose, never repair.** This skill reads and reports. `index`/`refresh` may be
   suggested; `init` must be requested.
2. **Never present a stale index as current.** If `overall_score` is low or any asset is
   stale, say so in the first line, not a closing footnote.
3. **Never confuse registry state with index state.** An empty registry with a full
   `.terrain/` is a *recovery* case, not a rebuild case.
4. **Terrain is optional.** If `pai_terrain_ops` is absent or `/healthz` fails, this skill
   reports "no terrain service" and callers fall back to `grep` + targeted reads. Nothing
   breaks.