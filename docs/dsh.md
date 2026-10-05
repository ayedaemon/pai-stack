# DSH (DeepSeek Harness) — Optional Container

DeepSeek Harness on the opt-in `dsh` profile. Never starts with `make up`.

## Image

**`ghcr.io/steven-stack-s/dsh-docker-server:latest`** (or pin a version tag)

| Layer | What it is |
|---|---|
| Base | `node:24-slim` + git + socat + openssh-client + ca-certificates |
| Toolchain | `python3` + `uv`, `go`, `rustc`/`cargo` + C toolchain — see [Toolchain](#toolchain) |
| Docker CLI | `docker-ce-cli` + `docker-compose-plugin` + `jq`, client-only (no daemon) — backs the [Docker socket](#docker-socket) |
| DSH program | `@deepseek-ai/dsh@0.2.0-rc.2` pre-installed into `/opt/dsh-seed` at build time |
| Runtime | Seed copied to `/opt/dsh` volume on first boot (offline, version-pinned) |
| Web UI | `dsh web` on `127.0.0.1:3081`, socat forwards `0.0.0.0:3080` → `3081` |
| Auth | `@xgone/dsh-remote` plugin — admin + random 16-char password (printed once in first-boot logs) |
| Security | Non-root (uid 1000), read-only root FS, `no-new-privileges`, `cap_drop: [ALL]` + 4 minimal caps |
| Self-healing | Rescue system: snapshot rollback → plugin removal → escalated rollback → lifeboat |

**Pin a version** (locked to `dsh@0.2.0-rc.2`):

```bash
# .env
DSH_IMAGE=ghcr.io/steven-stack-s/dsh-docker-server:v0.6.0-dsh-0.2.0-rc.2
```

## Toolchain

The container ships **Python 3, Go, and Rust** so agents can run the test suites of the projects they edit instead of only reading them. Installed by [`dsh/Dockerfile`](../dsh/Dockerfile), alongside the Mnemon CLI.

| Tool | Version | Path |
|---|---|---|
| Python | 3.11 (Debian 12) + `python3-dev`/`python3-venv` | `/usr/bin/python3` |
| uv | 0.12.23 | `/usr/local/bin/uv`, `uvx` |
| Go | 1.27.1 (linux arm64/amd64, checksum-verified) | `/usr/local/go` |
| Rust | rustc + cargo 1.99.0, minimal profile + `clippy` + `rustfmt` | `/usr/local/cargo`, `/usr/local/rustup` |
| C toolchain | `build-essential`, `pkg-config`, `libssl-dev` | `/usr/bin/cc` |

**Why build-time.** The container is `read_only: true` with `cap_drop: [ALL]`, so nothing can be installed after boot — same constraint that forced `mnemon` into the image.

**Why the C toolchain.** Not for Go or Rust, which compile natively. It's for Python C extensions: `uv sync` on any project pulling `pydantic-core`, `numpy`, `cryptography` or `orjson` needs a compiler and `python3-dev` at install time, and dies halfway without them.

### Caches live on the volume, never in the workspace

`HOME=/opt/data/workspace`, so every default cache path would scatter build artifacts into the shared host workspace that Hermes also reads. `docker-compose.dsh.yaml` redirects them onto the `dsh_data` volume instead — the toolchains stay read-only in `/usr/local`, only mutable state moves:

`GOCACHE`, `GOMODCACHE`, `GOPATH`, `CARGO_HOME`, `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `PIP_CACHE_DIR` → all under `/data/dsh/toolchains/`. Each directory is created on first use by its own tool; nothing needs a pre-seed step.

#### Consequence: build commands need an approval escalation

That location sits outside the agent's sandbox, and it cannot be otherwise — DSH's sandbox policy (`@deepseek-ai/dsh-sandbox-policy`) exposes only `mode` and `workspaceRoot`: **one** writable root, the session cwd, with no extra-roots allowlist and only three modes (`read-only`, `workspace-write`, `danger-full-access`).

So under the default `workspace-write`, `/data/dsh` is unreachable by design and any command that *writes* a cache — `go build`, `go test`, `cargo build`, `uv sync`, `uvx` — fails with `permission denied` until the call is retried with an approval escalation. Pure-read commands (`go doc`, `cargo fmt --check`, `ruff --version`) are unaffected. Verified Oct-2026: escalated, all three toolchains build and test normally against these exact paths.

Don't try to relocate the caches to dodge this — each alternative is worse:

- `/opt/data/workspace` **root** is outside the boundary too; the boundary is the session cwd (the project dir), not the workspace root.
- `/tmp` is a 128 MB tmpfs, which a cargo registry exhausts.
- Putting them in the project buries GBs in a git working tree.

### Usage

```bash
# Python — uv-managed interpreters, not the system one
uv python install 3.13            # lands in UV_PYTHON_INSTALL_DIR (the volume)
cd "$EXECUTION_DIR" && uv sync && uv run pytest

# Go — build cache and module cache are already pointed at the volume
cd "$EXECUTION_DIR" && go test ./...

# Rust — the rustup proxies in /usr/local/cargo/bin dispatch via RUSTUP_HOME,
# so overriding CARGO_HOME at runtime costs nothing
cd "$EXECUTION_DIR" && cargo test
```

### Caveats

| Symptom | Cause / fix |
|---|---|
| `pip install` → `externally-managed-environment` | Debian's PEP 668 marker. Expected — use `uv` or a venv, never a system-wide `pip`. |
| `cargo install`'d binary not found | It lands in `$CARGO_HOME/bin`, which isn't on `PATH`. `export PATH="$CARGO_HOME/bin:$PATH"`. |
| `error: $HOME differs from euid-obtained home directory` | Benign. `HOME` is the workspace bind mount, uid 1000's home is `/home/node`. rustup prints it and continues. |
| `rustup self update` fails | `RUSTUP_HOME` is in the read-only image layer. Bump `RUST_VERSION` and rebuild instead. |
| Build output appears in the repo | Expected. `cargo test` writes `target/` into the project, and `go build -o` writes the binary to the cwd — caches are redirected, *outputs* are not. Both belong in `.gitignore`. |
| `go: creating work dir: mkdir /data/dsh/tmp/…: permission denied` | Sandbox, not a broken install — the cache is on the volume, outside the writable root. Re-run with an approval escalation. Same for cargo's `Cannot create temporary file in /data/dsh/tmp/` and uv's `Failed to initialize cache`. See [Consequence](#consequence-build-commands-need-an-approval-escalation). |
| Disk | The volume grows with module/registry caches. `docker volume prune` is safe — it costs a re-download. |

### Bumping versions

Edit the ARGs at the top of [`dsh/Dockerfile`](../dsh/Dockerfile) and `make dsh-build && make dsh-up`.

- **Go** — `GO_VERSION` *and both* `GO_SHA256_*`. Read the new checksums from `https://go.dev/dl/?mode=json`; the build fails on a mismatch rather than installing an unverified tarball.
- **uv** — the release tag from GitHub.
- **Rust** — take the version from the `[pkg.rust]` block of `https://static.rust-lang.org/dist/channel-rust-<v>.toml`, **not** the first `version =` line of `channel-rust-stable.toml`: that one is *cargo's* (reads `0.100.0` while rustc reads `1.99.0`).

The image verifies every toolchain at the end of the build (`go version`, `cargo fmt --version`, …). A missing tool fails the build rather than surfacing mid-test-run.

## Pets

**There are none, deliberately.** DSH has no native pet feature — no `dsh pets` command, and no pet plugin among its 277 bundled packages. The image previously carried the third-party `petdex` gallery CLI plus a vendored `nightleaf` sprite; both are gone.

Why they were always dead weight: `petdex` targets **Codex / Petdex desktop** apps, which float a window on a real display. This container is headless — it serves a web UI and has no X11/Wayland — so nothing here could ever render them. The install was also silently broken (it resolved `$HOME` at build time to `/root`, mode `700`, which uid 1000 could not read).

Pets live in **hermes**, which has a real `hermes pets install` subcommand and seeds its sprite into `/opt/hermes/pets-seed` each boot. Use that one.

If a pet is ever wanted in dsh, the only viable route is a Web-UI plugin (e.g. `deepseek-harness-pets`, which renders into the `shell.overlay` slot and needs no display). That is a deliberate adoption with a supply-chain review — this container holds the docker socket, so third-party plugin code is a bigger deal than it looks.

## Run

```bash
make dsh-up       # create volume + fix ownership + build/start dsh
make dsh-logs     # tail logs
make dsh-down     # stop container only (workspace + volume untouched)
make dsh-config   # validate merged compose
make dsh-build    # rebuild image
```

UI: http://127.0.0.1:9229 (bound to `127.0.0.1` only by default). First visit needs the one-time token URL:

```bash
make dsh-password   # http://127.0.0.1:9229/?token=<one-time-token>
```

Later visits log in as `admin` + password. Password source of truth is `DSH_ADMIN_PASSWORD` in `.env` — it seeds the account DB on first boot and persists in the `dsh_data` volume (`auth/store.json`), so it survives restarts and rebuilds. Leave it empty for a random one-time password (printed once under `first-boot admin credentials`). To rotate: `make dsh-down`, delete `auth/store.json` from the `dsh_data` volume, set the new value, `make dsh-up`. Deliberately NOT baked into the image (image ENVs are readable via `docker inspect`).

## LLM Gateway

DSH connects to the same `llm-gateway:4000` LiteLLM proxy that Hermes uses (manually verified). Model key and base URL reuse the existing gateway vars — no new provider credentials.

```bash
# .env — DSH section (values mirror the llm-gateway's upstream)
DSH_IMAGE=ghcr.io/steven-stack-s/dsh-docker-server:v0.6.0-dsh-0.2.0-rc.2
DSH_PORT=9229
DEEPSEEK_API_KEY=${OPENAI_COMPATIBLE_API_KEY:-not-needed}
DEEPSEEK_BASE_URL=http://llm-gateway:4000/v1
```

`depends_on: llm-gateway (service_healthy)` so DSH never boots against a dead gateway.

> Env vars alone do NOT connect DSH: the built-in `deepseek-official` route
> is Anthropic-protocol pinned to `api.deepseek.com` and only reads the *key*
> from env. The gateway needs a **custom provider** (`openai-completions`
> protocol). Canonical copy: `dsh/settings.yaml` → `/data/dsh/settings.yaml`
> in the volume (one-time per fresh volume; UI edits merge into the same file,
> no restart needed):
>
> ```yaml
> llm-pi-ai:
>   providers:
>     pai-gateway:          # provider ID is permanent — sessions reference it
>       api: openai-completions
>       baseURL: http://llm-gateway:4000/v1
>       apiKeyEnv: OPENAI_API_KEY
>       models:
>         - id: default   # + every other gateway model ID, verbatim —
>                         # DSH never queries the endpoint, so unlisted IDs
>                         # are rejected with UNKNOWN_MODEL. After `make sync`
>                         # changes the gateway list, mirror it in dsh/settings.yaml.
> ```
>
> Then select the `pai-gateway` provider in the model picker. `DEEPSEEK_BASE_URL`
> is intentionally unset — no DSH adapter honors it.

## Workspace sharing

`${WORKSPACE_DIR}` is mounted at `/opt/data/workspace:rw` — the **same path** Hermes uses. DSH sessions operate directly on the mounted workspace; generated files land as real files on the host where Hermes sees them.

DSH user data (sessions, configs, plugins, memory) stays in the `dsh_data` volume (`/data/dsh`) — never bind-mount into the workspace.

## Porting Hermes Skills → DSH

DSH loads skills from `.agents/skills/` in the DSH home directory. Each skill is a markdown file with YAML frontmatter (`name`, `description`).

**Direct copy** — the existing `skills/` directory is already in the right format:

```yaml
# docker-compose.dsh.yaml — both halves are required
environment:
  DSH_AGENTS_HOME: /data/dsh/.agents   # plugin scans $DSH_AGENTS_HOME/skills
volumes:
  - ./skills:/data/dsh/.agents/skills:ro
```

**The env var is not optional.** `dsh-skill-filesystem` resolves its user-agents
root as `$DSH_AGENTS_HOME/skills`, falling back to `$HOME/.agents/skills`. Because
this compose file sets `HOME=/opt/data/workspace` (pnpm needs a writable HOME),
the fallback points at `/opt/data/workspace/.agents/skills`, which does not exist.
The `./skills` mount is then live on disk but never scanned, and the catalog comes
back empty — every `skill` call fails with `unknown or no longer available`. That
is the failure mode this `DSH_AGENTS_HOME` line fixes.

Verified in the running container: 30 of 31 skills parse. The exception is
`skills/agents/SKILL.md`, which has no YAML frontmatter — it is an `AGENTS.md`-style
ground-rules doc for Hermes' always-on injection, not a loadable DSH skill, so the
parser skips it. Add frontmatter if you ever want it loadable in DSH.

No conversion needed. The hermes skills (stack-discovery, mermaid, system-design, python, docker, react, nodejs, sql, planning, gitops, research, opencode-delegate, etc.) work as-is — they are procedural markdown that the model reads on demand.

**Caveat**: Skills referencing Hermes-native tools (`pai_notebook_ops`,
`mnemosyne_recall`) load fine in DSH but those tools aren't registered yet, so the
skill text sends the model after tools that don't exist.

**Do not fork the skills to fix this.** The resolution is the opposite direction:
the Phase 2 plugins expose tools named after the Hermes originals, so the skills
resolve unmodified — see [Naming Rule](#naming-rule-binding). 11 of 30 skills are
affected; the other ~19 (the vendored methodology guides — `mermaid`,
`system-design`, `code-reviewer`, `web-design-guidelines`, `webapp-testing`,
`senior-backend`, `frontend-design`, `docker-development`, `ponytail`, …) carry
no tool dependency and work as-is today.

Until Phase 2 lands, the mitigation is to mark the two heaviest skills
(`agents`, 48; `autonomous-tech-learner`, 13) with `disable-model-invocation: true`
so the model won't auto-load a skill that would send it chasing absent tools. That
flag leaves `user-invocable` true — they stay loadable on request. **Not yet
applied** — tracked in the checklist below.

> **`code-intel` was removed 2026-10-04** along with `pai_code_intel`. The tool
> registered an in-process tree-sitter index over the entire workspace; measurement
> showed 42% of that index was a Go toolchain that had leaked into the workspace
> mount via `HOME=/opt/data/workspace`, and the whole index would not fit inside
> DSH's 1.2 GB heap cap. Code intelligence is intentionally absent from pai-stack
> and will be provided by a dedicated lightweight tool. That also retires the
> `dsh-pai-docker` sibling concern about index staleness semantics.

## Porting Hermes Tools → DSH

Hermes `pai_tools` are **Python** (pai_notebook_ops, pai_adr_ops, pai_docker_ops, pai_ops_design_ops). DSH plugins are **TypeScript** using the Cordis framework. Port them 1:1 — same logic, different language.

### Naming Rule (binding)

> **Canonical project-wide convention: [naming.md](naming.md).** This section is the
> Hermes↔DSH slice of it and does not restate the general rules.

> **The package name gets the `dsh-` prefix. The tool name does not.**

Two different identities, previously conflated:

| Identity | Value | Rule |
|---|---|---|
| **Package / plugin** | `dsh-pai-notebook` | Keeps `dsh-` — required by the `@deepseek-ai/dsh-*` npm scope convention. Never drop it. |
| **Tool the model calls** | `pai_notebook_ops` | Mirrors the Hermes name **byte-for-byte**. |

Rationale: the 30 skills already contain **51 live references** to these tools
(`pai_docker_ops` ×15, `pai_adr_ops` ×15, `pai_notebook_ops` ×14,
`pai_ops_design_ops` ×7), plus **19** to `mnemosyne_*`.
Eleven of the 30 skills are vendored third-party — eight carry a vendored
`LICENSE` (`code-reviewer`, `docker-development`, `frontend-design`,
`mcp-builder`, `senior-backend`, `skill-security-auditor`,
`supabase-postgres-best-practices`, `webapp-testing`) and three more are authored
by Vercel (`vercel-composition-patterns`, `vercel-react-best-practices`,
`web-design-guidelines`). Rewriting their bodies to match DSH tool names buys a
merge conflict on every upstream bump for zero benefit.

Matching the tool surface to the skills costs **zero skill edits**.

### One Tool Per Hermes Tool, Not Per Action

Skills call a single tool with an `action` discriminator:

```
pai_notebook_ops(action="search", …)
pai_notebook_ops(action="add_note", …)
```

Registering one tool per action (e.g. a superseded `pai_notebook_ops_search`
design) produces a *fourth* naming variant that matches nothing. `action` is the discriminator:

```typescript
// packages/dsh-pai-notebook/src/index.ts
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Context } from '@deepseek-ai/cordis'

export const name = 'dsh-pai-notebook'   // package keeps the dsh- prefix
export const inject = ['tools']

export function apply(ctx: Context) {
  ctx.tools.register(defineTool({
    name: 'pai_notebook_ops',              // tool mirrors Hermes exactly
    description: 'Research Brain vault: notes, sources, search, synthesis',
    parameters: {
      action: {
        type: 'string',
        required: true,
        description: 'list_notebooks | create_notebook | search | add_note | add_source_url | ...',
      },
    },
    output: { schema: { type: 'string' } },
    render: (_args, value) => [{ type: 'text', text: value }],
    async execute(args, exec) {
      // Dispatch on args.action. Direct Markdown I/O on research/ — no index.
      return handler(args.action, args)
    },
  }))
}
```

### Contract: Required Action Sets

Extracted from actual skill usage — implement **at minimum** these actions, with
these parameter names. Anything narrower breaks live skill references.

| Tool | Actions referenced by skills | Refs |
|---|---|---|
| `pai_docker_ops` | `exec` (5), `list` (1), `start` (1) | 7 |
| `pai_adr_ops` | `create_adr` (4), `check_drift` (4) | 8 |
| `pai_notebook_ops` | `add_note` (4), `search`, `get_source` | 6 |

Implement the full Hermes action set where cheap (`pai_notebook_ops` also needs
`list_notebooks`, `create_notebook`, `ask_notebook`; `pai_adr_ops` also
`list_adrs`) — the skills are a floor, not a ceiling.

### Porting Map

| Hermes Tool | DSH Package | Strategy |
|---|---|---|
| `pai_notebook_ops` | `dsh-pai-notebook` | Native TS plugin, direct file I/O on `research/` |
| `pai_adr_ops` | `dsh-pai-adr` | Native TS plugin, direct file I/O + git |
| `pai_ops_design_ops` | `dsh-pai-design` | Native TS plugin, REST client to OpenDesign |
| `pai_docker_ops` | `dsh-pai-docker` | Native TS plugin driving the Docker API over a mounted socket |
| `mnemosyne_*` | `dsh-mnemon` | Tools named `mnemosyne_*` — see below |

### Blockers to clear before Phase 2

**RESOLVED — option 1 taken: socket mount + `group_add`.**

The blocker used to be that dsh had `read_only: true`, `cap_drop: [ALL]`, no
`/var/run/docker.sock` in `volumes`, and no docker binary on `PATH`, making
`pai_docker_ops` unimplementable. The three options were:

1. **Socket mount + `CAP_DAC_OVERRIDE`** — grants root-equivalent host control.
2. **Named subset** — a thin shim restricted to pai-stack's own services.
3. **Defer** — drop `pai_docker_ops` (7 references).

**Option 1 is now implemented.** `/var/run/docker.sock` is mounted `:ro` (exactly
as hermes has it) and `docker-ce-cli` + `docker-compose-plugin` are baked into
the image. `CAP_DAC_OVERRIDE` turned out to be unnecessary — see
[Docker socket](#docker-socket) below.

### Docker socket

Mirrors hermes, so both agents can drive the host docker the same way.

```yaml
# docker-compose.dsh.yaml
build:
  context: ./dsh
  args:
    DOCKER_GID: ${DOCKER_GID:-999}   # baked into /etc/group — see below
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
group_add:
  - "${DOCKER_GID:-999}"
environment:
  DOCKER_CONFIG: /data/dsh/.docker   # keeps ~/.docker out of the workspace
```

`DOCKER_GID` is auto-detected in the Makefile (`stat -c %g /var/run/docker.sock`,
fallback `999`) and exported, so compose picks it up. Override via `.env` or
`make up DOCKER_GID=999`.

#### Hosts where the socket is `root:root` → `DOCKER_GID=0`

Not every host gives the socket a dedicated `docker` group. When
`stat -c %g` reports **0** (common for a rootful daemon started by a distro
unit or a rootless-less install), the correct value is `0` — and the build then
resolves `getent group 0` → `root` and runs `usermod -aG root node`, putting the
uid-1000 process in **group 0**.

That is a deliberate, bounded grant, not an oversight:

- `cap_drop: [ALL]` + `no-new-privileges:true` still block any uid-0
  transition, so it does **not** make the process root.
- The marginal power is near zero because the socket is *already* the grant:
  anyone who can use it can `docker run -v /:/host` and be root on the host
  anyway (see the tradeoff note below). Group 0 is only the key to that door.
- The real, if small, residue is DAC access to any *root:root group-writable*
  file inside the dsh image.

Set it explicitly in `.env` on such hosts rather than relying on the Makefile:
raw `docker compose` skips the Makefile's `stat` and silently takes the `999`
fallback, which produces the `EACCES` failure described in the next section
while the mount still looks correct. Because the value is baked into `/etc/group`
at build time, changing it needs a rebuild (`make dsh-up` does that).

#### `group_add` alone is NOT enough — this is the subtle part

Hermes needs neither of these: it runs as **root** inside its container, which
bypasses the socket's permission bits entirely. DSH runs as uid 1000, so it must
belong to the socket's group.

But `group_add` on its own **silently fails**, for a reason worth writing down:

```
# /usr/local/bin/dsh-entrypoint, final privilege drop
exec setpriv --reuid="$RUN_USER_ID" --regid="$RUN_GROUP_ID" --init-groups "$0" "$@"
```

`--init-groups` calls `initgroups(3)` → `setgroups(2)`, and **setgroups REPLACES
the supplementary group list rather than adding to it**. Everything Docker
injected via `group_add` is therefore discarded at the drop, and every docker
call fails with `EACCES` while the mount still *looks* correct.

There is no runtime fix — the root FS is `read_only: true`, so `/etc/group`
cannot be edited after boot. The fix has to be baked in, which is why the build
takes `DOCKER_GID` and runs `usermod -aG` on the `node` user. `initgroups` then
rebuilds the list *from* `/etc/group` and the socket group survives. `group_add`
is kept alongside purely as belt-and-braces (it covers a re-detected GID after a
rebuild, and an entrypoint that someday drops `--init-groups`).

**No capability is involved.** Connecting to a unix socket needs only DAC
permission on the socket inode, so `cap_drop: [ALL]` is unchanged and
**`CAP_DAC_OVERRIDE` was never needed** — option 1 in the original blocker list
over-specified it.

> **The tradeoff, stated once, deliberately.** The docker API is
> root-equivalent on the host: anything holding this socket can start a container
> that bind-mounts `/` and reads it. The blast radius is the host, not the dsh
> container. `read_only: true`, `cap_drop: [ALL]` and the loopback-only port bind
> bound the *dsh* process, not what it can ask the daemon to do.

> This does **not** apply the `docker` skill's "never add a `/var/run/docker.sock`
> mount to project stacks" rule — that rule is about third-party stacks, and
> still governs them. pai-stack's own agent container is the deliberate exception.

Useful inside dsh:

```bash
docker ps                                    # pai-stack's own containers
cd "$EXECUTION_DIR" && docker compose -p <project> up -d --build
```

Verify after a rebuild — if `id` lacks the socket's GID, the image predates the
`DOCKER_GID` build arg:

```bash
docker exec dsh id                # expect the docker GID in the groups list
docker exec dsh docker ps
```

### Decision

**Native DSH plugins for the four remaining tool surfaces, tool names mirroring Hermes.**
No MCP bridge, no Hermes API coupling — same logic, different language. Each is a
TypeScript DSH plugin registered via `ctx.tools.register()`, running in-process.

The naming rule is the load-bearing decision here: it is what lets the entire
existing skill library — vendored ones included — run unmodified against DSH.
Without it, the alternative is 51 edits spread across 30 files, 11 of them
vendored.

## Plugins

### Telegram Bot

**`dsh-telegram-control`** (jackControls) — runs inside the DSH process, long-polling, zero runtime dependencies.

| Feature | Detail |
|---|---|
| Remote control | Send messages as follow-ups to agent sessions; replies stream back to Telegram |
| Commands | `/status`, `/agents`, `/agent <id>`, `/jobs`, `/kill <id>`, `/cancel`, `/watch`, `/unwatch`, `/chatid`, `/help` |
| Approval on phone | Sandbox/permission requests arrive with Allow/Reject inline buttons |
| Auth | Chat allowlist — unknown chats get an onboarding hint with their chat id |
| Output | HTML-escaped, split at Telegram's 4096-char limit |

Install:

```bash
dsh plugin --profile web add github:jackControls/dsh-telegram-control
```

Configure via env in `docker-compose.dsh.yaml`:

```yaml
environment:
  DSH_TELEGRAM_TOKEN: ${TELEGRAM_BOT_TOKEN}
```

Reuses the same `TELEGRAM_BOT_TOKEN` as Hermes — notifications only, no long-running conversations (avoids long-polling fights over one token). Allowed chat IDs configured in DSH settings or via the plugin config. If update conflicts appear, split to a dedicated bot token.

### Local Memory

Six viable plugins compared. All are local-first, no cloud dependency.

| Plugin | Storage | Retrieval | Auto-capture | Curation | Web UI | Best for |
|---|---|---|---|---|---|---|
| **dsh-memoir** | JSON SSOT + `PROJECT_MEMORY.md` | BM25 (n-gram, phrase boost) | Distillation reminders after productive turns | Duplicate/conflict detection, archive (never delete) | Bilingual panel | Project-focused work |
| **dsh-mnemon** | SQLite + JSON + Markdown (3-tier) | Semantic recall + knowledge graph | Supervised writes via subagent | LLM-supervised, importance decay, auto-dedup | Sidebar workbench | Cross-agent sharing |
| **dsh-memory** (LZMW) | Markdown files + frontmatter | Keyword/scope-based | Auto-summary at 50% context pressure | Curator subagent (merge/rewrite/delete) | None | Human-editable, git-friendly |
| **dsh-mneme** | Markdown + optional local embeddings | Semantic (local) or keyword | Entity extraction, autoDream consolidation | Self-evolving, forgets low-value over time | Settings panel | "Memory that dreams" |
| **dsh-memory** (doublehappy123) | JSON file | Keyword search | Auto-save prompt | Manual CRUD | Visual settings page | Simple, zero-config |
| **dsh-plugin-memory** | Markdown (5-layer: profile/topics/daily/skills) | Keyword + index | LLM extraction from finished sessions | Per-layer truncation budgets | None | Structured multi-layer |

#### Decision: **dsh-mnemon**

For high-end coding + planning + tuning against designed plans:

| Need | Why dsh-mnemon |
|---|---|
| Remember plans & design decisions | Memory Spaces — structured, long-term, linkable |
| Track tuning experiments | Runtime Memory (hot, every turn) + importance decay keeps fresh stuff relevant |
| Code context across sessions | Project Documents tier — searchable codebase index |
| Link decisions to code | Knowledge graph connects concepts to symbols |
| No stale clutter | Auto-dedup + importance decay forgets what matters less |

Install:

```bash
dsh plugin --profile web add dsh-mnemon
```

Requires the Mnemon CLI — baked into the image at build time (`./dsh/Dockerfile`: `FROM` the pinned base + install mnemon binary), not on the host. Three-tier storage: Runtime Memory (hot), Project Documents (searchable), Memory Spaces (long-term). Cross-agent sharing, LLM-supervised writes, knowledge graph, and importance decay. Replaces Hermes's Mnemosyne with a structured, graph-backed alternative.

**Tool-naming requirement (non-negotiable):** the package is `dsh-mnemon`, but the
tools it registers must be named `mnemosyne_*` — `mnemosyne_recall`,
`mnemosyne_remember`, `mnemosyne_triple_add`, `mnemosyne_triple_query`,
`mnemosyne_sleep`, `mnemosyne_stats`. Not `mnemon_*`. Skills call the Mnemosyne
names directly (**19 references**: 16 in `agents`, 2 in `research`, 1 in
`autonomous-tech-learner`), so renaming the tools to match the package would
reintroduce exactly the drift the
[Naming Rule](#naming-rule-binding) exists to prevent. Package identity and tool
identity are separate concerns — `dsh-mnemon` wrapping `mnemosyne_*` is the
intended shape, not an inconsistency.

## Compose Override

`docker-compose.dsh.yaml` follows the exact same pattern as `docker-compose.opendesign.yaml`:

- `profiles: ["dsh"]` — opt-in only, never starts with `make up`
- Same `${WORKSPACE_DIR}` bind mount at `/opt/data/workspace:rw` (matches Hermes mount path exactly)
- Two named volumes: `dsh_programs:/opt/dsh` (DSH program) + `dsh_data:/data/dsh` (sessions, configs, plugins, memory, toolchain caches)
- `/var/run/docker.sock:/var/run/docker.sock:ro` + `group_add: ["${DOCKER_GID:-999}"]` — host docker access, same socket hermes has. Also passed as a **build arg** so it survives the entrypoint's `setpriv --init-groups`, which would otherwise discard `group_add`. See [Docker socket](#docker-socket)
- `DOCKER_CONFIG=/data/dsh/.docker` — keeps the CLI's state off the workspace mount, same rule as the toolchain caches
- `depends_on: llm-gateway (service_healthy)`
- `TMPDIR=/data/dsh/tmp` — inside the data volume, outside the mounted workspace
- Fixed runtime uid `1000:1000` (image's `node` user — deliberate divergence from the host-UID pattern): the entrypoint's setpriv drop requires a passwd-resolvable uid, and a host uid (e.g. macOS 502) crash-loops the container (`setpriv: --[re]gid requires ...`, verified Oct-2026). Entrypoint still starts as root, chowns both volumes, then drops. No `user:` line (would break root first-boot init)
- `NARB_DISABLE_NATIVE_CACHE=1` (native bindings load from the executable volume, not noexec `/tmp`)
- Loopback-only port bind by default (`"${DSH_BIND_IP:-127.0.0.1}:${DSH_PORT:-9229}:3080"` — host 9229 → container 3080)
- `read_only: true` + `tmpfs /tmp:size=128m,exec` + `no-new-privileges`, `cap_drop: [ALL]` + `CHOWN/DAC_OVERRIDE/SETUID/SETGID`
- Healthcheck on internal port 3081 (not the socat-forwarded 3080)

## Makefile Targets

```makefile
# ── DSH (see docs/dsh.md) ──

dsh-up: check-workspace dsh-perms
	$(DSH_COMPOSE) --profile dsh up -d --build dsh

dsh-perms:
	docker volume create $(DSH_PROGRAMS_VOLUME) >/dev/null
	docker volume create $(DSH_DATA_VOLUME) >/dev/null
	docker run --rm -v $(DSH_PROGRAMS_VOLUME):/data alpine chown -R $(UID):$(GID) /data
	docker run --rm -v $(DSH_DATA_VOLUME):/data alpine chown -R $(UID):$(GID) /data

dsh-password:  ## Print the one-time first-boot admin password
	docker logs dsh 2>&1 | grep -A9 'first-boot admin credentials'

dsh-down:
	$(DSH_COMPOSE) stop dsh

dsh-logs:
	$(DSH_COMPOSE) logs -f dsh

dsh-config:
	$(DSH_COMPOSE) --profile dsh config

dsh-build:
	$(DSH_COMPOSE) --profile dsh build dsh
```

`DSH_PROGRAMS_VOLUME := $(COMPOSE_PROJECT_NAME)_dsh_programs`, `DSH_DATA_VOLUME := $(COMPOSE_PROJECT_NAME)_dsh_data` (deterministic names, same pattern as `DESIGN_VOLUME`).

## Implementation Checklist

Skills mount and tool-naming contract are settled; the plugin code is not written.

- [ ] `./dsh/Dockerfile` — `FROM ${DSH_IMAGE}` + install Mnemon CLI binary
- [ ] `docker-compose.dsh.yaml` — service per Compose Override above
- [ ] `Makefile` — `DSH_COMPOSE`, `DSH_PROGRAMS_VOLUME`/`DSH_DATA_VOLUME`, `dsh-up/down/logs/config/build/perms/password` targets + help text
- [ ] `.env.example` — new § DSH: `DSH_IMAGE`, `DSH_PORT`, `DSH_BIND_IP`, `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`
- [ ] `README.md` — service row (port `3080`) + `make dsh-up` row
- [ ] `docs/operations.md` — `dsh-*` targets row, env vars row, override file row
- [ ] `docs/architecture.md` — Mermaid update (load `mermaid` skill first, per AGENTS.md)
- [x] Skills mount `./skills:/data/dsh/.agents/skills:ro` — path verified; requires `DSH_AGENTS_HOME=/data/dsh/.agents` (see "Porting Hermes Skills"). 29/30 load; `agents` has no frontmatter and is skipped by design.
- [x] Tool-naming contract for Phase 2 — package keeps `dsh-`, tool mirrors Hermes, `action` enum per tool ([Naming Rule](#naming-rule-binding)); required action sets extracted from skill usage; `dsh-pai-docker` blocker documented
- [x] `pai_code_intel` + `skills/code-intel` **removed** (2026-10-04) — code intelligence is out of pai-stack, replaced by a dedicated lightweight tool. Retires the index-staleness blocker.
- [ ] Mark `agents`, `autonomous-tech-learner` with `disable-model-invocation: true` — interim mitigation until Phase 2 ships (see "Porting Hermes Skills")
- [ ] `dsh-pai-*` TypeScript plugins (notebook, adr, design, docker) — Phase 2. Tool names must mirror Hermes (`pai_notebook_ops` + `action` enum), package names keep the `dsh-` prefix — see [Naming Rule](#naming-rule-binding) and the required action sets. Clear the blocker first: `pai_docker_ops` needs a socket-mount/capability decision.
- [ ] `dsh-telegram-control` + `dsh-mnemon` plugin installs — post-boot via `dsh plugin add`. `dsh-mnemon` must register tools as `mnemosyne_*` to match the 19 skill references.

## What's NOT Ported

| Hermes Feature | DSH Equivalent | Notes |
|---|---|---|
| Code intelligence | *(none — removed from pai-stack)* | Dedicated lightweight tool planned; not a DSH plugin |
| Mnemosyne memory | `dsh-mnemon` plugin | Graph-backed; CLI baked into image at build |
| Hermes dashboard | DSH Web UI | Different UI, host port 9229 |
| Kanban swarms | DSH Agent Teams | Built into DSH (experimental) |
| Telegram platform | `dsh-telegram-control` plugin | In-process long-polling bot; approval on phone |
| Langfuse tracing | DSH telemetry | Built into DSH |
| Compressor plugin | DSH compaction | Built into DSH |
| prompt-optimizer | N/A | Hermes-specific |
| next-prompt | N/A | Hermes-specific |
| hermes-labyrinth | N/A | Hermes-specific dashboard |
| hermes-memory-ui | N/A | Hermes-specific dashboard |
| opencode-delegate | N/A | Hermes-specific (DSH has its own agent) |
