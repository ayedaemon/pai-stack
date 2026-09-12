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
| **codegraph** | 20128 | Code intelligence: AST (Tree-sitter) + ripgrep full-text + semantic vector search |
| **embeddings** | 8080 (internal), 8088 (host) | Embedding model server (nomic-embed-text-v1.5, OpenAI-compatible API) |
| **mcp-server** | 8000 | MCP server: bundled skills (resources) and tools |
| **surrealdb** | 8000 (internal only) | Database for Open Notebook — **opt-in**, only with `make up-all` |
| **open-notebook** | 8502 (UI), 5055 (API) | Research Brain: external knowledge store — **opt-in**, only with `make up-all` |

## Container Mounts

| Host path | Container path | Service | Access |
|---|---|---|---|
| `$WORKSPACE_DIR` | `/opt/data/workspace` | hermes | **read-write** |
| `$WORKSPACE_DIR/$CODEGRAPH_SUBDIR` | `/opt/data/workspace` | codegraph | read-only |

Both hermes and codegraph mount the same workspace path (`/opt/data/workspace`), so path references
are consistent across containers. Hermes writes files → codegraph indexes them on next reindex.
Hermes can also write helper scripts and scratch tools to `/opt/data`.

> Open Notebook and SurrealDB use **only named Docker volumes** (`surreal-data`, `open-notebook-data`).
> They do NOT bind-mount `WORKSPACE_DIR`. This is intentional: Hermes's `fs-notifier.sh` watches
> `WORKSPACE_DIR` and triggers CodeGraph reindexes on changes. Notebook blobs in the workspace
> would cause constant spurious reindexes and pollute code-search results.

## Service Interconnection

```
hermes ──→ [Mnemosyne: SQLite]  local persistent memory (working/episodic memory, knowledge graph)
hermes ──→ codegraph:20128      code intelligence queries (symbols, search, impact, map)
hermes ──→ mcp-server:8000      skills + tools via MCP protocol (streamable-http)
codegraph ──→ embeddings:8080   vector embeddings for semantic search

── opt-in (make up-all) ──────────────────────────────────────────────────────
open-notebook ──→ surrealdb:8000    database (internal network, no host port)
open-notebook ──→ embeddings:8080   shared embedding model (same as CodeGraph)
hermes ──→ mcp-server ──→ notebook_ops ──→ open-notebook:5055   research queries
```

Hermes does NOT call `embeddings:8080` directly. CodeGraph handles semantic search internally.
Hermes does NOT call `open-notebook:5055` directly. `notebook_ops` MCP tool handles it.
Mnemosyne runs embedded inside Hermes using local ONNX fastembed and SQLite (`hermes-data` volume).

## How Hermes Uses Each Service

### CodeGraph — primary retrieval (use before reading raw files)

The main token-efficiency mechanism. Converts "read 200 files" into "query 2 endpoints".

```
GET /search?q=<term>&type=hybrid   → AST symbols + ripgrep text + semantic (one call)
GET /search?q=<term>&type=semantic → pure semantic/doc/notes search
GET /symbols/<name>                → definition + callers + callees in one call
GET /impact/<path>                 → blast radius of a file change
GET /map                           → most-connected files overview
POST /reindex                      → trigger reindex after writing files
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
| `skill://codegraph` | CodeGraph query procedures |
| `skill://planning` | planning-with-files discipline (task_plan.md etc.) |
| `skill://_TEMPLATE` | Template for new custom skills |
| `skill://agents` | Ground rules injected at session start |

#### Tools (MCP tools)

| Tool | Purpose | Allowed actions |
|---|---|---|
| `docker_ops` | Manage pai-stack containers via Docker socket | `list`, `status`, `logs`, `restart`, `start`, `stop`, `exec` |

All container actions are audited to `/app/logs/docker-ops.log` on the persistent `mcp-logs` volume.

### Embeddings — indirect (via CodeGraph only)

Hermes does NOT call the embeddings service directly.
CodeGraph uses it for `/search?type=semantic` and `/search?type=hybrid`.
Semantic search over workspace files is available through CodeGraph at no extra cost.

### Mnemosyne — agent memory (decisions, execution outcomes, lessons learned)

Mnemosyne is Hermes's native, local-first agent memory layer. It operates entirely within Hermes
using embedded SQLite (`/opt/hermes/data/mnemosyne/data/mnemosyne.db`) and local ONNX vector embeddings (`fastembed`).

- **Automatic capture**: every turn (decisions, tool calls, user preferences, failure modes) is automatically indexed.
- **Dynamic prompt prefetch**: relevant working memories are fetched and injected before model turns.
- **Recall tools**: `mnemosyne_recall` (hybrid semantic + FTS5 + recency search), `mnemosyne_remember` (explicit fact recording), `mnemosyne_sleep` (episodic consolidation), `mnemosyne_stats`.
- **Knowledge graph**: `mnemosyne_triple_add`, `mnemosyne_triple_query` for relationship traversal.

| Retrieval System | Scope | Storage | Role |
|---|---|---|---|
| **CodeGraph** | Workspace code & files | `/data` on codegraph-data | AST symbols, full-text grep, code embeddings |
| **Open Notebook** | External knowledge | SurrealDB & Open Notebook volumes | RFCs, API docs, papers, research notes |
| **Mnemosyne** | Agent experience | `/opt/hermes/data/mnemosyne` | Decisions, prior fixes, session continuity, user preferences |

## Where Hermes Writes

| What | Where | When |
|---|---|---|
| Code changes | `/opt/data/workspace/<project>/<file>` | After user confirms the proposed diff |
| Planning files | `/opt/data/workspace/<project>/.planning/<slug>/` | When starting a complex task |
| Helper scripts & scratch tools | `/opt/data/<tool_name>` | For internal Hermes operations |
| Agent memory (Mnemosyne DB) | `hermes-data` volume (`/opt/hermes/data/mnemosyne/data/`) | Post-turn capture & explicit remember calls |
| App state (DB, sessions) | `hermes-data` Docker volume | Automatically — never touches workspace |

Planning files (`task_plan.md`, `findings.md`, `progress.md`) are developer artifacts.
They live in the project, get indexed by CodeGraph, and are searchable in future sessions.

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
| [`mcp-server/kb/AGENTS.md`](mcp-server/kb/AGENTS.md) | Ground rules injected into Hermes context |
| [`.env.example`](.env.example) | Template for `WORKSPACE_DIR`, LLM config, API keys |

## Quick Start for Agents

1. Read this file (`AGENTS.md` at repo root)
2. Read [`mcp-server/kb/AGENTS.md`](mcp-server/kb/AGENTS.md) for operational ground rules
3. Read [`hermes/config.yaml`](hermes/config.yaml) for the full system prompt
4. Check [`docker-compose.yaml`](docker-compose.yaml) for current mount paths and port bindings
5. For code questions: query `http://codegraph:20128/search?type=hybrid` (if running inside stack) or inspect `codegraph/server.js` for the API surface
