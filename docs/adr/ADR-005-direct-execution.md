# ADR-005: Direct Execution — Delegates Retired

## Status
Accepted (supersedes MCP delegates 2026-09-04)

## Context
Previously Hermes delegated coding/research to two MCP-isolated containers (`antigravity` + `opencode` at `http://antigravity:8000/mcp` / `http://opencode:8001/mcp` `hermes/config.yaml:20`) to avoid giving Hermes host/Docker access. This added `agent-workspace` + `antigravity-auth` volumes `docker-compose.yaml:133`, 3 GB RAM for delegates, OAuth handling, and serialization latency. Goal shifted to direct execution; delegates added operational cost without tailnet benefit.

## Decision
Remove `antigravity` and `opencode` services from `docker-compose.yaml:121`, their volumes `agent-workspace`/`antigravity-auth` `docker-compose.yaml:180`, `mcp_servers` from `hermes/config.yaml:17`, `platform_toolsets` delegate entries `hermes/config.yaml:151`, and ansible copy/verify tasks `ansible/roles/pai_stack/tasks/main.yml:125`. Hermes now implements directly in `/opt/data/Personal` and writes to `silverbulletKB` itself; `agent.system_prompt` delegation section removed.

## Alternatives Considered
- **Keep delegates** — retains second model family for fan-out but keeps Pi at 7GB + auth friction.
- **In-process shell for Hermes** — already the chosen path; Hermes uses LLM providers directly, no extra isolation needed at this scale.

## Consequences
- Positive: ~3 GB RAM saved, no OAuth, simpler `docker compose ps`, one `hermes/config.yaml:54` to govern behavior, `kb/Skills/_TEMPLATE/SKILL.md:13` steps simplified to direct draft.
- Negative: No automatic second-opinion fan-out; can be added later as a fallback provider if needed.

## Trade-offs
Simplicity and resource efficiency prioritized over isolated model-family fan-out.
