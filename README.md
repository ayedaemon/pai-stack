# pai-stack

**Hermes Agent** + **OmniRoute** + **SilverBullet** + **Syncthing** + **Caddy (Tailscale HTTPS)**.

---

## 🌐 Network Blueprint

- **Outside access (from your Mac / devices)**: Accessed via **Tailscale HTTPS** using Caddy (`https://<tailscale-domain>:<port>`) with automatic Tailscale TLS certificates.
- **Inside communication**: Inter-container traffic communicates securely over the local Docker network (`caddy -> omniroute:20128`, `caddy -> hermes:9119`, `caddy -> silverbullet:3000`, `hermes -> omniroute:20128`).

```text
Mac / Clients (over Tailscale)
              │
              ▼ HTTPS (Tailscale TLS)
      ┌───────────────┬───────────────┐
      │             Caddy             │ (Reverse Proxy)
      └───┬───────┬───────┬───────┬───┘
          │       │       │       │
  ┌───────┘       │       │       └───────┐
  ▼               ▼       ▼               ▼
Hermes       OmniRoute  SilverBullet  Syncthing
(:9119)      (:20128)     (:3000)      (:8384)
```

---

## 🚀 Quick Start

This stack is provisioned **entirely by Ansible** — there is no separate Docker-only
bootstrap. You point it at the target machine by IP/hostname, and it SSHes in and
installs everything from bare SSH:

- **Docker** (if missing)
- **Tailscale** (if missing) + joins your tailnet via `TAILSCALE_AUTH_KEY`
- secrets, data dirs, the container stack, and OmniRoute seeding

The target address in `.env` (`TARGET_HOST`) can be **either**:

- a **LAN address** (e.g. `192.168.1.50`) while the Pi is on your local network, **or**
- a **Tailscale address** (MagicDNS name like `rpi.burro-smelt.ts.net`, or a `100.x.y.z` IP) once it's already on your tailnet.

> The only prerequisite is **SSH reachability** to `TARGET_HOST` from wherever you run
> `./deploy.sh` (your Mac, or the Pi itself with `--local`). Ansible handles the rest.

### 1. Configure

```bash
cp .env.example .env
# Edit:
#   TARGET_HOST      = LAN or Tailscale IP/hostname of the target
#   TARGET_USER      = SSH user on the target (e.g. pi)
#   TAILSCALE_DOMAIN = MagicDNS name Caddy serves TLS for
#   TAILSCALE_AUTH_KEY = key so a FRESH device auto-joins Tailscale
#                        (leave blank if the target is already on Tailscale)
#   SSH_PASSWORD     = SSH login password (remote runs) — set for ZERO prompts
#   BECOME_PASSWORD  = sudo password (remote AND --local) — set for ZERO prompts
```

> **Fully unattended:** set `SSH_PASSWORD` and `BECOME_PASSWORD` in `.env` and the
> deploy runs end-to-end with no prompts. They are used only locally to authenticate
> the Ansible SSH/become session and are **never copied to the target**. Leave them
> blank to be prompted interactively instead.

### 2. Deploy

```bash
# From your Mac (or any Docker host) — SSHes to TARGET_HOST:
./deploy.sh

# Or directly on the target machine itself:
./deploy.sh --local
```

*(Enter your SSH and sudo password when prompted. The runner installs Docker +
Tailscale, generates secrets, starts all containers, and seeds model combos.)*

---

## 🧭 Services & Access

All services are securely accessible over HTTPS via your Tailscale domain (e.g. `rpi.burro-smelt.ts.net`):

