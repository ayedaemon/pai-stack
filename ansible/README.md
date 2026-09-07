# Ansible Automation for pai-stack

Automated deployment of **Hermes Agent**, **CodeGraph**, **Syncthing (host)** and **Caddy (Tailscale HTTPS)** to a Raspberry Pi or any Linux server directly from your Mac.

Point it at any SSH-reachable address — a **LAN IP** (e.g. `192.168.1.50`) or a **Tailscale address** (MagicDNS name / `100.x.y.z`) — and it bootstraps **Docker + Tailscale** from bare SSH, then starts the whole stack.

**Prerequisites:** `ansible-core` and `sshpass` installed on your dev machine.

## How it fits together

```
.env (local, gitignored)  ──source──►  ./deploy.sh  ──extra_vars──►  Ansible  ──template──►  target ~/pai-stack/.env
                                                    │                           (ansible/roles/pai_stack/templates/env.j2)
                                                    └─ mounts ──► docker-compose.yaml
```

* **Local `.env`** is the single source of truth you edit. Copy from `.env.example`. Never committed (see `.gitignore`).
* **`./deploy.sh`** is the only supported entrypoint. It loads `.env` and invokes `ansible/playbook.yml` via SSH.
* **Generated target `.env`** (`~/pai-stack/.env` on the Pi, `0600`) is rendered from `roles/pai_stack/templates/env.j2`. It contains `UID`/`GID`, `TAILSCALE_DOMAIN`, `PERSONAL_FOLDER`, provider keys, `API_SERVER_KEY`, `HERMES_DASHBOARD_BASIC_AUTH_*`, `SYNCTHING_GUI_*`. Secrets are auto-generated on first deploy and preserved on re-runs.

## What deploy.sh forwards

`deploy.sh` sources `.env` and passes these as Ansible `extra_vars` (see `deploy.sh:110`):

| `.env` var | Ansible var | Notes |
|---|---|---|
| `TAILSCALE_DOMAIN` | `tailscale_domain` | Caddy TLS hostname |
| `TAILSCALE_AUTH_KEY` | `tailscale_auth_key` | Only needed for fresh devices |
| `HERMES_DASHBOARD_PASSWORD` | `hermes_dashboard_password` | Auto-generated (`openssl rand -hex 12`) if blank |
| `PERSONAL_FOLDER` | `pai_personal_dir` | Only if set; otherwise defaults to `~/Personal` on target |

Other `.env` vars (`TARGET_HOST`, `TARGET_USER`, `SSH_PASSWORD`, `BECOME_PASSWORD`) are used directly by `deploy.sh` for SSH/become and never copied to the target.

All other target secrets (`API_SERVER_KEY`, `HERMES_DASHBOARD_BASIC_AUTH_SECRET`, `SYNCTHING_GUI_PASSWORD`, `UID`/`GID`) are generated inside `roles/pai_stack/tasks/main.yml` if no `~/pai-stack/.env` exists yet, otherwise preserved from the existing file.

## Quick Start (recommended)

### 1. Configure

```bash
cp .env.example .env
# Edit .env:
#   TARGET_HOST      = LAN or Tailscale IP/hostname of the target
#   TARGET_USER      = SSH user on the target (e.g. pi)
#   TAILSCALE_DOMAIN = MagicDNS name Caddy serves TLS for
#   TAILSCALE_AUTH_KEY = leave blank if target already on tailnet
#   HERMES_DASHBOARD_PASSWORD = blank = auto-generate
#   SSH_PASSWORD / BECOME_PASSWORD = set for zero prompts, else leave blank
```

### 2. Deploy

From your Mac (any Docker host) — SSHes to `TARGET_HOST`:

```bash
./deploy.sh
```

When prompted (if `SSH_PASSWORD`/`BECOME_PASSWORD` were left blank):
- **SSH password**: server's SSH password
- **BECOME password [sudo]**: server's sudo password

On success Ansible prints the access URLs and generated passwords.

## Roles

| Role | Purpose |
|---|---|
| `common` | Base packages (`curl`, `gnupg`, `ca-certificates`, `python3`) |
| `tailscale` | Install + `tailscale up` (skipped if already on tailnet), socket perms for Caddy |
| `docker` | Official Docker Engine + Compose plugin |
| `pai_stack` | Data dirs, secret generation, `env.j2` → `~/pai-stack/.env`, Syncthing host install, copy build contexts, KB scaffold (`kb/` → `PERSONAL_FOLDER/silverbulletKB`, `force: no`), `docker compose up --build`, Hermes restart |

## Configuration reference

* **Local template:** `.env.example` (all tunable local vars, with comments).
* **Ansible defaults:** `group_vars/all.yml` — `pai_stack_dir`, `pai_personal_dir`, `pai_uid`/`pai_gid`, `tailscale_domain`, `hermes_dashboard_*`, `codegraph_enabled`. Override via extra vars from `.env` or by editing the file for advanced use.
* **Target env template:** `roles/pai_stack/templates/env.j2` — authoritative list of what ends up in `~/pai-stack/.env` on the Pi.
* **Inventory:** `inventory.ini` is not used by `deploy.sh` (it builds its own `-i` inline). Only relevant for manual `ansible-playbook` runs.
* **Ansible config:** `ansible.cfg`

## Manual execution (without deploy.sh)

If you already have `ansible` and `sshpass` locally and prefer not to use the container runner:

```bash
# Remote
ansible-playbook -i "rpi.burro-smelt.ts.net," -u <target-user> ansible/playbook.yml -k -K \
  -e tailscale_domain="rpi.burro-smelt.ts.net"

# Local
ansible-playbook -i "localhost," -c local ansible/playbook.yml -K
```

You lose the `.env` auto-loading and secret-file handling that `deploy.sh` provides — prefer `deploy.sh` unless you know why you need this.

## Re-deploy / idempotency

Re-running `./deploy.sh` is safe: existing `~/pai-stack/.env` secrets are read back (`roles/pai_stack/tasks/main.yml:88`) and preserved, `kb/` scaffold is not overwritten (`force: no`), and Syncthing config is only patched if needed.
