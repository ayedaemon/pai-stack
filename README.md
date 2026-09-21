# pai-stack

A streamlined AI development stack running three core Docker Compose services: **Hermes** (AI Agent Gateway), **MCP Server** (Code Intelligence, Tools, Skills, and native File-Based Research Brain), and **LLM Gateway** (LiteLLM Proxy). Optional **DSH** (DeepSeek Harness) available via profile.

All services operate directly on your local workspace directory mounted from the host.

---

## Services

| Service | Port | Description |
|---|---|---|
| **Hermes** | `9119` / `8642` | Primary AI agent gateway + web dashboard (with native Mnemosyne memory). Operating in `/opt/data`. |
| **MCP Server** | `8000` | Model Context Protocol server exposing code intelligence (`code_intel`), bundled tools (`docker_ops`, `notebook_ops`, `adr_ops`), and procedural skills to Hermes. |
| **LLM Gateway** | `4000` | Dedicated LiteLLM proxy — single gateway for all model inference, routing, fallbacks, and provider credentials. |
| **DSH** | `9120` | (Optional) DeepSeek Harness — alternative agent UI. Activate with `docker compose --profile dsh up -d`. |

---

## Autonomous Research Agent Capabilities

Hermes operates with a unified **"Tri-Brain" architecture**:

### 🧠 Tri-Brain Architecture

| Brain | Service | Capability |
|---|---|---|
| **Code Brain** | Code Intelligence (`mcp-server:8000`) | AST symbols, semantic search, call graphs, file APIs, drift detection via `code_intel` tool |
| **Research Brain** | File Vault (`research/`) | External knowledge: RFCs, papers, API docs, web articles, Markdown notes via `notebook_ops` tool |
| **Memory Brain** | Mnemosyne | Episodic memory, decisions, prior fixes, user preferences, knowledge graph triples |

### 🔗 Cross-Brain Synthesis (Symbolic Research Anchors)

- **Anchor syntax**: `@symbol:path/to/file.ext:SymbolName` embedded in all research notes
- **Mnemosyne triples**: Link notebook notes → code symbols → decisions
- **Reverse lookup**: Before new research, query Mnemosyne for existing notes on a symbol
- **Native file storage**: Notes saved to `research/<notebook>/notes/` → indexed by code_intel → searchable in IDE & code search

### 🔬 Empirical Lab Notebook Engine

When documentation is ambiguous, Hermes runs **micro-probes** in `/opt/data/probes/`:

```
Hypothesis → Micro-script (Python/Shell) → Execute (30s/256MB guardrails) → Evidence Note → Research Brain
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
  │       ├── notes/
  │       └── sources/
  └── .planning/                       ← Planning artifacts per project
      └── YYYY-MM-DD-slug/
          ├── task_plan.md
          ├── findings.md
          ├── progress.md
          └── research/
              └── ADR-XXX.md           ← Living ADRs with symbol hashes
        │
        ├── [mount: /opt/data/workspace (rw)]  ──> Hermes (Agent workspace + execution)
        ├── [mount: /opt/data/workspace (rw)]  ──> MCP Server (Code intelligence + Research Brain file vault)
        │
        ├── Hermes ──→ MCP Server:8000/mcp       (Code intelligence, Tools & Skills via MCP)
        ├── Hermes ──→ LLM Gateway:4000          (ALL model inference)
        └── MCP Server (notebook_ops) ──→ research/ (Native Markdown file vault)
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
   - LLM settings and API keys.

2. **Start the Stack**:
   ```bash
   make up
   ```
   This verifies that `WORKSPACE_DIR` exists on the host and starts all core containers (`hermes`, `mcp-server`, `llm-gateway`) in the background. Research Brain is built-in natively.

3. **Check Status & Logs**:
   ```bash
   make status
   make logs
   ```

4. **Initial Prompt for Hermes (Turn 1)**:
   Provide this prompt on Turn 1 to orient Hermes to its full ecosystem:

   ```text
   You are operating inside the pai-stack Docker Compose environment with full autonomous research capabilities. Execute your Turn 1 Startup Protocol:

   1. Read your ground rules and research powers by calling:
      mcp__pai_tools__read_resource(uri='skill://agents')

   2. Survey your environment using:
      mcp__pai_tools__docker_ops(action='list')
      to verify core stack services (MCP Server, LLM Gateway, Hermes). Note: Research Brain operates natively through mcp-server over Markdown files in /opt/data/workspace/research/.

   3. Check your long-term memory via:
      mnemosyne_recall(query='workspace projects structure boundaries')
      to recall previous project contexts and architectural decisions.

   4. Inspect /opt/data/workspace and run mcp__pai_tools__code_intel(action="repo_map") to determine project boundaries and declare your EXECUTION_DIR.

   5. For research tasks:
      - Use mcp__pai_tools__notebook_ops for Research Brain vault operations (list_notebooks, add_note, search, ask_notebook).
      - Call mcp__pai_tools__read_resource(uri='skill://autonomous-tech-learner') for the **Hypothesis-Testing Protocol** (empirical probes) and **Deep Inquiry Trees** (perspective decomposition, dialectical inquiry, Living ADRs).
      - Note: Kanban worker roles (`researcher`, `synthesizer`, `adr_author`) and patterns (`deep_research`, `quick_fact_check`, `empirical_validation`) are configured in your system prompt under `kanban.workers` and `kanban.patterns`.

   6. Report your discovered:
      - `EXECUTION_DIR` (single project directory)
      - Active stack services
      - Ready MCP tools: `mcp__pai_tools__code_intel`, `mcp__pai_tools__notebook_ops`, `mcp__pai_tools__adr_ops`, `mcp__pai_tools__docker_ops`, `mcp__pai_tools__read_resource`, `mnemosyne_*`
      - Available skills (via `mcp__pai_tools__read_resource`): `agents`, `autonomous-tech-learner`, `code-intel`, `planning`, `stack-discovery`, `python`, `docker`, `react`, `nodejs`, `sql`, `gitops`
      - Kanban swarm patterns for delegation

   This activates your **full autonomous research mode**: Tri-Brain synthesis, empirical validation, multi-perspective inquiry, and Kanban delegation.
   ```

   **What this prompt accomplishes:**
   - **Ground Rules & Invariants**: Enforces `skill://agents`, anchoring Hermes strictly to `<EXECUTION_DIR>` and preventing monolithic workspace confusion.
   - **Native File Vault Awareness**: Directs Hermes to file-based research in `/opt/data/workspace/research/` via `notebook_ops`.
   - **Memory Re-hydration**: Pulls past project lessons and architectural context via Mnemosyne.
   - **Research Powers Unlocked**: Activates all 6 phases — notebook_ops expansion, workspace sync, Tri-Bridge, empirical probes, inquiry trees, Kanban swarms.
   - **Self-Realization**: Hermes understands its own ecosystem, tools, and delegation patterns without external instruction.