| Service | Tailscale URL | Purpose | Auth |
|---------|---------------|---------|------|
| **Hermes Dashboard** | `https://rpi.burro-smelt.ts.net:9119` | Hermes Web Agent UI | Basic Auth (`admin` / password in `.env`) |
| **Hermes API** | `https://rpi.burro-smelt.ts.net:8642` | OpenAI-compatible Agent API | Bearer Token (`API_SERVER_KEY`) |
| **OmniRoute** | `https://rpi.burro-smelt.ts.net:20128` | Multi-LLM Routing Gateway | Managed by OmniRoute |
| **SilverBullet** | `https://rpi.burro-smelt.ts.net:7070` | Knowledge base & note-taking | Basic Auth (`admin` / password in `.env`) |
| **Syncthing GUI** | `https://rpi.burro-smelt.ts.net:8384` | Cross-device file synchronization | Syncthing GUI auth (`admin` / password in `.env`) |

---

## 🧠 Knowledge Base & Hermes RAG

- **SilverBullet Space**: Stored at `STACK_ROOT` (default `$HOME/Personal`, configurable in `.env`) on the host (shared directly with Hermes).
- **Hermes Vector Search**: Hermes indexes `STACK_ROOT` automatically using local embeddings (`all-MiniLM-L6-v2` via fastembed, ~80MB RAM) with automatic re-indexing on file change.
- **Pre-loaded Plugs**: SilverBullet comes with `silverbullet-graphview` (Obsidian-style graph) and `treeview` pre-installed and auto-seeded.

---

## 📚 Structuring the Knowledge Base (keeping Hermes on-scope)

Hermes is grounded by three things (all in `hermes/config.yaml`):

1. **`agent.system_prompt`** — fixed rules: retrieve first, cite sources, refuse
   out-of-scope, never guess. This is what stops it from drifting.
2. **`context_files: [/opt/data/Personal/AGENTS.md]`** — a project manifest that is
   **always injected**, even when retrieval returns nothing. Edit `AGENTS.md` as
   projects change.
3. **The RAG index** over `STACK_ROOT` — auto-retrieved chunks (max 8, relevance ≥ 0.5).

### Recommended layout (seeded automatically into `STACK_ROOT` on first deploy)

```
~/Personal/                        (STACK_ROOT → /opt/data/Personal)
├── AGENTS.md                      ← scope manifest (always injected via context_files)
├── Projects/
│   ├── ProjectAlpha/
│   │   ├── README.md             ← overview, goals, status
│   │   ├── docs/architecture.md   ← technical design (specific headings = better chunks)
│   │   ├── telegram.md            ← channels/groups + what Hermes may act in
│   │   └── config.md              ← params, secret *references* (never raw secrets)
│   └── ProjectBeta/ ...
└── References/                   ← shared glossary, runbooks
```

Tips for good retrieval (less drift):
- Use **specific H2/H3 headings** so chunks map to one topic.
- Keep `AGENTS.md` as the single source of truth for *which* projects/channels exist.
- Put Telegram channel → project mapping in each `telegram.md` and summarize in `AGENTS.md`.
- Store secret *references* (e.g. "API key in 1Password / env `X`"), never the raw values, in notes.
- The scaffold under `kb/` in this repo is copied into `STACK_ROOT` once (`force: no`),
  so your later edits are never overwritten on re-deploy.

---

## 🔄 Syncing Your Devices (Syncthing)

The Pi's `~/Personal` (i.e. `STACK_ROOT`) is the **canonical sync folder**.
Syncthing runs directly on the Pi host (systemd service, not a container) and the
deploy
automatically configures Syncthing's default folder with **Folder ID `personal`**
pointing at that path, so you only need to link your other devices to it.
Wire up any other machine so its local notes folder stays bidirectionally in sync
with the Pi.

### Prerequisites
- Install Syncthing on the other device (macOS: `brew install syncthing` / Syncthing
  app; Linux: your package manager; Windows/mobile: syncthing.net).
- Both devices must be reachable. Easiest: **join the same Tailscale tailnet** so they
  discover each other directly. (Syncthing also works over LAN or relayed, but Tailscale
  keeps it simple and encrypted.)

### Steps
  1. **Open the Pi's GUI** — `https://<tailscale-domain>:8384` and log in with the
     Syncthing GUI credentials printed at the end of `./deploy.sh`
     (default user `admin`, random password saved in the target `.env` as
     `SYNCTHING_GUI_PASSWORD`). The GUI is served through Caddy (Tailscale TLS),
     which proxies to Syncthing's local port `8385`.
