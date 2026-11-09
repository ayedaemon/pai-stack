# pai-stack — Agent Context

> Read this file first. It explains what this repo is, how the services interconnect,
> and how any AI agent (Hermes, or otherwise) should work within this environment.

## What this is

Two core Docker services that give an AI agent (Hermes) a complete local development environment:
read-write workspace access, persistent local memory, and native procedural skills —
no sidecar containers needed for tools.

## Services & Ports

| Service | Port | Role | Profile |
|---|---|---|---|
| **llm-gateway** | 4000 | Unified LLM Gateway: Bifrost high-performance Go proxy (routes, dynamic fallbacks, observability) | `gateway` |
| **hermes** | 9119 / 8642 | AI agent gateway + web dashboard (native Mnemosyne memory, native `pai_*` tools, native skills) | `hermes` |
| **dsh** | 9229 | DeepSeek Harness agent — second agent on the same workspace | `dsh` |
| **open-design** | 7456 | Design generation / mockup bridge | `design` |
| **terrain** | 7878 | Code intelligence — the single index owner (see below) | `terrain` |
| **searxng** | 8888 | Self-hosted metasearch engine | `searxng` |

All services are optional profiles. Run any combination:
```bash
make gateway-up hermes-up       # Gateway + Hermes
make gateway-up dsh-up          # Gateway + DSH
make all-up                     # Everything
```

## Container Mounts

| Host path | Container path | Service | Access |
|---|---|---|---|
| `$WORKSPACE_DIR` | `/opt/data/workspace` | hermes | **read-write** (project files + `.project/` vault) |
| `$WORKSPACE_DIR` | `/opt/data/workspace` | terrain | **read-write** (writes `.terrain/` into the repo it indexes) |
| `$WORKSPACE_DIR` | `/opt/data/workspace` | dsh | **read-write** (same container path as hermes — shared filepaths) |
| `$WORKSPACE_DIR` | `/opt/data/workspace` | open-design | **read-write** (import folder for design generation) |

Hermes and dsh both mount the workspace at `/opt/data/workspace`. Hermes writes helper scripts
and scratch tools to `/opt/data`.

Terrain's *project registry* deliberately does **not** live on that mount — it sits
in the `terrain_data` volume at `/var/lib/terrain/.terrain/registry.json`, because
it is host state, not repo content.

OpenDesign's daemon state stays in the `open_design_data` volume at `/app/.od` — never bind-mounted into the workspace to avoid SQLite lock contention.



## Service Interconnection

```
hermes ──→ [Mnemosyne: SQLite]  local persistent memory (working/episodic memory, knowledge graph)
hermes ──→ [pai_tools plugin]   native tools: pai_notebook_ops, pai_adr_ops, pai_ops_design_ops (Docker is native CLI via the `docker` skill, not a tool)
hermes ──→ [pai_terrain_ops]    code intelligence → terrain:7878/call  (HTTP)
dsh    ──→ [dsh-pai-terrain]    code intelligence → terrain:7878/call  (HTTP)
hermes ←─→ [pair/ blackboard] ←─→ dsh   peer queue: pair/queue → claim.py → worktree → done.py; wake via poke.py (docker exec headless)
hermes ──→ [skills: /opt/pai/skills]  native procedural skills via skills_list / skill_view
hermes ──→ llm-gateway:4000     ONLY gateway for LLM completions & reasoning
hermes (pai_notebook_ops) ──→ <session workspace>/.project/research/ (Markdown wiki)
         └─ workspace = agent.runtime_cwd session cwd, resolved per call
dsh    (pai_notebook_ops) ──→ <session workspace>/.project/research/ (same wiki)
         └─ workspace = exec.agent.session.header.cwd, resolved per call
hermes (pai_notebook_ops ask) ──→ llm-gateway:4000 (synthesis)
dsh    ──→ llm-gateway:4000     LLM completions & reasoning
open-design ──→ llm-gateway:4000  LLM completions (BYOK or gateway)
terrain ──→ <repo>/.terrain/    the ONLY writer of index artifacts
terrain ──→ opencode acp (ACP)  ask/init — always on, no feature flag
         └─ NOT llm-gateway. Terrain holds no gateway link and no provider key:
            its ACP agent runs OpenCode's keyless Zen models. Do NOT re-add
            OPENAI_API_KEY — it makes opencode pin the ACP session to a catalog
            OpenAI model and both ask/init die. See docs/terrain.md.
```

