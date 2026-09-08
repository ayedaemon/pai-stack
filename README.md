# pai-stack

**Hermes Agent** + **Syncthing** + **CodeGraph** — personal AI infrastructure on a single Pi/server.

---

## Architecture

```text
Mac / Clients (over Tailscale)
              │
              ▼ WireGuard (encrypted)
┌─────────────────────────────────────────────┐
│              Raspberry Pi                    │
│                                             │
│  ┌─────────────────┐  ┌─────────────────┐  │
│  │     Hermes      │  │   CodeGraph     │  │
│  │  :9119 dashboard│  │  :20128 internal│  │
│  │  :8642 API      │  │                 │  │
│  └────────┬────────┘  └────────┬────────┘  │
│           │  Docker network    │           │
│           └────────┬───────────┘           │
│                    │                       │
│  ┌─────────────────┴─────────────────────┐ │
│  │           Syncthing (host)            │ │
│  │  :8384 GUI  :22000 sync               │ │
│  └───────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

No reverse proxy. Tailscale encrypts all traffic via WireGuard. Each service binds directly to the Tailscale IP.

---

## What You Get

| Service | Purpose | Access |
|---------|---------|--------|
| **Hermes** | AI agent — RAG, Kanban, Telegram, Dashboard | `https://TailscaleIP:9119` (dashboard), `:8642` (API) |
| **Syncthing** | Bidirectional file sync across devices | `https://TailscaleIP:8384` |
| **CodeGraph** | Code intelligence API (call chains, impact, search) | Internal only (`http://codegraph:20128`) |

**Data flow:** Write notes on Mac → Syncthing syncs to Pi → Hermes indexes for RAG → CodeGraph parses code → Hermes uses both to answer.

---

## Quick Start

This stack is provisioned **entirely by Ansible** — it SSHes into the target machine and installs everything from bare SSH.

**Prerequisites on your dev machine:** `ansible-core` + `sshpass`

```bash
pip install ansible-core
# macOS: brew install hudochenkov/sshpass/sshpass
# Debian/Ubuntu: apt install sshpass
```

### Local install (on the same machine)

Even localhost deploy uses SSH — ensure `sshd` is running:

```bash
# macOS: System Settings → General → Sharing → Remote Login
# Linux: sudo systemctl enable --now sshd
ansible-playbook -i "localhost," -u $USER ansible/playbook.yml -K -k
```

### Remote install (the common case)

Point at your Pi via LAN or Tailscale address:

```bash
cp .env.example .env
# Edit .env with TARGET_HOST, TARGET_USER, etc.

ansible-playbook -i "${TARGET_HOST}," -u "${TARGET_USER}" ansible/playbook.yml \
  -e "@.env" -k -K
```

Or set `SSH_PASSWORD` and `BECOME_PASSWORD` in `.env` for zero-prompt deploys.

### Post-deploy workflow

