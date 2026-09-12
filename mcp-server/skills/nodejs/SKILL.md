# Node.js Project

> Read, understand, and safely change Node.js codebases — detect runtime, package manager, framework, scripts, and deps.

## When to use
- Trigger: user says Node, npm, `package.json`, `*.js`/`*.ts`, `express`, `nestjs`, `fastify`, or asks to read/debug/build a Node app
- Preconditions: project under `/opt/data/workspace/...` with `package.json`
- Auto-use: when `stack-discovery` finds `package.json` (and Node is not just React tooling)

## Inputs
- Required: project root path
- Optional: service focus (API vs CLI vs worker), Node version constraint

## Steps
1. Retrieve scoped KB: `AGENTS.md` + `Projects/<Name>/**` + `issues/<slug>.md`. Cite `file:lines`.
2. Detect runtime & manager:
   - Read `package.json: engines.node` + `.nvmrc` + `.node-version` + `Dockerfile: FROM node:X` for Node version — cite `file:lines`
   - Lockfile: `package-lock.json` → npm, `yarn.lock` → yarn, `pnpm-lock.yaml` → pnpm, `bun.lockb` → bun. Note required install cmd (`npm ci` vs `yarn --frozen-lockfile` vs `pnpm i --frozen-lockfile`)
   - Check `packageManager` field in `package.json` (Corepack)
3. Inventory package.json:
   - `name`, `version`, `type` (`module` → ESM vs CJS), `main`/`exports`
   - `scripts`: `dev`, `start`, `build`, `test`, `lint`, `migrate` — record exact command per script with `file:lines`
   - `dependencies` vs `devDependencies` — flag framework (`express`, `fastify`, `nestjs`, `koa`, `hono`, `next`, `remix`) and runtime (`prisma`, `typeorm`, `drizzle`, `pg`)
4. Detect framework & structure:
   - `express`/`fastify`/`koa`: look for `src/server.*`, `src/app.*`, `src/routes/`, `src/middleware/` — sample route file for handler pattern
   - `nestjs`: `src/main.ts`, `src/app.module.ts`, `@Module` / `@Controller` decorators — list modules with `file:lines`
   - CLI: `bin` field, `commander`/`yargs`, `src/cli.*`
   - Check `tsconfig.json` — `module`, `target`, `strict`, `paths` aliases
5. Map entrypoints & config:
   - Trace `package.json: scripts.start` → file; check `src/index.*`, `src/server.*`, `src/main.*` first 30 lines for bootstrap
   - Env: `.env.example` / `.env` / `config/*.ts` — list required vars (`DATABASE_URL`, `PORT`, `JWT_SECRET` as refs, never raw)
   - Docker: `Dockerfile` / `docker-compose.yaml` → also retrieve `Skills/docker/SKILL.md`; Postgres detected → `Skills/postgres/SKILL.md`
6. Assess quality & health:
   - Tests: `__tests__/`, `*.test.*`, `*.spec.*`, `jest.config.*`, `vitest.config.*` — note runner
   - Lint/format: `eslint`, `prettier`, `biome` configs
   - Type safety: `tsc --noEmit` status, `strict` flag; flag `any` heavy files if sampled
   - Deps health: unpinned `^` vs pinned, `npm audit` risk if lockfile present
7. Plan work:
   - Read-only: summarize runtime (Node X + manager Y + framework Z), entrypoint, scripts table, how to run (`npm run dev` + port), how to test
   - Edits: minimal diff — keep ESM/CJS consistent, reuse existing router/middleware pattern, add test co-located, run `npm run lint` / `npm test` before done
   - For monorepo (`pnpm-workspace.yaml`, `lerna.json`, `turbo.json`) note workspace list and which package is in scope — don't edit outside scoped project
8. Write & cite:
   - Update `Projects/<Name>/docs/architecture.md` with Node map (runtime, manager, framework, entry, scripts, env) + `file:lines`
   - Post concise table + run/test commands in same Telegram topic, cited

## Outputs
- Primary: KB Node map (Node version, manager, framework, entrypoints, scripts, env) + `file:lines`
- Changelog: inspected files, proposed diff, validation note
- Next step: `npm ci && npm run dev` or `pnpm i && pnpm dev` etc., isolated to topic

## Related files
- `package.json`
- `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` / `bun.lockb`
- `tsconfig.json`
- `.nvmrc` / `.node-version`
- `src/server.*` / `src/app.*` / `src/main.*`
- `Skills/react/SKILL.md` (if React frontend), `Skills/docker/SKILL.md`, `Skills/postgres/SKILL.md`

## Notes for Hermes
- Headings: `## Runtime`, `## Scripts`, `## Framework`, `## Entrypoints`, `## Env` — better retrieval.
- Always cite `package.json:lines` for scripts/framework. State gap if missing: "No .nvmrc — inferred Node 20 from Dockerfile:3".
- Prefer `npm ci` for CI/repro, `npm install` only when adding deps. Respect lockfile of repo.
- If `package.json` has both `react` and `express`, treat as full-stack — retrieve both `Skills/react` and this skill, keep backend/frontend summaries separate.
