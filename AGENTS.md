# pai-stack — Agent Context

> Read this file first. It explains what this repo is, how the services interconnect,
> and how any AI agent (Hermes, or otherwise) should work within this environment.

## What this is

Two core Docker services that give an AI agent (Hermes) a complete local development environment:
in-process code intelligence, semantic search, read-write workspace access, and native procedural skills —
no sidecar containers needed for tools.

## Services & Ports

| Service | Port | Role |
|---|---|---|
| **hermes** | 9119 / 8642 | AI agent gateway + web dashboard (native Mnemosyne memory, native `pai_*` tools, native skills) |
| **llm-gateway** | 4000 | Unified LLM Gateway: LiteLLM proxy (routes, fallbacks, provider credentials) |

## Container Mounts

| Host path | Container path | Service | Access |
|---|---|---|---|
| `$WORKSPACE_DIR` | `/opt/data/workspace` | hermes | **read-write** (`research/` vault + code intelligence indexing) |

Hermes mounts the workspace at `/opt/data/workspace` and runs code intelligence
in-process (tree-sitter index over the entire workspace, file changes detected
in real-time). Hermes writes helper scripts and scratch tools to `/opt/data`.

> Research Brain is a root-level wiki (SCHEMA.md, index.md, log.md, raw/, entities/, concepts/, comparisons/, queries/)
> at `$WORKSPACE_DIR/${RESEARCH_SUBDIR:-research}` (container `$RESEARCH_DIR == $WIKI_PATH`), with legacy
> `<notebook-name>/{notes/,sources/}` vaults kept readable alongside. There are no external databases (SurrealDB)
> or dedicated embedding containers needed, saving ~2.3 GB of RAM and ensuring instant IDE search.

## Service Interconnection

```
hermes ──→ [Mnemosyne: SQLite]  local persistent memory (working/episodic memory, knowledge graph)
hermes ──→ [pai_tools plugin]   native tools: pai_code_intel, pai_notebook_ops, pai_adr_ops, pai_docker_ops
hermes ──→ [skills: /opt/pai/skills]  native procedural skills via skills_list / skill_view
hermes ──→ llm-gateway:4000     ONLY gateway for LLM completions & reasoning
hermes (pai_notebook_ops) ──→ /opt/data/workspace/research/ (file vault)
hermes (ask_notebook) ──→ llm-gateway:4000 (synthesis)
```

All model inference routes through `llm-gateway:4000` (LiteLLM).
`pai_notebook_ops` runs in-process in Hermes, operating directly on Markdown files in the workspace.

### LLM routing posture (gateway-only)
- Hermes declares exactly one provider (`gateway`); model selection, fallbacks, and
  provider credentials live in `llm-gateway/config.yaml` (+ `scripts/sync-models.py`
  templates). Never add direct provider keys, auxiliary providers, or Hermes-level
  fallbacks — Models.dev catalog reads are metadata-only and fine.
- Known exceptions: `opencode-delegate` calls Zen free models directly (keyless,
  documented in its skill); Langfuse receives traces (it IS the audit trail).
- Secrets caveat: provider keys are absent from the hermes container *environment*,
  but `.env` lives inside the mounted workspace — file-capable tools can still read
  it. `*.env` reads are hard-denied for delegates; treat Hermes-side reads as auditable.
- Gateway image is digest-pinned (see `docker-compose.yaml`); routes use mistral/
  provider mapping with per-model `drop_params` so reasoning params are stripped
  pre-flight (our LiteLLM synthesizes a conflicting nested object otherwise — Sep-25
  incident). Verify any routing change with a pair-shape probe before committing.
Mnemosyne runs embedded inside Hermes using local ONNX fastembed and SQLite (`hermes-data` volume).

## How Hermes Uses Each Service

### Code Intelligence — primary retrieval (use before reading raw files)

The main token-efficiency mechanism. Converts "read 200 files" into "native tool query".

```
pai_code_intel(find_code)       → find implementation details and explanations
pai_code_intel(file_api)        → inspect file method/type signatures without bodies
pai_code_intel(trace_calls)     → inspect callers/callees and blast radius
pai_code_intel(find_all)        → regex search grouped by symbol
pai_code_intel(repo_map)        → high-level repo orientation and hubs
pai_code_intel(check_freshness) → verify index freshness
```

### Skills — procedural knowledge (native Hermes skills)

Hermes loads skill `<name>` via `skill_view(name="<name>")` before working on any unknown stack or process (or lists them via `skills_list()`).
Skills are markdown files in `./skills/`, mounted read-only into Hermes via `skills.external_dirs` — zero model tokens to load.

