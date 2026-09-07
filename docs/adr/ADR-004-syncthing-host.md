# ADR-004: Syncthing as Host Systemd Service, Not a Container

## Status
Accepted

## Context
`PERSONAL_FOLDER` (`~/Personal`) must be the canonical folder shared by Hermes (`/opt/data/Personal`), CodeGraph (`/codebase`), and the user's Mac/phone. Earlier stack ran Syncthing as a container; it lacked Tailscale interface binding and required volume hacks.

## Decision
Install `syncthing` via apt `ansible/roles/pai_stack/tasks/main.yml:214`, generate `/var/lib/syncthing` `tasks/main.yml:227`, configure `config.xml` to `path: pai_personal_dir` `tasks/main.yml:264`, `id: personal` `tasks/main.yml:272`, GUI `0.0.0.0:8385` `tasks/main.yml:279`, bcrypt auth `tasks/main.yml:106`, and run `syncthing serve --home=/var/lib/syncthing` as systemd `tasks/main.yml:308` owned by `ansible_user`. Caddy proxies `host.docker.internal:8385` → `:8384` `caddy/Caddyfile:37`.

## Alternatives Considered
- **Syncthing container** — extra NAT, no direct Tailscale announce (needs hostNetwork), extra volume mounts.
- **Nextcloud / Dropbox** — proprietary or heavier; Syncthing is P2P and fits Pi.

## Consequences
- Positive: Direct Tailscale `100.x:22000` discovery, single canonical path, deletes → `.stversions`, no container UID mapping for sync data.
- Negative: One service not in `docker compose ps`; managed via `systemctl` and `ansible/roles/pai_stack/tasks/main.yml:331`.

## Trade-offs
Native network reachability and single-source `PERSONAL_FOLDER` prioritized over compose purity.
