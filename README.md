# pai-stack

**Hermes Agent** + **Syncthing** + **Caddy (Tailscale HTTPS)** + **CodeGraph**.

One command (`./deploy.sh`) provisions a Pi or Linux server from bare SSH into a
personal AI infrastructure: an AI agent grounded in your notes, file sync across
your devices, code intelligence, all served over Tailscale TLS.

---

## 🌐 Network Blueprint

- **Outside access (from your Mac / devices)**: only via **Tailscale HTTPS** through
  Caddy (`https://<tailscale-domain>:<port>`) with automatic Tailscale certificates.
  No public ports.
- **Inside communication**: plain HTTP over the local Docker network
  (`caddy → hermes:9119`, `hermes → codegraph:20128`, Caddy → host Syncthing).

```text
Mac / Clients (over Tailscale)
               │
               ▼ HTTPS (Tailscale TLS)
       ┌───────────────┬───────────────┐
       │             Caddy             │ (Reverse Proxy)
       └───────┬───────┬───────┬───────┘
               │       │       │
       ┌───────┘       │       └───────┐
       ▼               ▼               ▼
Hermes (:9119/8642)  CodeGraph       Syncthing
                       (:20128)        (:8384)
                     internal only   (host service)
```

---

## 🧭 What You Get

| Service | Purpose | How it connects |
|---------|---------|-----------------|
| **Hermes** | AI agent — RAG over your notes, Kanban boards, Telegram chat-ops, web dashboard | Reads/writes `PERSONAL_FOLDER`, queries CodeGraph for code intelligence |
| **Syncthing** | Bidirectional file sync across your devices (runs on the Pi host as a systemd service, not a container) | Syncs `PERSONAL_FOLDER` so Mac ↔ Pi notes stay identical |
| **Caddy** | Reverse proxy with automatic Tailscale TLS | Only entry point — all services via `https://domain:port` |
| **CodeGraph** | Code intelligence API (call chains, impact analysis, symbol search) | Hermes queries it internally; reads your codebase read-only |

**Data flow:** write notes on Mac → Syncthing syncs to Pi → Hermes indexes them for
RAG → CodeGraph parses code files → Hermes uses both to answer.

---

## 🚀 Setup

Provisioning is done **entirely by Ansible** — there is no separate Docker-only
bootstrap. You point `./deploy.sh` at the target by IP/hostname; it SSHes in and
installs Docker (if missing), Tailscale (if missing, joins your tailnet), secrets,
data dirs, and the container stack.

**Prerequisites on your dev machine:** `ansible-core` + `sshpass`.

```bash
pip install ansible-core
# macOS: brew install hudochenkov/sshpass/sshpass
# Debian/Ubuntu: apt install sshpass
```

`TARGET_HOST` can be a **LAN address** (e.g. `192.168.1.50`) or a **Tailscale
address** (MagicDNS name like `rpi.burro-smelt.ts.net`, or a `100.x.y.z` IP).
The only requirement is SSH reachability from wherever you run `./deploy.sh`.

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env` (see `.env.example` for the full reference):

| Variable | What to set |
|----------|-------------|
| `TARGET_HOST` / `TARGET_USER` | SSH address + user on the target (e.g. `rpi…ts.net` / `pi`) |
| `TAILSCALE_DOMAIN` | MagicDNS name Caddy serves TLS for |
| `TAILSCALE_AUTH_KEY` | Auth key so a **fresh** device auto-joins Tailscale (blank if already on the tailnet) |
| `HERMES_DASHBOARD_PASSWORD` | Blank = auto-generated on first deploy, printed at the end |
| `SYNCTHING_GUI_USER` / `SYNCTHING_GUI_PASSWORD` | GUI login (blank password = auto-generated) |
| `LLAMACPP_BASE_URL` / `LLAMACPP_MODEL_NAME` | Primary model server + default model |
| `OPENROUTER_API_KEY` / `KILO_GATEWAY_API_KEY` / `MISTRAL_API_KEY` | Fallback providers (blank = skipped) |
| `PERSONAL_FOLDER` | Path **on the target** for your synced notes (default: target user's `~/Personal`, sitting next to `~/pai-stack` under the same user) |
| `SSH_PASSWORD` / `BECOME_PASSWORD` | Set for zero prompts; blank = prompted interactively. Used only locally for the SSH/sudo session, never copied to the target |

### 2. Deploy

```bash
./deploy.sh
```

The runner installs Docker + Tailscale, generates secrets, and starts all
containers. At the end it prints every URL, username, and generated password —
**save that output.**

> Re-running `./deploy.sh` is safe: secrets already in the target
> `~/pai-stack/.env` are preserved, the `kb/` scaffold never overwrites your
> edits (`force: no`), and Syncthing config is only patched when needed.
> `./deploy.sh --renew` does a full fresh reinstall instead (destructive).

---

## ✅ Post-Setup Verification (do these in order)

All `docker compose …` commands below run **on the Pi** inside `~/pai-stack`
(SSH in first). Anything that fails here will cascade into the later steps, so
don't skip ahead.

### Step 1 — Sync your local folder (Syncthing)

The Pi's `PERSONAL_FOLDER` (`~/Personal`) is the canonical sync folder (Folder ID
`personal`). Syncthing runs as a host systemd service; Caddy proxies its GUI
with Tailscale TLS.

1. Install Syncthing on your Mac (`brew install syncthing`, or the Syncthing app).
   Join the same Tailscale tailnet so the devices find each other directly.
2. Open the Pi's GUI at `https://<tailscale-domain>:8384`, log in with the
   Syncthing credentials from the deploy output, and copy the Pi's Device ID
   (**Actions → Show ID**).
