# ADR-007: Ansible Provisioning from Bare SSH

## Status
Accepted

## Context
Target Pi may be fresh (no Docker/Tailscale). Must be provisionable from a Mac via one SSH endpoint (LAN or Tailscale). Terraform/Pulumi expect cloud APIs; shell scripts drift.

## Decision
Flat Ansible playbook (`ansible/playbook.yml`) — no roles, just task blocks with tags. `TARGET_HOST` is LAN or Tailscale IP. Generates `~/deployed-pai-stack/.env` with `openssl rand` if blank, templates `env.j2`, clones repo, templates hermes `config.yaml`, seeds `kb/ → silverbulletKB force: no`, installs Syncthing host, builds & starts Docker containers. All tasks in one file, no role directory overhead.

## Alternatives Considered
- **Terraform + cloud-init** — great for clouds, not for a Pi behind NAT without API.
- **Plain shell script** — idempotence and secret preservation harder; Ansible handles it.
- **Ansible roles** — added structure for a ~300-line playbook; not worth the indirection.

## Consequences
- Positive: Fully unattended with `SSH_PASSWORD`/`BECOME_PASSWORD` set, otherwise prompted; re-deploy preserves secrets. One file to read, no role indirection.
- Negative: Requires Python/ansible-core on deploy host.

## Trade-offs
Reproducibility and single-SSH bootstrap prioritized over cloud-native IaC. Flat structure prioritized over role indirection for a small playbook.
