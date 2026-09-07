# pai-stack — Design & Blueprint

> **Status:** Accepted — reflects `main` at 2026-09-04. Single source of truth for architecture, decisions, and philosophy. Update this file on any structural change and add an ADR under `docs/adr/`.

---

## 1. Vision

**pai-stack** is a personal AI infrastructure that turns a single Pi/home-server into an **operations manager for an evolving portfolio of projects**. A human lives in Telegram Forum Topics; Hermes thinks in markdown KB — and gets better at software planning by learning across projects without leaking project data.

**One command to rebuild from bare SSH:** `TARGET_HOST` (LAN or Tailscale IP) + `./deploy.sh` provisions Docker, Tailscale, secrets, containers, and model routing — no manual Docker bootstrap.

Tagline: **Hermes Agent + Syncthing + Caddy (Tailscale HTTPS)** `README.md:3`.

---

## 2. Requirements

### 2.1 Functional

| ID | Requirement |
|----|-------------|
| F1 | Chat-ops via Telegram Forum: one Forum Group per project, one Topic per issue/feature/bug; answers isolated to originating topic |
| F2 | Grounded answers: retrieve from KB before answering, cite `file:lines`, never guess beyond context |
| F3 | KB as durable memory: plain markdown at `silverbulletKB/` is both human-readable and vector-indexed |
| F4 | Code execution: Hermes implements/researches tasks directly, writes back to KB |
| F5 | Sync: `PERSONAL_FOLDER` (`~/Personal`) bidirectionally synced across user devices |
| F6 | Model routing: free-first LLM with failover, ability to pin paid/pro models on demand; catalog browseable |
| F7 | Self-hosted on one host, reproducible from scratch |

### 2.2 Non-Functional

| Category | Requirement | Current handling |
|----------|-------------|------------------|
| **Confidentiality** | No raw secrets in KB; access only over Tailscale | `OPENAI_API_KEY` dummy, `API_SERVER_KEY` bearer, BasicAuth on dashboards, refs like `env VAR` in markdown |
| **Availability** | Pi-grade resilience; unattended restart | `restart: unless-stopped`, healthchecks `docker-compose.yaml:55`, `umask 000` WAL fix `hermes/entrypoint.sh:23` |
| **Resource** | Fit in ~4 GB RAM on Pi | Limits: `caddy 64M` `docker-compose.yaml:11`, `hermes 3G` `:40`, `codegraph 512M` `:78` |
| **Latency** | Chat replies in seconds, not minutes | `auto_retrieve: true` `max_context_chunks: 8` `relevance_threshold: 0.5` + `reindex_on_change: true` `hermes/config.yaml:140` |
| **Operability** | Full rebuild <15 min from bare SSH | Ansible `common → tailscale → docker → pai_stack` `ansible/playbook.yml:8` |
| **Portability** | Move to new Pi without data loss | Named volumes `docker-compose.yaml:101` + bind mount `PERSONAL_FOLDER`, `make clean` is explicit `Makefile:37` |
| **Evolvability** | Unbounded projects, no hardcoded names | `AGENTS.md` manifest `kb/AGENTS.md:13` + `_TEMPLATE` scaffolding `kb/Projects/_TEMPLATE/` |

---

## 3. High-Level Architecture

