# pai-stack — Agent Context

> Read this file first. It explains what this repo is, how the services interconnect,
> and how any AI agent (Hermes, or otherwise) should work within this environment.

## What this is

Three core Docker services that give an AI agent (Hermes) a complete local development environment:
code intelligence, semantic search, read-write workspace access, and procedural skills.

## Services & Ports

| Service | Port | Role |
|---|---|---|
| **hermes** | 9119 / 8642 | AI agent gateway + web dashboard (with native Mnemosyne memory) |
| **mcp-server** | 8000 | MCP server: code intelligence, bundled skills, tools, and native Research Brain |
| **llm-gateway** | 4000 | Unified LLM Gateway: LiteLLM proxy (routes, fallbacks, provider credentials) |

## Container Mounts

| Host path | Container path | Service | Access |
|---|---|---|---|
| `$WORKSPACE_DIR` | `/opt/data/workspace` | hermes | **read-write** |
| `$WORKSPACE_DIR` | `/opt/data/workspace` | mcp-server | **read-write** (for `research/` vault + code intelligence indexing) |

All core services mount the same workspace path (`/opt/data/workspace`), so path references
are consistent across containers. Code intelligence indexes the entire workspace and detects file changes in real-time.
Hermes writes helper scripts and scratch tools to `/opt/data`.

> Research Brain stores all notes and sources as human-readable Markdown with YAML frontmatter
> directly in `$WORKSPACE_DIR/research/<notebook-name>/`. There are no external databases (SurrealDB)
> or dedicated embedding containers needed, saving ~2.3 GB of RAM and ensuring instant IDE search.

## Service Interconnection

```
hermes ──→ [Mnemosyne: SQLite]  local persistent memory (working/episodic memory, knowledge graph)
hermes ──→ mcp-server:8000      code intelligence + skills + tools via MCP protocol (streamable-http)
hermes ──→ llm-gateway:4000     ONLY gateway for LLM completions & reasoning
mcp-server (notebook_ops) ──→ /opt/data/workspace/research/ (file vault)
mcp-server (ask_notebook) ──→ llm-gateway:4000 (synthesis)
```

All services use `llm-gateway:4000` (LiteLLM) as their single gateway for model inference.
`notebook_ops` runs natively inside `mcp-server` operating directly on Markdown files in the workspace.
Mnemosyne runs embedded inside Hermes using local ONNX fastembed and SQLite (`hermes-data` volume).

## How Hermes Uses Each Service

### Code Intelligence — primary retrieval (use before reading raw files)

The main token-efficiency mechanism. Converts "read 200 files" into "query via MCP".

```
code_intel(find_code)       → find implementation details and explanations
code_intel(file_api)        → inspect file method/type signatures without bodies
code_intel(trace_calls)     → inspect callers/callees and blast radius
code_intel(find_all)        → regex search grouped by symbol
code_intel(repo_map)        → high-level repo orientation and hubs
code_intel(check_freshness) → verify index freshness
```

### MCP Server — procedural knowledge (skills as MCP resources)

Hermes fetches `skill://<name>` via `mcp__pai_tools__read_resource(uri="skill://<name>")` before working on any unknown stack or process (or lists them via `mcp__pai_tools__list_resources()`).
Skills are markdown files baked into the mcp-server image — zero model tokens to load.

| Resource | Purpose |
|---|---|
| `skill://stack-discovery` | Detect stack markers before any codebase work |
| `skill://python` | Python conventions (pyproject.toml, uv, FastAPI, pytest) |
| `skill://docker` | Docker/Compose conventions |
| `skill://react` | React/Next.js conventions |
| `skill://nodejs` | Node.js conventions |
| `skill://sql` | SQL/Postgres conventions |
| `skill://code-intel` | Code intelligence query procedures and tools reference |
| `skill://planning` | planning-with-files discipline (task_plan.md etc.) |
| `skill://agents` | Ground rules injected at session start |

#### Tools (MCP tools)

| Tool | Purpose | Allowed actions |
|---|---|---|
| `mcp__pai_tools__docker_ops` | Manage pai-stack containers via Docker socket | `list`, `status`, `logs`, `restart`, `start`, `stop`, `exec` |
| `mcp__pai_tools__notebook_ops` | Query and manage Research Brain (native file vault in `research/`) | `list_notebooks`, `create_notebook`, `search`, `add_note`, `add_source_url`, `poll_source_status`, `get_source`, `add_source_file`, `ask_notebook`, `get_notebook` |
| `mcp__pai_tools__adr_ops` | Living ADR creation & code symbol drift detection | `create_adr`, `check_drift`, `list_adrs` |
| `mcp__pai_tools__code_intel` | Code intelligence: symbol search, call graphs, impact analysis | `find_code`, `file_api`, `trace_calls`, `find_all`, `repo_map`, `check_freshness` |
| `mcp__pai_tools__read_resource` | Fetch procedural skills or template resources by URI | `uri="skill://<name>"` |
| `mcp__pai_tools__list_resources` | Discover all available skills and templates on mcp-server | (none) |

