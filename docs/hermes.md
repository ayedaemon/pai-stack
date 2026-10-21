# Hermes

Agent gateway + dashboard (`:9119` / `:8642`). See [architecture.md](architecture.md) for how it fits the stack.

## Turn 1 startup

Give Hermes this prompt on Turn 1 so it orients instead of guessing:

```text
You are operating inside the pai-stack Docker Compose environment. Execute your Turn 1 Startup Protocol:

1. Read ground rules: skill_view(name='agents'), then skills_list().
2. Parallel: `docker ps` (pai-stack label filter, see `docker` skill) + mnemosyne_recall(query='workspace projects structure boundaries').
3. List /opt/data/workspace (depth 1), check for root markers (.git/, manifests) in root AND subdirectories.
4. Confirm the attached workspace: `pai_notebook_ops(action='list_pages')` reports the vault path, or read the cwd the terminal already runs in. Do NOT scan the workspace root to pick a project — the attachment is the boundary, and the user chose it. If the workspace holds several projects and no attachment was made, say so and ask which one to attach.
5. IFF research task OR <workspace>/.project/research/SCHEMA.md exists: skill_view(name='research'), then read .project/research/{SCHEMA.md,index.md,log.md} tail-20 only.
6. Report the attached workspace, active services, ready tools, available skills.
```

What this accomplishes: confirms the one workspace this session is attached to, re-hydrates memory, unlocks research mode. Full invariant in [AGENTS.md](../AGENTS.md) and `skills/agents/SKILL.md`.

## Tools (`pai_tools` plugin)

| Tool | Purpose | Actions |
|---|---|---|
| `pai_notebook_ops` | Research wiki ops on `<workspace>/.project/research/` | `init_wiki`, `list_pages`, `get_page`, `write_page`, `search`, `ingest_url`, `ingest_file`, `get_source`, `ask` |
| `pai_adr_ops` | Living ADRs + symbol drift detection | `create_adr`, `check_drift`, `list_adrs` |
| `pai_ops_design_ops` | OpenDesign visual generation / mockups bridge | (see `opendesign-integration` skill) |
| `pai_terrain_ops` | Code intelligence via Terrain service (`terrain:7878/call`) | `index`, `refresh`, `search`, `read`, `overview`, `projects`, `unregister`, `source`, `init`, `ask` |
| `skill_view` / `skills_list` | Load / discover procedural skills | `name="<skill>"` |

> For code questions: prefer `pai_terrain_ops` when the repo is indexed; otherwise use `grep` + targeted reads.
>
> Docker is not a tool: native `docker` + `docker compose` over the mounted socket (see `docker` skill).

## Skills

Load via `skill_view(name="<name>")` before working on an unknown stack. Files live in `./skills/`, mounted read-only.

**Routers/shims:** `stack-discovery`, `python`, `docker`, `react`, `nodejs`, `sql`, `planning`, `gitops`, `research`, `opencode-delegate`, `agents`.

**Vendored depth:** `vercel-react-best-practices`, `vercel-composition-patterns`, `frontend-design`, `supabase-postgres-best-practices`, `senior-backend`, `docker-development`, `web-design-guidelines`, `webapp-testing`, `mcp-builder`, `code-reviewer`, `skill-security-auditor`.

**gstack suite:** `gstack` + 25 `gstack-*` skills (router, office-hours/spec/autoplan, plan reviews, reviews/investigate/cso/health, ship/land-and-deploy/document-*, learn/retro/context-*, careful/freeze/guard).

## Memory (Mnemosyne)

Local-first, embedded in Hermes: SQLite (`hermes-data` volume) + ONNX fastembed. Auto-captures turns; prefetches relevant memories; `mnemosyne_recall` / `mnemosyne_remember` / `mnemosyne_sleep` / `mnemosyne_stats` + triple graph (`mnemosyne_triple_add` / `mnemosyne_triple_query`).

## Where Hermes writes

| What | Where |
|---|---|
| Code changes | `<workspace>/<file>` (after diff confirmation) |
| Planning files | `<workspace>/.project/planning/<YYYY-MM-DD-slug>/` (`task_plan.md`, `findings.md`, `progress.md`) |
| Scratch tools | `/opt/data/<tool_name>` |
| Memory / state | `hermes-data` volume (never in workspace) |

For 3+ step tasks Hermes follows planning-with-files: 2-operation rule (2 searches → write `findings.md`), propose-before-writing, 3-strike escalate. Research procedures: [research.md](research.md).