```mermaid
flowchart TB
    subgraph Client["Client — any device on Tailnet"]
        U[Mac / Phone]
    end

    subgraph Pi["Pi Host — pai-stack"]
        direction TB
        Caddy["Caddy<br/>caddy/Dockerfile:1<br/>caddy/Caddyfile:5<br/>get_certificate tailscale<br/>:9119 :8642 :8384"]
        Hermes["Hermes<br/>docker-compose.yaml:33<br/>hermes/config.yaml:1<br/>gateway run :9119 dash :8642 api"]
        CG["CodeGraph<br/>docker-compose.yaml:72<br/>codegraph/server.js:1<br/>:20128 HTTP API"]
        ST["Syncthing<br/>host systemd :8385<br/>ansible/roles/pai_stack/tasks/main.yml:308"]
        D1[("hermes-data<br/>/opt/hermes/data")]
        D2[("codegraph-data<br/>/opt/codegraph/data")]
        Root[("PERSONAL_FOLDER<br/>~/Personal<br/>env.j2:9<br/>Folder ID personal")]
    end

    U -- "https:// $TAILSCALE_DOMAIN:*<br/>WireGuard + Tailscale TLS" --> Caddy
    Caddy -- ":9119 :8642" --> Hermes
    Caddy -- ":8384 → host.docker.internal:8385" --> ST

    Hermes -- "http://codegraph:20128<br/>code intelligence" --> CG

    Hermes --- D1
    CG --- D2

    Root -- "/opt/data/Personal :66" --> Hermes
    Root -- "/codebase:ro" --> CG
    Root -- "Send&Receive<br/>:8385 :280" --> ST
```

**Network blueprint** `README.md:7`:
- **Outside:** only via Tailscale HTTPS (`Caddy` holds `/var/run/tailscale/tailscaled.sock:ro` `docker-compose.yaml:26` and `get_certificate tailscale` `caddy/Caddyfile:6`). No public ports.
- **Inside:** plain HTTP over Docker bridge (`hermes → codegraph:20128`, `caddy → hermes:9119` etc. `README.md:10`). `extra_hosts: host.docker.internal:host-gateway` `docker-compose.yaml:21` lets Caddy reach host Syncthing.

### 3.1 Service Inventory

| Service | Container | Ports | Auth | Purpose | Key file |
|---------|-----------|-------|------|---------|----------|
| **Caddy** | `caddy:builder` → `caddy:latest` w/ `caddy-tailscale` | `9119,8642,8384` `docker-compose.yaml:13` | Tailscale TLS | Reverse proxy, certs in `caddy-data` | `caddy/Caddyfile:1` |
| **Hermes** | `nousresearch/hermes-agent:latest` patched `pai-stack-hermes:patched` | `9119` dash `8642` api | `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` → scrypt `hermes/entrypoint.sh:37`, `API_SERVER_KEY` bearer | Telegram bot, RAG, Kanban | `hermes/config.yaml:1` |
| **CodeGraph** | `codegraph:latest` (Debian 12 + codegraph binary + Node.js) | `20128` int | none (internal) | Code intelligence HTTP API | `codegraph/server.js:1` |
| **Syncthing** | host `syncthing serve --home=/var/lib/syncthing` `tasks/main.yml:312` | `8385` host → `8384` via Caddy | bcrypt `config.xml` `tasks/main.yml:106` | Sync `PERSONAL_FOLDER` | `tasks/main.yml:214` |

---

## 4. Data Plane

```mermaid
flowchart LR
    subgraph Volumes["Named volumes — owned by container UID (no EACCES)"]
        V1["hermes-data<br/>/opt/hermes/data<br/>sessions, kanban.db, keys"]
        V2["codegraph-data<br/>/opt/codegraph/data<br/>SQLite graph DB"]
        V3["caddy-data + caddy-config"]
    end
    subgraph Binds["Bind mounts — host-coupled"]
        B1["${PERSONAL_FOLDER}<br/>/opt/data/Personal<br/>→ hermes RAG"]
        B2["${PERSONAL_FOLDER}<br/>/codebase:ro<br/>→ CodeGraph (read-only)"]
        B3["./hermes/config.yaml:ro<br/>/tmp/hermes-config.yaml.host<br/>./caddy/Caddyfile:ro"]
    end
    B1 --> Hermes
    B2 --> CG
    V1 --> Hermes
    V2 --> CG
```

*Only host-coupled data is bind-mounted* `README.md:268`. Scaffold `kb/` → `silverbulletKB/` copied once `force: no` `tasks/main.yml:172` — user edits never overwritten.

---

## 5. Hermes — The Mind (`hermes/config.yaml:1`)

