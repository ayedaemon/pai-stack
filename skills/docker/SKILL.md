---
name: docker
description: Docker discovery router — map Dockerfiles, compose services, volumes, and networks in this repo. Load on Dockerfile/compose/container questions or when stack-discovery finds them. Delegates optimization, validator tooling, and security hardening to docker-development.
---

# Docker (router)

> You own repo **service mapping**. Optimization and audit depth live upstream.
> Shared Hermes glue is canonical in the `agents` skill.

## ⚠️ Tool Selection — MANDATORY FIRST STEP

Before ANY docker action, determine which tool to use. This is non-negotiable:

```
Does EXECUTION_DIR contain a compose file?
(docker-compose*.yaml OR compose.yaml)
│
├── YES → Use `docker compose -p <project_name>` CLI ONLY
│         NEVER use pai_docker_ops for this project's containers.
│         NEVER use bare `docker run` / `docker create`.
│
└── NO  → Is it a pai-stack service (hermes, llm-gateway)?
          ├── YES → Use pai_docker_ops
          └── NO  → Use `docker run` only after user confirmation.
                    Document why no compose file exists.
```

**NEVER rules (hard invariants — no exceptions):**
- NEVER call `pai_docker_ops` for a container that is not `hermes` or `llm-gateway`.
- NEVER run `docker run`, `docker create`, or `docker start <name>` for a project that has a compose file.
- NEVER run `docker compose` without `-p <project_name>` (pai-stack exports `COMPOSE_PROJECT_NAME=pai-stack`, which would hijack all bare compose commands).
- NEVER run `docker compose up/down/restart` from a directory other than `EXECUTION_DIR`.
- NEVER create or modify containers in the pai-stack compose cluster for a project that is not pai-stack.

## Discover (validate cheaply: `docker compose config` before proposing `up --build`)
1. **Artifacts**: `Dockerfile*`, `docker-compose*.yaml`, `compose.yaml`, `.dockerignore`, `Makefile` targets (`make status`/`logs`).
2. **Dockerfile**: `FROM` + stages, `COPY` context hygiene, `RUN` caching, `USER`/`EXPOSE`/`ENTRYPOINT`/`HEALTHCHECK`. Pai notes: `hermes/Dockerfile` + `entrypoint.sh` patterns when relevant.
3. **Compose**: service→port map, named vs bind volumes (`EACCES`/`UID` risk, `deploy.resources.limits`), networks, `extra_hosts: host.docker.internal`, env provenance (host `.env` vs hardcoded — flag raw secrets).
4. **Conventions**: multi-stage, minimal base, non-root `USER`, pinned tags (never `:latest`), `.dockerignore` present. Never suggest `--privileged` or public `0.0.0.0` outside Tailscale.

## Stack projects — isolated compose cluster per project

Applies when `stack-discovery` finds compose markers (`compose.yaml`, `docker-compose*.yaml`) in `EXECUTION_DIR`. Each project that has a compose file **must run in its own isolated Docker compose cluster**, separate from the pai-stack cluster.

- **Why isolation matters**: Hermes runs with the host Docker socket mounted. The hermes process also exports `COMPOSE_PROJECT_NAME=pai-stack`. Without `-p <project_name>`, every `docker compose` command — regardless of working directory — will operate on the pai-stack cluster instead of the project's cluster. This silently adds the project's containers to pai-stack's network, naming space, and lifecycle.
- **Scope split**: pai-stack services (`hermes`, `llm-gateway`) → `pai_docker_ops`. Every other project with a compose file → `docker compose -p <project_name>` CLI via the mounted socket. Never cross the streams.
- **Always anchor**: every compose invocation runs with `cd <EXECUTION_DIR>` first. Compose v2 syntax only: `docker compose` (no hyphen).
- **Project name**: use the `name:` field from the project's compose file if present; otherwise use the basename of `EXECUTION_DIR`. Run `docker compose ls` to confirm the active cluster name before any mutating operation.
- **Lifecycle** (read-only freely; mutating only after propose → confirm):
  ```bash
  cd <EXECUTION_DIR> && docker compose -p <project_name> config          # validate first — resolves vars, catches syntax errors
  cd <EXECUTION_DIR> && docker compose -p <project_name> ps              # state of THIS project's cluster only
  cd <EXECUTION_DIR> && docker compose -p <project_name> logs --tail=50 <service>
  cd <EXECUTION_DIR> && docker compose -p <project_name> up -d --build   # mutating: propose first
  cd <EXECUTION_DIR> && docker compose -p <project_name> down            # mutating: propose first, confirm volumes kept
  ```
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
