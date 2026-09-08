# Docker Project

> Read, reason, and safely change Docker/Docker Compose projects — understand build, runtime, networking, volumes.

## When to use
- Trigger: user mentions Docker, `Dockerfile`, `docker-compose.yaml`, `compose.yaml`, `container`, `image`, or asks to containerize/debug/deploy
- Preconditions: project under `/opt/data/Personal/...` with `Dockerfile` or `docker-compose.yaml`
- Auto-use: when `stack-discovery` finds `Dockerfile*` or `docker-compose*` at root or `hermes/` style subdirs

## Inputs
- Required: project root path, target service name if compose has many
- Optional: env overrides, host port expectations, Tailscale context

## Steps
1. Retrieve scoped KB: `AGENTS.md` + `Projects/<Name>/**` + `issues/<slug>.md`. Cite `file:lines`.
2. Inventory Docker artifacts:
   - Glob `Dockerfile*`, `docker-compose*.yaml`, `compose*.yaml`, `.dockerignore`, `Makefile` at root and one level deep
   - For compose, read `services:` map — note `build:`, `image:`, `ports:`, `volumes:`, `environment:`, `depends_on:`, `healthcheck:` per service with `file:lines`
3. Analyze Dockerfile:
   - Base `FROM` (distroless vs `python:slim` vs `node:alpine`) + stage names if multi-stage
   - `COPY`/`ADD` layers — flag large context, missing `.dockerignore` patterns (`node_modules`, `.git`, `__pycache__`, `*.db`)
   - `RUN` caching hints (layer order, `apt-get` cleanup, `npm ci` vs `npm install`)
   - `USER`, `EXPOSE`, `ENTRYPOINT`/`CMD`, `HEALTHCHECK`
   - Note s6-overlay / `USER root` patterns (see `hermes/Dockerfile:7` / `hermes/entrypoint.sh:1` if relevant)
4. Analyze Compose:
   - Map service → port → host mapping (`ports: - "20128:20128"` style `docker-compose.yaml:14`)
   - Volumes: named (`hermes-data:/opt/hermes/data` `docker-compose.yaml:89`) vs bind (`${PERSONAL_FOLDER}:/opt/data/Personal` `:92`) — check for `EACCES` risk, `user: "${UID:-1000}"`, `deploy.resources.limits`
   - Network: default bridge vs custom; `extra_hosts: host.docker.internal` `docker-compose.yaml:22` for host services (Syncthing pattern)
   - Env: which vars come from host `.env` vs hard-coded; flag raw secrets in compose
5. Check pai-stack conventions (if repo is pai-stack itself):
   - Build contexts must be flat (playbook copies files into `~/deployed-pai-stack/`)
   - `silverbulletKB/` seeding is `force: no` — never overwrite user edits
   - Services bind directly to Tailscale IP (no reverse proxy) — Tailscale encrypts via WireGuard
6. Plan change:
   - For read-only: summarize services, deps graph, build order, how to run (`docker compose up --build`, `docker compose logs -f <svc>`)
   - For edits: keep diff minimal — edit `Dockerfile` or `compose.yaml` one service at a time, preserve `deploy.resources.limits`, keep secrets in env not in image. Propose `docker compose config` validate step.
   - If deployment target is pai-stack Pi, remind `ansible/playbook.yml` copies build contexts explicitly — new files need a copy entry.
7. Verify without heavy builds when possible:
   - `docker compose config` for YAML validity (dry-run)
   - `docker build --dry-run` or `hadolint` mental lint; flag missing `HEALTHCHECK` / running as root unwarranted
   - Suggest `make status` / `make logs` for runtime checks (`Makefile:1`)
8. Write & cite:
   - Update `Projects/<Name>/docs/architecture.md` with service map + `file:lines`
   - Post concise service table + next command in same Telegram topic, cited

## Outputs
- Primary: KB service map (Dockerfile stages, compose services, ports, volumes, env) + `file:lines`
- Changelog: what was inspected/changed, validation (`docker compose config` OK)
- Next step: `docker compose up -d --build <svc>` or `make logs` etc.

## Related files
- `docker-compose.yaml` (or `compose.yaml`)
- `Dockerfile` per service
- `.dockerignore`
- `ansible/playbook.yml` (pai-stack deploy conventions)
- `Skills/python/SKILL.md`, `Skills/nodejs/SKILL.md`, `Skills/postgres/SKILL.md` (stacks often compose with Docker)

## Notes for Hermes
- Use `docker compose config` before proposing `up --build` — cheap validation.
- Keep headings `## Services`, `## Build stages`, `## Volumes & perms`, `## Networking` for retrieval.
- Never suggest `--privileged` or exposing `0.0.0.0` publicly unless via Tailscale.
- For multi-stage builds, cite stage name: `Dockerfile:12 (builder)` → `Dockerfile:28 (runtime)`.
