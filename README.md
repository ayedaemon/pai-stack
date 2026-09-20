# pai-stack

A streamlined AI development stack running four core Docker Compose services: **Hermes** (AI Agent Gateway), **Graft** (Code Intelligence), **LLM Gateway** (LiteLLM Proxy), and **MCP Server** (Tools & Skills). Extended with **Open Notebook** (Research Brain) and **SurrealDB** via opt-in overlay.

All services operate directly on your local workspace directory mounted from the host.

---

## Services

| Service | Port | Description |
|---|---|---|
| **Hermes** | `9119` / `8642` | Primary AI agent gateway + web dashboard (with native Mnemosyne memory). Operating in `/opt/data`. |
| **Graft** | `20128` | Multi-modal code intelligence engine: hybrid search (AST symbols + ripgrep text + vector semantics), caller/callee graphs, impact analysis, drift detection. |
| **LLM Gateway** | `4000` | Dedicated LiteLLM proxy — single gateway for all model inference, routing, fallbacks, and provider credentials. |
| **MCP Server** | `8000` | Model Context Protocol server exposing bundled development tools (`docker_ops`, `notebook_ops`) and procedural skills to Hermes. |

### Extended Stack (opt-in via `make up-all`)

Activates a research knowledge base layer. No impact on the base stack.

| Service | Port | Description |
|---|---|---|
| **SurrealDB** | internal only | Database backend for Open Notebook. No host port (avoids conflict with MCP Server on 8000). |
| **Open Notebook** | `8502` (UI), `5055` (API) | Self-hosted research knowledge base. Ingest URLs, PDFs, local files; semantic search & grounded RAG. Shares the `embeddings` container (no extra RAM). |

---

## Autonomous Research Agent Capabilities

When running `make up-all`, Hermes becomes an **autonomous empirical research agent** with a "Tri-Brain" architecture:

### 🧠 Tri-Brain Architecture

| Brain | Service | Capability |
|---|---|---|
| **Code Brain** | Graft | AST symbols, semantic search, call graphs, file APIs, drift detection |
| **Research Brain** | File Vault | External knowledge: RFCs, papers, API docs, web articles, Markdown notes |
| **Memory Brain** | Mnemosyne | Episodic memory, decisions, prior fixes, user preferences, knowledge graph triples |

### 🔗 Cross-Brain Synthesis (Symbolic Research Anchors)

- **Anchor syntax**: `@symbol:path/to/file.ext:SymbolName` embedded in all research notes
- **Mnemosyne triples**: Link notebook notes → code symbols → decisions
- **Reverse lookup**: Before new research, query Mnemosyne for existing notes on a symbol
- **Native file storage**: Notes saved to `research/<notebook>/notes/` → indexed by Graft → searchable in IDE & code search

### 🔬 Empirical Lab Notebook Engine

When documentation is ambiguous, Hermes runs **micro-probes** in `/opt/data/probes/`:

```
Hypothesis → Micro-script (Python/Shell) → Execute (30s/256MB guardrails) → Evidence Note → Open Notebook
```

- Evidence notes prefixed `EVIDENCE:` with status `supported|refuted|inconclusive`
- Always include `@symbol:` anchors to code under test
- Reproducible: probe scripts stored alongside results

### 🌳 Deep Inquiry Trees & Living ADRs

Complex questions decomposed into **4 mandatory perspectives**:

| Perspective | Focus |
|---|---|
| Systems Architecture | Components, data flow, boundaries, scaling |
| Security & Threats | Attack surface, trust boundaries, data exposure |
| Developer Ergonomics | API design, debugging, onboarding, migration |
| Failure Modes | Timeouts, partial degradation, cascade, recovery |

**Dialectical inquiry**: Mandatory search for counterpoints (GitHub issues, anti-patterns, version gotchas, incident reports).

**Living ADRs (L-ADRs)**: Stored in `<EXECUTION_DIR>/.planning/research/ADR-XXX.md` with:
- YAML frontmatter (status, symbols, supersession chain)
- Symbol hashes for drift detection (`@symbol:path:Symbol#sha256:...`)
- Dialectical record, validation probes, review triggers
- Lifecycle: `proposed` → `accepted` → `superseded`/`deprecated`

### 🤖 Async Multi-Agent Delegation (Kanban Research Swarms)

Hermes orchestrates **specialized workers** via Kanban:

| Worker | Role | Model Config |
|---|---|---|
| **Researcher** | Deep-dive, ingest sources, run probes, produce evidence notes | 8k tokens, temp 0.3 |
| **Synthesizer** | Consolidate evidence, surface counterpoints, produce synthesis | 16k tokens, temp 0.2 |
| **ADR Author** | Generate Living ADR from synthesis with symbol hashes | 16k tokens, temp 0.1 |