All model inference routes through `llm-gateway:4000` (Bifrost), except the two
keyless-Zen cases noted under *LLM routing posture* below.

**Each service runs independently via its profile.** No service is required to run.
Start only what you need: `make gateway-up hermes-up`, `make gateway-up dsh-up`, etc.
`pai_notebook_ops` runs in-process in Hermes, operating directly on Markdown files in the workspace.

### LLM routing posture (gateway-only)
- Hermes declares exactly one provider (`gateway`); model selection, fallbacks, and
  provider credentials live in `llm-gateway/config.json` (+ `scripts/sync-models.py`
  templates). Never add direct provider keys, auxiliary providers, or Hermes-level
  fallbacks — Models.dev catalog reads are metadata-only and fine.
- Known exceptions: `opencode-delegate` calls Zen free models directly (keyless,
  documented in its skill); Terrain's ACP agent (`opencode acp`) does the same for
  `ask`/`init`, which is why terrain carries no gateway link at all; Langfuse
  receives traces (it IS the audit trail).
- Secrets caveat: provider keys are absent from the hermes container *environment*,
  but `.env` lives inside the mounted workspace — file-capable tools can still read
  it. `*.env` reads are hard-denied for delegates; treat Hermes-side reads as auditable.
- Gateway runs Bifrost Go proxy with CEL routing rules, unauthenticated inference, and
  structured JSON logs recorded to SQLite (`/app/data/logs.db`) and stdout. Web UI available on `:4000`.
Mnemosyne runs embedded inside Hermes using local ONNX fastembed and SQLite (`hermes-data` volume).

## How Hermes Uses Each Service

### Code Intelligence — Terrain (opt-in profile)