Hermes is the only stateful brain. Its behavior is governed by **one file** plus env overlay at boot. `docker-compose.yaml:64` mounts `config.yaml:ro` to `/tmp/hermes-config.yaml.host`; `hermes/entrypoint.sh:26` copies to `/opt/hermes/data/{hermes-config.yaml,config.yaml}`, hashes dashboard password, sets `HERMES_CONFIG`, then `exec /opt/hermes/docker/entrypoint-dispatch.sh gateway run` `docker-compose.yaml:69`.

```mermaid
flowchart TB
    subgraph ConfigAnatomy["hermes/config.yaml"]
        C1["model :1<br/>provider office1<br/>default {{ llamacpp_model_name }}"]
        C2["providers.office1 :11<br/>api {{ llamacpp_base_url }}<br/>key_env OPENAI_API_KEY"]
        C3["fallback_providers :16<br/>openrouter → mistral → kilo-gateway"]
        C4["database :27<br/>journal_mode wal"]
        C5["kanban :39<br/>default_model {{ llamacpp_model_name }}"]
        C6["dashboard :42<br/>cyberpunk + scrypt"]
        C7["agent.system_prompt :53<br/>ECOSYSTEM MAP + KB LAYOUT<br/>7 GOLDEN RULES + LOOP A-G + SKILLS"]
        C8["context_files :121<br/>AGENTS.md always injected"]
        C9["knowledgebase :126<br/>/opt/data/Personal<br/>local embeddings<br/>8 chunks ≥0.5 reindex_on_change"]
        C10["platforms :137<br/>telegram enabled<br/>hints + toolsets"]
    end
    C1 & C2 & C3 & C4 & C5 & C8 & C9 & C10 --> C7
```

### 5.1 System Prompt = Philosophy in Code `hermes/config.yaml:54`

* **Ecosystem Map:** tells Hermes where everything lives (`PERSONAL_FOLDER`, `silverbulletKB`, CodeGraph, Caddy).
* **KB Layout** `hermes/config.yaml:66`:
  ```
  /opt/data/Personal/                     ← indexed entirely
  └── silverbulletKB/                     ← WRITE HERE (indexed + synced)
      ├── AGENTS.md                       ← always injected `context_files:121`
      ├── Projects/<Name>/{README, docs/architecture.md, telegram.md, config.md, issues/<slug>.md}
      ├── References/                     ← cross-project growth
      └── Skills/<skill-name>/SKILL.md
  ```
* **Golden Rules** `hermes/config.yaml:84` — see §8 Philosophy.

### 5.2 Kanban Patch `hermes/Dockerfile:3` `hermes/kanban-default-model.patch:1`

Upstream lacks board-wide model. Patch adds `kanban.default_model` to `hermes_cli/config_defaults.py:28` + dispatcher in `hermes_cli/kanban_db.py:39`:

```
if task.model_override → -m <override> [--provider <override>]
else if kanban.default_model → -m <default> [--provider <name> if provider embedded else profile default]
else → profile model

Precedence: 1. model_override > 2. kanban.default_model > 3. profile
```

Applied via `patch -p1` with `apply-kanban-patch.py:11` regex fallback if upstream drifted; verified by `python -c assert` `hermes/Dockerfile:17`. Empty = legacy — forward-compatible.

### 5.3 RAG & Write Discipline `hermes/config.yaml:131`

- Indexes **entire** `PERSONAL_FOLDER` so `~/Personal` is searchable even before KB scaffold.
- `local` embeddings (`all-MiniLM-L6-v2`, ~80 MB) — no external API.
- `reindex_on_change: true` → immediate retrieval after write.
- **Write rule:** Hermes writes only to `silverbulletKB` (indexed + synced). Ensures `KB FIRST, topic second` `hermes/config.yaml:82`.

---

## 6. CodeGraph — Code Intelligence `codegraph/server.js:1`

CodeGraph provides code intelligence via HTTP API (`:20128`) using the `codegraph-ai/CodeGraph` binary in `--graph-only` mode (no ONNX embeddings, ~256MB RAM). The HTTP wrapper (`codegraph/server.js`) exposes endpoints for context, callers, callees, impact analysis, and search — all backed by a RocksDB graph stored in `codegraph-data` volume.