**Swarm patterns**:
- `deep_research`: 4-perspective parallel → synthesize → ADR
- `quick_fact_check`: Single question → evidence → answer
- `empirical_validation`: Hypothesis → probe → evidence note

**Handoff protocol**: Structured context passing (`notebook_id`, `execution_dir`, `anchor_symbols`, `inquiry_question`, `perspective`) + required artifacts (`evidence_note_ids`, `symbol_anchors`, `confidence`, `unresolved_questions`).

---

## Architecture

```
Host Machine (WORKSPACE_DIR)
  ├── Projects/ & Codebases
  ├── research/                        ← Native Research Brain (Markdown + YAML frontmatter)
  │   └── <notebook>/
  │       ├── notebook.json
  │       ├── notes/
  │       └── sources/
  ├── .planning/                       ← Planning artifacts per project
  │   └── YYYY-MM-DD-slug/
  │       ├── task_plan.md
  │       ├── findings.md
  │       ├── progress.md
  │       └── research/
  │           └── ADR-XXX.md           ← Living ADRs with symbol hashes
  └── .scripts/                        ← Helper utilities
      ├── new_probe.sh
      ├── run_probe.sh
      ├── ingest_evidence.sh
      ├── new_adr.sh
      ├── check_adr_drift.sh
      ├── create_research_board.sh
      └── handoff_context.sh
        │
        ├── [mount: /opt/data/workspace (rw)]  ──> Hermes (Agent workspace + probes)
        ├── [mount: /opt/data/workspace (ro)]  ──> Graft (Hybrid search: AST + text + semantic)
        │
        ├── Hermes ──→ Graft:20128/mcp           (Code intelligence via MCP)
        ├── Hermes ──→ MCP Server:8000/mcp       (Tools & Skills via MCP)
        ├── Hermes ──→ LLM Gateway:4000          (ALL model inference)
        ├── Graft ──→ LLM Gateway:4000           (Code summarization)
        ├── Open Notebook ──→ SurrealDB:8000     (Database)
        ├── Open Notebook ──→ Embeddings:8080    (Vector embeddings)
        ├── Open Notebook ──→ LLM Gateway:4000   (Note generation, RAG)
        └── Hermes ──→ MCP Server ──→ notebook_ops ──→ Open Notebook:5055
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
   - `CODEGRAPH_SUBDIR`: (Optional) Subdirectory inside `WORKSPACE_DIR` for Graft to index (leave empty for entire workspace).
   - LLM settings and API keys.

2. **Start the Base Stack**:
   ```bash
   make up
   ```
   This verifies that `WORKSPACE_DIR` exists on the host and starts all core containers in the background.

3. **Start Extended Stack (Research Agent)**:
   ```bash
   make up-all
   ```
   Adds Open Notebook + SurrealDB. Enables full autonomous research capabilities.

4. **Check Status**:
   ```bash
   make status-all
   ```

5. **View Logs**:
   ```bash
   make logs-all
   ```

6. **Initial Prompt for Hermes (Turn 1)**:
   Provide this prompt on Turn 1 to orient Hermes to its full ecosystem:

   ```text
   You are operating inside the pai-stack Docker Compose environment with full autonomous research capabilities. Execute your Turn 1 Startup Protocol:

   1. Read your ground rules and research powers by calling:
      mcp__pai_tools__read_resource(uri='skill://agents')

   2. Survey your environment using:
      mcp__pai_tools__docker_ops(action='list')
      to check which stack services are active (Graft, LLM Gateway, MCP Server, Open Notebook, SurrealDB, Embeddings).

   3. Check your long-term memory via:
      mnemosyne_recall(query='workspace projects structure boundaries')
      to recall previous project contexts and architectural decisions.

   4. Inspect /opt/data/workspace and run mcp__graft__graft_repo_map to determine project boundaries and declare your EXECUTION_DIR.

   5. If Open Notebook is running (from `make up-all`):
      - Call mcp__pai_tools__read_resource(uri='skill://open-notebook') to activate mcp__pai_tools__notebook_ops for external research
      - Call mcp__pai_tools__read_resource(uri='skill://autonomous-tech-learner') for the **Hypothesis-Testing Protocol** (empirical probes) and **Deep Inquiry Trees** (perspective decomposition, dialectical inquiry, Living ADRs)
      - Note: Kanban worker roles (`researcher`, `synthesizer`, `adr_author`) and patterns (`deep_research`, `quick_fact_check`, `empirical_validation`) are configured in your system prompt under `kanban.workers` and `kanban.patterns`.

   6. Report your discovered:
      - `EXECUTION_DIR` (single project directory)
      - Active stack services
      - Ready MCP tools: `mcp__graft__*`, `mcp__pai_tools__notebook_ops`, `mcp__pai_tools__docker_ops`, `mcp__pai_tools__read_resource`, `mnemosyne_*`
      - Available skills (via `mcp__pai_tools__read_resource`): `agents`, `open-notebook`, `autonomous-tech-learner`, `graft`, `planning`, `stack-discovery`, `python`, `docker`, `react`, `nodejs`, `postgres`, `gitops`
      - Kanban swarm patterns for delegation

   This activates your **full autonomous research mode**: Tri-Brain synthesis, empirical validation, multi-perspective inquiry, and Kanban delegation.
   ```

   **What this prompt accomplishes:**
   - **Ground Rules & Invariants**: Enforces `skill://agents`, anchoring Hermes strictly to `<EXECUTION_DIR>` and preventing monolithic workspace confusion.
   - **Stack Awareness**: Auto-detects whether the base stack or extended research stack (`make up-all`) is running via `docker_ops`.
   - **Memory Re-hydration**: Pulls past project lessons and architectural context via Mnemosyne.
   - **Research Powers Unlocked**: Activates all 6 phases — notebook_ops expansion, workspace sync, Tri-Bridge, empirical probes, inquiry trees, Kanban swarms.
   - **Self-Realization**: Hermes understands its own ecosystem, tools, and delegation patterns without external instruction.