All container actions are audited to `/app/logs/docker-ops.log` on the persistent `mcp-logs` volume.

### Mnemosyne — agent memory (decisions, execution outcomes, lessons learned)

Mnemosyne is Hermes's native, local-first agent memory layer. It operates entirely within Hermes
using embedded SQLite (`/opt/hermes/data/mnemosyne/data/mnemosyne.db`) and local ONNX vector embeddings (`fastembed`).

- **Automatic capture**: every turn (decisions, tool calls, user preferences, failure modes) is automatically indexed.
- **Dynamic prompt prefetch**: relevant working memories are fetched and injected before model turns.
- **Recall tools**: `mnemosyne_recall` (hybrid semantic + FTS5 + recency search), `mnemosyne_remember` (explicit fact recording), `mnemosyne_sleep` (episodic consolidation), `mnemosyne_stats`.
- **Knowledge graph**: `mnemosyne_triple_add`, `mnemosyne_triple_query` for relationship traversal.

| Retrieval System | Scope | Storage | Role |
|---|---|---|---|
| **Code Intelligence** | Workspace code & files | `/data` on mcp-server | AST symbols, semantic search (via MCP) |
| **Research Brain** | External knowledge & notes | `$WORKSPACE_DIR/research/` | RFCs, API docs, papers, research notes in Markdown + code intelligence search |
| **Mnemosyne** | Agent experience | `/opt/hermes/data/mnemosyne` | Decisions, prior fixes, session continuity, user preferences |

## Startup Protocol: Workspace Understanding & Boundaries

> **CRITICAL INVARIANT**: The host workspace (`$WORKSPACE_DIR` mounted to `/opt/data/workspace`)
> is often a multi-project container holding several independent repositories or projects side-by-side.
> Hermes must never confuse one project with another or treat `/opt/data/workspace` as a monolithic project.

On **Turn 1 of every session**:
1. **Recall Known Boundaries**: Call `mnemosyne_recall(query="workspace projects structure boundaries")` to check previously remembered projects.
2. **Survey Directory Structure**: List `/opt/data/workspace` (depth 1) to identify project subdirectories and identify root markers (`.git/`, `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Makefile`).
3. **Map with Code Intelligence**: Call `code_intel(repo_map)` to orient on code hubs and symbol hierarchies. If the stack is unknown, fetch `skill://stack-discovery`.
4. **Persist Boundaries**: Record discovered project boundaries using `mnemosyne_remember(content="Workspace Project: '<name>' at /opt/data/workspace/<name>...")`.
5. **Enforce Boundary Isolation**: Strictly avoid cross-project contamination of files, git branches, or planning files.

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
They live in the project, get indexed by code_intel, and are searchable in future sessions.

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

See `skill://planning` for the full discipline.

## Key Config Files

| File | Purpose |
|---|---|
| [`hermes/config.yaml`](hermes/config.yaml) | System prompt, model providers, MCP config, knowledgebase |
| [`docker-compose.yaml`](docker-compose.yaml) | All service definitions, mounts, resource limits |
| [`mcp-server/server.py`](mcp-server/server.py) | MCP server: auto-discovers and registers skills and tools |
| [`mcp-server/skills/`](mcp-server/skills/) | Bundled SKILL.md files (one per skill) |
| [`mcp-server/skills/agents/SKILL.md`](mcp-server/skills/agents/SKILL.md) | Ground rules injected into Hermes context |
| [`.env.example`](.env.example) | Template for `WORKSPACE_DIR`, LLM config, API keys |

## Quick Start for Agents

1. Read this file (`AGENTS.md` at repo root)
2. Read [`mcp-server/skills/agents/SKILL.md`](mcp-server/skills/agents/SKILL.md) for operational ground rules
3. Read [`hermes/config.yaml`](hermes/config.yaml) for the full system prompt
4. Check [`docker-compose.yaml`](docker-compose.yaml) for current mount paths and port bindings
5. For code questions: query code intelligence via Hermes directly (e.g. `mcp__pai_tools__code_intel(action="find_code")`, `mcp__pai_tools__code_intel(action="trace_calls")`)
