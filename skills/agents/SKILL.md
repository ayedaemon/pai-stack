---
name: agents
description: Ground rules for operating inside pai-stack, shared by every agent in the stack - the Turn-1 startup protocol, the session-workspace invariant and project-boundary isolation, code intelligence via Terrain, propose-before-writing, planning discipline, and skill routing. Load this FIRST in every session, in every unfamiliar directory, before any other skill.
---

# Ground Rules — pai-stack (all agents)

> Single source of truth for how an agent operates in this stack. Injected into Hermes at
> session start; mounted read-only for every other agent. **Agent-neutral:** everything here
> is available to every agent. If you lack a tool named below, skip that step — do not
> assume it exists and do not substitute a guess for it.

## Ecosystem

| Thing | Where | Role |
|---|---|---|
| Attached workspace | wherever this session is attached | The boundary for **everything**: paths, git, research, planning |
| Workspace root | `/opt/data/workspace` | Multi-project bind mount, read-write |
| Scratch | `/opt/data` | Helper scripts, one-off probes |
| llm-gateway | `http://llm-gateway:4000` | Sole LLM endpoint for hermes + dsh |
| terrain | `terrain:7878` | Code intelligence — the **single index owner** (opt-in profile) |
| skills | `skills_list` / `skill_view` | Procedural knowledge, loaded on demand |

---

## Turn 1 — every session, every unfamiliar directory

> **CRITICAL INVARIANT**: the attached workspace is the boundary. It is chosen by whoever
> attached it, not inferred. `/opt/data/workspace` holds **several independent projects**
> side-by-side, so a session attached to the root must not treat it as one project.

1. **Discover skills** — call `skills_list()`. Do not rely on any hand-written catalogue of
   skills; the tool is the catalogue. Load a skill before any task it covers.
2. **Confirm the attached workspace** — do NOT scan for a project and pick one. Ask the
   runtime: your tools already resolve against it, so `pai_notebook_ops(action="list_pages")`
   reports the vault path, and the terminal starts in the workspace cwd.
   - Attached workspace is one project → work there, no further questions.
   - Attached workspace is the multi-project root, or nothing is attached → **stop and ask**
     which project to attach. Do not guess from markers; a wrong guess writes another
     project's files into the wrong tree.
3. **Recall what you already know**, if your agent has memory (`mnemosyne_recall` on hermes).
   Skip silently where that tool does not exist.
4. **Check the index** if the terrain service is up: `pai_terrain_ops(action="projects")`.
   Load `skill_view(name="index-health")` before trusting any terrain answer — it distinguishes
   indexed / registry-lost / stale and names the fix without running it.
5. **Orient on the stack** — `skill_view(name="stack-discovery")` for an unknown codebase;
   otherwise read the project's manifest.
6. **Announce** the attached workspace, active services, and your plan.

---

## Session Workspace Invariant

Everything stays inside the **attached workspace** for the whole session. It is the project
boundary: research, planning, git, and edits all resolve relative to it, so a session scoped
to one project can never touch a sibling.

| What | Where |
|---|---|
| Shell / build / git | `cd <workspace> && <cmd>` |
| Code edits | `<workspace>/<file>` only |
| Research vault | `<workspace>/.project/research/` — nowhere else, ever |
| Planning artifacts | `<workspace>/.project/planning/<YYYY-MM-DD-slug>/` |
| Probe scripts | `/opt/data/probes/<slug>/` — never in a project |

Write paths **relative to the attached workspace** (`.project/research/...`), not as absolute
paths built from a guess at where the workspace is mounted. Tools resolve the base.

Never mix files, branches, planning files, or build artifacts across projects. If the task
needs a second project, say so and ask for that project to be attached — do not reach outside
the boundary yourself.

## Code intelligence

Terrain is the **only** index owner, and indexing is **free** (`index` / `refresh` make no LLM
call). Both hermes and dsh share it — index once, either agent benefits.

- `pai_terrain_ops(action="projects")` first. If the repo isn't indexed, `index` is free.
- If `projects` is empty but `<project>/.terrain/` exists, the **registry was lost** with its
  volume while the index survived. Re-register with `refresh` — also free. Do not rebuild.
- `ask` / `init` use Terrain's own keyless Zen models (not the gateway). Enabled by default;
  `init` costs an LLM pass, so request it rather than running it unprompted.
- **Terrain is optional.** With the service down, fall back to `grep` + targeted reads and say
  so. Never stall waiting for it.

## Propose before writing

1. Propose the exact diff, file content, or command.
2. **Wait for explicit confirmation.**
3. Write inside the attached workspace.
4. Record what changed in `progress.md`.

Mutating git operations (`commit`, `merge`, `rebase`, `worktree add`, `push`) are gated the
same way — see `skill_view(name="gitops")`. Reads never need confirmation.

Never write raw secrets to any file. Reference them (env var name, vault path).

## Planning discipline

For 3+ steps, research, or multi-file changes, plan first — `skill_view(name="planning")`.

```
<workspace>/.project/planning/<YYYY-MM-DD-slug>/
  task_plan.md   phases, current status, decisions, next step
  findings.md    discoveries — write after every 2 search/read operations
  progress.md    session log: what ran, what failed, what was written
```

## Retrieval

Search narrow, then read only what matched. Never bulk-read a directory without a prior
code-intelligence search or a `grep`.

| Question | Go to |
|---|---|
| Where is this symbol / what depends on it | `pai_terrain_ops` `search` → `source`; `change-impact` for a diff |
| How do I onboard onto this repo | `skill_view(name="codebase-tour")` |
| Is the index trustworthy | `skill_view(name="index-health")` |
| Wiki / notes / knowledge base | `skill_view(name="research")` + `pai_notebook_ops` (wiki under `.project/research/`) |
| Architecture decisions, drift | `pai_adr_ops` |
| Unknown stack, or unfamiliar territory | `skill_view(name="stack-discovery")` |
| Anything I must not forget after the session | your agent's memory tool |

## Skill routing

Load the named skill **before** the task, not during it. Router skills delegate to vendored
depth — load the router, let it name the other.

| Task | Skill |
|---|---|
| Planning, multi-step work | `planning` |
| Git safety, branches, worktrees | `gitops` |
| Codebase onboarding, architecture tour | `codebase-tour` |
| Blast radius of a change | `change-impact` |
| Trustworthiness of the index | `index-health` |
| Diagrams that stay in sync with code | `visualize` |
| Wiki / KB / notes | `research` |
| Explaining anything to a human | `teach` |
| Unknown stack | `stack-discovery` |
| Docker (native CLI over the socket) | `docker` → `docker-development` |
| Python / Node / React / SQL authoring | `python` / `nodejs` / `react` / `sql` |
| Code review, security, shipping, retros | `code-reviewer`, `gstack` (router) |
| Architecture diagrams | `mermaid` |

## Ground rules

1. Stay inside the attached workspace. Never pollute the workspace root.
2. Retrieve before reading — search, then read only matches.
3. Cite `path:line` relative to the attached workspace.
4. Propose, then wait, then write.
5. Plan for 3+ steps.
6. Log every error; never repeat a failing action unchanged. After 3 failures, escalate with a
   structured table of attempt / action / error.
7. No secrets in files.
8. Report honestly. A stale index, an unverified dependency, or a degraded fallback gets
   **stated**, not hidden. Do not present a guess in the shape of a finding.