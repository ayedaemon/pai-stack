---
name: docker
description: Docker discovery router — map Dockerfiles, compose services, volumes, and networks in this repo. Load on Dockerfile/compose/container questions or when stack-discovery finds them. Delegates optimization, validator tooling, and security hardening to docker-development.
---

# Docker (router)

> You own repo **service mapping**. Optimization and audit depth live upstream.
> Shared Hermes glue is canonical in the `agents` skill.

## Discover (validate cheaply: `docker compose config` before proposing `up --build`)
1. **Artifacts**: `Dockerfile*`, `docker-compose*.yaml`, `compose.yaml`, `.dockerignore`, `Makefile` targets (`make status`/`logs`).
2. **Dockerfile**: `FROM` + stages, `COPY` context hygiene, `RUN` caching, `USER`/`EXPOSE`/`ENTRYPOINT`/`HEALTHCHECK`. Pai notes: `hermes/Dockerfile` + `entrypoint.sh` patterns when relevant.
3. **Compose**: service→port map, named vs bind volumes (`EACCES`/`UID` risk, `deploy.resources.limits`), networks, `extra_hosts: host.docker.internal`, env provenance (host `.env` vs hardcoded — flag raw secrets).
4. **Conventions**: multi-stage, minimal base, non-root `USER`, pinned tags (never `:latest`), `.dockerignore` present. Never suggest `--privileged` or public `0.0.0.0` outside Tailscale.

## Stack projects — operate with `docker compose` (v2 plugin, installed in hermes image)

Applies when `stack-discovery` finds compose markers (`compose.yaml`, `docker-compose*.yaml`) in `EXECUTION_DIR` — i.e. the project IS a compose stack (e.g. ytune: api-gateway + workers + pgvector).

- **Scope split**: pai-stack's own services (`hermes`, `llm-gateway`) stay on `pai_docker_ops` (allowlisted). Project stacks use the native `docker compose` CLI over the mounted socket (`/var/run/docker.sock`). Never run compose against the pai-stack root unless the user explicitly asks.
- **Always anchor**: every compose invocation runs with `cd <EXECUTION_DIR>` first (Execution Directory Invariant). Compose v2 syntax only: `docker compose` (no hyphen).
- **Lifecycle** (read-only freely, mutating only after propose → confirm; `<P>` = `-p <project>`, see naming below):
  ```bash
  cd <EXECUTION_DIR> && docker compose <P> config          # validate: resolves vars, catches syntax errors — run first
  cd <EXECUTION_DIR> && docker compose <P> ps              # state of this stack
  cd <EXECUTION_DIR> && docker compose <P> logs --tail=50 <service>   # no follow by default
  cd <EXECUTION_DIR> && docker compose <P> up -d --build   # mutating: propose first
  cd <EXECUTION_DIR> && docker compose <P> down            # mutating: propose first, confirm volumes kept
  ```
- **Project naming (mandatory `-p`)**: the hermes container exports `COMPOSE_PROJECT_NAME=pai-stack`, which overrides compose's directory-based default — bare `docker compose ps` inside a project dir will list pai-stack, not the project. ALWAYS pass `-p <project>` (basename of `EXECUTION_DIR`, or the `name:` in the project's compose file) or inline `COMPOSE_PROJECT_NAME=<project>`:
  ```bash
  cd <EXECUTION_DIR> && docker compose -p ytune ps
  ```
  `docker compose ls` lists all host projects visible over the socket — use it to confirm the project name before mutating.
- **Env & secrets**: compose reads `<EXECUTION_DIR>/.env` — verify required vars exist before `up`; use `${VAR:-default}` substitution; never commit `.env`; flag raw secrets in `environment:` blocks.
- **Safety**: never add `--privileged`, host network mode, or `/var/run/docker.sock` mounts to project stacks; keep `restart: unless-stopped`, healthchecks, and `deploy.resources.limits` on every service.

## Tooling (absolute paths — skill dirs mount read-only)
- Analyze: `python3 /opt/pai/skills/docker-development/scripts/dockerfile_analyzer.py <Dockerfile>`
- Validate: `python3 /opt/pai/skills/docker-development/scripts/compose_validator.py <compose.yaml>`
- **Severity caveat**: the validator flags standard `${VAR}` substitutions as CRITICAL — treat its severities as **advisory only**; verify each finding against the file before acting.

## Delegate (load via `skill_view`)
| Need | Load |
|---|---|
| Optimization checklists, multi-stage patterns, security audit tables | `docker-development` |