---

## Management Commands

| Command | Action |
|---|---|
| `make setup` | Initialize `.env` from `.env.example` and create default workspace folder |
| `make up` | Validate workspace existence and start stack in background (supports `s=<service>`) |
| `make down` | Stop running services |
| `make restart` | Restart services (supports `s=<service>`) |
| `make logs` | Tail logs for containers (supports `s=<service>`) |
| `make status` | View running containers and health status (supports `s=<service>`) |
| `make sync` | Sync LLM models with local & cloud providers and auto-reload gateway |
| `make sync-all` | Sync models and include all cloud provider templates |
| `make build` | Build / rebuild container images (supports `s=<service>`) |
| `make clean` | Stop containers and remove persisted volumes (destroys hermes state) |
| `make config` | Validate and resolve Docker Compose configuration |

---

## Accessing Services

### Services

- **Hermes Web UI**: [http://localhost:9119](http://localhost:9119)
- **MCP Server**: [http://localhost:8000/mcp](http://localhost:8000/mcp)
- **Research Brain**: Built-in native file vault at `${WORKSPACE_DIR}/research/` (queried via `notebook_ops`)

---

## Key Files for Agents

| File | Purpose |
|---|---|
| `AGENTS.md` | This context file — read first |
| `hermes/config.yaml` | System prompt, model providers, MCP config, **Kanban swarm config** |
| `docker-compose.yaml` | Base service definitions, mounts, resource limits |
| `mcp-server/server.py` | MCP server: auto-discovers tools & skills |
| `mcp-server/tools/code-intel/` | `code_intel` MCP tool (symbol search, call graphs, impact analysis) |
| `mcp-server/tools/notebook-ops/` | `notebook_ops` MCP tool (10 actions over native Markdown vault) |
| `mcp-server/tools/adr-ops/` | `adr_ops` MCP tool (Living ADR creation & symbol drift detection) |
| `mcp-server/skills/agents/SKILL.md` | Ground rules injected at session start |
| `mcp-server/skills/autonomous-tech-learner/SKILL.md` | Learning loop + **Hypothesis-Testing Protocol** + **Deep Inquiry Trees & L-ADRs** |
| `mcp-server/skills/planning/SKILL.md` | Planning discipline (task_plan.md, findings.md, progress.md) |

---

## Philosophy

- **Zero Contamination**: External research never pollutes git code directories; lives in `research/<notebook>/` or `.planning/research/`.
- **Zero-Container Research**: Pure file-based Markdown + YAML frontmatter eliminates external database overhead (~2.3 GB RAM saved) and avoids RPi5 jemalloc page size incompatibilities.
- **Single LLM Gateway**: All model calls route through `llm-gateway:4000` (LiteLLM).
- **Empirical Over Theoretical**: When documentation is ambiguous, micro-probes in `/opt/data/probes/` take precedence over web claims.
- **Self-Realizing Agent**: Hermes discovers its own capabilities, tools, and ecosystem on Turn 1 — no external orchestration needed.
