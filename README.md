# pai-stack

Local AI dev stack: **Hermes** (agent gateway + dashboard) + **LLM Gateway** (LiteLLM proxy). Optional **OpenDesign** studio on a `design` profile, optional **DSH** agent on a `dsh` profile, and optional **Terrain** code-intel service on a `terrain` profile.

All services operate on your host workspace mounted read-write into Hermes.

## Services

| Service | Port | What |
|---|---|---|
| **hermes** | `9119` / `8642` | Agent gateway + web UI. `pai_*` tools, skills, Mnemosyne memory |
| **llm-gateway** | `4000` | Sole LLM endpoint (LiteLLM). Routes, fallbacks, provider keys live here |
| **open-design** *(opt-in)* | `7456` | Design studio sharing `${WORKSPACE_DIR}` at `/opt/data/workspace`. See [docs/opendesign.md](docs/opendesign.md) |
| **dsh** *(opt-in)* | `9229` | DeepSeek Harness agent sharing `${WORKSPACE_DIR}` at `/opt/data/workspace`. See [docs/dsh.md](docs/dsh.md) |
| **terrain** *(opt-in)* | `7878` | Code intelligence — the single index owner. Writes `.terrain/` into each repo. See [docs/terrain.md](docs/terrain.md) |

Details: [docs/architecture.md](docs/architecture.md)

## Prerequisites

- Docker + Docker Compose v2
- Make
- An existing workspace dir on the host (you create it — the stack never does)

## Quick start

You create everything on the host — the stack only validates, never creates.

1. **Create your workspace directory** (an existing projects folder works fine):
   ```bash
   mkdir -p /path/to/workspace
   ```
2. **Create your env file and point it at that directory**:
   ```bash
   cp .env.example .env
   ```
   Set `WORKSPACE_DIR=/path/to/workspace`, plus your provider URL/keys.
3. **Start the stack** (fails with a clear error if `.env` or `WORKSPACE_DIR` is missing):
   ```bash
   make up      # start hermes + llm-gateway
   make status  # check health
   ```

Open Hermes UI: http://localhost:9119

## Common commands

| Command | Action |
|---|---|
| `make up` / `make down` / `make restart` | Start / stop / restart (add `s=<service>`) |
| `make status` / `make logs` | Health + ports / tail logs |
| `make sync` | Sync LLM model list, reload gateway |
| `make build` / `make config` / `make clean` | Rebuild / validate compose / stop + wipe volumes |
| `make design-up` | OpenDesign — [docs/opendesign.md](docs/opendesign.md) |
| `make dsh-up` | DSH agent — [docs/dsh.md](docs/dsh.md) |
| `make terrain-up` | Terrain code-intel service — [docs/terrain.md](docs/terrain.md) |
| `make terrain-index d=/opt/data/workspace/<project>` | Index a repo (free, no LLM) |

Full reference: [docs/operations.md](docs/operations.md)

## Docs

| Page | Covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Services, mounts, Dual-Brain, philosophy |
| [docs/hermes.md](docs/hermes.md) | Turn 1 startup, `pai_*` tools, skills, memory |
| [docs/research.md](docs/research.md) | Research vault, probes, inquiry trees, ADRs, swarms |
| [docs/llm-gateway.md](docs/llm-gateway.md) | Gateway-only routing, sync, digest pin |
| [docs/delegation.md](docs/delegation.md) | Keyless OpenCode handoffs from Hermes |
| [docs/opendesign.md](docs/opendesign.md) | Design profile: run, import, auth, build |
| [docs/dsh.md](docs/dsh.md) | DSH profile: image, gateway, tools, plugins |
| [docs/terrain.md](docs/terrain.md) | Terrain code-intel profile: build, shim, actions, cost |
| [docs/operations.md](docs/operations.md) | All `make` targets, `.env` keys, file layout |

Agent entrypoint: [AGENTS.md](AGENTS.md)
