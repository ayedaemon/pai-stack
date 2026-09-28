---
name: planning
description: Planning router for multi-step work — owns the persistent task_plan.md/findings.md/progress.md discipline in <EXECUTION_DIR>/.planning/. Load when a task has 3+ steps, research, or multi-file changes. Delegates plan authoring rigor to writing-plans and execution rigor to executing-plans.
---

# Planning (router)

> You own planning **discipline and paths**. Plan **authorship and execution rigor**
> live upstream. Shared Hermes glue (EXECUTION_DIR, vault, citations, propose-before-write)
> is canonical in the `agents` skill — follow it, it is not repeated here.

## When to use
- IF a task needs 3+ steps, multi-file changes, or research, THEN load this skill.
- IF the task is a single-file edit or one-off lookup, THEN skip.

## Pai paths (non-negotiable)
```
<EXECUTION_DIR>/.planning/<YYYY-MM-DD-slug>/
  task_plan.md   ← phases, decisions, ## Next Step (update per phase)
  findings.md    ← discoveries (2-operation rule: write after every 2 searches/reads)
  progress.md    ← session log, errors, test results
```
- One plan per task. Re-read `task_plan.md` before major decisions.
- Log ALL errors in `task_plan.md` (`| Error | Attempt | Resolution |`).
- 3-strike protocol: diagnose → different approach → rethink → escalate with attempts table.

## Delegate (load via `skill_view`)
| Need | Load |
|---|---|
| Authoring a spec-grade implementation plan | `writing-plans` (superpowers, plugin) |
| Executing a plan task-by-task with verification gates | `executing-plans` (superpowers, plugin) |
| Code-anchored findings | `pai_code_intel(action="find_code")`, then `check_freshness` |

## Outputs
- `task_plan.md` always has a single `## Next Step` before you conclude.
- Planning files are indexed — future sessions find them via code intelligence.