Key endpoints:
* `GET /context/:symbol` — full context (source, callers, callees, deps)
* `GET /callers/:symbol` / `GET /callees/:symbol` — call chain tracing
* `GET /impact/:path` — blast radius of file changes
* `GET /search?q=:query` — semantic symbol search
* `GET /map` — most-connected files overview
* `POST /query` — arbitrary codegraph CLI command

Hermes queries CodeGraph via `http://codegraph:20128` for code-aware planning and refactoring.

---

## 7. Execution Model — Hermes Works Directly

Hermes now implements tasks directly in `/opt/data/Personal` without delegate containers. `HOW TO WORK D` `hermes/config.yaml:93` reads relevant files, makes edits, runs tests, writes result to `silverbulletKB/issues/*.md` + `References/Skills` if generic, and summarizes in **same Telegram topic only** with `file:lines` citations. No MCP, no `agent-workspace` volume, no `TASK_TIMEOUT` queue.

---

## 8. Core Principles & Philosophy — Non-Negotiable

These are the **guardrails that keep Hermes from drifting** as portfolio grows. Violating any one requires an ADR.

| # | Principle | Statement | Enforced by |
|---|-----------|-----------|-------------|
| P1 | **Isolation per topic, learning across topics** `hermes/config.yaml:85` | In topic X, retrieve & answer ONLY `AGENTS.md` + `Projects/X/**` + its `issues/<slug>.md`. After completion, distill generic patterns into `References/` or `Skills/` — compound growth without leaking project data. | `system_prompt` + `AGENTS.md:29` + retrieval scoping |
| P2 | **KB first, topic second** `hermes/config.yaml:86` | Never post decision/diff to Telegram without first writing to `silverbulletKB`. Topic is ephemeral view; KB is durable truth. Cite `file:lines`. | `system_prompt` loop A-G |
| P3 | **Ask first (hybrid)** `hermes/config.yaml:87` | Mirror & propose, but never write KB from chat without explicit confirm from that topic. | `system_prompt` + `AGENTS.md:34` |
| P4 | **Permission gate + searchable mapping** `hermes/config.yaml:88` | First message in new group/topic → record `group_id + topic_id` in `Projects/<Name>/telegram.md` + `issues/<slug>.md`. If not listed, refuse: "Not in telegram.md". | `telegram.md` `kb/Projects/_TEMPLATE/telegram.md:1` + `AGENTS.md:24` |
| P5 | **Evolving portfolio — no hardcoded names** `hermes/config.yaml:89` | Never invent `ProjectAlpha/Beta`. On unknown project, search `~/Personal` via RAG, create scaffold from `_TEMPLATE`, propose, wait confirm, write `Projects/<Name>/{README,docs/architecture,telegram,config}` + update `AGENTS.md`. No project limit. | `system_prompt` + `AGENTS.md:14` |
| P6 | **Secrets as references** `hermes/config.yaml:90` | Never write raw secrets to KB or git; use "API key in 1Password / env `X`". | `system_prompt` + `env.j2:1` (0600) |
| P7 | **Concise per-topic, no cross-post** `hermes/config.yaml:91` | Telegram: short bullets + citations per topic; Dashboard/API may be verbose. Never duplicate content across topics/groups. | `system_prompt` + `platform_hints.telegram` `hermes/config.yaml:149` |
| P8 | **Unified paths** | `${PERSONAL_FOLDER}` is `/opt/data/Personal` everywhere (Hermes, RAG). | `docker-compose.yaml:92` |
| P9 | **Free-first, quality on demand** `hermes/config.yaml:7` | Default chat = free combos (`personal/free-chat`) with failover. | `discover_models: true` |
| P10 | **Skills compound** `hermes/config.yaml:111` | After 2nd repeat or on "create a skill", draft `Skills/<name>/SKILL.md` directly, write to KB, retrieve next time. Generic skills are portfolio-wide. | `_TEMPLATE/SKILL.md` `kb/Skills/_TEMPLATE/SKILL.md:1` |

**Mantra:** *You live in Telegram Topics, but think in markdown KB.*

---

