# ADR-001: Single Pi + Docker Compose over Kubernetes

## Status
Accepted

## Context
pai-stack runs on a single Pi/home-server (3–7 GB RAM, 3 cores). Must be operable by one person from a Mac via bare SSH. Earlier iterations considered k3s/Kind. Team size = 1 operator, portfolio grows via markdown not services.

## Decision
Run all services as a single `docker-compose.yaml:1` stack. `ansible/playbook.yml:8` provisions Docker + Tailscale + stack from one playbook. No orchestrator.

## Alternatives Considered
- **k3s / Kubernetes** — excellent for multi-node scale, but adds etcd, CNI, ingress complexity; overkill for 6 containers on one host.
- **Nomad** — lighter than K8s, still extra binary + scheduling for static set.
- **Systemd bare binaries** — no isolation, harder rollback and secret handling.

## Consequences
- Positive: `make deploy` idempotent, `docker compose ps/logs` trivial, resource limits explicit `docker-compose.yaml:8`.
- Negative: No horizontal scaling; single host failure = stack down until Pi restored.

## Trade-offs
Operability and single-host cost prioritized over horizontal scale. If a service needs independent scaling, split it to its own compose host first.
