# pai-stack

A streamlined AI development stack running four core Docker Compose services: **Hermes**, **CodeGraph**, **Embeddings**, and **MCP Server**.

All services operate directly on your local workspace directory mounted from the host.

---

## Services

| Service | Port | Description |
|---|---|---|
| **Hermes** | `9119`, `8642` | Autonomous AI agent gateway, dashboard, and knowledge base indexer. Operating in `/opt/data`. |
| **CodeGraph** | `20128` | Multi-modal code intelligence engine providing hybrid search (AST symbols + ripgrep text + vector semantics), caller/callee graphs, and impact analysis. |
| **Embeddings** | `8088` | Lightweight FastEmbed ONNX server (`nomic-embed-text-v1.5`) providing OpenAI-compatible embeddings for CodeGraph and Hermes KB. |
| **MCP Server** | `8000` | Model Context Protocol server exposing bundled development tools and skills to Hermes. |

---

## Architecture

```
Host Machine (WORKSPACE_DIR)
 ├── Projects/ & Codebases
 ├── Knowledge Base & Notes
 └── Skills & Tools
      │
      ├── [mount: /opt/data/workspace (rw)]        ──> hermes (Knowledge base & agent workspace)
      ├── [mount: /opt/data/workspace (ro)]        ──> codegraph (Hybrid search: AST + text + semantic)
      │
      ├── hermes queries codegraph (:20128) & mcp-server (:8000)
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

---

## Management Commands

| Command | Action |
|---|---|
| `make up` | Validate workspace existence and start services in background |
| `make down` | Stop running services |
| `make restart` | Restart all services |
| `make logs` | Tail logs for all containers |
| `make status` | View running containers and health status |
| `make build` | Build / rebuild container images |
| `make clean` | Stop containers and remove persisted volumes (`hermes-data`, `codegraph-data`) |

---

## Accessing Services

- **Hermes Gateway & Dashboard**: [http://localhost:9119](http://localhost:9119) (or port `8642`)
- **CodeGraph Visualizer**: [http://localhost:20128/viz/](http://localhost:20128/viz/)
- **CodeGraph API**: [http://localhost:20128/search?q=query&type=hybrid](http://localhost:20128/search?q=query&type=hybrid)
- **Embeddings API**: [http://localhost:8088/v1/embeddings](http://localhost:8088/v1/embeddings) (`GET /health`)
- **MCP Server**: [http://localhost:8000/mcp](http://localhost:8000/mcp)