## 9. Request Flows

### 9.1 Telegram Task (canonical)

```mermaid
sequenceDiagram
    participant TG as Telegram Topic<br/>group_id/topic_id
    participant H as Hermes
    participant RAG as RAG
    participant KB as silverbulletKB

    TG->>H: Implement feature X
    H->>RAG: scoped retrieve<br/>AGENTS.md + Projects/X/** + issue file :93
    H->>H: Read /opt/data/Personal/... make edits, run tests
    H->>KB: write issue changelog + References/Skills if generic
    H->>TG: diff + next step in SAME topic + citations
```

### 9.2 Dashboard / API

`Caddy :9119 → hermes:9119` (BasicAuth `admin/$HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` `docker-compose.yaml:84`, hash in `hermes-data/hermes-config.yaml` `entrypoint.sh:44`) and `:8642 → hermes:8642` (Bearer `API_SERVER_KEY` `docker-compose.yaml:82`). Inter-container traffic plain HTTP inside Docker net.

### 9.3 Syncthing

`Pi ~/Personal` canonical `tasks/main.yml:264` (`path: pai_personal_dir`, `id: personal` `tasks/main.yml:272`, GUI `0.0.0.0:8385` `tasks/main.yml:279`, bcrypt `tasks/main.yml:106`). Host systemd `tasks/main.yml:308` binds Tailscale `100.x:22000` directly — peers discover via Device ID, optional explicit `tcp://rpi.burro-smelt.ts.net:22000` `README.md:192`. Bidirectional Send&Receive, deletes → `.stversions`.

---

## 10. Deployment & Operations

**Ansible pipeline** `ansible/playbook.yml:8`: `common` (dirs `tasks/main.yml:19`), `tailscale` (install/join via `TAILSCALE_AUTH_KEY` `.env.example:46`), `docker`, `pai_stack`.

`tasks/main.yml:38` reads existing `~/pai-stack/.env` → preserves secrets `tasks/main.yml:88` else generates `openssl rand -hex 32` `tasks/main.yml:49`. Templates `env.j2:1` (UID/GID resolved `tasks/main.yml:4`, `TAILSCALE_DOMAIN`, `PERSONAL_FOLDER`, keys). Copies build contexts flat `tasks/main.yml:147`, seeds `kb/ → silverbulletKB force: no` `tasks/main.yml:172`, installs Syncthing host, configures `config.xml` (telemetry `urAccepted=-1` `:258`, folder path/ID, GUI address/auth, `.stfolder` `:299`), systemd `tasks/main.yml:308`, `docker compose up -d --build --remove-orphans` `tasks/main.yml:347`, wait `:20128` `tasks/main.yml:353`, seed combos `tasks/main.yml:361`, `restart hermes` `tasks/main.yml:368`.

**Env forwarding contract** `README.md:92`: local `.env` never copied; only `TAILSCALE_DOMAIN`, `HERMES_DASHBOARD_PASSWORD`, `PERSONAL_FOLDER` forwarded as extra vars `deploy.sh:115`.

**Make** `Makefile:1`: `deploy`/`deploy-renew`, `logs` (`docker compose logs -f`), `status`, `stop`/`restart`, `update` (`pull && up --build`), `clean` (`down -v` — destructive, deletes volumes).

---

## 11. ADRs — Key Decisions

| ADR | Decision |
|-----|----------|
| [ADR-001: Single Pi + Compose](adr/ADR-001-single-pi-compose.md) | Compose over K8s — operability on constrained host |
| [ADR-002: Caddy + Tailscale TLS](adr/ADR-002-caddy-tailscale.md) | `caddy-tailscale` over Traefik/Cloudflare — zero public ports, MagicDNS |
| [ADR-004: Syncthing on host](adr/ADR-004-syncthing-host.md) | Host systemd vs container — Tailscale interface + canonical `~/Personal` |
| [ADR-005: Direct execution (delegates removed)](adr/ADR-005-direct-execution.md) | Hermes implements directly; MCP delegates retired |
| [ADR-006: Local embeddings + file RAG](adr/ADR-006-local-rag.md) | fastembed on whole `Personal` vs vector DB service — simplicity + privacy |
| [ADR-007: Ansible provisioning](adr/ADR-007-ansible-provisioning.md) | Ansible over Terraform — bare-SSH to full stack, secret preservation |

