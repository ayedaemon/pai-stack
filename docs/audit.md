# Audit — 2026-10-05

Full-stack review of pai-stack: services, processes, permissions, and the docs that
describe them. `docs/terrain.md` was used as the reference anchor for correlating
the rest, which is itself one of the findings.

Two tiers below. **Verified** = I opened the file and confirmed the line. **Reported**
= surfaced by an auditor and consistent with what I read, but not independently
re-verified in this pass. Nothing here was fixed — this file records state.

## Verified — breaks the documented system

| # | Sev | Finding | Evidence |
|---|---|---|---|
| 1 | security | **`pai_terrain_ops` is never enabled.** The plugin is baked into the image but is the only baked plugin missing from `plugins.enabled`, so the tool AGENTS.md tells every agent to prefer does not exist at runtime. Turn-1 step 8 of the startup protocol cannot fire. | `hermes/Dockerfile:81` bakes it; `hermes/config.yaml:324-341` omits it (zero `terrain` hits in the file) |
| 2 | security | **The LLM gate does not exist on `/mcp`.** `TERRAIN_ALLOW_LLM` is checked only inside the `/call` branch. `handleRpc` → `tools/call` → `run()` has no such check, so an MCP client can invoke `ask`/`init` at the default `TERRAIN_ALLOW_LLM=0`. Contradicts `terrain.md`, the compose comment, and architecture.md. | `terrain/server.mjs:306-311` inside `/call`; `terrain/server.mjs:231-239` unguarded; `handleRpc` contains 0 `ALLOW_LLM` references |
| 3 | inconsistency | **Per-repo serialisation does not serialise per repo.** The key is `action + '|' + path`, so `index|repo` and `refresh|repo` are different queues and can interleave writes into `.terrain/` — the exact corruption the chain was added to prevent. | `terrain/server.mjs:167` |
| 4 | inconsistency | **`ask`/`init` are advertised but unreachable from Hermes.** `terrain_ops.py` hard-rejects `LLM_ACTIONS` unconditionally, with no `TERRAIN_ALLOW_LLM` escape, while its own action enum and AGENTS.md list both actions. | `terrain_ops.py:177-184` vs `terrain_ops.py:35-46` and `AGENTS.md:150` |
| 5 | inconsistency | **`terrain.md`'s stated reason for the shim is false.** It claims *"DSH has no Docker socket"* — DSH mounts it `:ro`. And `pai_docker_ops` could not reach terrain anyway: it is scoped to `("hermes", "llm-gateway")`. | `docker-compose.dsh.yaml:153`; `docker_ops.py:24`; `terrain.md:63` |
| 6 | inconsistency | **Terrain's LLM backend is documented two opposite ways.** `opencode.json` pins a keyless Zen model with no provider/base_url; AGENTS.md and `terrain.md:107-142` say keyless Zen and no gateway link; but `terrain.md:104,220`, `Makefile:230`, `server.mjs:195,329` and an 11-line `terrain/Dockerfile:151-161` comment all still say "gateway". The Dockerfile comment is the worst: it cites an AGENTS.md line that no longer exists and quotes an auth error as evidence for a config that was since removed. | as cited |
| 7 | security | **Three plugin env vars never reach Hermes.** `TERRAIN_TOKEN`, `TERRAIN_URL` and `OD_API_TOKEN` are read by plugin code and absent from the hermes environment block. So the documented token is a one-way lock (set it and every call 401s) and the OpenDesign bridge can never authenticate. | `docker-compose.yaml:12-47` vs `terrain_ops.py:29-32`, `ops_design_ops.py:78-79` |
| 8 | security | **`hermes` runs as uid 0 with the docker socket and zero hardening** while all three opt-in profiles declare `read_only`, `cap_drop: [ALL]`, `no-new-privileges`, `pids_limit`. It is also published on **0.0.0.0** (`:9119`, `:8642`), as is `llm-gateway` (`:4000`). AGENTS.md and operations.md both describe docker-compose.yaml as carrying resource limits. | `docker-compose.yaml:48-55` (absent hardening) vs `terrain.yaml:70-83`, `dsh.yaml:169-189` |
| 9 | error | **The `code-intel` removal is uncommitted while its replacement is untracked.** The three deletions are unstaged; `docker-compose.terrain.yaml`, `docs/terrain.md`, `terrain/`, `pai_terrain_ops/` are all untracked. A `git commit -a` would ship the removal *without* the replacement. | `git status`: ` D hermes/plugins/pai_tools/code_intel.py`, ` D skills/code-intel/*`, and 7 `??` entries |
| 10 | error | **`od_design_ops` does not exist.** The `opendesign-tool` skill calls it 6 times; the registered tool is `pai_ops_design_ops`. A model that loads that skill will chase a tool that is not there. | `skills/opendesign-tool/SKILL.md` (6 refs) vs `pai_tools/plugin.yaml:4-8` |
| 11 | error | **Four referenced skills do not exist**: `writing-plans`, `executing-plans`, `using-git-worktrees`, `finishing-a-development-branch` — all routed to via "the superpowers plugin", which is not in `plugins.enabled` and has no directory. | `AGENTS.md:130,132`; `skills/agents/SKILL.md:78-79`; `ls skills/` |
| 12 | inconsistency | **`docs/operations.md` is stale.** Zero mentions of terrain: all 8 `terrain-*` targets, all 7 `TERRAIN_*` env keys, and terrain's absence from Access and Repo layout. It is the Makefile's declared "full reference". | `grep -c terrain docs/operations.md` → `0` |
| 13 | error | **Gateway's first fallback is the primary route.** `default` → `mistral/kilo-auto/free` @ `api.kilo.ai`; `fallbacks[0]` is `kilo/kilo-auto/free` — the same upstream, so the first fallback re-issues the identical failing call. | `llm-gateway/config.yaml:10-16`, `:214-218` |
| 14 | inconsistency | **Gateway Langfuse is not wired.** AGENTS.md says Langfuse "IS the audit trail" and operations.md lists gateway telemetry, but the config has no `litellm_settings` and no `success_callback`; `LANGFUSE_*` is passed as env that this config never reads. Hermes *does* wire it via the `observability/langfuse` plugin. | `llm-gateway/config.yaml` (no callbacks block); `docker-compose.yaml:97-99`; `hermes/config.yaml:326` |
| 15 | inconsistency | **`open-design` "memory uncapped on purpose" is contradicted by its own compose** — `NODE_OPTIONS: --max-old-space-size=192` caps the V8 heap at 192 MB, less than half the 384 MB the docs cite as too small. | `docker-compose.opendesign.yaml:54` vs `docs/opendesign.md` / compose comment `:39-41` |

