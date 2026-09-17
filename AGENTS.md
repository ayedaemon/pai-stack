# pai-stack — Agent Context

> Read this file first. It explains what this repo is, how the services interconnect,
> and how any AI agent (Hermes, or otherwise) should work within this environment.

## What this is

Four Docker services that give an AI agent (Hermes) a complete local development environment:
code intelligence, semantic search, read-write workspace access, and procedural skills.

## Services & Ports

| Service | Port | Role |
|---|---|---|
| **hermes** | 9119 / 8642 | AI agent gateway + web dashboard (with native Mnemosyne memory) |
| **graft** | 20128 | Code intelligence: AST + semantic search (via MCP) |
| **mcp-server** | 8000 | MCP server: bundled skills (resources) and tools |
| **llm-gateway** | 4000 | Unified LLM Gateway: LiteLLM proxy (routes, fallbacks, provider credentials) |
| **surrealdb** | 8000 (internal only) | Database for Open Notebook — **opt-in**, only with `make up-all` |
| **open-notebook** | 8502 (UI), 5055 (API) | Research Brain: external knowledge store — **opt-in**, only with `make up-all` |

## Container Mounts

| Host path | Container path | Service | Access |
|---|---|---|---|
| `$WORKSPACE_DIR` | `/opt/data/workspace` | hermes | **read-write** |
| `$WORKSPACE_DIR` | `/opt/data/workspace` | graft | read-only (or read-write for cache) |

Both hermes and graft mount the same workspace path (`/opt/data/workspace`), so path references
are consistent across containers. Graft natively detects file changes (drift) in real-time.
Hermes can also write helper scripts and scratch tools to `/opt/data`.

> Open Notebook and SurrealDB use **only named Docker volumes** (`surreal-data`, `open-notebook-data`).
> They do NOT bind-mount `WORKSPACE_DIR`. This is intentional: writing notebook blobs in the workspace
> would cause constant spurious Graft graph rebuilds and pollute code-search results.

## Service Interconnection

```
hermes ──→ [Mnemosyne: SQLite]  local persistent memory (working/episodic memory, knowledge graph)
hermes ──→ graft:20128          code intelligence via MCP (streamable-http)
hermes ──→ mcp-server:8000      skills + tools via MCP protocol (streamable-http)
hermes ──→ llm-gateway:4000     ONLY gateway for LLM completions & reasoning
graft  ──→ llm-gateway:4000     ONLY gateway for code summarization & deep indexing

── opt-in (make up-all) ──────────────────────────────────────────────────────
open-notebook ──→ surrealdb:8000    database (internal network, no host port)
open-notebook ──→ embeddings:8080   dedicated embedding model server (nomic-embed)
open-notebook ──→ llm-gateway:4000  ONLY gateway for note generation & LLM queries
hermes ──→ mcp-server ──→ notebook_ops ──→ open-notebook:5055   research queries
```

All services use `llm-gateway:4000` (LiteLLM) as their single gateway for model inference.
Hermes does NOT call `embeddings:8080` directly. Open Notebook uses it for vector search.
Hermes does NOT call `open-notebook:5055` directly. `notebook_ops` MCP tool handles it.
Mnemosyne runs embedded inside Hermes using local ONNX fastembed and SQLite (`hermes-data` volume).

## How Hermes Uses Each Service

### Graft — primary retrieval (use before reading raw files)

The main token-efficiency mechanism. Converts "read 200 files" into "query via MCP".

```
graft_find_code        → find implementation details and explanations
graft_file_api         → inspect file method/type signatures without bodies
graft_trace_calls      → inspect callers/callees and blast radius
graft_find_all         → regex search grouped by symbol
graft_repo_map         → high-level repo orientation and hubs
graft_check_freshness  → verify index freshness
```

### MCP Server — procedural knowledge (skills as MCP resources)

Hermes fetches `skill://<name>` before working on any unknown stack or process.
Skills are markdown files baked into the mcp-server image — zero model tokens to load.

| Resource | Purpose |
|---|---|
| `skill://stack-discovery` | Detect stack markers before any codebase work |
| `skill://python` | Python conventions (pyproject.toml, uv, FastAPI, pytest) |
| `skill://docker` | Docker/Compose conventions |
| `skill://react` | React/Next.js conventions |
| `skill://nodejs` | Node.js conventions |
| `skill://postgres` | Postgres conventions |
| `skill://graft` | Graft query procedures and tools reference |
| `skill://planning` | planning-with-files discipline (task_plan.md etc.) |
| `skill://_TEMPLATE` | Template for new custom skills |
| `skill://agents` | Ground rules injected at session start |

#### Tools (MCP tools)

| Tool | Purpose | Allowed actions |
|---|---|---|
| `docker_ops` | Manage pai-stack containers via Docker socket | `list`, `status`, `logs`, `restart`, `start`, `stop`, `exec` |

All container actions are audited to `/app/logs/docker-ops.log` on the persistent `mcp-logs` volume.

### Embeddings — Open Notebook only

Hermes does NOT call the embeddings service directly.
It is primarily used by the `open-notebook` service.

### Mnemosyne — agent memory (decisions, execution outcomes, lessons learned)

Mnemosyne is Hermes's native, local-first agent memory layer. It operates entirely within Hermes
using embedded SQLite (`/opt/hermes/data/mnemosyne/data/mnemosyne.db`) and local ONNX vector embeddings (`fastembed`).

- **Automatic capture**: every turn (decisions, tool calls, user preferences, failure modes) is automatically indexed.
- **Dynamic prompt prefetch**: relevant working memories are fetched and injected before model turns.
- **Recall tools**: `mnemosyne_recall` (hybrid semantic + FTS5 + recency search), `mnemosyne_remember` (explicit fact recording), `mnemosyne_sleep` (episodic consolidation), `mnemosyne_stats`.
- **Knowledge graph**: `mnemosyne_triple_add`, `mnemosyne_triple_query` for relationship traversal.

| Retrieval System | Scope | Storage | Role |
|---|---|---|---|
| **Graft** | Workspace code & files | `/data` on graft-cache | AST symbols, semantic search (via MCP) |
| **Open Notebook** | External knowledge | SurrealDB & Open Notebook volumes | RFCs, API docs, papers, research notes |
| **Mnemosyne** | Agent experience | `/opt/hermes/data/mnemosyne` | Decisions, prior fixes, session continuity, user preferences |

## Startup Protocol: Workspace Understanding & Boundaries

> **CRITICAL INVARIANT**: The host workspace (`$WORKSPACE_DIR` mounted to `/opt/data/workspace`)
> is often a multi-project container holding several independent repositories or projects side-by-side.
> Hermes must never confuse one project with another or treat `/opt/data/workspace` as a monolithic project.

On **Turn 1 of every session**:
1. **Recall Known Boundaries**: Call `mnemosyne_recall(query="workspace projects structure boundaries")` to check previously remembered projects.
2. **Survey Directory Structure**: List `/opt/data/workspace` (depth 1) to identify project subdirectories and identify root markers (`.git/`, `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Makefile`).
3. **Map with Graft**: Call `graft_repo_map` to orient on code hubs and symbol hierarchies. If the stack is unknown, fetch `skill://stack-discovery`.
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
They live in the project, get indexed by Graft, and are searchable in future sessions.

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
5. For code questions: query `graft` tools via Hermes directly (e.g. `graft_find_code`, `graft_trace_calls`)
