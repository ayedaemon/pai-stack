# pai-stack

**Hermes Agent + Syncthing + CodeGraph — stack_root on a Pi or your Mac.**

One `.env`, two commands, same stack. No reverse proxy. Tailscale WireGuard encrypts all remote traffic.

```text
Mac / Workstation (STACK_ROOT) ──WireGuard──▶ Pi (~/stack_root, Syncthing ID stack_root)
         │                                              │
         │ docker compose up (local)                   │ ansible + docker compose (remote)
         ▼                                              ▼
┌─────────────────┐  Docker network  ┌─────────────────┐
│ Hermes :9119    │──────────────────│ CodeGraph :20128│
│   :8642 API     │  /stack_root     │                 │
└─────────────────┘                  └─────────────────┘
         │                                    │
         └──────────┬─────────────────────────┘
                    ▼
         ┌───────────────────────────┐
         │ Syncthing (host, Pi only) │
         │ :8384 GUI  :22000 sync    │
         └───────────────────────────┘
```

* Inside every container the same path: `/stack_root` (host `$STACK_ROOT` → container `/stack_root`). `Projects/Foo` is always `stack_root/Projects/Foo`.
* On Pi host the same path: `~/stack_root` (Syncthing folder ID `stack_root`).
* Secrets are in `~/deployed-pai-stack/.env` (remote) or `./.env` (local), auto-generated on first run if blank.

---

## 1) Prerequisites

- **Both modes:** Docker & Docker Compose (Docker Desktop, OrbStack, or Engine), `git`.
- **Remote only:** `ansible-core` + `sshpass` on your Mac (`pip install ansible-core; brew install hudochenkov/sshpass/sshpass`), SSH to Pi (`ssh pi@rpi.burro-smelt.ts.net`).

---

## 2) One env file for both modes

```bash
cp .env.example .env
# Edit only Sections 1-3 in .env — rest has sane defaults or auto-generates.
```

```env
# 1. WORKSPACE — REQUIRED (both) — absolute path, no default
STACK_ROOT=/Users/you/stack_root          # Mac: /Users/you/stack_root, Pi: ~/stack_root after sync

# 2. LLM — set at least one so Hermes answers when local LLM is down
OPENROUTER_API_KEY="sk-or-v1-..."
# KILO_GATEWAY_API_KEY=""  MISTRAL_API_KEY=""

# 3. DEPLOY TARGET — empty = local, set = remote Pi
TARGET_HOST=""                             # "" → local, "rpi.burro-smelt.ts.net" → remote
TARGET_USER="pi"

# 4. SECRETS — leave blank → deploy.sh generates and writes back to .env
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=""
API_SERVER_KEY=""

# 5. SERVICES — rarely change
CODEGRAPH_ENABLED=true
KB_DIRS="."                                # "." = index whole stack_root

# 6. ADVANCED — remote-only & rarely touched
TAILSCALE_AUTH_KEY=""                      # only for fresh Pi not yet on tailnet
SYNCTHING_GUI_PASSWORD=""                  # blank → auto-generated on Pi, ignored locally
UID=1000 GID=1000                          # fallbacks, auto-detected
```

See `.env.example` for full 6-section order (Workspace → LLM → Deploy Target → Secrets → Services → Advanced). **Most users only touch 1-3.**

---

## 3) Choose a mode — what `deploy.sh` will do

### A. Local (`--local`, default) — no Pi, no Syncthing, no Tailscale

```bash
./deploy.sh              # same as --local
# or: make deploy
```

**Sequential nested steps (exactly what runs):**

1. **Pre-flight**
   1.1. Ensure `.env` exists (if missing, `cp .env.example .env` and exit so you edit `STACK_ROOT`).
   1.2. Load `.env` (filters `UID/GID` — bash readonly; docker reads file directly).
   1.3. Validate `STACK_ROOT` is set and absolute (`/…` or `~/…`). Fail fast if empty.
   1.4. Auto-generate missing secrets (`API_SERVER_KEY` 32 hex, `HERMES_*` 32/12) and write back to `.env` (idempotent — re-run preserves).

