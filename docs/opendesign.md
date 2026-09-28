# OpenDesign (optional)

Design studio on the opt-in `design` profile. Never starts with `make up`.

## Run

```bash
make design-up      # create volume + fix ownership + build/start open-design
make design-logs    # tail logs
make design-down    # stop container only (workspace + volume untouched)
make design-config  # validate merged compose
make design-build   # rebuild image (bundled linux opencode)
```

UI: http://localhost:7456 (bound to `127.0.0.1` only). Login user `open-design` + `OD_API_TOKEN` from `.env` (default `admin` — replace with `openssl rand -hex 32` for anything beyond local use).

## Workspace sharing

`${WORKSPACE_DIR}` is mounted at `/workspace`. In the UI: **Import folder → `/workspace/<project>`**. Generated files land as real files in the host workspace where Hermes code intel sees them. Daemon state stays in the `open_design_data` volume (`/app/.od`) — never bind-mount `.od` into the workspace (SQLite lock contention, index noise).

Link a folder from CLI:

```bash
make design-import d=/workspace/<dir> [n=<name>]   # container path, not host path
```

Fix volume ownership to host UID:GID:

```bash
make design-perms
```

## Image

Built locally as `pai-stack-open-design:latest` (`./opendesign/Dockerfile`): upstream base + Linux opencode v1.18.32 + `libc6-compat`. v1 is deliberate — the daemon's adapter needs `--dir` / `--pure` / `--variant` / `-s`, removed in the v2 track. The model comes from the UI picker per run; no config baked in. `HOME=/tmp` (tmpfs) gives opencode a writable home; daemon state is unaffected.

Stock upstream instead (no bundled opencode — generation then needs BYOK keys):

```bash
OPEN_DESIGN_IMAGE=ghcr.io/nexu-io/od:<version> make design-up
# or pin base at build: --build-arg OPEN_DESIGN_BASE=ghcr.io/nexu-io/od:<ver|digest>
```

No `mem_limit` on purpose: daemon + opencode server + run exceed upstream's 384m and get SIGKILLed (`AGENT_SIGNAL_SIGKILL`). `pids_limit: 256` stays.

## Auth notes

Single-tenant `OD_API_TOKEN`. Browser: user `open-design` + token. API: `Authorization: Bearer <token>`. Never publish on LAN/public without a TLS proxy in front.