Each ADR follows template: Status, Context, Decision, Alternatives, Consequences, Trade-offs. See `docs/adr/`.

---

## 12. Trade-offs & Constraints

* **Simplicity > horizontal scale:** single host, no sharding; scaling = bigger Pi then split services.
* **Consistency > write scale:** WAL SQLite for Kanban (one writer, many readers); fixed with `umask 000` `deploy-notes/2026-09-01-kanban-wal-readonly.md:33`.
* **Cost > peak quality:** free-first combos; paid pin when needed.
* **Durability > convenience:** named volumes + explicit `make clean`; KB is plain files under `PERSONAL_FOLDER/silverbulletKB`.

---

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Pi disk failure | Lose volumes in `/var/lib/docker/volumes` | `tar czf` busybox export `README.md:322`; KB already Syncthing-synced off-host |
| WAL read-only regression `deploy-notes/2026-09-01-kanban-wal-readonly.md:5` | Kanban event stream warnings | `entrypoint.sh:23` fix + `find chmod a+rw` back-fix; re-applies on deploy |

| Upstream Hermes image drift | Patch fails | `apply-kanban-patch.py:11` fallback + `docker logs` verification `hermes/Dockerfile:17` |
| Tailscale key expiry | New Pi can't join | Manual `TAILSCALE_AUTH_KEY` `tasks/main.yml` + `deploy.sh`; or SSH via LAN `TARGET_HOST` `.env.example:4` |

---

## 14. Security

* No public ports — all via Tailscale TLS `caddy/Caddyfile:6`.
* Secrets in target `~/pai-stack/.env 0600` `tasks/main.yml:104`, generated via `openssl rand` if blank `tasks/main.yml:49`, preserved on re-deploy `tasks/main.yml:88`. `SSH_PASSWORD`/`BECOME_PASSWORD` never copied to target `.env.example:71`.
* Syncthing GUI bcrypt 12 `tasks/main.yml:108` via Caddy (not direct 8385).
* KB secret refs only `hermes/config.yaml:90` — audit `References/` and `config.md`.

---

## 15. How to Keep Philosophy Intact — Contributor Guide

1. **Edit `hermes/config.yaml:53` `system_prompt` first** — that's the constitution. Every new capability must fit Ecomap → Golden Rules → Loop.
2. **Add a project = scaffold, not hardcode:** mention in chat → Hermes searches `Personal` → creates from `_TEMPLATE` → update `silverbulletKB/AGENTS.md` and `telegram.md`. Never add `if project==X` in code.
3. **New automation = Skill:** after 2nd repeat, `Skills/<name>/SKILL.md` via `_TEMPLATE/SKILL.md` — imperative `When to use / Inputs / Steps / Outputs`.
4. **New architecture = ADR:** create `docs/adr/ADR-00N-*.md`, mark Accepted/Rejected, reference here.
5. **Verify:** `make deploy`, `make logs`, `make status`, check `https://$TAILSCALE_DOMAIN:9119/8384`.

---

## 16. References

* `README.md:1` — user-facing quickstart & network blueprint
* `hermes/config.yaml:1`, `hermes/entrypoint.sh:1`, `hermes/Dockerfile:1`, `hermes/kanban-default-model.patch:1`
* `docker-compose.yaml:1`, `caddy/Caddyfile:1`, `codegraph/server.js:1`
* `ansible/playbook.yml:8`, `ansible/roles/pai_stack/tasks/main.yml:1`, `ansible/roles/pai_stack/templates/env.j2:1`, `ansible/group_vars/all.yml:6`
* `kb/AGENTS.md:1`, `kb/Projects/_TEMPLATE/`, `kb/Skills/_TEMPLATE/SKILL.md:1`
* `Makefile:1`, `deploy.sh:1`, `.env.example:1`
