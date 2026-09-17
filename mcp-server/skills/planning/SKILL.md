---
name: planning
description: Persistent file-based planning for multi-step tasks. Keeps task_plan.md, findings.md, and progress.md on disk so plans survive context loss, session restarts, and crashes. Use for any task with 3+ steps, research, or multi-file changes.
---
# Planning with Files

> Persistent file-based planning for multi-step tasks. Keeps task_plan.md, findings.md, and
> progress.md on disk so plans survive context loss, session restarts, and crashes.
> Use for any task with 3+ steps, research, or multi-file changes.

## ════════════════════════════════════════════════════════════════════════
## SELF-REALIZATION: YOUR PERSISTENT MEMORY UNLOCKED
## ════════════════════════════════════════════════════════════════════════

When you fetch this skill, you're activating **persistent planning** that survives context loss:

**Your Planning Artifacts (in `<EXECUTION_DIR>/.planning/<YYYY-MM-DD-slug>/`):**
| File | Purpose | When to Update |
|---|---|---|
| `task_plan.md` | Phases, progress, decisions, next step | After each phase completes |
| `findings.md` | Research, discoveries, symbols, blast radius, COUNTERPOINTs | After ANY discovery (2-operation rule) |
| `progress.md` | Session log, errors, test results, what changed | Throughout the session |

**Research Integration (Phase 5):**
- `research/` subdirectory for Living ADRs: `ADR-XXX.md`
- Symlinks to `/opt/data/probes/<slug>/` for empirical evidence
- ADRs have symbol hashes for drift detection

**Critical Rules:**
1. **2-operation rule**: After every 2 search/read operations → write to `findings.md`
2. **Propose before writing**: Show diff, wait for confirmation, then write
3. **3-strike protocol**: Attempt 1 (diagnose) → Attempt 2 (different approach) → Attempt 3 (rethink) → Escalate
4. **One plan per task**: Never overwrite another task's plan
5. **Re-read before decisions**: Keeps goals in your attention window

**Graft Integration:**
- Planning files are indexed by Graft → searchable in future sessions
- `graft_find_code` finds your own prior findings and decisions
- `graft_check_freshness` ensures index is current

**When to use:**
- Any task with 3+ steps, research, or multi-file changes
- Complex debugging (root cause analysis in findings.md)
- Architectural decisions (ADR in research/)
- Multi-session work (context survives restarts)

## Where Files Go

Planning files live **in the project** like any developer artifact — not in a special namespace:

```
/opt/data/workspace/<project>/.planning/<YYYY-MM-DD-slug>/
  task_plan.md   ← phases, progress, decisions, next step
  findings.md    ← discoveries: symbols found, blast radius, root causes
  progress.md    ← session log: what ran, errors, what changed
```

CodeGraph indexes these files on the next reindex — they are searchable in future sessions.

## Quick Start

Before a complex task:

1. **Initialize**: Use `planning_with_files_init` or `/pwf "Task Name"` to create the task directory and files.
2. **Create missing files only**: Use the structure above. Preserve existing work when resuming.
3. **Re-read the plan before decisions**: Keeps goals in your attention window.
4. **One plan per task**: Do not overwrite another task's plan.

## File Purposes

| File | Purpose | When to Update |
|---|---|---|
| `task_plan.md` | Phases, progress, decisions | After each phase completes |
| `findings.md` | Research, discoveries, retrieved context | After ANY discovery or CodeGraph result |
| `progress.md` | Session log, errors, test results | Throughout the session |

## Critical Rules

### 1. Plan First — Non-Negotiable
Never start a complex task (3+ steps, research, multi-file) without `task_plan.md`.

### 2. The 2-Operation Rule
> After every 2 read/search/browse operations → IMMEDIATELY save key findings to `findings.md`.

This prevents retrieved context (CodeGraph results, file contents, search hits) from being lost.

### 3. Read Before Decide
Before any major decision, re-read `task_plan.md`. Keeps goals in attention window.

### 4. Update After Each Phase
After completing any phase:
- Mark phase status: `in_progress` → `complete`
- Update `## Next Step` in `task_plan.md` to name the single next action
- Log what changed in `progress.md`

### 5. Log ALL Errors
Every error goes in `task_plan.md`. Builds knowledge, prevents repetition.

```markdown
## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| FileNotFoundError | 1 | Created default config |
| API timeout | 2 | Added retry logic |
```

### 6. 3-Strike Error Protocol

```
Attempt 1: Diagnose & fix
  → Read error carefully
  → Identify root cause
  → Apply targeted fix

Attempt 2: Alternative approach
  → Same error? Try a different method
  → Different tool? Different library?
  → NEVER repeat the exact same failing action

Attempt 3: Broader rethink
  → Question assumptions
  → Search CodeGraph for related context
  → Consider updating the plan

After 3 failures: Escalate to user
  → Explain what was tried (all 3 attempts)
  → Share the specific error
  → Ask for guidance
```

### 7. Propose Before Writing
Always show the user what you will write and where. Wait for explicit confirmation.

## The 5-Question Reboot Test

If you can answer these, your context management is solid:

| Question | Answer Source |
|---|---|
| Where am I? | Current phase in `task_plan.md` |
| Where am I going? | Remaining phases |
| What's the goal? | Goal statement in the plan |
| What have I learned? | `findings.md` |
| What have I done? | `progress.md` |
| What am I about to do? | `## Next Step` in `task_plan.md` |

## Read vs Write Decision Matrix

| Situation | Action |
|---|---|
| Just wrote a file | Don't re-read — still in context |
| Got CodeGraph results | Write to `findings.md` immediately |
| Starting new phase | Re-read `task_plan.md` and `findings.md` |
| Error occurred | Read relevant file for current state |
| Resuming after session gap | Read all 3 planning files |
| Completed phase | Update phase status + `## Next Step` |

## When to Use

- IF a task requires 3+ steps, multi-file changes, or spans many tool calls, THEN you MUST execute this skill.
- IF you are doing research (stack discovery, debugging) or building new features, THEN you MUST execute this skill.
- IF a task is a simple single-file edit, quick lookup, or one-off command, THEN you MAY skip this skill.

## Related Skills

- `skill://stack-discovery` — run first on unknown codebase; save result to `findings.md`
- `skill://codegraph` — CodeGraph query procedures; save results to `findings.md`
- `skill://python`, `skill://docker`, etc. — stack skills; follow after stack-discovery

## Verification
- Verify that `task_plan.md`, `findings.md`, and `progress.md` exist in the `<EXECUTION_DIR>/.planning/<slug>/` directory.
- Verify that the `task_plan.md` has a clear `## Next Step` defined before concluding.
