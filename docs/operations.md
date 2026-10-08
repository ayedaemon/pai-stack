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
| `make all-up` / `make all-down` / `make all-clean` | Start / stop everything (core + design + dsh + terrain); `all-clean` wipes **all** volumes |
| `make design-up` / `make design-down` / `make design-logs` / `make design-config` / `make design-build` / `make design-perms` / `make design-import d=/workspace/<dir> [n=<name>]` | OpenDesign ([opendesign.md](opendesign.md)) |
| `make dsh-up` / `make dsh-down` / `make dsh-logs` / `make dsh-config` / `make dsh-build` / `make dsh-perms` / `make dsh-password` | DSH agent ([dsh.md](dsh.md)) |

UID/GID auto-detect (`id -u` / `id -g`) keeps bind-mounted files owned by you. Override per-invocation: `make up UID=1000 GID=1000`.

All profiles share one compose project: running a subset (e.g. `make up` while `dsh` runs) prints a benign `Found orphan containers` warning — use `make all-down` / `make all-clean` for full-stack stops. Volumes created before the compose-label fix still print `not created by Docker Compose` until recreated (e.g. via `make all-clean`, which destroys state).

## Image drift — the repo can be ahead of the running containers

`skills/`, `hermes/config.yaml`, `Makefile` and `.env` are **bind-mounted**, so
edits are live on the next process start. Anything the **Dockerfile copies** is
baked at build time and will *not* appear until you rebuild.

Audit it rather than guessing:

```bash
# which local COPY directives are missing from the running image?
docker inspect pai-stack-hermes:latest --format '{{.Created}}'   # when it was built
stat -f '%Sm %N' -t '%Y-%m-%d %H:%M' hermes/Dockerfile             # when it last changed
docker exec hermes ls /opt/hermes/plugins/                       # what actually shipped
```

**Found 2026-10-07:** `pai-stack-hermes:latest` was built 2026-09-30, four days
before `hermes/Dockerfile:81` added
`COPY plugins/pai_terrain_ops`. The plugin is absent from the container, so
`pai_terrain_ops` — enabled in `hermes/config.yaml` and documented in
`AGENTS.md` — was invisible to every session and the Turn-1 terrain step could not
fire. Three `pai_tools` files (`__init__.py`,
`ops_design_ops.py`) had also drifted.

```bash
make build s=hermes && docker compose up -d hermes
```

The other three images were current at the time of writing (`dsh` ~4h,
`terrain` and `open-design` same-day). Check yours the same way after any
Dockerfile edit — a plugin that exists in the repo but not in the image fails
*silently*, which is the whole problem.

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
| `HERMES_TELEGRAM_*` | Hermes bot token + numeric-ID allowlists; empty = disabled; restart hermes after change |
| `DSH_TELEGRAM_*` | Separate DSH bot token + allowlists; empty = disabled |
| `OPEN_DESIGN_IMAGE`, `OPEN_DESIGN_PORT`, `OD_API_TOKEN` | Design profile (see [opendesign.md](opendesign.md)) |
| `DSH_IMAGE`, `DSH_PORT`, `DSH_BIND_IP`, `DEEPSEEK_API_KEY`, `DSH_ADMIN_PASSWORD`, `DSH_SETUP_REMOTE`, `DSH_TRUSTED_HOSTS` | DSH profile (see [dsh.md](dsh.md)) |

Template with generation hints: [.env.example](../.env.example)

## Access

- Hermes UI: http://localhost:9119
- LLM Gateway: http://localhost:4000 (`/health/liveliness`)
- OpenDesign (when up): http://localhost:7456
- DSH (when up): http://localhost:9229

## Repo layout

| Path | Purpose |
|---|---|
| `AGENTS.md` | Agent context — read first |
| `docker-compose.yaml` | Base services, mounts, limits |
| `docker-compose.opendesign.yaml` | Design profile override |
| `hermes/config.yaml` | System prompt, providers, skills, Kanban |
| `hermes/plugins/pai_tools/` | Native `pai_*` tools |
| `hermes/plugins/pai_terrain_ops/` | Code-intel tool → `terrain:7878/call` (image-baked; see *Image drift*) |
| `skills/` | `SKILL.md` files, mounted read-only into Hermes (and into DSH at `/data/dsh/.agents/skills`) |
| `skills/agents/SKILL.md` | Ground rules — on-demand copy of `AGENTS.md` |
| `llm-gateway/config.yaml` + `scripts/sync-models.py` | Routes + model sync |
| `opendesign/Dockerfile` | Local open-design build |
| `docker-compose.dsh.yaml` | DSH profile override |
| `dsh/Dockerfile` | Local dsh build (bundled mnemon CLI) |