3. On your Mac (`http://127.0.0.1:8384`): **Add Remote Device** → paste the Pi's
   Device ID → Save. Add your local notes folder (e.g. `~/Personal`) with
   **Folder ID exactly `personal`**, share it with the Pi, Save.
4. Back on the Pi: accept the folder share and point it at the existing
   `~/Personal` path.

**Confirm it works:**

- Both GUIs show the `personal` folder as **Up to Date**.
- `ls ~/Personal/.stfolder` exists on the Pi (folder marker).
- Drop a canary file on one side and watch it appear on the other:
  ```bash
  # on your Mac:
  echo "sync-check $(date)" > ~/Personal/.sync-check.txt
  # on the Pi (give it up to a minute):
  cat ~/Personal/.sync-check.txt
  ```
  Then delete the canary from either side.

> If a device won't connect, set its **Addresses** explicitly to the other side's
> Tailscale address, e.g. `tcp://rpi.burro-smelt.ts.net:22000`. Sync is
> bidirectional (Send & Receive); deletes land in `.stversions`, not permanent loss.

### Step 2 — Check CodeGraph sees the shared folder

CodeGraph is **internal only**: it exposes no host port (`docker-compose.yaml`
has no `ports:` for it; Caddy's `:20128` block is container-internal). Hermes
reaches it at `http://codegraph:20128`. It mounts your notes read-only at
`/codebase` and keeps its graph DB in the `codegraph-data` volume. The image
ships `curl`, so query it from inside the container:

```bash
cd ~/pai-stack

# 1. container is up
docker compose ps codegraph

# 2. liveness (lightweight by design — no graph work here)
docker compose exec -T codegraph curl -s http://localhost:20128/health
# → {"status":"ok"}

# 3. it sees your synced files (read-only mount of PERSONAL_FOLDER)
docker compose exec -T codegraph ls /codebase
# → should list your Personal contents (silverbulletKB, Projects, github.com/…)

# 4. graph queries work — pick a real symbol from one of your synced code files
docker compose exec -T codegraph curl -s http://localhost:20128/stats
docker compose exec -T codegraph curl -s "http://localhost:20128/search?q=<symbol-from-your-code>"
```

**What good looks like:** `/health` returns ok, `/codebase` mirrors `~/Personal`,
`/stats` and `/search` return JSON for your code (not errors/empty). First heavy
queries build the graph and can take a few minutes on large codebases — that's
normal. If `/codebase` is empty, fix Step 1 first; CodeGraph can only index what
Syncthing has synced.

### Step 3 — Verify Hermes KB indexing

Hermes indexes the **entire** `PERSONAL_FOLDER` (`/opt/data/Personal` in the
container, `hermes/config.yaml.j2:127-135`) with local embeddings and
re-indexes on file change. `silverbulletKB/AGENTS.md` is always injected via
`context_files`, even when retrieval returns nothing. Hermes writes back to
`silverbulletKB/` — plain markdown, Syncthing-synced.

```bash
cd ~/pai-stack

# 1. scaffold was seeded once (never overwritten on re-deploy)
ls ~/Personal/silverbulletKB/AGENTS.md

# 2. config the container actually booted with indexes all of PERSONAL_FOLDER
grep -A4 knowledgebase hermes/config.yaml

# 3. dashboard is up behind Caddy (log in: admin + HERMES_DASHBOARD_PASSWORD)
curl -sk -o /dev/null -w "%{http_code}\n" https://<tailscale-domain>:9119
# → 200 (or a login redirect — anything but connection refused / 502)

# 4. look for indexing activity
docker compose logs --tail=200 hermes | grep -iE "reindex|knowledge|embed|AGENTS"
```

**Functional check (strongest signal):** the canary file from Step 1 lives in
`~/Personal`, so it is already in Hermes' index. Ask Hermes about it in Step 4 —
if it can quote it back with a `file:lines` citation, indexing works end to end.

### Step 4 — First chat: confirm Hermes understands your projects and its role

Hermes lives in **Telegram Forum Topics** (one group per project, one topic per
issue) plus the Dashboard/API. Its standing rules (`hermes/config.yaml.j2:48-118`): retrieve first, cite
`file:lines`, stay in the originating topic's project, never guess, never write
KB without your confirm, never store raw secrets.

1. Add Hermes to a Telegram forum group for one real project and post in a topic.
   On a brand-new group/topic it should **propose recording** the `group_id` +
   `topic_id` in `Projects/<Name>/telegram.md` (and an `issues/<slug>.md`) before
   acting — that mapping is its permission gate. Confirm it.
2. Send these three probes in the same topic:
   - `What projects do you know about? Quote AGENTS.md.`
     → Expect a short list citing `silverbulletKB/AGENTS.md:lines`. If the KB has
     no entry for your project yet, expect it to **search `~/Personal` and propose
     a scaffold** from `kb/Projects/_TEMPLATE/` (README, architecture, telegram,
     config) + an `AGENTS.md` update — then wait for your confirm. It must not
     invent project names.
   - `Where do you read and write notes, where is my code, and how do you use CodeGraph?`
     → Expect: reads all of `PERSONAL_FOLDER` (`/opt/data/Personal`), writes KB to
     `silverbulletKB/`, code under `github.com/…` or `Projects/…`, CodeGraph at
     `http://codegraph:20128` for call chains / impact / symbol search.
   - `What did my canary note say, and where is it stored?`
     → Expect the synced content quoted back with a `file:lines` citation —
     proof that Sync → index → retrieval works.
3. Check the write-back: after it proposes a KB update and you confirm, verify the
   file exists under `~/Personal/silverbulletKB/` **and** on your Mac (Syncthing
   round-trip), e.g. `Projects/<Name>/issues/<slug>.md`.

**You are done when:** answers stay scoped to the topic's project, every factual
claim carries a `file:lines` citation, out-of-scope requests get refused with a
pointer to the right topic (`Not in telegram.md…`), secrets are stored as
references (never raw values), and nothing is cross-posted to other topics.

---

## 🧭 Services & Access

All services are reachable over HTTPS via your Tailscale domain:

| Service | Tailscale URL | Auth |
|---------|---------------|------|
| **Hermes Dashboard** | `https://<tailscale-domain>:9119` | Basic Auth `admin` / `HERMES_DASHBOARD_PASSWORD` (auto-generated if blank; stored as `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` in target `~/pai-stack/.env`) |
| **Hermes API** | `https://<tailscale-domain>:8642` | Bearer token `API_SERVER_KEY` (auto-generated on target) |
| **Syncthing GUI** | `https://<tailscale-domain>:8384` | `SYNCTHING_GUI_USER` / `SYNCTHING_GUI_PASSWORD` (proxy → host `:8385`) |

> Generated secrets live in the **target** `~/pai-stack/.env` (`0600`,
> rendered from `ansible/roles/pai_stack/templates/env.j2`) and are preserved on
> re-deploy. Your local `.env` is never copied to the target — only
> `TAILSCALE_DOMAIN`, `HERMES_DASHBOARD_PASSWORD`, and `PERSONAL_FOLDER` are forwarded
> as Ansible extra vars (see `deploy.sh` and `ansible/README.md`).

---

## 🧠 Structuring the Knowledge Base (keeping Hermes on-scope)

Hermes is grounded by three things (all in `hermes/config.yaml`):

1. **`agent.system_prompt`** — fixed rules: retrieve first, cite sources, refuse
   out-of-scope, never guess.
2. **`context_files: [/opt/data/Personal/silverbulletKB/AGENTS.md]`** — the project
   manifest, always injected even when retrieval returns nothing. Edit it as
   projects change.
3. **The RAG index** over `PERSONAL_FOLDER` — auto-retrieved chunks (max 8, relevance ≥ 0.5).

### Recommended layout (seeded once into `PERSONAL_FOLDER` on first deploy)

```text
~/Personal/                        (PERSONAL_FOLDER → /opt/data/Personal)
├── AGENTS.md                      ← scope manifest (always injected via context_files)
├── Projects/
│   ├── ProjectAlpha/
│   │   ├── README.md              ← overview, goals, status
│   │   ├── docs/architecture.md   ← technical design (specific headings = better chunks)
│   │   ├── telegram.md            ← channels/groups + what Hermes may act in
│   │   └── config.md              ← params, secret *references* (never raw secrets)
│   └── ProjectBeta/ ...
└── References/                    ← shared glossary, runbooks
```

Tips for good retrieval (less drift):

- Use **specific H2/H3 headings** so chunks map to one topic.
- Keep `AGENTS.md` as the single source of truth for *which* projects/channels exist.
- Put Telegram channel → project mapping in each `telegram.md` and summarize in `AGENTS.md`.
- Store secret *references* (e.g. "API key in 1Password / env `X`"), never raw values.
- The scaffold under `kb/` in this repo is copied into `PERSONAL_FOLDER` once
  (`force: no`), so your later edits are never overwritten on re-deploy.

---

## ⚙️ Updating Configuration

To update Hermes configuration:

1. Edit `hermes/config.yaml`
2. Run `docker compose restart hermes` (or `./deploy.sh --tags pai_stack`)

### 🛠️ Makefile Shortcuts

`make deploy` provisions remotely via `./deploy.sh`. The runtime targets below
run `docker compose …` in the current directory — use them **on the Pi inside
`~/pai-stack`** (or anywhere the compose files live):

| Command | Description |
|---------|-------------|
| `make deploy` | Remote provision via `./deploy.sh` |
| `make logs` | Tail logs |
| `make status` | Show running services |
| `make stop` / `make restart` | Stop / restart the stack |
| `make update` | Pull latest images & rebuild |
| `make clean` | Stop & remove local data (destructive) |

---

## 📖 Design & Philosophy

> For the full system design, trade-offs, and the principles that keep Hermes from
> drifting, see **[docs/BLUEPRINT.md](docs/BLUEPRINT.md)** and **[docs/adr/](docs/adr/)**.

## 📁 Repository Structure

```text
├── README.md                  # Quickstart & user guide
├── docs/
│   ├── BLUEPRINT.md           # Full architecture, flows, principles, ADRs index
│   └── adr/                   # Decisions with trade-offs
├── deploy.sh                  # One-command Ansible runner (Mac remote or host local)
├── docker-compose.yaml        # Main stack: caddy, hermes, codegraph
├── caddy/                     # Caddy reverse proxy & TLS config
├── hermes/                    # Hermes agent config, entrypoint, kanban patch
├── codegraph/                 # CodeGraph API server (HTTP wrapper, :20128 internal)
├── kb/                        # KB scaffold (copied to PERSONAL_FOLDER on first deploy)
├── Skills/                    # CodeGraph usage skill for Hermes
└── ansible/                   # Automation suite
    ├── ansible.cfg            # Ansible & SSH configuration
    ├── inventory.ini          # Target inventory (deploy.sh builds its own -i inline)
    ├── playbook.yml           # Unified deployment playbook
    ├── group_vars/            # User settings & secrets (all.yml)
    └── roles/                 # Roles: common, tailscale, docker, pai_stack
```

---

## 💾 Data Storage & Permissions

Container state lives in **Docker named volumes** (owned by each container's own
runtime UID) rather than host bind mounts. Only host-coupled data is bind-mounted.

| Data | Storage | Notes |
|------|---------|-------|
| Hermes sessions/keys | named volume `hermes-data` | chowned to `HERMES_UID` in `hermes/entrypoint.sh` |
| Caddy certs/config | named volumes `caddy-data`, `caddy-config` | |
| Knowledge Base | **bind mount** `${PERSONAL_FOLDER}` → `/opt/data/Personal` | Syncthing syncs `${PERSONAL_FOLDER}`; plain markdown indexed by Hermes |
| CodeGraph graph DB | named volume `codegraph-data` | SQLite graph, separate from the codebase |
| Codebase (CodeGraph view) | **bind mount (ro)** `${PERSONAL_FOLDER}` → `/codebase` | read-only, never written by CodeGraph |
| Config files | **bind mount (ro)** `./hermes/config.yaml`, `./caddy/Caddyfile` | read-only, no writes |

**Backups:** named volumes live in `/var/lib/docker/volumes/` on the Pi. Export one with:

```bash
docker run --rm -v <volume>:/data -v "$PWD":/backup busybox \
  tar czf /backup/<volume>.tar.gz -C /data .
```

The KB is just files under `${PERSONAL_FOLDER}/silverbulletKB` (already Syncthing-synced).

**Reset:** `make clean` runs `docker compose down -v`, which deletes all named
volumes (Hermes re-auths, Caddy re-issues Tailscale certs).

**Fresh reinstall:** `./deploy.sh --renew` — Ansible removes docker, syncthing and
their configs, plus the entire `~/pai-stack` directory, then reinstalls from
scratch. Synced KB files under `PERSONAL_FOLDER` and Tailscale are **not** deleted.