2. **Local filesystem**
   2.1. `mkdir -p $STACK_ROOT` on **this machine only**.
   2.2. **Does NOT** create `~/deployed-pai-stack` on this machine.
   2.3. **Does NOT** touch `/var/lib/syncthing`, `~/.config/syncthing`, or install Syncthing/Tailscale.
   2.4. Prints `Note: TARGET_HOST/TAILSCALE_AUTH_KEY ignored in --local` if those are set — they are Pi-only.

3. **Docker**
   3.1. `docker compose config` — validates `${STACK_ROOT}:/stack_root` mount.
   3.2. `docker compose up -d --build --remove-orphans` — builds/starts 3 services:
       - `hermes` (`:9119` dashboard, `:8642` API) — mounts `${STACK_ROOT}:/stack_root`
       - `codegraph` (`:20128`) — mounts `${STACK_ROOT}:/stack_root:ro` + alias `${STACK_ROOT}:/codebase:ro`
       - `mcp-server` (`:8000`) — no host mount, serves `skills/`/`tools/`/`kb/` via MCP.
   3.3. Volumes created (if missing): `hermes-data` (`/opt/hermes/data`), `codegraph-data` (`/data`). **NOT deleted** on `stop` — only `clean` (`down -v`) deletes.

4. **Post-check**
   4.1. `docker compose ps` — all 3 `healthy`/`running`.
   4.2. No `~/deployed-pai-stack/.env` created locally (that's Pi-only).
   4.3. **No folders modified outside:** does not create `~/stack_root/.stfolder`, does not write to `~/stack_root/Projects` (scaffold seed is Pi-only; locally your `STACK_ROOT` is used as-is).

**Result on disk (local):**
```
./pai-stack/.env                 # your edited + auto-generated secrets (0600 if you chmod)
$STACK_ROOT/                     # your existing folder, untouched except mkdir if missing
  Projects/  (as you left it)    # NOT seeded with _TEMPLATE locally
  github.com/ ...                # as you left it
```

---

### B. Remote (`--remote`) — Pi via SSH, full stack

```bash
# in .env: TARGET_HOST="rpi.burro-smelt.ts.net"  TARGET_USER="pi"
./deploy.sh --remote
# or: make deploy-remote
# fresh Pi: ./deploy.sh --remote --renew  (or make deploy-remote-renew)
```

**Sequential nested steps (linear Ansible playbook `ansible/playbook.yml:1-290`, flat no roles):**

1. **Pre-flight (same as local 1.1-1.4, but `SYNCTHING_GUI_PASSWORD` also generated if blank, only in --remote)**

2. **Host environment on Pi**
   2.1. **Detect UID/GID** — `getent passwd {{ansible_user}}` → `target_uid/gid` (e.g. `1000`), sets `pai_stack_root = {{ STACK_ROOT | default(pai_stack_root) }}` → `/home/pi/stack_root`.
   2.2. **Tailscale (optional)** — *only if `TAILSCALE_AUTH_KEY` non-empty*:
       2.2.1. Add GPG key + repo `pkgs.tailscale.com`
       2.2.2. `apt install tailscale`
       2.2.3. `tailscale up --authkey=... --hostname={{inventory_hostname}}`
       2.2.4. `tailscale set --operator={{ansible_user}}`
       *Skipped entirely if Pi already on tailnet (`TAILSCALE_AUTH_KEY=""`). No host files touched.*

   2.3. **Docker** — `docker --version` check → if missing `curl get.docker.com | sh` → `usermod -aG docker {{ansible_user}}`.

3. **Directories on Pi**
   3.1. `mkdir -p {{pai_stack_root}}` (`~/stack_root`, `0755`, `owner: pi`) — **the literal stack_root** (Syncthing ID `stack_root`).
   3.2. `mkdir -p {{pai_stack_dir}}` (`~/deployed-pai-stack`, `0755`) — the running copy of this repo.
   3.3. **Does NOT** create `~/Personal` or `~/stack_root/Projects` yet (next step).

4. **Clone repo on Pi**
   4.1. `git clone {{pai_repo_url}} → {{pai_stack_dir}}` (`force: yes`) — overwrites `~/deployed-pai-stack` with your Mac's `pai-stack` repo. **Local `~/deployed-pai-stack` on Mac is untouched.**
   4.2. **Does NOT** clone into `~/stack_root` — that stays your KB/code.

5. **Secrets on Pi (in memory → templated)**
   5.1. `openssl rand -hex` four times → `gen_api_key, gen_dash_pass, gen_dash_secret, gen_syncthing_pass`.
   5.2. `generated_* = existing .env value ? keep : new` — **preserves** `~/deployed-pai-stack/.env` secrets on re-deploy. Only first deploy writes.

6. **Template configs (overwritten every deploy)**
   6.1. `template env.j2 → {{pai_stack_dir}}/.env` (`0600`) — `STACK_ROOT={{pai_stack_root}}` (`/home/pi/stack_root`), `UID={{target_uid}}`, `API_SERVER_KEY={{generated_api_key}}`, `KB_DIRS={{kb_dirs}}`.
   6.2. `template hermes/config.yaml.j2 → {{pai_stack_dir}}/hermes/config.yaml` (`0644`) — Ecosystem Map now `stack_root: /stack_root [host ${STACK_ROOT} ↔ container /stack_root]`, `knowledgebase: - /stack_root`, `KB LAYOUT: /stack_root/ ← stack_root`.
   6.3. **Does NOT** template to `~/stack_root/.env` — only to `~/deployed-pai-stack`.

7. **Seed scaffold on Pi (only if missing)**
   7.1. `copy mcp-server/kb/Projects/ → {{pai_stack_root}}/Projects/` (`force: no`, `preserve`).
   7.2. Creates `~/stack_root/Projects/_TEMPLATE/{README.md, docs/architecture.md, telegram.md, config.md}` and `~/stack_root/AGENTS.md` **if they don't exist**.
   7.3. **Does NOT** overwrite existing `~/stack_root/Projects/YourApp/` — safe to re-run.
   7.4. **Local mode does NOT run this step** — no scaffold seeded locally.

8. **Syncthing host service on Pi (systemd, NOT Docker)**
   8.1. `apt install syncthing` (if missing).
   8.2. `syncthing --generate=/var/lib/syncthing` (creates `config.xml` if missing).
   8.3. Patch `config.xml` (become true):
       8.3.1. `urAccepted → -1` (telemetry off)
       8.3.2. `folder path → {{pai_stack_root}}` (`~/stack_root`)
       8.3.3. `folder id → stack_root` (was `personal`)
       8.3.4. `127.0.0.1:8384 → 0.0.0.0:8384` (bind to Tailscale IP)
       8.3.5. `address → tcp://0.0.0.0:22000`
       8.3.6. GUI `admin` + bcrypt hash of `generated_syncthing_pass` (only if no `<user>` yet)
   8.4. `touch {{pai_stack_root}}/.stfolder` (`0644`).
   8.5. Install `/etc/systemd/system/syncthing.service` (`ExecStart=syncthing serve --home=/var/lib/syncthing User={{ansible_user}}`), `daemon-reload`, `enable`, `start`.
   8.6. **Does NOT** install Syncthing as a Docker container — `docker compose ps` will **not** show it. `make clean` ( `down -v`) does **not** delete it.

9. **Build & start containers on Pi**
   9.1. `docker compose -f {{pai_stack_dir}}/docker-compose.yaml up -d --build --remove-orphans` — same 3 services as local, same mounts `~/stack_root:/stack_root` (and `:/codebase:ro` alias), same volumes `hermes-data`, `codegraph-data`.
   9.2. **Entrypoints inside containers:**
       9.2.1. `hermes/entrypoint.sh` — `KB_DIRS` → `/stack_root/${dir}`, `chown /opt/hermes/data`, `umask 000` for WAL, copy `hermes-config.yaml`, start `fs-notifier.sh &` (`WATCH_PATH=/stack_root`).
       9.2.2. `hermes/fs-notifier.sh` — `inotifywait -r /stack_root` → POST `http://codegraph:20128/query` debounce 30s.

10. **Health wait & output**
    10.1. Wait for `curl -f http://localhost:20128/health` (codegraph) and `http://localhost:8000/health` (mcp-server), then print:
        `Hermes https://<Tailscale IP>:9119  Syncthing https://<Tailscale IP>:8384`
    10.2. Secrets now live only in `~/deployed-pai-stack/.env` on Pi (`0600`).

**Result on disk (remote Pi):**
```
~/stack_root/                         # STACK_ROOT host, Syncthing ID stack_root, Send&Receive
  .stfolder
  AGENTS.md                           # seeded if missing
  Projects/_TEMPLATE/ ...             # seeded if missing (force: no)
  Projects/YourApp/ ...               # you create via chat, synced from Mac
~/deployed-pai-stack/                 # pai_stack_dir — the running compose project
  .env                                # templated, 0600, STACK_ROOT=/home/pi/stack_root
  docker-compose.yaml                 # /stack_root mounts
  hermes/config.yaml                  # templated
/var/lib/syncthing/config.xml         # patched — path ~/stack_root, id stack_root
/etc/systemd/system/syncthing.service # host service
Docker volumes: hermes-data, codegraph-data
```

---

## 4) What is NOT created or modified

| Mode | Not created / Not modified |
|------|----------------------------|
| **Local** | No `~/deployed-pai-stack` on local machine; no `/var/lib/syncthing`; no `/etc/systemd/system/syncthing.service`; no Tailscale install; no `~/stack_root/.stfolder` created by deploy (only `mkdir -p $STACK_ROOT` if missing); no seed of `Projects/_TEMPLATE` (your `STACK_ROOT` is left as-is); no overwrite of an existing `.env` secrets (generated only if blank). |
| **Remote** | Does not modify your Mac's `STACK_ROOT` folder (except via Syncthing sync after); does not modify `~/stack_root/Projects/YourApp` if it already exists (`force: no`); does not delete `hermes-data`/`codegraph-data` unless `--renew`/`make clean`; does not overwrite `~/deployed-pai-stack/.env` secrets on re-deploy (preserves); does not create `~/Personal` (literal `~/stack_root` only). |
| **Both** | Never writes raw secrets to KB markdown (`Projects/`, `Skills`); never `force: yes` on `~/stack_root`; `clean` (`down -v`) is explicit and deletes named volumes only. |

---

## 5) Verify after deploy

```bash
# Local or Pi (SSH to Pi first if remote):
docker exec hermes ls -la /stack_root          # should show Projects
docker exec codegraph ls -la /stack_root       # same
docker compose ps                               # hermes/codegraph/mcp-server healthy
docker compose logs -f hermes
# Remote Pi only:
systemctl status syncthing                      # active
grep -A2 '<folder id="stack_root"' /var/lib/syncthing/config.xml  # path ~/stack_root
cat ~/deployed-pai-stack/.env | grep STACK_ROOT # /home/pi/stack_root
```

---

## 6) Update & clean

```bash
./deploy.sh --local              # local update (rebuild)
./deploy.sh --remote             # remote update (git pull + rebuild, preserves secrets)
./deploy.sh --local --renew      # local fresh (DELETE volumes)
./deploy.sh --remote --renew     # remote fresh
make clean                       # DANGER: docker compose down -v (named volumes)
```

See `docs/SETUP_FLOW.md` for the 2-mode mental model and `docs/BLUEPRINT.md` for decisions.

