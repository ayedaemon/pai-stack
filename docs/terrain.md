# Terrain — Code Intelligence Service

> Optional profile. Start with `make terrain-up`. Reference card for
> [`AGENTS.md`](../AGENTS.md); architecture context in
> [`architecture.md`](architecture.md); process-level view in
> [`architecture.md` → Process model](architecture.md#process-model).

Terrain ([sopaco/terrain](https://github.com/sopaco/terrain), MIT) scans a project
repo into `.terrain/` — Markdown knowledge docs, an agent context layer, and a
repomix source pack. It replaces `pai_code_intel`, removed 2026-10-04.

## Why it is a separate container

The tool it replaces built a tree-sitter index **in every agent's heap**. Two
measurements ended that:

- the workspace-wide surface was **27,291 files**, of which **11,505 (42%)** were a
  Go toolchain that had leaked into the mount via `HOME=/opt/data/workspace`;
- DSH's heap cap is **1,216 MB** (`NODE_OPTIONS=--max-old-space-size=1024`).

Neither agent can afford a resident index, and duplicating one per agent is exactly
what we did not want. Terrain inverts it: **one container owns the index**, agents
trigger jobs and read the result.

```
hermes ─┐
        ├──→ POST /call ──→ terrain:7878 ──→ <repo>/.terrain/
dsh     ┘                     (one writer)
```

That inversion is a process decision, not a packaging one — the shim is stateless
and the `terrain` binary runs as a fresh process per call, so no agent heap ever
grows. Full view: [`architecture.md` → Process model](architecture.md#process-model).

## Why it is built from source

Terrain publishes prebuilt binaries for `darwin-arm64` and `win32-x64` only.
`@terrain-ai/cli-linux-x64` is **not on npm**, and pai-stack is Linux-only. So
[`terrain/Dockerfile`](../terrain/Dockerfile) builds it in two stages:

| Stage | Base | Contents |
|---|---|---|
| build | `rust:1.94-slim` (Debian 13 trixie, glibc 2.41) | `cargo build --release -p terrain-cli` |
| runtime | `debian:trixie-slim` (Debian 13 trixie, glibc 2.41) | the `terrain` binary + `server.mjs` + `nodejs` |

The two bases **must be the same Debian major**. This was not hypothetical: the
runtime was originally `bookworm-slim` (glibc 2.36) while `rust:1.94-slim` is
trixie (2.41), so the freshly built binary failed at the build's `--version`
gate with `version 'GLIBC_2.38' not found`. `rust:*-slim` tracks current Debian
stable, so re-check both when bumping the toolchain tag rather than assuming the
tag implies a distro.

The runtime also needs `nodejs`: the ENTRYPOINT is `node /opt/terrain/server.mjs`
even though the terrain binary itself is Rust. The shim uses only Node's stdlib, so
the distro package suffices — no install stage, no version to drift.

`src-tauri` is a cargo workspace member, but `terrain-cli` does not depend on it, so
the webkit/GTK chain never enters the image. `rust-toolchain.toml` pins stable;
edition 2024 means **MSRV 1.94**.

**The first build is slow** (LTO + `codegen-units=1`). Later builds reuse the layer cache.

## Why there is a shim

The Terrain CLI has **no `serve` or daemon subcommand** — it is a CLI only.
Both agents reach it over the network instead of `docker exec`: DSH has no
in-process access to the binary, and Hermes reaches it through
`pai_terrain_ops` rather than the socket. Without a network endpoint neither
would get anything.

[`terrain/server.mjs`](../terrain/server.mjs) fronts the binary on one port:

| Endpoint | Consumer | Protocol |
|---|---|---|
| `GET /healthz` | compose healthcheck, both clients' availability probe | plain HTTP |
| `POST /call` | Hermes (`pai_terrain_ops`), DSH (`dsh-pai-terrain`) | JSON |

**One transport, two consumers.** Both plugins speak `POST /call`. An earlier
revision also exposed `POST /mcp` (hand-rolled JSON-RPC) on the theory that DSH
would reach terrain through `@deepseek-ai/dsh-mcp-client`; that never happened —
DSH ships a native TypeScript plugin against `/call` instead. The MCP endpoint had
zero consumers, so it was removed rather than left as unexercised surface. The
lesson: the transport a plugin *would* use is not the transport it *does* use.
Check the shipped plugin, not the design doc.

## Two safety invariants

**1. A closed action allowlist.** `terrain env apply` rewrites `AGENTS.md` and installs
preset skills from `.agents/skills` — it would overwrite files pai-stack owns. So the
shim exposes only:

```
index  refresh  search  read  overview  projects  unregister  source  init  ask
```

`env`, `sdd`, `settings`, `usage` and the raw `tools` surface are unreachable — an
unknown action is rejected by name, so they cannot even be invoked.

**2. Path confinement.** `index`/`refresh`/`init` targets must resolve inside
`/opt/data/workspace`; anything else returns `403` before the Terrain binary runs.
Without this, any agent holding the tool could point Terrain at the container image.

## Token cost

| Action | LLM? | Cost |
|---|---|---|
| `index`, `refresh`, `search`, `read`, `source`, `overview`, `projects`, `unregister` | no | free |
| `init` | yes (Litho doc generation) | keyless Zen — no tokens |
| `ask` | yes (DeepWiki Q&A) | keyless Zen — no tokens |

`refresh` explicitly **skips Litho**, Terrain's LLM doc generator, so incremental
re-indexing is free. `init` and `ask` are always available — there is no feature
flag. They do **not** use `llm-gateway` — terrain spawns an ACP agent that runs on
OpenCode's keyless Zen models, so no provider key exists in this container and they
cost latency, not tokens.

Two consequences:

- **`init` is the expensive action.** It regenerates a whole corpus through the ACP
  agent. `index` and `refresh` are free and safe to suggest freely; `init` should be
  requested rather than run unprompted. Note also that a stale `human_docs` asset
  survives any number of `refresh` calls — only `init` regenerates that corpus.
- **Provider credentials leaking into this container is a live footgun**, because
  nothing gates these actions any more. See below; `server.mjs` deletes them before
  every spawn.

### `init` and `ask` need an ACP agent — and it must NOT see `OPENAI_API_KEY`

Terrain does not write its knowledge assets through an OpenAI-compatible endpoint —
it **spawns an ACP agent subprocess** (`settings check-acp` →
`spawn_command: "opencode acp"`). The image ships opencode 2.0.16 in `/opt/opencode`
with a keyless Zen config symlinked into `$XDG_CONFIG_HOME` at boot.

**Prohibition: `OPENAI_API_KEY` (and any other provider credential) must never be
present in this container.** `init` and `ask` work only while it is absent.
That is counter-intuitive, because the key looks harmless — but it is the single
thing that breaks them:

- With `OPENAI_API_KEY=not-needed` exported, opencode reports the OpenAI provider
  as authenticated (`auth list` → `OpenAI OPENAI_API_KEY environment`).
- `opencode acp` then **ignores `opencode.json`'s model** and pins the session to
  a catalog OpenAI model (`openai/gpt-6.1-sol`). Driving the ACP protocol by hand
  shows the model list is `openai/*` only — Zen and custom providers are not
  offered at all.
- That model is then called against a backend that cannot serve it, and the
  session dies at first prompt with:
  ```
  Error: Litho agent failed: ACP protocol error: Authentication required:
         provider authentication required
  ```
- With the key removed, the `openai` provider is no longer "available", opencode
  falls back to the configured Zen model, and both actions succeed.

So the fix is **subtractive**: delete `OPENAI_BASE_URL` and `OPENAI_API_KEY` from the `terrain` service in `docker-compose.yaml` (there is no `depends_on` on `llm-gateway` either). Terrain then has no link to the gateway at all, and its LLM work runs on OpenCode's keyless Zen models — the same exception `opencode-delegate` already makes in hermes.

**This is now enforced, not just documented.** The terrain service declares an explicit
`environment:` map with no `env_file:` and no `- VAR` passthrough, so nothing in `.env`
reaches the container in the first place. On top of that, `server.mjs` deletes
`PROVIDER_KEYS` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`,
`NVIDIA_API_KEY`) from every spawned child's environment, and logs a boot warning naming
any that were present in the shim's own env. The keys are **deleted, not blanked** —
`ENV FOO=""` leaves `FOO` defined, and provider selection branches on presence rather than
truthiness, so blanking would trade a guaranteed-absent variable for an ambiguous one. Do
not add an `ENV`/`ARG` for this in `terrain/Dockerfile`: a build arg only persists into
image history, which is a downgrade.

Verified end to end after the change: `init` → 13 human docs +
agent context, `litho_ran: true`, status `partial` → `ready` (~6 min);
`ask` → answered with real file:line citations (~60 s).

### When a Zen model is retired

The keyless Zen slugs are **not stable**. They get dropped upstream with no
deprecation here, and the failure is quiet in a specific way:

```
docker exec terrain opencode run --model opencode/<old-slug> 'reply OK'
# Error: Model unavailable: opencode/<old-slug>
```

`terrain settings check-acp` still reports `{"available": true}` throughout,
because that only proves the **binary** exists — not the model.

**The shim now catches this at boot.** It runs `opencode models` (~50 ms) and
compares the pinned model against the live keyless pool, so a retired slug is a
banner line rather than a 10-minute hang:

```
[terrain] ACP model opencode/space-bunny-free verified against 10 keyless model(s)
```

and when it fails:

```
[terrain] ERROR: ACP model opencode/<old> is NOT available keylessly — init and ask WILL FAIL.
           Retired upstream; nothing in this container changed. Live alternatives:
             opencode/space-bunny-free
             ...
           Fix: edit "model" in terrain/opencode.json, then make terrain-build && make terrain-up.
```

It is never fatal: `scan`, `search`, `read`, `source` and `projects` are offline
and keep working. Only `init` and `ask` are affected.

#### Which models are actually available

`opencode models` is the **only** source of truth. models.dev is a catalog that
disagreed with reality for weeks — it still listed `muse-spark-1.3-contributor-free`
at `cost: 0` long after the keyless pool dropped it, and it advertises ~50 "free"
models where only ~10 are keyless. Do not rebuild a model list from the catalog.

[`scripts/opencode-free-models.py`](../scripts/opencode-free-models.py) keeps the
two straight: availability comes from the CLI, and models.dev is used only to
enrich context/output windows. It also flags upstream `status: deprecated`, vision
input, and the `big-pickle` alias (whose backing model can change without the slug
changing — a poor choice for a knowledge corpus).

```bash
make free-models              # ranked table of what is live, largest context first
make free-models --min-context 500000
make free-models-check        # is the model pinned in terrain/opencode.json still keyless?
make free-models-allowlist    # emit ids for a shell allowlist
```

Then edit `"model"` in [`terrain/opencode.json`](../terrain/opencode.json) and
rebuild (`make terrain-build && make terrain-up`). The file is symlinked into
`$XDG_CONFIG_HOME` at boot, so the image copy is the single source of truth — no
volume cleanup needed.

The shim prints the pinned model in its boot banner and returns it from
`/healthz` as `acpModel` so this is visible without spelunking the container.

Two related traps:

- **`terrain settings set <file.json>` replaces the whole file with no
  validation.** A partial JSON silently drops `base_url`. Always write the full
  `provider`/`model`/`api_key`/`base_url` block.
- **`check-llm` does not validate the model name** — it reported `ready: true`
  for a model the gateway did not serve. Do not trust it.

## Usage

```bash
make terrain-up                      # build + start (opt-in)
make terrain-index d=/opt/data/workspace/github.com/ayedaemon/pai-stack
make terrain-build                   # rebuild after bumping TERRAIN_REF
make terrain-config                  # validate compose config with terrain profile
make terrain-down                    # stop; workspace and volume untouched
make terrain-ask q="where is auth enforced?"   # keyless Zen, no tokens
make free-models-check             # is the pinned ACP model still keyless?
```

From inside Hermes, via `pai_terrain_ops`:

```jsonc
{"action": "projects"}                                        // what is indexed?
{"action": "index",  "path": "github.com/ayedaemon/pai-stack"} // index (free)
{"action": "search", "query": "workspace mount", "project": "pai-stack"}
// `source` takes TWO paths with DIFFERENT bases — this is the single easiest
// thing to get wrong. `path` is repo-relative; `file` is resolved against
// /opt/data/workspace, so it must repeat the project directory.
{"action": "source", "path": "github.com/ayedaemon/pai-stack",
                   "file": "github.com/ayedaemon/pai-stack/hermes/plugins/pai_terrain_ops/terrain_ops.py"}
```

A bare `{"action": "source", "file": "README.md"}` fails with
`no such file: /opt/data/workspace/README.md` — the shim confines `file` against the
workspace root, not against the repo.

## From DSH

DSH reaches terrain through a native plugin,
[`dsh/plugins/dsh-pai-terrain`](../dsh/plugins/dsh-pai-terrain), which calls the same
`POST /call` endpoint Hermes uses and exposes the same `pai_terrain_ops` tool with
the same ten actions.

It is enabled by default via
[`cordis.patch.yml`](../dsh/plugins/dsh-pai-terrain/cordis.patch.yml) and gated only
by the overall `DSH_WITH_PAI_PLUGINS` build flag. It also ships `paiTerrainHealth`,
a provided service wrapping the `/healthz` probe.

> **Not MCP.** An earlier revision of this doc claimed DSH connected through
> `@deepseek-ai/dsh-mcp-client` to `POST /mcp`, and the shim implemented a
> hand-rolled JSON-RPC endpoint to match. In practice DSH uses the TypeScript
> plugin above, the MCP endpoint had no consumers, and it has been removed. There
> is no `mcpServers` config anywhere in this repo.

## `.terrain/` is gitignored

The index is **per-host, not per-repo-lifetime**. Indexing once benefits every agent
on this host — Hermes and DSH share both the workspace mount and the service — but it
does not travel to teammates through git.

To share it instead, commit only the small agent-context file and keep the bulk
regenerated locally:

```gitignore
.terrain/agent/repomix.md
.terrain/agent/codegraph*
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TERRAIN_REF` | `main` | git ref to build (pin deliberately — `.terrain/` format may change) |
| `TERRAIN_IMAGE` | `pai-stack-terrain:latest` | built image tag |
| `TERRAIN_PORT` | `7878` | host bind port |
| `TERRAIN_BIND_IP` | `127.0.0.1` | host bind address |
| `TERRAIN_TOKEN` | *(unset)* | if set, callers must send `x-terrain-token` — see the caveat below |
| `TERRAIN_MEM_LIMIT` | `2g` | memory ceiling |

There is no flag for `ask` / `init`. They are always on, because they cost latency
rather than tokens — see [Token cost](#token-cost). The model itself is not a
variable either: it is pinned in [`terrain/opencode.json`](../terrain/opencode.json)
and edited there.

The project registry lives in the `terrain_data` volume at
`/var/lib/terrain/.terrain/registry.json` — deliberately **not** on the workspace
bind, since it is host state rather than repo content.

### The registry and the index have different lifetimes

Those two paths are on **different mounts**, so they can survive or die independently:
the registry is in the `terrain_data` Docker volume; `.terrain/` is inside the indexed
repo on the workspace bind mount. Recreating the volume — `docker compose down -v`,
a renamed project, a manual `docker volume rm` — silently drops `registry.json` while
every index artifact survives intact on disk.

The symptom is `pai_terrain_ops(action="projects")` returning `[]` while
`<repo>/.terrain/` is fully populated. That breaks everything project-scoped:
`overview`, `search --project`, and `ask --project` all have no target. It reads like
"terrain lost my index" but the index is fine — only its address book is gone.

**Recovery:**

```bash
make terrain-index d=/opt/data/workspace/<project>     # = terrain scan; free, no LLM
```

`scan` re-registers the project and reuses the index already on disk. Do **not** reach
for a different verb to "fix" this: there is nothing to rebuild, and re-scanning is
cheaper than any repair. The `index-health` skill detects this state automatically and
names the command without running it.

## Degradation — this is the designed default, not a failure

**Terrain is a temporary accelerator.** The baseline for locating code in this stack is
`grep` plus targeted reads using the agent's own tools; that path always works and is what
an agent should reach for by default. Terrain adds a shared index when it happens to be
running.

`pai_terrain_ops.check_fn` probes `/healthz` with a 3s timeout and **hides the tool**
when the service is down, so an agent cannot even see a tool that would fail. Removing
Terrain is therefore a supported operation, not a migration:

```bash
make terrain-down          # stop the profile
rm -rf <repo>/.terrain/    # gitignored artifacts, safe to delete
```

Nothing in the core stack references it.

## `TERRAIN_TOKEN` — off by design

The shim accepts an optional shared secret (`x-terrain-token`). Both clients send it
when set — compose passes `TERRAIN_TOKEN` into the hermes service — but the shipped
configuration leaves it **empty on purpose**.

Terrain is a **shared LAN service**: Hermes, DSH, and any other agent on the network
are all meant to reach `terrain:7878` and use the one shared index. Requiring a token
would mean every agent on the LAN needs the secret before it can read code
intelligence, which trades a deliberate sharing boundary for a secret-distribution
problem on a trusted home network.

What actually constrains an open `/call`:

- a **closed action allowlist** — ten actions; `env`, `sdd`, `settings`, `usage` and
  the raw `tools` surface are unreachable and rejected by name;
- **path confinement** — every path parameter must resolve inside
  `/opt/data/workspace`, checked twice (lexically and via `realpathSync`) before the
  binary runs;
- **argv arrays, never a shell**, so parameters cannot inject;
- **no credential in the container**, so the ACP agent cannot reach a paid backend.

That is a containment boundary, not an authorization boundary. It assumes the network
is trusted — do not expose this port to the public internet, and if you ever need to,
set `TERRAIN_TOKEN` (it is wired on both sides; nothing else changes).

`/healthz` is unauthenticated either way — it returns only the commit ref, workspace
path, and pinned ACP model.