| Skill | Purpose |
|---|---|
| `stack-discovery` | Detect stack markers before any codebase work |
| `python` | Python discovery router (uv-run) → `senior-backend` for authoring |
| `docker` | Docker discovery router → `docker-development` (validators advisory-only) |
| `react` | React discovery router → `vercel-react-best-practices` et al. |
| `nodejs` | Node.js discovery → `senior-backend` for backend authoring |
| `sql` | DB discovery router → `supabase-postgres-best-practices` for depth |
| `planning` | Planning router → `writing-plans` + `executing-plans` (superpowers plugin) |
| `system-design` | System design methodology, capacity planning, and trade-off matrices |
| `gitops` | Git safety router → `using-git-worktrees` et al. (superpowers plugin) |
| `vercel-react-best-practices` / `vercel-composition-patterns` / `frontend-design` | Vendored React/perf/design depth (MIT/MIT/Apache-2.0) |
| `supabase-postgres-best-practices` / `senior-backend` / `docker-development` | Vendored Postgres/backend/Docker depth + scripts (MIT) |
| `web-design-guidelines` / `webapp-testing` / `mcp-builder` | Vendored UI-audit / browser-testing / MCP scaffolding (MIT/Apache-2.0) |
| `code-reviewer` / `skill-security-auditor` | Vendored review rubrics + skill supply-chain gate (MIT) |
| `code-intel` | Code intelligence query procedures and tools reference |
| `mermaid` | Mermaid diagram authoring guide (type selection, syntax safety, C4 abstraction protocol) |
| `research` | Root-level wiki (SCHEMA/index/log, ingest/query/lint) — load for wiki/kb/notes tasks |
| `opencode-delegate` | Keyless OpenCode delegation (background+poll, branch review) — load for implementation handoffs |
| `agents` | Ground rules injected at session start |

#### Tools (native `pai` toolset, `pai_tools` plugin)

| Tool | Purpose | Allowed actions |
|---|---|---|
| `pai_docker_ops` | Manage pai-stack containers via Docker socket | `list`, `status`, `logs`, `restart`, `start`, `stop`, `exec` |
| `pai_notebook_ops` | Query and manage Research Brain (native file vault in `research/`) | `list_notebooks`, `create_notebook`, `search`, `add_note`, `add_source_url`, `poll_source_status`, `get_source`, `add_source_file`, `ask_notebook`, `get_notebook` |
| `pai_adr_ops` | Living ADR creation & code symbol drift detection | `create_adr`, `check_drift`, `list_adrs` |
| `pai_code_intel` | Code intelligence: symbol search, call graphs, impact analysis | `find_code`, `file_api`, `trace_calls`, `find_all`, `repo_map`, `check_freshness` |
| `skill_view` | Load a procedural skill by name | `name="<skill>"` |
| `skills_list` | Discover all available native skills | (none) |

All container actions are audited to `/opt/hermes/data/logs/docker-ops.log` on the persistent `hermes-data` volume.

### Mnemosyne — agent memory (decisions, execution outcomes, lessons learned)

Mnemosyne is Hermes's native, local-first agent memory layer. It operates entirely within Hermes
using embedded SQLite (`/opt/hermes/data/mnemosyne/data/mnemosyne.db`) and local ONNX vector embeddings (`fastembed`).

- **Automatic capture**: every turn (decisions, tool calls, user preferences, failure modes) is automatically indexed.
- **Dynamic prompt prefetch**: relevant working memories are fetched and injected before model turns.
- **Recall tools**: `mnemosyne_recall` (hybrid semantic + FTS5 + recency search), `mnemosyne_remember` (explicit fact recording), `mnemosyne_sleep` (episodic consolidation), `mnemosyne_stats`.
- **Knowledge graph**: `mnemosyne_triple_add`, `mnemosyne_triple_query` for relationship traversal.

| Retrieval System | Scope | Storage | Role |
|---|---|---|---|
| **Code Intelligence** | Workspace code & files | In-process tree-sitter index in hermes | AST symbols, semantic search (native tool) |
| **Research Brain** | External knowledge & notes | `$WORKSPACE_DIR/research/` | RFCs, API docs, papers, research notes in Markdown + code intelligence search |
| **Mnemosyne** | Agent experience | `/opt/hermes/data/mnemosyne` | Decisions, prior fixes, session continuity, user preferences |

## Startup Protocol: Workspace Understanding & Boundaries

> **CRITICAL INVARIANT**: The host workspace (`$WORKSPACE_DIR` mounted to `/opt/data/workspace`)
> is often a multi-project container holding several independent repositories or projects side-by-side.
> Hermes must never confuse one project with another or treat `/opt/data/workspace` as a monolithic project.

On **Turn 1 of every session**:
1. **Discover skills**: Call `skills_list()` to confirm `research` and other skills are available.
2. **Recall Known Boundaries + services (parallel)**: Call `mnemosyne_recall(query="workspace projects structure boundaries")` and `pai_docker_ops(action="list")`.
3. **Survey Directory Structure**: List `/opt/data/workspace` (depth 1) to identify project subdirectories and identify root markers (`.git/`, `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Makefile`).
4. **Map with Code Intelligence**: Call `code_intel(repo_map)` to orient on code hubs and symbol hierarchies. If the stack is unknown, load the `stack-discovery` skill first.
5. **Orient on wiki (IFF research task OR `$RESEARCH_DIR/SCHEMA.md` exists)**: Load `skill_view(name="research")`, then read `SCHEMA.md` + `index.md` + `log.md` tail-20 only (index-first, top-3 pages max).
6. **Persist Boundaries**: Record discovered project boundaries using `mnemosyne_remember(content="Workspace Project: '<name>' at /opt/data/workspace/<name>...")`.
7. **Enforce Boundary Isolation**: Strictly avoid cross-project contamination of files, git branches, or planning files.

