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

### Lifeboat (token gate instead of login)

If the UI shows `dsh web authentication required; reopen the URL printed by dsh
web` instead of the admin login, DSH is in its **lifeboat** profile (no
third-party plugins, so the `dsh-remote` login is absent). Fresh volumes land
here deterministically: `remote-setup` installs the auth plugin as root
*after* the entrypoint's ownership pass, so the first `web` boot dies on
`EACCES ... cordis.patch.yml` and lifeboat (which is sticky) takes over.
`make dsh-up` runs `dsh-ensure-web` after start, which detects the lifeboat
marker in the current boot's logs, re-aligns both volumes to `1000:1000` from
outside, and restarts back to `web` — fully automatic, verified on a real
`all-clean` + `all-up` cycle.

### LAN / DNS access (e.g. Tailscale names)

The port bind alone (`DSH_BIND_IP=0.0.0.0`) is not enough: DSH's `/api`
browser-trust fence rejects any `Host` it doesn't know, so over another name
the UI shell loads but every API call (login included) fails. Add each name
you browse by to `.env`:

```bash
DSH_TRUSTED_HOSTS="office1:9229,office1,127.0.0.1:9229,127.0.0.1,localhost:9229,localhost"
```

Both bare-host and `host:port` forms are accepted; keep the loopback entries
or localhost stops working too (setting the var replaces the implicit
loopback trust). Recreate after changing (`docker compose ... up -d dsh` —
env-only, no rebuild needed). Verified: identical status codes on `/` and
`/api/*` via `127.0.0.1` and the DNS name, plus a working `POST /auth/login`
+ cookie round-trip over the DNS name.

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
> protocol) on the `llm-pi-ai` profile entry. Canonical copy:
> `dsh/settings.yaml` — a Cordis **profile-patch snippet** (entry-list
> dialect), applied to `profiles/web/cordis.patch.yml`, the same file the
> Models page writes to:
>
> ```yaml
> - id: llm-pi-ai
>   config:
>     providers:
>       pai-gateway:          # provider ID is permanent — sessions reference it
>         api: openai-completions
>         baseURL: http://llm-gateway:4000/v1
>         apiKeyEnv: OPENAI_API_KEY
>         models:
>           - id: default   # full gateway fallback chain — always works
>           - id: <every live gateway alias, verbatim>
> ```
> DSH never queries the endpoint, so unlisted IDs are rejected with
> UNKNOWN_MODEL. The list is **generated, not hand-maintained**:
> every `make sync` rebuilds `dsh/settings.yaml` from the same
> liveness-probed alias list as `llm-gateway/config.yaml`
> (`generate_dsh_seed`, `default` first). Push it into the running
> volume with:
>
> ```bash
> make dsh-refresh   # replace the llm-pi-ai entry live, restart only on change
> ```
>
> The merge is surgical: only the seed-managed entries are replaced;
> the managed auth block and all other entries are preserved byte-for-byte
> (script: `scripts/refresh-dsh-models.py`). `default` keeps working even
> between refreshes, because its fallback chain lives gateway-side.
>
> Gateway-only by default: the seed also carries three static overlays —
> `llm-deepseek` and `llm-deepseek-account` set `disabled: true`, and
> `agent-default-model` is pinned to `pai-gateway` / `default`. A user-patch
> row addresses a base row by id with last-write-wins, so the native
> `deepseek-official` provider never registers and the picker shows only
> the gateway (verified via `dsh --profile web --dump-config`). The only
> remaining DeepSeek-tied rows are `web` / `web-search-deepseek` (the
> auxiliary web_search tool, which needs its own key and base-URL override —
> out of scope for chat routing).
>
> Applied automatically: `make dsh-up` runs `dsh-settings` after boot, which
> appends the snippet iff `pai-gateway` is absent (never duplicates, never
> clobbers UI edits) and restarts. (HMR *is* active — a `cordis.patch.yml`
> edit hot-reloads live, which is how the [default-workspace plugin](#default-workspace)
> activates with no restart. The restart here is for the provider list:
> credentials are re-read per request, the provider list is not.)
> Do NOT use `$DSH_HOME/settings.yaml` for this: the legacy user-layer import
> consumes the file without merging providers (verified: renamed to
> `.imported`, tree unchanged, UI still DeepSeek-only).
>
> Then select the `pai-gateway` provider in the model picker. `DEEPSEEK_BASE_URL`
> is intentionally unset — no DSH adapter honors it.

## Workspace sharing

`${WORKSPACE_DIR}` is mounted at `/opt/data/workspace:rw` — the **same path** Hermes uses. DSH sessions operate directly on the mounted workspace; generated files land as real files on the host where Hermes sees them.

DSH user data (sessions, configs, plugins, memory) stays in the `dsh_data` volume (`/data/dsh`) — never bind-mount into the workspace.

### Default workspace

The dashboard's workspace registry lives in the `dsh_data` volume
(`storages/workspace.json`, domain spec version 2). The directory the
dashboard opens is **not** a config value — it is whichever workspace the
registry lists as most recently used (the workspace whose sessions have the
latest `updatedAt`, falling back to `createdAt`). On a volume that already
holds active agent sessions, that is the busiest project workspace, not the
workspace mount root.

**How the mount root becomes the default workspace — no plugin.**
Oct-2026 research (`.planning/2026-10-06-dsh-workspace-root-research/`,
verified against image `@deepseek-ai/dsh@0.2.0-rc.2`) showed the stock
first-use flow can never succeed here: with no `documentsDirectory` override
the Linux path runs `xdg-user-dir DOCUMENTS`, which is not installed in the
image, so `initializeDefault` throws and the dashboard shows "Unable to
create default workspace". (`$HOME` is never consulted on this path — the
desktop `~/Documents/...` behavior simply doesn't apply in the container.)
An earlier `dsh-default-workspace` plugin worked around this and has been
removed; the entrypoint now uses two native levers instead:

- **Registry pre-seed** — on boot, if `storages/workspace.json` is absent the
  entrypoint writes it with `/opt/data/workspace` as the sole workspace and
  `defaultWorkspaceId` set (exact DSH-written schema). The mount root is
  therefore registered from the first boot, and stock creation stays
  ineligible forever after. (Briefly removed Oct-2026 in favor of the stock
  subdir fallback; restored by explicit user choice — the mount root as the
  default makes more sense than a `deepseek-harness/default-workspace`
  subdir.) Existing volumes are untouched.
- **Native controller override** — a `- id: workspace-controller` patch row
  sets the code-documented *"explicit deployment override"*
  `documentsDirectory: /opt/data/workspace`. The fixed
  `deepseek-harness/default-workspace` suffix still applies, so this can
  never yield the mount root itself — it is a safety net only: if the seeded
  registration is ever deleted, the stock fallback creates under the mount
  instead of throwing.

Entry points: `seed_workspace_registry`, `ensure_workspace_controller_row`,
`retire_default_workspace_plugin` in `dsh/docker-entrypoint.sh` (the last one
is one-time cleanup of the removed plugin's patch entry + stale volume copy).
If `DSH_VERSION` is bumped, re-verify the pre-seed schema against a
live-written `workspace.json`.

> **Do not empty the registry.** DSH recreates a default workspace on every
> load while the registry is empty (verified Oct-2026: deleting the last
> entry just respawns `deepseek-harness/default-workspace`, shown localized
> as "Default Workspace"). To get rid of it: add the project folder(s) via
> Choose workspace first, then delete the subdir default once — with ≥1
> workspace registered, auto-creation stays ineligible forever.

**Caveat — first browser load on a dirty volume.** DSH opens the most
recently *used* workspace. With a live agent session in a project
workspace, that session's activity keeps the project workspace "most
recent", so the first dashboard load still lands there. Opening
`/opt/data/workspace` once persists the selection for that browser
(localStorage `dsh.sessions.current`); every load after that opens at the
mount. On a fresh volume (or after `make dsh-clean`) the first load opens
at `/opt/data/workspace` automatically. Forcing the first-load target on a
dirty volume without opening it once would require a DSH-core change to the
selection rule (`restoreSelection` → `recentWorkspace` in
`@deepseek-ai/dsh-client-ui-workspace`).

> The fixed `deepseek-harness/default-workspace` suffix is why the
> `documentsDirectory` row alone can never yield the mount root — the
> registry pre-seed above is what puts `/opt/data/workspace` itself in.

### Directory picker start directory

The "Select Workspace Directory" browse dialog takes no initial-path input:
every open lists with no path, and the server resolves that to
`homedir()` — i.e. it always opened at `$HOME`. The browse backend's config
is `{ maxEntries }` only, so there is no supported knob. The image carries a
one-line build-time patch (`dsh-host-directory-picker-browse`: resolve the
no-path case against `process.env.WORKSPACE_DIR` first, home as fallback),
and compose sets `WORKSPACE_DIR=/opt/data/workspace` in the container — the
same value as the workspace mount, no extra vars. Empty/unset keeps the old
home behavior. If `DSH_VERSION` is bumped, re-verify the patched line
(`const target = resolve(path ?? home);`) still exists exactly once.

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
(The vendored `skills/gstack/` + 25 `skills/gstack-*/` dirs follow the same
`name`/`description` frontmatter convention and parse the same way; re-verify
with `skills_list` after adding skills.)

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

**RESOLVED — proxy socket (Option A, Oct-2026).**

The blocker used to be that dsh had `read_only: true`, `cap_drop: [ALL]`, no
`/var/run/docker.sock` in `volumes`, and no docker binary on `PATH`, making
`pai_docker_ops` unimplementable. The three options were:

1. **Socket mount + `CAP_DAC_OVERRIDE`** — grants root-equivalent host control.
2. **Named subset** — a thin shim restricted to pai-stack's own services.
3. **Defer** — drop `pai_docker_ops` (7 references).

**Option 1 is now implemented directly.** `/var/run/docker.sock` is mounted
`:ro` (exactly as hermes has it), `docker-ce-cli` + `docker-compose-plugin`
are baked into the image, and compose `user:` + `group_add: [DOCKER_GID]`
gives the agent user socket access — see [Docker socket](#docker-socket).
(The earlier socat proxy existed only because the `setpriv` privilege drop
discarded `group_add`; with `user:` there is no drop, so no proxy.)

### Docker socket

Mirrors hermes: `/var/run/docker.sock` mounted `:ro`, `docker-ce-cli` +
`docker-compose-plugin` baked into the image. DSH runs as the host user via
compose `user:` and reaches the socket directly through `group_add`
(no proxy socket, no setpriv — the old `setpriv --init-groups` drop
discarded `group_add`, which is why the proxy existed; `user:` preserves it).

```yaml
# docker-compose.dsh.yaml
user: "${UID:-1000}:${GID:-1000}"
group_add:
  - "${DOCKER_GID:-0}"   # Desktop = 0/root, Linux = docker gid (Makefile auto-detects)
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
environment:
  DOCKER_CONFIG: /data/dsh/home/.docker   # keeps ~/.docker out of the workspace
```

**No capability is involved.** Connecting to a unix socket needs only DAC
permission on the socket inode, so `cap_drop: [ALL]` stands alone.

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

Verify after a rebuild — if `docker ps` fails with `permission denied`,
the container predates `group_add` (compose-only change, no rebuild needed —
just `make dsh-up`):

```bash
docker exec dsh docker ps   # must list containers (already runs as host uid)
docker exec dsh id          # uid:gid matches host; groups include DOCKER_GID
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

### Automation tasks (scheduled reminders)

**Official bundle `@deepseek-ai/dsh-experimental-schedule-bundle`** — ships inside
the `@deepseek-ai/dsh` image itself (verified at build time by `dsh/Dockerfile`),
so there is no seed copy and no npm install. The entrypoint enables it the same
way the plugin manager does: appends the bundle to the web profile's
`dsh.profile.bundles` iff absent (idempotent, preserves everything else).
Opt out with `DSH_WITH_SCHEDULE=false` (rebuild not needed — compose-only).

What it adds: `schedule_create` / `schedule_list` / `schedule_update` /
`schedule_delete` tools for live root agents, the sidebar **Automation tasks**
page (alarm-clock icon under Plugins), a per-session reminder catalog, and
`time-context` clock readings. Verify with
`docker exec dsh dsh --profile web --dump-config` (schedule rows present).

Two caveats, both upstream properties, not container bugs:

* **Session-local delivery.** Timers live in the dsh process; a stopped container
  or cold session pauses them. This is reminders attached to live sessions, not
  cron that fires with no chat open — for that, see Durable automation below.
* **Token cost.** Four tool schemas on every root-agent request plus one durable
  clock reading per eligible step, even in conversations that never schedule.

#### Durable automation: `@michengai/dsh-automation@0.1.54` (pinned exact)

Cron that fires with nobody watching: each occurrence starts a fresh root agent +
session (no chat history inherited), with per-task workspace, model, skills, and
permission preset. UI: sidebar **Scheduled** tab + Settings → Scheduled Tasks;
agents get `automation_create/list/update/run/pause/resume/delete` tools.

Wired like the other seeds: `dsh/Dockerfile` pnpm-installs it into a joint tree
on top of the auth+memory seeds (one superset, no runtime merge conflicts),
and the entrypoint installs that tree wholesale into the web profile iff the
manifest/tree is absent. Runtime skip via `DSH_WITH_AUTOMATION=false`.

**Review (Oct-2026, against the published tarball — re-audit on version bump):**

* **Compat is exact, not hoped.** Its peerDeps list `0.2.0-rc.2` explicitly for
  every `@deepseek-ai/dsh-*` package. The alternatives
  (`@syncended/dsh-automations`, `@alpacachen/dsh-automation`) peer only
  `<0.2.0`, so pnpm would flag them against this image.
* **Proper DSH bundle** (`dsh.bundle.patch` + declared web client injects),
  Apache-2.0, no install scripts (and the seed uses `--ignore-scripts` anyway).
  Runtime deps are `zod`, `luxon`, and `antd` (client UI — bloats the seed tree,
  harmless on the volume).
* **One invasive row, by design.** Its patch overrides the core `connection`
  row (`inject: [webServer, webRuntime]`). Written for this DSH line, but a
  DSH bump must re-verify web connectivity, not just the seed gate.
* **No exfil, no silent mutation.** The only network egress found is an npm
  registry version check; the only `child_process` use is the user-triggered,
  loopback-guarded self-update flow (admin clicks update in UI). It never
  auto-updates, so the seed pin holds. (A UI-triggered update diverges the
  volume from the pin — same property as the other seeds; the seed skips when
  valid and never downgrades.)
* **Trust boundary unchanged.** Runs execute under the task's own workspace +
  permission preset (sandbox still applies); state lives under `$DSH_HOME` on
  the `dsh_data` volume. Same blast radius as an interactive session — the
  docker socket it can reach is the deliberate host-daemon reuse, not new.

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

Install: baked into the image, no manual step. `dsh/Dockerfile` pnpm-installs
`dsh-mnemon@${DSH_MNEMON_PLUGIN_VERSION:-0.5.24}` into a seed staging dir
(jointly resolved with the auth plugin, so the tree mirrors `dsh plugin add`
exactly), and the entrypoint installs that tree into the web profile on boot
iff the manifest/tree is absent — same seed pattern as the auth plugin, so
fresh volumes (and `dsh-clean`) self-heal. Override via
`DSH_WITH_MNEMON_PLUGIN=false` / `DSH_MNEMON_PLUGIN_VERSION=` (rebuild).

**Tool-naming outcome:** the package registers `mnemon_*` tools and offers no
rename/prefix support (verified against 0.5.24: names are hardcoded literals,
and a mechanical rename is semantically wrong — `mnemosyne_triple_*`,
`sleep`, `stats` have no counterparts, arg shapes differ). Shared skills
therefore keep calling Hermes-native `mnemosyne_*` (see `skills/agents`,
`skills/research`); on DSH, memory is used via the workbench UI and direct
`mnemon_*` calls. Revisiting this means either upstream rename support or a
per-agent skill rewrite — not a text rename.

## Compose Override

`docker-compose.dsh.yaml` follows the exact same pattern as `docker-compose.opendesign.yaml`:

- `profiles: ["dsh"]` — opt-in only, never starts with `make up`
- Same `${WORKSPACE_DIR}` bind mount at `/opt/data/workspace:rw` (matches Hermes mount path exactly)
- Two named volumes: `dsh_data:/data/dsh` (sessions, configs, plugins, memory) + `dsh_toolchains:/data/dsh/home/.cache` (Go/Rust/uv/pip caches, kept out of the workspace)
- `/var/run/docker.sock:/var/run/docker.sock:ro` + `group_add: [DOCKER_GID]` — host daemon reuse (same daemon hermes reaches directly). See [Docker socket](#docker-socket)
- `DOCKER_CONFIG=/data/dsh/home/.docker` — keeps the CLI's state off the workspace mount, same rule as the toolchain caches
- `depends_on: llm-gateway (service_healthy)`
- `TMPDIR=/data/dsh/tmp` — inside the data volume, outside the mounted workspace
- Host UID/GID via `user: "${UID}:${GID}"` (dedicated `dsh` user baked at build, fresh volumes inherit ownership, `make dsh-perms` repairs pre-existing ones once — no per-boot chown, no setpriv)
- `NARB_DISABLE_NATIVE_CACHE=1` (native bindings load from the executable volume, not noexec `/tmp`)
- Loopback-only port bind by default (`"${DSH_BIND_IP:-127.0.0.1}:${DSH_PORT:-9229}:3080"` — host 9229 → container 3080)
- `read_only: true` + `tmpfs /tmp:size=128m,exec` + `no-new-privileges`, `cap_drop: [ALL]` (no extra caps)
- Healthcheck on internal port 3081 (not the socat-forwarded 3080)

## Makefile Targets

```makefile
# ── DSH (see docs/dsh.md) ──

dsh-up: check-workspace dsh-perms
	$(DSH_COMPOSE) --profile dsh up -d --build dsh
	$(MAKE) dsh-ensure-web   # auto-recover a lifeboat landing (see Lifeboat)
	$(MAKE) dsh-settings     # ensure pai-gateway provider patch (see LLM Gateway)

dsh-perms:
	docker volume create $(DSH_PROGRAMS_VOLUME) >/dev/null
	docker volume create $(DSH_DATA_VOLUME) >/dev/null
	docker run --rm -v $(DSH_PROGRAMS_VOLUME):/data alpine chown -R 1000:1000 /data
	docker run --rm -v $(DSH_DATA_VOLUME):/data alpine chown -R 1000:1000 /data

dsh-settings:  # append ./dsh/settings.yaml to cordis.patch.yml iff pai-gateway absent (never duplicates, never clobbers UI edits); restarts only on change

dsh-refresh:  # replace the llm-pi-ai entry with the freshly synced seed (other entries preserved); restarts only on change

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
- [x] Default workspace = `/opt/data/workspace` (2026-10-06) — registry pre-seed + native `workspace-controller` `documentsDirectory` override, both ensured by the entrypoint on every boot; survives `dsh-clean`. Replaced the retired `dsh-default-workspace` plugin. See [Default workspace](#default-workspace).
- [ ] Mark `agents`, `autonomous-tech-learner` with `disable-model-invocation: true` — interim mitigation until Phase 2 ships (see "Porting Hermes Skills")
- [ ] `dsh-pai-*` TypeScript plugins (notebook, adr, design, docker) — Phase 2. Tool names must mirror Hermes (`pai_notebook_ops` + `action` enum), package names keep the `dsh-` prefix — see [Naming Rule](#naming-rule-binding) and the required action sets. Clear the blocker first: `pai_docker_ops` needs a socket-mount/capability decision.
- [x] `dsh-mnemon` memory plugin — baked into the image + entrypoint-seeded (no post-boot install). Tools surface as `mnemon_*` (no upstream rename support); shared skills keep `mnemosyne_*` for Hermes — memory-via-skills stays Hermes-only, DSH uses the workbench + direct calls. (`dsh-telegram-control` still pending post-boot install.)

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
