# pai-stack — Setup Flow & Architecture

> **Purpose:** Setup and operational guide for running `pai-stack` in two configurations:
> 1. **Local Mode:** Running directly via Docker Compose on your workstation (Mac/Linux), mounting your external workspace directly.
> 2. **Remote Pi Mode:** Running on a remote headless Raspberry Pi via Ansible + Syncthing, keeping your local workspace mirrored to the Pi.

---

## 1. Core Mental Model & Folder Mapping

Regardless of where `pai-stack` runs, all containers always interact with a single standardized root directory inside Docker: `/stack_root`.

```text
┌─────────────────────────────────────────────────────────────┐
│                      CONTAINER VIEW                         │
│                                                             │
│   Hermes (KB & Tasks) ────────┐                             │
│   CodeGraph (Code Search) ────┼──▶  /stack_root             │
│   MCP Server (Tools & KB) ────┘                             │
└──────────────────────────────┬──────────────────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
┌───────────────────────────────┐   ┌───────────────────────────┐
│     MODE 1: LOCAL DOCKER      │   │    MODE 2: REMOTE PI      │
│                               │   │                           │
│  Host (Mac / Workstation)     │   │  Remote Pi Host           │
│  Mounted from:                │   │  Mounted from:            │
│  ${STACK_ROOT} in .env        │   │  ~/stack_root             │
│  (e.g. /Users/.../Personal)   │   │  (kept in sync via        │
│                               │   │   Syncthing from Mac)     │
└───────────────────────────────┘   └───────────────────────────┘
```

### Single `.env` File Configuration
All configuration is managed from one root `.env` file on your machine:

```env
# ── Common Configuration (Both Local & Remote) ──────────────
# Path to your external notes, docs, and codebases on your machine
STACK_ROOT=/Users/rishabh.umrao/Personal

# LLM Providers (at least one key required for Hermes)
OPENROUTER_API_KEY="sk-or-v1-..."
# MISTRAL_API_KEY=""
# KILO_GATEWAY_API_KEY=""

# Optional overrides (defaults will be used if unset)
# API_SERVER_KEY=...
# HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=...

# ── Remote Pi Only (Used by Ansible / make deploy) ──────────
TARGET_HOST="rpi.burro-smelt.ts.net"
TARGET_USER="pi"
TAILSCALE_AUTH_KEY="tskey-auth-..."   # Optional (only for fresh Pi setup)
```

---

## 2. Mode 1: Local Docker Compose (Bypass Sync)

In Local Mode, you run Docker on the same machine where your files reside. There is no need for Syncthing, Ansible, or remote networking.

### Prerequisites
- Docker & Docker Compose installed (e.g. Docker Desktop, OrbStack, or Docker Engine).

### Setup Steps:
1. **Configure `.env`:**
   Set `STACK_ROOT` to the absolute path of your workspace/folder on your host.
2. **Start the stack:**
   ```bash
   docker compose up -d --build
   ```
3. **Access Services:**
   - **Hermes Dashboard:** http://localhost:9119 (User: `admin`, Password: `${HERMES_DASHBOARD_BASIC_AUTH_PASSWORD}`)
   - **Hermes API:** http://localhost:8642 (Bearer Token: `${API_SERVER_KEY}`)
   - **CodeGraph:** http://localhost:20128/health
   - **MCP Server:** http://localhost:8000/health

---

## 3. Mode 2: Remote Raspberry Pi (Ansible + Syncthing)

In Remote Mode, the stack runs continuously on a headless Raspberry Pi. A folder sync engine (Syncthing) mirrors your Mac's `STACK_ROOT` to the Pi's `~/stack_root`.

### Prerequisites
- `ansible-core` and `sshpass` installed on your Mac (`pip install ansible-core; brew install hudochenkov/sshpass/sshpass`).
- SSH access to the Pi (`ssh pi@<pi-ip-or-tailscale-name>`).

