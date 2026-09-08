# ADR-004: Syncthing as Host Systemd Service, Not a Container

## Status
Accepted

## Context
`PERSONAL_FOLDER` (`~/Personal`) must be the canonical folder shared by Hermes (`/opt/data/Personal`) and the user's Mac/phone. Earlier stack ran Syncthing as a container; it lacked Tailscale interface binding and required volume hacks.

## Decision
Install `syncthing` via apt `ansible/playbook.yml`, generate `/var/lib/syncthing` config, configure `config.xml` to `path: pai_personal_dir`, `id: personal`, GUI `0.0.0.0:8384` (direct on Tailscale IP, no reverse proxy), bcrypt auth, and run `syncthing serve --home=/var/lib/syncthing` as systemd owned by `ansible_user`. All services bind directly to Tailscale IP; Tailscale encrypts via WireGuard.

## Alternatives Considered
- **Syncthing container** — extra NAT, no direct Tailscale announce (needs hostNetwork), extra volume mounts.
- **Nextcloud / Dropbox** — proprietary or heavier; Syncthing is P2P and fits Pi.

## Consequences
- Positive: Direct Tailscale `100.x:22000` discovery, single canonical path, deletes → `.stversions`, no container UID mapping for sync data.
- Negative: One service not in `docker compose ps`; managed via `systemctl` and `ansible/playbook.yml`.

## Trade-offs
Native network reachability and single-source `PERSONAL_FOLDER` prioritized over compose purity.
