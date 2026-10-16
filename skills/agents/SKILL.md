---
name: agents
description: Ground rules for operating inside pai-stack, shared by every agent in the stack - the Turn-1 startup protocol, EXECUTION_DIR and project-boundary invariants, code intelligence via Terrain, propose-before-writing, planning discipline, and skill routing. Load this FIRST in every session, in every unfamiliar directory, before any other skill.
---

# Ground Rules — pai-stack (all agents)

> Single source of truth for how an agent operates in this stack. Injected into Hermes at
> session start; mounted read-only for every other agent. **Agent-neutral:** everything here
> is available to every agent. If you lack a tool named below, skip that step — do not
> assume it exists and do not substitute a guess for it.

## Ecosystem

| Thing | Where | Role |
|---|---|---|
| Workspace | `/opt/data/workspace` | Multi-project bind mount, read-write |
| Scratch | `/opt/data` | Helper scripts, one-off probes |
| llm-gateway | `http://llm-gateway:4000` | Sole LLM endpoint for hermes + dsh |
| terrain | `terrain:7878` | Code intelligence — the **single index owner** (opt-in profile) |
| skills | `skills_list` / `skill_view` | Procedural knowledge, loaded on demand |

---

## Turn 1 — every session, every unfamiliar directory

> **CRITICAL INVARIANT**: the workspace holds **several independent projects** side-by-side.
> Never confuse them, and never treat `/opt/data/workspace` as one project unless its root is
> itself a confirmed repo.

1. **Discover skills** — call `skills_list()`. Do not rely on any hand-written catalogue of
   skills; the tool is the catalogue. Load a skill before any task it covers.
2. **Survey the workspace root** — list `/opt/data/workspace` (depth 1) and look for root
   markers in the root **and** in subdirectories: `.git/`, `package.json`, `pyproject.toml`,
   `Cargo.toml`, `go.mod`, `Makefile`, `docker-compose.yaml`, `.project/`.
3. **Declare `EXECUTION_DIR`** — announce it before doing anything else.
   - Root has markers, subdirectories do not → `EXECUTION_DIR = /opt/data/workspace`
   - Subdirectories have their own markers → `EXECUTION_DIR = /opt/data/workspace/<project>`
4. **Recall what you already know**, if your agent has memory (`mnemosyne_recall` on hermes).
   Skip silently where that tool does not exist.
5. **Check the index** if the terrain service is up: `pai_terrain_ops(action="projects")`.
   Load `skill_view(name="index-health")` before trusting any terrain answer — it distinguishes
   indexed / registry-lost / stale and names the fix without running it.
6. **Orient on the stack** — `skill_view(name="stack-discovery")` for an unknown codebase;
   otherwise read the project's manifest.
7. **Announce** `EXECUTION_DIR`, active services, and your plan.

---

## Execution Directory Invariant

Everything stays inside `<EXECUTION_DIR>` for the whole session.

| What | Where |
|---|---|
| Shell / build / git | `cd <EXECUTION_DIR> && <cmd>` — never run these in the workspace root |
| Code edits | `<EXECUTION_DIR>/<file>` only |
| Planning artifacts | `<EXECUTION_DIR>/.project/planning/<YYYY-MM-DD-slug>/` |
| Probe scripts | `/opt/data/probes/<slug>/` — never in a project |

Never mix files, branches, planning files, or build artifacts across projects.

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
3. Write inside `<EXECUTION_DIR>`.
4. Record what changed in `progress.md`.

Mutating git operations (`commit`, `merge`, `rebase`, `worktree add`, `push`) are gated the
same way — see `skill_view(name="gitops")`. Reads never need confirmation.

Never write raw secrets to any file. Reference them (env var name, vault path).

## Planning discipline

For 3+ steps, research, or multi-file changes, plan first — `skill_view(name="planning")`.

```
<EXECUTION_DIR>/.project/planning/<YYYY-MM-DD-slug>/
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
| Wiki / notes / knowledge base | `skill_view(name="research")` + `pai_notebook_ops` |
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

1. Anchor to `EXECUTION_DIR`. Never pollute the workspace root.
2. Retrieve before reading — search, then read only matches.
3. Cite `path:line` relative to `EXECUTION_DIR`.
4. Propose, then wait, then write.
5. Plan for 3+ steps.
6. Log every error; never repeat a failing action unchanged. After 3 failures, escalate with a
   structured table of attempt / action / error.
7. No secrets in files.
8. Report honestly. A stale index, an unverified dependency, or a degraded fallback gets
   **stated**, not hidden. Do not present a guess in the shape of a finding.