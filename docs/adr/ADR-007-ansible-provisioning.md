# ADR-007: Ansible Provisioning from Bare SSH

## Status
Accepted

## Context
Target Pi may be fresh (no Docker/Tailscale). Must be provisionable from a Mac via one SSH endpoint (LAN or Tailscale). Terraform/Pulumi expect cloud APIs; shell scripts drift.

## Decision
Containerized Ansible runner via `deploy.sh` + `ansible/playbook.yml:8` (`common → tailscale → docker → pai_stack` `ansible/roles/pai_stack/tasks/main.yml:1`). `TARGET_HOST` is LAN or MagicDNS/100.x `.env.example:4`. Generates `~/pai-stack/.env 0600` `tasks/main.yml:104` with `openssl rand` if blank `tasks/main.yml:49`, preserves existing `tasks/main.yml:88`, templates `env.j2:1`, flat-copies build contexts `tasks/main.yml:147`, seeds `kb/ → silverbulletKB force: no` `tasks/main.yml:172`, installs Syncthing host, then `docker compose up -d --build` `tasks/main.yml:347`, wait `20128` `tasks/main.yml:353`, seed + `restart hermes` `tasks/main.yml:361,368`. Only 3 vars forwarded as extra vars `deploy.sh:115` (`TAILSCALE_DOMAIN`, `HERMES_DASHBOARD_PASSWORD`, `PERSONAL_FOLDER`); `SSH_PASSWORD`/`BECOME_PASSWORD` never copied `.env.example:71`.

## Alternatives Considered
- **Terraform + cloud-init** — great for clouds, not for a Pi behind NAT without API.
- **Plain shell script** — idempotence and secret preservation harder; Ansible handles it.

## Consequences
- Positive: Fully unattended with `SSH_PASSWORD`/`BECOME_PASSWORD` set, otherwise prompted; re-deploy preserves secrets.
- Negative: Requires Python/Ansible container on deploy host.

## Trade-offs
Reproducibility and single-SSH bootstrap prioritized over cloud-native IaC.