## Reported — consistent, not independently re-verified

- Gateway `general_settings` appear inert at runtime: `drop_params` resolves False and
  `request_timeout` stays at the 6000 s default despite the config declaring both. 9 of 27
  routes carry no per-model `drop_params` (verified count: 18 of 27 do).
- `LITELLM_MASTER_KEY` is unset, the gateway logs `LITELLM_MASTER_KEY is not set! All requests
  will be treated as INTERNAL_USER`, and unauthenticated `GET /v1/models` returns 200 on a port
  bound to 0.0.0.0.
- `DSH_IMAGE` cannot select a stock upstream image — `build:` is unconditional in
  `docker-compose.dsh.yaml`.
- `docs/dsh.md` states the DSH skill count three incompatible ways against 30 real skills, and
  claims "CAP_DAC_OVERRIDE was never needed" while the compose grants it.
- `DEEPSEEK_BASE_URL` is simultaneously documented as set in `.env`, hardcoded in compose, and
  declared unconsumed.
- `make design-import` and three docs point at `/workspace`; compose mounts `/opt/data/workspace`.
- Terrain's `confine()` is applied to `path`/`repo_path` but **not** to `params.file`, which is
  pushed verbatim as `--file`.
- The MCP `inputSchema` declares properties but no `required` array, so every tool accepts `{}`.
- `/healthz` is answered *before* the token check, unauthenticated, leaking the workspace path,
  commit ref and the LLM action list.
- The `chains` Map is never pruned — one entry per action/target pair, for the container's life.
- Skill-name drift: `AGENTS.md` names 24, `docs/hermes.md` names 22, 30 directories are mounted;
  6 mounted skills (`tmux`, `ponytail`, `full-stack-workflow`, `autonomous-tech-learner`,
  `opendesign-integration`, `opendesign-tool`) have no table row.
- `FS_NOTIFIER_DEBOUNCE_SECONDS` ships in `.env.example` and live `.env` with no consumer
  anywhere. **Verified.**
- `Makefile:80` help says `terrain-index d=/opt/data/<dir>`; the recipe at `:226` says
  `d=/opt/data/workspace/<folder>`. **Verified.**
- The `setpriv`/socat/seed chain for DSH is inherited from the upstream base image — no
  entrypoint or plugin source exists in the repo, so none of it is verifiable from these files.

## What is *correct* — do not "fix" these

The audit confirms the load-bearing claims behind terrain's design, which are easy to doubt:

- The closed action allowlist is complete. `ACTIONS` is a static literal, `spawn()` always
  takes an argv array, and no caller input can reach `env`/`sdd`/`settings`/`usage`/`tools`.
- Path confinement holds: relative resolution against `WORKSPACE`, prefix check, `realpath`
  re-check, 403 before spawn.
- `seedAcpConfig` genuinely never overwrites (`if (existsSync(dst)) return`).
- `HOME=/var/lib/terrain` with the registry at `~/.terrain/registry.json`, off the shared mount —
  and `terrain-perms` deliberately chowns to 1000:1000 rather than the host uid, with the
  reasoning written down in the Makefile.
- The 10-minute spawn timeout is honoured on both `/call` and `/mcp`, since both go through `run()`.
- Dockerfile gates that would have caught real breakage are present and correct: the
  same-Debian-major pairing, the `--version` run in the *final* image, and the
  `/src/crates/terrain-core/../../preset_skills/...` `cat` gate (including the empty crate dir,
  which is load-bearing for POSIX `..` traversal).
- `make up` genuinely starts only hermes + llm-gateway; all three opt-in profiles are gated.
- Every documented `make` target and every port number resolves correctly.

## Suggested order of work

1. **Enable `pai_terrain_ops`** in `hermes/config.yaml` — one line, unblocks the entire Terrain story.
2. **Move the `TERRAIN_ALLOW_LLM` check** so both `/call` and `/mcp` pass through it.
3. **Fix the serialisation key** to key on path only for mutating actions.
4. **Commit the removal and its replacement together** — right now they are in opposite states.
5. **Sweep the "gateway" claims** in `terrain.md`, `Makefile`, `server.mjs` and `terrain/Dockerfile`
   to the keyless-Zen truth that `opencode.json` already implements.
6. Decide whether `hermes` gets containment parity or an explicit, documented exemption.