---

## Management Commands

| Command | Action |
|---|---|
| `make setup` | Initialize `.env` from `.env.example` and create default workspace folder |
| `make up` | Validate workspace existence and start base services in background (supports `ALL=1`, `s=<service>`) |
| `make down` | Stop running base services (supports `ALL=1`) |
| `make restart` | Restart base services (supports `ALL=1`, `s=<service>`) |
| `make logs` | Tail logs for base containers (supports `ALL=1`, `s=<service>`) |
| `make status` | View running base containers and health status (supports `ALL=1`, `s=<service>`) |
| `make sync` | Sync LLM models with local & cloud providers and auto-reload gateway |
| `make sync-all` | Sync models and include all cloud provider templates |
| `make build` | Build / rebuild base container images (supports `ALL=1`, `s=<service>`) |
| `make clean` | Stop base containers and remove persisted volumes (`hermes-data`, `graft-cache`) |
| `make config` | Validate and resolve Docker Compose configuration for base stack (supports `ALL=1`) |

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

### Services

- **Hermes Web UI**: [http://localhost:9119](http://localhost:9119)
- **Graft Visualizer**: [http://localhost:20128/viz/](http://localhost:20128/viz/)
- **Graft API**: [http://localhost:20128/search?q=query&type=hybrid](http://localhost:20128/search?q=query&type=hybrid)
- **MCP Server**: [http://localhost:8000/mcp](http://localhost:8000/mcp)
- **Research Brain**: Built-in native file vault at `${WORKSPACE_DIR}/research/` (queried via `notebook_ops`)

---

## Key Files for Agents

| File | Purpose |
|---|---|
| `AGENTS.md` | This context file — read first |
| `hermes/config.yaml` | System prompt, model providers, MCP config, **Kanban swarm config** |
| `docker-compose.yaml` | Base service definitions, mounts, resource limits |
| `docker-compose.open-notebook.yml` | (Deprecated) Superseded by native file vault |
| `mcp-server/server.py` | MCP server: auto-discovers tools & skills |
| `mcp-server/tools/notebook-ops/` | `notebook_ops` MCP tool (10 actions over native Markdown vault) |
| `mcp-server/skills/agents/SKILL.md` | Ground rules injected at session start |
| `mcp-server/skills/open-notebook/SKILL.md` | Research Brain usage + **Symbolic Anchor Protocol** |
| `mcp-server/skills/autonomous-tech-learner/SKILL.md` | Learning loop + **Hypothesis-Testing Protocol** + **Deep Inquiry Trees & L-ADRs** |
| `mcp-server/skills/planning/SKILL.md` | Planning discipline (task_plan.md, findings.md, progress.md) |
| `.scripts/` | Hermes utilities: probes, ADRs, Kanban boards, handoffs |

---

## Philosophy

- **Zero Contamination**: External research never pollutes git code directories; lives in `research/<notebook>/` or `.planning/research/`.
- **Zero-Container Research**: Pure file-based Markdown + YAML frontmatter eliminates external database overhead (~2.3 GB RAM saved) and avoids RPi5 jemalloc page size incompatibilities.
- **Single LLM Gateway**: All model calls route through `llm-gateway:4000` (LiteLLM).
- **Empirical Over Theoretical**: When documentation is ambiguous, micro-probes in `/opt/data/probes/` take precedence over web claims.
- **Self-Realizing Agent**: Hermes discovers its own capabilities, tools, and ecosystem on Turn 1 — no external orchestration needed.