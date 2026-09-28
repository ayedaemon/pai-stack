# Hermes

Agent gateway + dashboard (`:9119` / `:8642`). See [architecture.md](architecture.md) for how it fits the stack.

## Turn 1 startup

Give Hermes this prompt on Turn 1 so it orients instead of guessing:

```text
You are operating inside the pai-stack Docker Compose environment. Execute your Turn 1 Startup Protocol:

1. Read ground rules: skill_view(name='agents'), then skills_list().
2. Parallel: pai_docker_ops(action='list') + mnemosyne_recall(query='workspace projects structure boundaries').
3. List /opt/data/workspace and run pai_code_intel(action="repo_map") to declare your EXECUTION_DIR.
4. IFF research task OR $RESEARCH_DIR/SCHEMA.md exists: skill_view(name='research'), then read SCHEMA.md + index.md + log.md tail-20 only.
5. Report EXECUTION_DIR, active services, ready tools, available skills.
```

What this accomplishes: pins Hermes to one `EXECUTION_DIR` (never treat the multi-project workspace root as one repo), re-hydrates memory, unlocks research mode. Full invariant in [AGENTS.md](../AGENTS.md) and `skills/agents/SKILL.md`.

## Tools (`pai_tools` plugin)

| Tool | Purpose | Actions |
|---|---|---|
| `pai_code_intel` | Symbols, call graphs, impact analysis — use **before** reading raw files | `find_code`, `file_api`, `trace_calls`, `find_all`, `repo_map`, `check_freshness` |
| `pai_notebook_ops` | Research vault ops on `research/` | `list_notebooks`, `create_notebook`, `search`, `add_note`, `add_source_url`, `poll_source_status`, `get_source`, `add_source_file`, `ask_notebook`, `get_notebook` |
| `pai_adr_ops` | Living ADRs + symbol drift detection | `create_adr`, `check_drift`, `list_adrs` |
| `pai_docker_ops` | Manage pai-stack containers (audited to `/opt/hermes/data/logs/docker-ops.log`) | `list`, `status`, `logs`, `restart`, `start`, `stop`, `exec` |
| `skill_view` / `skills_list` | Load / discover procedural skills | `name="<skill>"` |

## Skills

Load via `skill_view(name="<name>")` before working on an unknown stack. Files live in `./skills/`, mounted read-only.

Routers/shims: `stack-discovery`, `python`, `docker`, `react`, `nodejs`, `sql`, `planning`, `gitops`, `code-intel`, `research`, `opencode-delegate`, `agents`. Vendored depth: `vercel-react-best-practices`, `vercel-composition-patterns`, `frontend-design`, `supabase-postgres-best-practices`, `senior-backend`, `docker-development`, `web-design-guidelines`, `webapp-testing`, `mcp-builder`, `code-reviewer`, `skill-security-auditor`.

## Memory (Mnemosyne)

Local-first, embedded in Hermes: SQLite (`hermes-data` volume) + ONNX fastembed. Auto-captures turns; prefetches relevant memories; `mnemosyne_recall` / `mnemosyne_remember` / `mnemosyne_sleep` / `mnemosyne_stats` + triple graph (`mnemosyne_triple_add` / `mnemosyne_triple_query`).

## Where Hermes writes

| What | Where |
|---|---|
| Code changes | `<EXECUTION_DIR>/<file>` (after diff confirmation) |
| Planning files | `<EXECUTION_DIR>/.planning/<YYYY-MM-DD-slug>/` (`task_plan.md`, `findings.md`, `progress.md`) |
| Scratch tools | `/opt/data/<tool_name>` |
| Memory / state | `hermes-data` volume (never in workspace) |

For 3+ step tasks Hermes follows planning-with-files: 2-operation rule (2 searches → write `findings.md`), propose-before-writing, 3-strike escalate. Research procedures: [research.md](research.md).
