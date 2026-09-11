# Stack Discovery

> Auto-detect tech stack for any project under /opt/data so Hermes picks the right skill before reading code.

## When to use
- Trigger: user mentions a project without stating stack, or asks "what is this built with?", or before any read/edit on unknown codebase
- Preconditions: project path known (from `AGENTS.md` or user message or `/opt/data` search)
- Always run first when project has no `Projects/<Name>/docs/architecture.md` or stack is ambiguous

## Inputs
- Required: project root path(s) to scan (under `/opt/data/...`)
- Optional: depth limit (default 2 levels), language hint

## Steps
1. Retrieve scoped KB: `AGENTS.md` + `Projects/<Name>/**` if exists. Note if no KB → you will scaffold after discovery.
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
   - If no marker → state "unknown stack — listing files in /opt/data/<project>:..." and propose scaffold from `skill://templates/project/*`
5. Summarize & route:
   - Build table: `| Stack | Evidence | Skill |` with `file:lines` citations (e.g. `| Python | pyproject.toml:8 requires-python | skill://python |`)
   - State next skill to execute (e.g. "Detected Python + Docker + Postgres → will follow skill://python then skill://postgres + skill://docker")
6. Write & cite:
   - Update `Projects/<Name>/docs/architecture.md` with discovery table if KB exists, or propose new scaffold with it
   - Post 3-bullet summary in same Telegram topic, with skill citations (`skill://stack-discovery`, `skill://python`, etc.)

## Outputs
- Primary: discovery table (stack → evidence `file:lines` → skill) + primary/secondary ranking
- Next skill: which `skill://<name>` to retrieve next
- KB patch: proposed `docs/architecture.md` update or scaffold preview

## Related skills & resources
- `skill://python`
- `skill://docker`
- `skill://react`
- `skill://nodejs`
- `skill://postgres`
- `skill://templates/project/docs/architecture.md`
- `skill://agents`

## Notes for Hermes
- This skill is the router — run it before any stack-specific skill when stack is not already in KB.
- Keep headings `## Markers`, `## Scores`, `## Route` for retrieval.
- Cite every marker: `pyproject.toml:1`, `package.json:18`, `docker-compose.yaml:24`.
- Never guess stack without file evidence — if ambiguous, list files seen and ask user to confirm.