1. Credentials printed at end of deploy — save them
2. Open Hermes Dashboard at `https://TailscaleIP:9119`
3. Pair Syncthing devices — see [Syncing Your Devices](#syncing-your-devices)
4. Wait for initial sync (minutes depending on KB size)
5. Verify Hermes sees notes — query the dashboard
6. CodeGraph builds code graph automatically on first deploy

---

## Services & Access

| Service | URL | Auth |
|---------|-----|------|
| **Hermes Dashboard** | `https://TailscaleIP:9119` | Basic Auth `admin` / generated password |
| **Hermes API** | `https://TailscaleIP:8642` | Bearer token (`API_SERVER_KEY`) |
| **Syncthing GUI** | `https://TailscaleIP:8384` | Basic Auth `admin` / generated password |
| **CodeGraph** | `http://codegraph:20128` (Docker network) | None |

> All credentials are generated on first deploy and written to `~/deployed-pai-stack/.env`.

---

## How Hermes Uses Your Data

### RAG (Retrieval-Augmented Generation)

- **Indexes all of `STACK_ROOT`** — not just `silverbulletKB`. Everything under `~/Personal` is searchable.
- **Local embeddings** (`all-MiniLM-L6-v2`, ~80MB RAM) — no data leaves your machine.
- **Auto-reindex on file change** — edits are immediately available for retrieval.
- **`AGENTS.md`** always injected into Hermes' context (scope manifest).
- **`silverbulletKB/`** is where Hermes writes back — indexed + synced.

### CodeGraph (Code Intelligence)

- Hermes queries CodeGraph at `http://codegraph:20128` for code-aware planning.
- Provides: call chain tracing, impact analysis, symbol search.
- Reads `STACK_ROOT` **read-only** — never writes to your codebase.
- **fs-notifier** watches `STACK_ROOT` and triggers CodeGraph rebuild when files change (configurable debounce via `FS_NOTIFIER_DEBOUNCE_SECONDS`).

### Structuring the Knowledge Base

```
~/Personal/
├── AGENTS.md                      ← scope manifest (always injected)
├── Projects/
│   ├── ProjectAlpha/
│   │   ├── README.md
│   │   ├── docs/architecture.md
│   │   ├── telegram.md
│   │   └── config.md
│   └── ProjectBeta/ ...
└── References/                   ← shared glossary, runbooks
```

Tips: Use specific H2/H3 headings for better chunks. Keep `AGENTS.md` as the single source of truth. Store secret *references*, never raw values.

---

## Syncing Your Devices (Syncthing)

> Syncthing runs on the Pi host as a **systemd service** (not a Docker container).

The deploy configures Syncthing's default folder with **Folder ID `personal`** pointing at `~/Personal`.

### Quick Pairing

1. Install Syncthing on your device (`brew install syncthing` / syncthing.net)
2. Open Pi's Syncthing GUI: `https://TailscaleIP:8384`
3. Copy Pi's **Device ID** (Actions → Show ID)
4. On your device: Add Remote Device → paste Device ID → Save
5. Add local folder with **Folder ID** = `personal`, share with Pi
6. On Pi: accept folder share, point to existing `~/Personal`

### Detailed Steps

**Prerequisites:**
- Both devices on the same Tailscale tailnet (recommended) or reachable via LAN.

**Steps:**
1. Open Pi's GUI — `https://TailscaleIP:8384`, log in with deploy credentials
2. On Pi: **Actions → Show ID** → copy Device ID
3. On your machine: **Add Remote Device** → paste Device ID → Save
4. Add local folder, set **Folder ID** to `personal`, share with Pi
5. On Pi: accept folder share, choose existing `~/Personal`

**Notes:**
- Bidirectional by default (Send & Receive). Deletes go to `.stversions` (trash).
- `STACK_ROOT` is the same folder Hermes reads/writes.
- To change sync path: edit `STACK_ROOT` in `.env` and re-deploy.

---

## fs-notifier

A background process inside the Hermes container that watches `STACK_ROOT` for file changes and triggers CodeGraph graph rebuilds.

**Configurable via `.env`:**

| Variable | Default | Description |
|----------|---------|-------------|
| `FS_NOTIFIER_DEBOUNCE_SECONDS` | `30` | How long to wait after last change before triggering rebuild |

**How it works:**
1. `inotifywait` watches `/opt/data/Personal` recursively
2. On change, starts a debounce timer
3. After `DEBOUNCE_SECONDS` of no changes, sends `POST` to CodeGraph
4. CodeGraph runs `reindex_workspace` (incremental via content hashing)

---

## Updating Configuration

Configs are **overwritten on every deploy**. To update:

1. Edit `.env` or `ansible/group_vars/all.yml`
2. Re-run `ansible-playbook ...`

Hermes config is templated from `hermes/config.yaml.j2` on every deploy.

### Makefile Shortcuts

| Command | Description |
|---------|-------------|
| `make logs` | Tail logs |
| `make status` | Show running services |
| `make stop` / `make restart` | Stop / restart the stack |
| `make update` | Pull latest images & rebuild |
| `make clean` | Stop & remove data (destructive) |

---

## Repository Structure

```
├── README.md
├── ansible/
│   ├── playbook.yml           # Flat deployment playbook
│   ├── group_vars/all.yml     # Configurable variables
│   └── templates/
│       ├── env.j2             # Target .env template
│       └── hermes/config.yaml.j2
├── docker-compose.yaml        # Hermes + CodeGraph
├── hermes/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── fs-notifier.sh         # Filesystem watcher
│   ├── config.yaml.j2
│   └── apply-kanban-patch.py
├── codegraph/
│   ├── Dockerfile
│   ├── server.js
│   └── package.json
├── silverbulletKB/              # KB scaffold → ~/Personal/silverbulletKB
│   └── Skills/
│       ├── _TEMPLATE/
│       ├── codegraph/
│       ├── docker/
│       ├── nodejs/
│       ├── postgres/
│       ├── python/
│       ├── react/
│       └── stack-discovery/
├── docs/
│   ├── BLUEPRINT.md
│   └── adr/
├── .env.example
├── Makefile
└── docker-compose.yaml
```

---

## Design & Philosophy

> For the full architecture, trade-offs, and principles, see **[docs/BLUEPRINT.md](docs/BLUEPRINT.md)** and **[docs/adr/](docs/adr/)**.
