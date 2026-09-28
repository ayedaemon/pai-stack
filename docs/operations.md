# Operations

## Make targets

| Command | Action |
|---|---|
| `make up` | Validate workspace, start `hermes` + `llm-gateway` (`s=<service>` for one) |
| `make down` | Stop services |
| `make restart` | Restart (`s=<service>`) |
| `make status` | Containers, ports, health (`s=<service>`) |
| `make logs` | Tail logs (`s=<service>`) |
| `make sync` | Sync models from keyed providers, reload gateway |
| `make build` | Rebuild images (`s=<service>`) |
| `make config` | Validate resolved compose |
| `make clean` | Stop + remove volumes (**destroys hermes state**) |
| `make design-up` / `make design-down` / `make design-logs` / `make design-config` / `make design-build` / `make design-perms` / `make design-import d=/workspace/<dir> [n=<name>]` | OpenDesign ([opendesign.md](opendesign.md)) |

UID/GID auto-detect (`id -u` / `id -g`) keeps bind-mounted files owned by you. Override per-invocation: `make up UID=1000 GID=1000`.

## `.env` keys

| Key | Purpose |
|---|---|
| `WORKSPACE_DIR` | **Required, must already exist.** The stack never creates it — create your workspace dir yourself, point this at it, then `make up` |
| `OPENAI_COMPATIBLE_BASE_URL` / `_MODEL` / `_API_KEY` | Upstream provider for the gateway (LM Studio / Ollama / llama.cpp / LAN node / cloud) |
| `OPENROUTER_API_KEY`, `KILO_GATEWAY_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY` | Cloud fallback chains |
| `LITELLM_MASTER_KEY` | Leave commented for local use; an empty-but-set value breaks all requests |
| `LANGFUSE_*` | Optional tracing |
| `HERMES_DASHBOARD_BASIC_AUTH_*`, `API_SERVER_KEY` | Dashboard login + API bearer (generate with `openssl rand -hex 32`) |
| `RESEARCH_SUBDIR` | Vault subdir (default `research`) |
| `TELEGRAM_*` | Bot token + numeric-ID allowlists; empty = disabled; restart hermes after change |
| `OPEN_DESIGN_IMAGE`, `OPEN_DESIGN_PORT`, `OD_API_TOKEN` | Design profile (see [opendesign.md](opendesign.md)) |

Template with generation hints: [.env.example](../.env.example)

## Access

- Hermes UI: http://localhost:9119
- LLM Gateway: http://localhost:4000 (`/health/liveliness`)
- OpenDesign (when up): http://localhost:7456

## Repo layout

| Path | Purpose |
|---|---|
| `AGENTS.md` | Agent context — read first |
| `docker-compose.yaml` | Base services, mounts, limits |
| `docker-compose.opendesign.yaml` | Design profile override |
| `hermes/config.yaml` | System prompt, providers, skills, Kanban |
| `hermes/plugins/pai_tools/` | Native `pai_*` tools |
| `skills/` | `SKILL.md` files, mounted read-only into Hermes |
| `skills/agents/SKILL.md` | Ground rules injected at session start |
| `llm-gateway/config.yaml` + `scripts/sync-models.py` | Routes + model sync |
| `opendesign/Dockerfile` | Local open-design build |
