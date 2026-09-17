# pai-stack

A streamlined AI development stack running four core Docker Compose services: **DeepSeek Harness (DSH)**, **CodeGraph**, **Embeddings**, and **MCP Server**.

All services operate directly on your local workspace directory mounted from the host.

---

## Services

| Service | Port | Description |
|---|---|---|
| **Hermes** | `9119` / `8642`| Primary AI agent gateway + web dashboard (with native Mnemosyne memory). Operating in `/opt/data`. |
| **DeepSeek Harness (DSH)** | `9120` | Secondary autonomous agent frontend (opt-in via `dsh` profile). |
| **Graft** | `20128` | Multi-modal code intelligence engine providing hybrid search (AST symbols + ripgrep text + vector semantics), caller/callee graphs, and impact analysis. |
| **LLM Gateway** | `4000` | Dedicated LiteLLM proxy serving as the single gateway for all model inference, routing, and fallbacks. |
| **MCP Server** | `8000` | Model Context Protocol server exposing bundled development tools and skills to Hermes. |

### Extended Stack (opt-in)

Activate with `make up-all`. Adds a research knowledge base layer. No impact on the base stack.

| Service | Port | Description |
|---|---|---|
| **SurrealDB** | internal only | Database backend for Open Notebook. No host port (avoids conflict with MCP Server on 8000). |
| **Open Notebook** | `8502` (UI), `5055` (API) | Self-hosted research knowledge base. Ingest URLs, PDFs, and text; search and query with AI. Shares the `embeddings` container (no extra RAM for a second model). |

---

## Architecture

```
Host Machine (WORKSPACE_DIR)
 ├── Projects/ & Codebases
 ├── Knowledge Base & Notes
 └── Skills & Tools
      │
      ├── [mount: /opt/data/workspace (rw)]        ──> dsh (Agent workspace)
      ├── [mount: /opt/data/workspace (ro)]        ──> codegraph (Hybrid search: AST + text + semantic)
      │
      ├── dsh queries codegraph (:20128) & mcp-server (:8000)
      └── codegraph generates embeddings via embeddings (:8080)
```

---

## Prerequisites

- **Docker** and **Docker Compose** (v2+)
- **Make**
- A local directory on your host for your projects/knowledge base (e.g. `./workspace` or an existing workspace folder)

---

## Quick Start

1. **Configure Environment**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set:
   - `WORKSPACE_DIR`: Path to your host workspace directory (e.g. `./workspace` or `/path/to/projects`).
     > **Note**: This directory **must exist** on your host before starting. The stack will fail with an error if the directory is missing.
   - `CODEGRAPH_SUBDIR`: (Optional) Subdirectory inside `WORKSPACE_DIR` for CodeGraph to index (leave empty for entire workspace).
   - LLM settings and API keys.

2. **Start the Stack**:
   ```bash
   make up
   ```
   This verifies that `WORKSPACE_DIR` exists on the host and starts all three containers in the background.

3. **Check Status**:
   ```bash
   make status
   ```

4. **View Logs**:
   ```bash
   make logs
   ```

5. **Initial Prompt for Hermes/DSH**:
   The agent's system prompt is configured automatically on boot, but you should prompt the agent to load its operational ground rules on its first turn:
   > "Please read the `skill://agents` resource to load your operational ground rules, then execute your Turn 1 Startup Protocol to identify the project boundaries in this workspace."

---

## Management Commands

| Command | Action |
|---|---|
| `make setup` | Initialize `.env` from `.env.example` and create default workspace folder |
| `make up` | Validate workspace existence and start services in background (supports `ALL=1`, `s=<service>`) |
| `make down` | Stop running services (supports `ALL=1`) |
| `make restart` | Restart services (supports `ALL=1`, `s=<service>`) |
| `make logs` | Tail logs for containers (supports `ALL=1`, `s=<service>`) |
| `make status` | View running containers and health status (supports `ALL=1`, `s=<service>`) |
| `make sync` | Sync LLM models with local & cloud providers and auto-reload gateway |
| `make sync-all` | Sync models and include all cloud provider templates |
| `make build` | Build / rebuild container images (supports `ALL=1`, `s=<service>`) |
| `make clean` | Stop containers and remove persisted volumes (`hermes-data` (used by DSH), `graft-cache`) |
| `make config` | Validate and resolve Docker Compose configuration (supports `ALL=1`) |

### Extended Stack Commands

| Command | Action |
|---|---|
| `make up-all` | Start base stack **+ Open Notebook** (surrealdb + open-notebook; optional `s=<service>`) |
| `make down-all` | Stop base stack + Open Notebook |
| `make restart-all` | Restart all services including Open Notebook (optional `s=<service>`) |
| `make logs-all` | Tail logs for all services including Open Notebook (optional `s=<service>`) |
| `make status-all` | View all containers including Open Notebook (optional `s=<service>`) |
| `make build-all` | Build images for all services (optional `s=<service>`) |
| `make clean-all` | Stop and remove ALL volumes including Open Notebook data (**DESTRUCTIVE**) |
| `make config-all` | Validate and view merged compose config for all services |

---

## Accessing Services

### Base Stack

- **Hermes Web UI**: [http://localhost:9119](http://localhost:9119) (DSH available at `http://localhost:9120` if `dsh` profile enabled)
- **Graft Visualizer**: [http://localhost:20128/viz/](http://localhost:20128/viz/)
- **Graft API**: [http://localhost:20128/search?q=query&type=hybrid](http://localhost:20128/search?q=query&type=hybrid)
- **Embeddings API**: [http://localhost:8088/v1/embeddings](http://localhost:8088/v1/embeddings) (`GET /health`)
- **MCP Server**: [http://localhost:8000/mcp](http://localhost:8000/mcp)

### Extended Stack (`make up-all`)

- **Open Notebook UI**: [http://localhost:8502](http://localhost:8502)
- **Open Notebook API**: [http://localhost:5055](http://localhost:5055) (used by `notebook_ops` MCP tool)
