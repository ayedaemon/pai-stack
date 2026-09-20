---
name: sql
description: Read, understand, and safely work with SQL databases and queries — schema, migrations, optimization, and ORM integration.
---

# SQL Project

> Read, understand, and safely work with SQL databases and queries — schema, migrations, optimization, and ORM integration.

## When to use
- IF the user mentions SQL, `DATABASE_URL`, `psql`, `migrations`, `schema.sql`, `JOIN`, `GROUP BY`, `views`, `indexes`, OR asks to inspect/debug/migrate a DB, THEN you MUST execute this skill.
- IF `stack-discovery` detects a Python/Node.js project with DB integration (e.g. `DATABASE_URL`, `prisma`, `alembic`, `typeorm`, `sequelize`), THEN you MUST execute this skill.
- Preconditions: project under `/opt/data/workspace/...` with SQL-related config or ORM

## Inputs
- Required: project root path, DB type hint (optional: postgres, mysql, sqlite, mssql)
- Optional: env file location, migration tool hint, read-only vs migrate intent

## Steps
1. Retrieve scoped KB: `AGENTS.md` + `Projects/<Name>/**` + `issues/<slug>.md`. Cite `file:lines`.
2. Locate DB definition:
   - Compose: grep `image: postgres` / `image: mysql` / `image: mssql` / `postgres:` / `mysql:` / `mssql:` service in `docker-compose.yaml` — record `image:`, `ports:`, `volumes:`, `environment: POSTGRES_*` with `file:lines`
   - Env: read `.env.example` / `config.*` for `DATABASE_URL` / `POSTGRES_URL` / `DB_URL` — note as secret ref (never raw), format `postgres://user:pass@host:5432/db` or `mysql://user:pass@host:3306/db`
   - Dockerfile: check if DB is separate service vs embedded
3. Detect ORM / migration tool:
   - `prisma/schema.prisma` → Prisma (`package.json: prisma`); `drizzle.config.*` → Drizzle; `alembic.ini` / `migrations/` / `alembic/` → SQLAlchemy/Alembic; `typeorm` / `sequelize` / `knex` in `package.json` / `pyproject.toml`
   - List migration files: `prisma/migrations/*`, `migrations/*.sql`, `alembic/versions/*.py` — sample latest 2 for style (idempotent vs destructive)
   - Check `package.json: scripts` / `Makefile` for `migrate`, `db:push`, `db:generate`, `alembic upgrade` commands
4. Map schema:
   - Read `schema.prisma` / `schema.sql` / `models/*.py` (`sqlalchemy` declarative) / `entities/*.ts` — list tables, PKs, FKs, indexes, extensions (`pgvector`, `postgis`, `uuid-ossp`)
   - Note naming convention (snake_case vs camelCase), `created_at`/`updated_at` patterns, soft-delete vs hard
   - Sample 2-3 migration files for constraints, enums, triggers
5. Inspect data access:
   - Grep for `prisma.*` / `drizzle` / `sqlalchemy` / `typeorm` / `sequelize` / `knex` usage in `src/` — note connection pooling (`Pool`, `createPool`, `DATABASE_URL` single vs `PG*` parts)
   - Check for raw SQL (`SELECT` in code) vs query builder vs ORM — flag SQL injection risk (string concat vs parameterized)
   - Look for seeds: `seed.*`, `fixtures/`, `prisma/seed.*`, `scripts/seed*`
6. Check ops & safety:
   - Volumes: is DB data in named volume vs bind mount vs ephemeral — flag data-loss risk
   - Backups: any `pg_dump` / `mysqldump` / `backup` script, or `Makefile` target
   - Health: `healthcheck: pg_isready` in compose? `depends_on: condition: service_healthy`?
   - Never run destructive `DROP` / `TRUNCATE` / `migrate --force` without explicit confirm — propose `EXPLAIN` / dry-run first
7. Plan work:
   - Read-only: summarize DB (service, version `image: postgres:16-alpine` or `mysql:8`, ORM, tables count, migration tool, how to connect `psql $DATABASE_URL` or `docker compose exec db psql`, how to migrate)
   - Edits: propose migration file + ORM model diff together (e.g. `prisma/schema.prisma:12` + `migrations/…:1`), keep idempotent, add down migration note if tool supports it
   - Pair with `Skills/docker/SKILL.md` if compose service, `Skills/python/SKILL.md` if SQLAlchemy, `Skills/nodejs/SKILL.md` if Prisma/Drizzle
8. Write & cite:
   - Update `Projects/<Name>/docs/architecture.md` with DB map (service, image, ORM, tables, migrations, connect/migrate cmds) + `file:lines`
   - Post concise summary (service, ORM, 3 key tables, connect + migrate cmds) in same Telegram topic, cited

## SQL Patterns & Development Guidelines

When writing, editing, or planning SQL code, you MUST adhere to the following conventions:

1. **Schema & Migrations**:
   - Write idempotent migrations. Never use destructive operations (`DROP`, `TRUNCATE`, `migrate --force`) without explicit user consent.
   - Use appropriate indexing (e.g., B-Tree for equality/sorting, GIN for JSONB/Full-Text Search).

2. **Access & Performance**:
   - Always enforce connection pooling on the application side to prevent connection exhaustion.
   - **Anti-Pattern**: N+1 queries in ORMs. Always use `JOIN` or eager-loading.
   - **Anti-Pattern**: String interpolation for raw SQL (massive SQL injection risk). Always use parameterized queries.
   - **Anti-Pattern**: Using `SELECT *` in production code. Select only the columns needed.

## Verification
- Verify dry-runs of migrations before applying.
- Propose `EXPLAIN ANALYZE` for heavy queries before making optimization claims.

## Outputs
- Primary: KB DB map (service, image, ORM, tables, migrations, connect/migrate commands) + `file:lines`
- Changelog: inspected files, proposed migration/model diff, safety note
- Next step: `docker compose up -d db` / `psql` / `prisma migrate dev` / `alembic upgrade head` (ask-first for writes)

## Related files
- `docker-compose.yaml` (DB service)
- `prisma/schema.prisma` / `drizzle.config.*` / `alembic.ini` / `models/*.py` / `entities/*.ts`
- `migrations/**` / `prisma/migrations/**` / `alembic/versions/**`
- `.env.example` (`DATABASE_URL` ref)
- `Skills/docker/SKILL.md`, `Skills/python/SKILL.md`, `Skills/nodejs/SKILL.md`

## Notes for Hermes
- Headings: `## Service`, `## ORM`, `## Schema`, `## Migrations`, `## Access`, `## Safety` — better chunks.
- Cite `docker-compose.yaml:22` for `image: postgres:16`, `prisma/schema.prisma:14` for model, `migrations/001_init.sql:8` for table.
- Never log raw `DATABASE_URL` — use `DATABASE_URL in env` ref.
- For `SELECT` heavy tasks, suggest `EXPLAIN ANALYZE` before optimizing, and note index candidates with `file:lines`.