2. **On the Pi (the "introducer")**:
   - Go to **Actions → Show ID** and copy the Device ID.
   - (Optional but recommended) open the default folder (`Personal`), go to
     **Sharing**, and tick **Publish auto-accept**. Or enable
     **Settings → General → Default folder** as needed.
3. **On your local machine**:
   - Open its Syncthing GUI (usually `http://127.0.0.1:8384`).
   - **Add Remote Device** → paste the Pi's Device ID → **Save**.
   - Create (or pick) a local folder you want to sync (e.g. `~/Personal` on your Mac).
     When adding it, set the **Folder ID** to exactly the Pi's folder ID
     (default `personal` — copy it from the Pi's folder **Edit → General → Folder ID**).
   - Under **Sharing**, select the Pi device and **Save**.
 4. **Back on the Pi**: accept the incoming folder share, and choose the existing
    `~/Personal` path as the folder location (so the Pi's current notes become the
    synced copy). Syncthing will then sync **both ways** — edits on either side propagate.

> ⚠️ **Connecting devices.** Syncthing runs directly on the Pi host (as a systemd
> service), so it binds the **Tailscale** interface directly and advertises its
> Tailscale address (`100.x.y.z:22000`) automatically — usually no manual address
> override is needed.
> Just add the other device by its **Device ID** and it connects over Tailscale.
> If a particular device still won't connect, set its **Addresses** (under the
> device's *Advanced* settings) explicitly to the other side's Tailscale address,
> e.g. `tcp://rpi.burro-smelt.ts.net:22000`.

> **Tip — one-click pairing:** instead of manual IDs, on the Pi click
> **Actions → Show QR code / Add Device** and scan it from the Syncthing mobile/desktop
> app. Because the Pi is already on Tailscale, the link "just works".

### Notes
- This is **bidirectional** by default (Send & Receive). Deleting a file on one side
  moves it to `.stversions` (trash) on the other, not permanent loss.
- `STACK_ROOT` is the same folder Hermes and SilverBullet read/write, so notes you edit
  locally show up in your knowledge base automatically.
- To change the sync folder path on the Pi, edit `STACK_ROOT` in `.env` and re-run
  `./deploy.sh`.

---

---

## 🤖 Delegate Agents (Antigravity + OpenCode)

Hermes can delegate coding tasks to two **isolated CLI containers** over MCP
(Model Context Protocol). Hermes stays the manager: it retrieves project
context from the KB, formulates the precise task, calls a delegate, reviews
the result, and writes the final artifact back into `silverbulletKB` (which
syncs to your machine). The delegates never get host/Docker access.

```
Hermes ──MCP/HTTP──► antigravity container  ─┐
                   └─► opencode container     ├──► agent-workspace (/workspace, rw)
                                                └──► silverbulletKB (/kb, read-only)
```

- **`antigravity`** — Google Antigravity CLI (`agy`) on your **Pro account**
  (a different model family from OpenCode, good for independent second
  opinions / research / docs).
- **`opencode`** — OpenCode CLI using its **own free models**.
- Both expose one tool, `run_task(task, context_refs, mode)`, over HTTP MCP
  at `http://antigravity:8000/mcp` and `http://opencode:8001/mcp` (internal
  only — **not** exposed via Caddy). They share `agent-workspace` and a
  read-only mount of the KB; they cannot touch `STACK_ROOT` directly.
- Concurrency is one-task-at-a-time per delegate (protects the Pi).

### One-time Antigravity auth
The `agy` container uses your Pro account via OAuth. After the first deploy:

```bash
docker compose exec -it antigravity agy login   # device-code flow → paste in browser
```

Credentials persist in the `antigravity-auth` volume, so no re-login on restart.

### Configuration (`.env`)
| Var | Purpose | Default |
|-----|---------|---------|
| `ANTIGRAVITY_MODEL` | Model `agy` uses | `Gemini 3.5 Flash (High)` |
| `OPENCODE_MODEL` | OpenCode model (blank = its free/default) | _(blank)_ |
| `OPENCODE_PERMISSION` | Must be `{"*":"allow"}` or OpenCode hangs headless | `{"*":"allow"}` |

### Notes
- Delegates operate in `/workspace`. For code tasks, give Hermes a git repo
  URL or path; the delegate clones/edits there and returns a diff/summary.
- Hermes writes the merged result into `silverbulletKB` — it does **not** let a
  delegate write the live KB directly.

---

## ⚙️ Updating Configuration

To update Hermes configuration:
1. Edit `hermes/config.yaml`
2. Run `docker compose restart hermes` (or `./deploy.sh --tags pai_stack`)

To re-seed model combos in OmniRoute:
```bash
make seed
# (equivalent to: docker compose exec -T omniroute /app/seed-combos.sh)
```

### 🛠️ Makefile Shortcuts

A `Makefile` wraps the Ansible runner and common runtime operations:

| Command | Description |
|---------|-------------|
| `make deploy` | Remote provision via `./deploy.sh` |
| `make deploy-local` | Provision this host via `./deploy.sh --local` |
| `make seed` | Re-seed OmniRoute combos |
| `make logs` | Tail logs |
| `make status` | Show running services |
| `make stop` / `make restart` | Stop / restart the stack |
| `make update` | Pull latest images & rebuild |
| `make clean` | Stop & remove local data (destructive) |

---

## 📁 Repository Structure

```
├── README.md                  # Main blueprint & documentation
├── deploy.sh                  # One-command runner (Mac remote or host local)
├── docker-compose.yaml        # Main stack definition
├── caddy/                     # Caddy reverse proxy & TLS config
├── hermes/                    # Hermes agent config & entrypoint
├── omniroute/                 # OmniRoute setup scripts
├── silverbullet/              # SilverBullet Dockerfile & entrypoint
└── ansible/                   # Automation suite
    ├── Dockerfile             # One-time task runner image
    ├── ansible.cfg            # Ansible & SSH configuration
    ├── inventory.ini          # Target inventory
    ├── playbook.yml           # Unified deployment playbook
    ├── group_vars/            # User settings & secrets (all.yml)
    └── roles/                 # Roles: common, tailscale, docker, pai_stack

## 💾 Data Storage & Permissions

To avoid `EACCES` permission errors, container state is kept in **Docker named
volumes** (owned by each container's own runtime UID) rather than host bind
mounts. Only host-coupled data is bind-mounted.

| Data | Storage | Notes |
|------|---------|-------|
| Hermes sessions/keys | named volume `hermes-data` | chowned to `HERMES_UID` in `hermes/entrypoint.sh` |
| OmniRoute state | named volume `omniroute-data` | OmniRoute runs as root (`user: "0:0"`) |
| Caddy certs/config | named volume `caddy-data`, `caddy-config` | |
| Agent scratch + Antigravity OAuth | named volume `agent-workspace`, `antigravity-auth` | delegate containers run as root |
| Knowledge Base | **bind mount** `${STACK_ROOT}/silverbulletKB` | required — Syncthing syncs `${STACK_ROOT}`; SilverBullet runs as `${UID}:${GID}` to match host ownership |
| Config files | **bind mount (ro)** `./hermes/config.yaml`, `./caddy/Caddyfile`, `./omniroute/seed-combos.sh` | read-only, no writes |

**Backups:** named volumes live in `/var/lib/docker/volumes/` on the Pi. Export one with:
```bash
docker run --rm -v <volume>:/data -v "$PWD":/backup busybox \
  tar czf /backup/<volume>.tar.gz -C /data .
```
The KB is just files under `${STACK_ROOT}/silverbulletKB` (already Syncthing-synced).

**Reset:** `make clean` runs `docker compose down -v`, which deletes all named
volumes (Hermes re-auths, OmniRoute reseeds, Caddy re-issues Tailscale certs).
```