### Deployment Command:
From the repo root on your Mac:
```bash
make deploy
# or manually:
# ansible-playbook -i "${TARGET_HOST}," -u "${TARGET_USER}" ansible/playbook.yml -e "@.env" -k -K
```

---

### The Pi Deployment Conveyor Belt (What Ansible Does)

Ansible executes these linear stations on the remote Pi:

#### Phase A: Host Environment Setup
- **Station 0 — Identity & UID Detection:** Reads the target user's UID/GID (e.g. `1000`) so files created by Docker match host permissions. Pi's target directory is set to `~/stack_root`.
- **Station 1 — Tailscale VPN (Optional):** If `TAILSCALE_AUTH_KEY` is provided, installs Tailscale and connects the Pi to your tailnet. (Skipped if Pi is already connected).
- **Station 2 — Docker Engine:** Ensures Docker and Docker Compose plugin are installed on the Pi.
- **Station 3 — Directory Setup:** Ensures `~/stack_root` (synced data root) and `~/deployed-pai-stack` (deployed repo) exist.

#### Phase B: Sync Engine (Syncthing)
- **Station 4 — Syncthing Host Service:**
  - Installs Syncthing as a systemd service running directly on the Pi host.
  - Configures Syncthing to share `~/stack_root` under folder ID `stack_root`.
  - Exposes the Syncthing Web GUI on port `8384` (over Tailscale or LAN).
  - *Pairing:* Connect your local Syncthing client to the Pi's Syncthing instance to mirror your local `STACK_ROOT` to `~/stack_root`.

#### Phase C: Application Deployment
- **Station 5 — Clone / Update Repo:** Clones or updates `pai-stack` into `~/deployed-pai-stack`.
- **Station 6 — Secrets & Config Templating:**
  - Auto-generates secure random passwords/keys if not already configured in Pi's `.env`.
  - Templates the Pi's `.env` (with `STACK_ROOT=/home/pi/stack_root`) and `hermes/config.yaml`.
  - *(Note: Project templates and skills are served via `mcp-server` directly to Hermes; your user data folder is not polluted).*
- **Station 7 — Build & Start Containers:**
  - Runs `docker compose up -d --build` on the Pi.
  - Mounts `~/stack_root` into container `/stack_root`.
- **Station 8 — Health Verification:**
  - Polls CodeGraph and Hermes until healthy, then displays connection credentials and URLs.

---

## 4. Container Roles & Architecture

| Service | Internal Role | Volumes (Host → Container) | Ports |
|---|---|---|---|
| **`hermes`** | AI Agent runtime & Web UI | `hermes-data:/opt/hermes/data`<br>`${STACK_ROOT}:/stack_root` | `9119` (Dashboard)<br>`8642` (API) |
| **`codegraph`** | AST code indexer & symbol search | `codegraph-data:/data`<br>`${STACK_ROOT}:/stack_root:ro` | `20128` |
| **`mcp-server`** | Tool provider, skills, and scaffold templates | Internal codebase | `8000` |

*Note on Templates & Scaffolding:* Starter project blueprints and skills live inside `mcp-server`. Hermes accesses them via MCP when asked to scaffold new projects, keeping your personal workspace clean and unpolluted.

---

## 5. Verification & Troubleshooting

1. **Verify Mounts Inside Containers:**
   Check that your data is visible inside running containers:
   ```bash
   docker exec hermes ls -la /stack_root
   docker exec codegraph ls -la /stack_root
   ```
2. **Check Container Health & Logs:**
   ```bash
   docker compose ps
   docker compose logs -f hermes
   docker compose logs -f codegraph
   ```
3. **Verify Syncthing Status (Remote Pi Only):**
   ```bash
   systemctl status syncthing
   # Check folder path and ID in config:
   grep -A 2 '<folder id="stack_root"' /var/lib/syncthing/config.xml
   ```
4. **Secret Inspection:**
   - On Local: check your local `.env`.
   - On Pi: check `~/deployed-pai-stack/.env`. Re-running Ansible preserves existing secrets unless deleted.