Code intelligence is provided by [Terrain](https://github.com/sopaco/terrain), run as
a **single container that owns the index**. It replaces the removed `pai_code_intel`,
which built an in-process tree-sitter index over the whole workspace (42% of which was
a leaked Go toolchain, and far more than DSH's 1.2 GB heap could hold).

```
agent ──→ terrain:7878 ──→ terrain CLI ──→ <repo>/.terrain/
                            (one writer)      agent context, knowledge docs, source pack
```

- **Single index owner.** Only the `terrain` container writes `.terrain/`. Agents
  trigger jobs and read the result — neither keeps a private in-memory index, so the
  DSH heap cap is a non-issue.
- **Per-repo by construction.** Each scan writes `.terrain/` *inside* the repo it
  indexes, which structurally enforces the session-workspace boundary below.
- **Indexing is free.** `index`/`refresh` make no LLM call. `refresh` explicitly skips
  Litho, Terrain's LLM doc generator. Only `ask` and `init` invoke an LLM — via
  Terrain's own ACP agent on keyless Zen models, not the gateway. There is no
  feature flag: they are always on, because keyless means they cost latency, not
  tokens. `init` is the
  expensive one: it regenerates the whole `human/` corpus, so request it rather than
  running it unprompted — and note a stale corpus survives any number of `refresh`
  calls, since only `init` runs Litho.
- **The registry and the index can drift apart.** `registry.json` lives in the
  `terrain_data` volume; `.terrain/` lives in the indexed repo on the workspace bind.
  Recreating the volume drops the registry and leaves the index intact, so `projects`
  returns `[]` while `<repo>/.terrain/` is fully populated — which silently breaks every
  project-scoped call. Recovery is one free `scan`. See [`docs/terrain.md`](docs/terrain.md).
- **Degrades cleanly.** Terrain is optional. `pai_terrain_ops` probes `/healthz` and
  hides itself when the service is down; without it, locate code with `grep` + targeted
  reads. Nothing breaks.
- **`.terrain/` is gitignored.** The index is per-host, not per-repo-lifetime.

Start it with `make terrain-up`; see [`docs/terrain.md`](docs/terrain.md).

### Skills — procedural knowledge

Skills are Markdown files under `skills/`, mounted read-only into every agent
(`hermes` → `/opt/pai/skills`, `dsh` → `/data/dsh/.agents/skills`). They load on demand, so
a large catalogue costs nothing until used.

**There is deliberately no hand-written catalogue in this file.** `skills_list()` is the
catalogue — it emits every skill with its description at runtime. Duplicating it by hand is
how `teach` and `visualize` ended up mounted but invisible to agents for months.

Operating rules and skill **routing** (task → skill) live in one place:
[`skills/agents/SKILL.md`](skills/agents/SKILL.md).
### Mnemosyne — agent memory (decisions, execution outcomes, lessons learned)

Mnemosyne is Hermes's native, local-first agent memory layer. It operates entirely within Hermes
using embedded SQLite (`/opt/hermes/data/mnemosyne/data/mnemosyne.db`) and local ONNX vector embeddings (`fastembed`).

- **Automatic capture**: every turn (decisions, tool calls, user preferences, failure modes) is automatically indexed.
- **Dynamic prompt prefetch**: relevant working memories are fetched and injected before model turns.
- **Recall tools**: `mnemosyne_recall` (hybrid semantic + FTS5 + recency search), `mnemosyne_remember` (explicit fact recording), `mnemosyne_sleep` (episodic consolidation), `mnemosyne_stats`.
- **Knowledge graph**: `mnemosyne_triple_add`, `mnemosyne_triple_query` for relationship traversal.

| Retrieval System | Scope | Storage | Role |
|---|---|---|---|
| **Research Brain** | External knowledge & notes | `<session workspace>/.project/research/` | RFCs, API docs, papers, research notes in Markdown |
| **Mnemosyne** | Agent experience | `/opt/hermes/data/mnemosyne` | Decisions, prior fixes, session continuity, user preferences |

## Operating Protocol

**Maintained in exactly one place: [`skills/agents/SKILL.md`](skills/agents/SKILL.md).**
That file is agent-neutral, mounted into every agent in the stack, and is the first thing
Hermes loads each session. It owns:

- the **Turn-1 startup protocol** (confirm the attached workspace → check the
  terrain index → orient on the stack)
- the **session-workspace invariant** and project-boundary isolation
- **propose-before-writing** and the confirmation gate for mutating git
- **planning discipline** and the `.project/planning/` layout
- **code intelligence** via `pai_terrain_ops`, including the registry-lost recovery case
- **skill routing** — which skill to load for which task

Hermes-only depth — Mnemosyne, dual-brain symbol anchors, the empirical lab, Living ADRs,
Kanban swarms — is split into [`skills/hermes-memory/SKILL.md`](skills/hermes-memory/SKILL.md)
so the shared rules stay readable by agents that have none of those tools.

Do not add protocol to this file. If a rule is missing, it belongs in the `agents` skill.

## Key Config Files

| File | Purpose |
|---|---|
| [`skills/agents/SKILL.md`](skills/agents/SKILL.md) | Operating rules — Turn-1 protocol, invariants, routing (single source) |
| [`skills/hermes-memory/SKILL.md`](skills/hermes-memory/SKILL.md) | Hermes-only depth — Mnemosyne, ADR, Kanban, empirical lab |
| [`hermes/config.yaml`](hermes/config.yaml) | System prompt, model providers, skills, knowledgebase |
| [`docker-compose.yaml`](docker-compose.yaml) | All service definitions, mounts, limits (profiles: gateway, hermes, terrain, dsh, design) |
| [`hermes/plugins/pai_terrain_ops/`](hermes/plugins/pai_terrain_ops/) | Code-intel tool → terrain service |
| [`terrain/`](terrain/) | Terrain multi-stage image + HTTP shim |
| [`docs/architecture.md`](docs/architecture.md) | Living Mermaid diagram + process model |
| [`.env.example`](.env.example) | Template for `WORKSPACE_DIR`, LLM config, API keys |

### Quick start for an agent

1. `skill_view(name="agents")` — everything above, in one call.
2. `skills_list()` — discover what's available.
3. Read [`docs/architecture.md`](docs/architecture.md) for *why* the stack looks like this.
## System Architecture Maintenance Protocol

**CRITICAL RULE:** This project relies on a living, highly accurate Mermaid system design diagram located in `docs/architecture.md` to onboard users and track data flow. 

Whenever you modify the project's structural architecture (e.g., adding a new module, database table, API route, service, or altering core data flows), you **MUST** update the Mermaid diagram in `docs/architecture.md` before completing the task. Always load `skill_view(name="mermaid")` first for syntax rules and abstraction depth protocol.

### Diagram Requirements:
1. **Format:** Use a Mermaid `graph TD` or `graph LR` flowchart. 
2. **Abstraction Level:** Keep it high-level. Map components, services, databases, and core interactions. Do not map individual functions, classes, or files unless they represent an entire service.
3. **Interactive Linking:** You must use Mermaid's `click` syntax to make nodes clickable. Link every major node directly to its corresponding detailed documentation file or core source code directory so users can drill down.
4. **Validation:** Ensure the Mermaid syntax is strictly valid and uses proper escaping for special characters.