## Execution Directory Invariant

Hermes must strictly isolate its operations to a single project execution directory:
1. **Declare `EXECUTION_DIR` on Turn 1**: Hermes explicitly chooses `EXECUTION_DIR = /opt/data/workspace/<project>` (or `/opt/data/workspace` only if the workspace root is confirmed to be a single repo). Announce this to the user.
2. **Strict Persistence Throughout Session**:
   - **Terminal Commands**: ALWAYS run within or prefix with `cd <EXECUTION_DIR> && <cmd>`. Never run build/test/git commands in `/opt/data/workspace` root.
   - **Planning Artifacts**: Write exclusively to `<EXECUTION_DIR>/.planning/<YYYY-MM-DD-slug>/`.
   - **Code Changes**: Anchor all edits inside `<EXECUTION_DIR>`.

## Where Hermes Writes

| What | Where | When |
|---|---|---|
| Code changes | `<EXECUTION_DIR>/<file>` | After user confirms the proposed diff |
| Planning files | `<EXECUTION_DIR>/.planning/<slug>/` | When starting a complex task |
| Helper scripts & scratch tools | `/opt/data/<tool_name>` | For internal Hermes operations |
| Agent memory (Mnemosyne DB) | `hermes-data` volume (`/opt/hermes/data/mnemosyne/data/`) | Post-turn capture & explicit remember calls |
| App state (DB, sessions) | `hermes-data` Docker volume | Automatically — never touches workspace |

Planning files (`task_plan.md`, `findings.md`, `progress.md`) are developer artifacts.
They live in the project, get indexed by code intelligence, and are searchable in future sessions.

## Planning Discipline (planning-with-files)

For any task with 3+ steps, research, or multi-file changes, Hermes creates:

```
/opt/data/workspace/<project>/.planning/<YYYY-MM-DD-slug>/
  task_plan.md   — phases, current status, decisions, next step
  findings.md    — discoveries: symbols, blast radius, root causes, key facts
  progress.md    — session log: what ran, errors, what was written
```

Key rules:
- **2-operation rule**: after every 2 search/read operations → write findings to `findings.md`
- **Propose before writing**: show diff, wait for user confirmation, then write
- **3-strike protocol**: attempt 1 (diagnose) → attempt 2 (different approach) → attempt 3 (rethink) → escalate

See the `planning` skill for the full discipline.

## Key Config Files

| File | Purpose |
|---|---|
| [`hermes/config.yaml`](hermes/config.yaml) | System prompt, model providers, skills, knowledgebase |
| [`docker-compose.yaml`](docker-compose.yaml) | All service definitions, mounts, resource limits |
| [`hermes/plugins/pai_tools/`](hermes/plugins/pai_tools/) | Native Hermes tools: `pai_code_intel`, `pai_notebook_ops`, `pai_adr_ops`, `pai_docker_ops` |
| [`skills/`](skills/) | Bundled SKILL.md files (one per skill, mounted into Hermes) |
| [`skills/agents/SKILL.md`](skills/agents/SKILL.md) | Ground rules injected into Hermes context |
| [`.env.example`](.env.example) | Template for `WORKSPACE_DIR`, LLM config, API keys |

## Quick Start for Agents

1. Read this file (`AGENTS.md` at repo root)
2. Read [`skills/agents/SKILL.md`](skills/agents/SKILL.md) for operational ground rules
3. Read [`hermes/config.yaml`](hermes/config.yaml) for the full system prompt
4. Check [`docker-compose.yaml`](docker-compose.yaml) for current mount paths and port bindings
5. For code questions: query code intelligence via Hermes directly (e.g. `pai_code_intel(action="find_code")`, `pai_code_intel(action="trace_calls")`)


## System Architecture Maintenance Protocol

**CRITICAL RULE:** This project relies on a living, highly accurate Mermaid system design diagram located in `docs/architecture.md` to onboard users and track data flow. 

Whenever you modify the project's structural architecture (e.g., adding a new module, database table, API route, service, or altering core data flows), you **MUST** update the Mermaid diagram in `docs/architecture.md` before completing the task. Always load `skill_view(name="mermaid")` first for syntax rules and abstraction depth protocol.

### Diagram Requirements:
1. **Format:** Use a Mermaid `graph TD` or `graph LR` flowchart. 
2. **Abstraction Level:** Keep it high-level. Map components, services, databases, and core interactions. Do not map individual functions, classes, or files unless they represent an entire service.
3. **Interactive Linking:** You must use Mermaid's `click` syntax to make nodes clickable. Link every major node directly to its corresponding detailed documentation file or core source code directory so users can drill down.
4. **Validation:** Ensure the Mermaid syntax is strictly valid and uses proper escaping for special characters.
