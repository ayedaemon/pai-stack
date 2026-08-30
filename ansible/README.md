# Ansible Automation for pai-stack

Automated deployment of **Hermes Agent**, **OmniRoute Gateway**, **SilverBullet**, and **Caddy (Tailscale HTTPS)** to a Raspberry Pi or any Linux server directly from your Mac or locally on the server.

Point it at any SSH-reachable address — a **LAN IP** (e.g. `192.168.1.50`) or a **Tailscale address** (MagicDNS name / `100.x.y.z`) — and it bootstraps **Docker + Tailscale** from bare SSH, then starts the whole stack.

## Features

- 🐳 **Zero local dependencies on Mac**: Runs Ansible and `sshpass` inside a lightweight one-time container via `./deploy.sh`.
- 🔑 **Password-based authentication**: Supports password authentication for SSH and `sudo` (`BECOME`) without requiring SSH keys.
- 🔒 **Tailscale HTTPS & Socket Provisioning**: Automatically sets up Tailscale operator socket permissions so Caddy gets TLS certs without manual intervention.
- ⚡ **Full Stack Provisioning**:
  - Installs prerequisites (`curl`, `gnupg`, `ca-certificates`, `python3`).
  - Installs & starts Tailscale.
  - Installs official Docker Engine and Docker Compose plugin.
  - Creates the Syncthing note folder with correct UID/GID permissions (`~/Personal/silverbullet`). Container state (`hermes-data`, `omniroute-data`, `caddy-data`, `caddy-config`) lives in Docker **named volumes**, which Docker owns with each container's runtime UID — this avoids EACCES without host-UID coupling.
  - Builds custom images (Caddy with Tailscale plugin, SilverBullet with pre-loaded plugs).
  - Generates secure random credentials in `.env` (preserves existing secrets on re-runs).
  - Starts the stack with `docker compose up -d --build`.
  - Automatically seeds the model routing combos in OmniRoute.

---

## Quick Start

### 1. Configure Target Server

Edit `ansible/inventory.ini`:

```ini
[rpi]
raspberrypi ansible_host=rpi.burro-smelt.ts.net ansible_user=pi
```

*(Replace with your target's LAN IP or Tailscale MagicDNS hostname/IP, and your SSH user).*

### 2. Configure Domain & Secrets

Edit `ansible/group_vars/all.yml`:

```yaml
tailscale_domain: "rpi.burro-smelt.ts.net"
```

### 3. Deploy

From your Mac, run:

```bash
./deploy.sh
```

Or directly on the Raspberry Pi:

```bash
./deploy.sh --local
```

When prompted:
- **SSH password**: Enter your server's SSH password.
- **BECOME password[sudo]**: Enter your server's sudo password.

---

## Manual Execution (Without Docker runner)

If you already have `ansible` and `sshpass` installed locally:

```bash
ansible-playbook -i ansible/inventory.ini ansible/playbook.yml -k -K
```
