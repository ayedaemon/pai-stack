---
name: stack-discovery
description: Auto-detect tech stack for any project under /opt/data/workspace so Hermes picks the right skill before reading code.
---
# Stack Discovery

> Auto-detect tech stack for any project under /opt/data/workspace so Hermes picks the right skill before reading code.

## When to use
- IF the user mentions a project without stating the stack, OR asks "what is this built with?", OR before any read/edit on an unknown codebase, THEN you MUST execute this skill.
- IF the project has no existing `task_plan.md`/`findings.md` or the stack is ambiguous, THEN you MUST run this skill first.
- Preconditions: project path known (from user message or `/opt/data/workspace` search)

## Inputs
- Required: project root path(s) to scan (under `/opt/data/workspace/...`)
- Optional: depth limit (default 2 levels), language hint

## Steps
1. Check for prior findings: `graft_find_code(question="<project> stack discovery findings", scope=".")` — if results exist, note them. Either way, proceed with marker scan below.
2. Scan root (depth 1-2) for markers — record `file:lines` hit for each:
   - Python: `pyproject.toml`, `requirements*.txt`, `Pipfile`, `poetry.lock`, `uv.lock`, `setup.py`, `*.py` at top-level, `.python-version`
   - Docker: `Dockerfile*`, `docker-compose*.yaml`, `compose.yaml`, `.dockerignore`
   - Node.js: `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `bun.lockb`, `.nvmrc`, `.node-version`
   - React: `package.json` contains `react` / `next` + `src/**/*.jsx`/`*.tsx` / `vite.config.*` / `next.config.*`
   - Postgres: `docker-compose.yaml` with `postgres` image, `prisma/schema.prisma`, `drizzle.config.*`, `alembic.ini`, `migrations/*.sql`
3. Score stacks:
   - If `package.json` has `react` → React + Node.js (both apply)
   - If `package.json` without `react` but with `express`/`nestjs`/`fastify` → Node.js
   - If `pyproject.toml` / `requirements.txt` → Python (check Docker too for `FROM python`)
   - If `Dockerfile` + compose → Docker always co-applies
   - If `postgres` image or `DATABASE_URL` or ORM config → Postgres co-applies
   - Polyglot is common — list primary (most files/entripoint) vs secondary
4. Pick skills:
   - Primary stack → retrieve its `skill://<stack>` first and follow it
   - Secondary stacks → retrieve each co-skill (`skill://docker`, `skill://postgres`) and apply their steps where relevant
   - If no marker → state "unknown stack — listing files in /opt/data/workspace/<project>:..." and propose initializing a plan with `/pwf "Stack Discovery"`
5. Summarize & route:
   - Build table: `| Stack | Evidence | Skill |` with `file:lines` citations (e.g. `| Python | pyproject.toml:8 requires-python | skill://python |`)
   - State next skill to execute (e.g. "Detected Python + Docker + Postgres → will follow skill://python then skill://postgres + skill://docker")
6. Write & cite:
   - Write discovery table to `findings.md` in the active task plan directory
   - If no plan exists yet, propose creating one with `/pwf "Stack Discovery — <project>"`

## Verification
- Verify that `findings.md` was successfully written and contains the discovery table.
- Verify that you have explicitly named the next `skill://<name>` to execute.

## Outputs
- Primary: discovery table (stack → evidence `file:lines` → skill) + primary/secondary ranking
- Next skill: which `skill://<name>` to retrieve next
- Findings: written to `findings.md` in the active task plan directory

## Related skills & resources
- `skill://python`
- `skill://docker`
- `skill://react`
- `skill://nodejs`
- `skill://postgres`
- `skill://planning`
- `skill://agents`

## Notes for Hermes
- This skill is the router — run it before any stack-specific skill when stack is not already in findings.
- Keep headings `## Markers`, `## Scores`, `## Route` for retrieval.
- Cite every marker: `pyproject.toml:1`, `package.json:18`, `docker-compose.yaml:24`.
- Never guess stack without file evidence — if ambiguous, list files seen and ask user to confirm.
- Save the discovery table to `findings.md` immediately (2-operation rule).
