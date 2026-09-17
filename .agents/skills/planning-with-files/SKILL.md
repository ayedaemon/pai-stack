---
name: planning-with-files
description: Persistent file-based planning for multi-step tasks. Keeps task_plan.md, findings.md, and progress.md on disk so plans survive context loss, session restarts, and crashes. Use for any task with 3+ steps, research, or multi-file changes.
---
# Planning with Files

> Persistent file-based planning for multi-step tasks. Keeps task_plan.md, findings.md, and
> progress.md on disk so plans survive context loss, session restarts, and crashes.
> Use for any task with 3+ steps, research, or multi-file changes.

## Core Pattern

```
Context Window = RAM (volatile, limited)
Filesystem    = Disk (persistent, unlimited)
→ Anything important gets written to disk.
```

## Where Files Go

Planning files live **in the project** like any developer artifact:

```
<EXECUTION_DIR>/.planning/<YYYY-MM-DD-slug>/
  task_plan.md   ← phases, progress, decisions, next step
  findings.md    ← discoveries: symbols found, blast radius, root causes
  progress.md    ← session log: what ran, errors, what changed
```

## Critical Rules

### 1. Plan First — Non-Negotiable
Never start a complex task (3+ steps, research, multi-file) without `task_plan.md`.

### 2. The 2-Operation Rule
> After every 2 read/search/browse operations → IMMEDIATELY save key findings to `findings.md`.

### 3. Read Before Decide
Before any major decision, re-read `task_plan.md`. Keeps goals in attention window.

### 4. Update After Each Phase
After completing any phase:
- Mark phase status: `in_progress` → `complete`
- Update `## Next Step` in `task_plan.md` to name the single next action
- Log what changed in `progress.md`

### 5. Log ALL Errors
Every error goes in `task_plan.md`. Builds knowledge, prevents repetition.

### 6. 3-Strike Error Protocol
Attempt 1: Diagnose & fix
Attempt 2: Alternative approach
Attempt 3: Broader rethink
After 3 failures: Escalate to user

### 7. Propose Before Writing
Always show the user what you will write and where. Wait for explicit confirmation.
