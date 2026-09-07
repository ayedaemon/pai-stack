# React Project

> Quickly read and work with React codebases — detect toolchain, component model, state, routing, data-fetching.

## When to use
- Trigger: user says React, `*.jsx`, `*.tsx`, `package.json` with `react`/`next`/`vite`, or asks to read/debug/build a React app
- Preconditions: project under `/opt/data/Personal/...` with `package.json` containing `react`
- Auto-use: when `stack-discovery` finds `react` in `package.json:dependencies` or `src/**/*.jsx?` / `*.tsx`

## Inputs
- Required: project root path
- Optional: page/component focus, design system, target browser

## Steps
1. Retrieve scoped KB: `AGENTS.md` + `Projects/<Name>/**` + `issues/<slug>.md`. Cite `file:lines`.
2. Detect React flavor & toolchain:
   - Read `package.json: dependencies` + `devDependencies` — note `react` version, `react-dom`, `next` (→ Next.js), `react-router-dom` (→ SPA routing), `vite` / `webpack` / `cra` / `rsbuild`
   - Check `package.json: scripts` — `dev`, `build`, `start`, `preview` commands with `file:lines`
   - Look for `vite.config.*`, `next.config.*`, `tsconfig.json`, `tailwind.config.*`, `.eslintrc*` at root
3. Map source structure:
   - List `src/` (or `app/` for Next.js) top-level: `components/`, `pages/` / `app/`, `hooks/`, `context/`, `store/`, `lib/`, `api/`, `assets/`
   - For Next.js: distinguish `app/` (App Router) vs `pages/` (Pages Router), note `layout.tsx`, `page.tsx`, `route.ts`
   - For Vite/CRA: note `src/main.tsx` or `src/index.tsx` entry, `public/` vs `src/assets`
4. Inspect component model:
   - Sample 3-5 components: function vs class, hooks (`useState`, `useEffect`, `useContext`, custom `use*`), props typing (`PropTypes` vs `TypeScript`)
   - State: local `useState` vs `Context` vs `Zustand`/`Redux`/`Jotai`/`Recoil` — read `store/` or `*Slice*`
   - Styling: `CSS Modules` vs `Tailwind` vs `styled-components` vs `MUI`/`Chakra` — check imports in sampled files
5. Inspect routing & data:
   - Routing: `react-router` `createBrowserRouter` / `<Route>` vs Next.js file-based routing — list routes with `file:lines`
   - Data-fetching: `fetch`/`axios` in `lib/api` vs `react-query`/`swr` vs Next.js `fetch`/`server actions` — note base URL, auth header pattern
   - Forms: `react-hook-form` / `formik` / controlled inputs
6. Inspect build & env:
   - `tsconfig.json: compilerOptions` — strictness, `paths` aliases (`@/*`)
   - `.env*` / `vite` `VITE_*` / Next `NEXT_PUBLIC_*` — secret refs only, never raw
   - `Dockerfile` present → also retrieve `Skills/docker/SKILL.md`; Node backend present → `Skills/nodejs/SKILL.md`
7. Plan work:
   - Read-only: summarize flavor (Next.js App Router vs Vite SPA), component hierarchy (2-3 levels), state + routing + data layer, how to run (`npm run dev` + port), build (`npm run build`)
   - Edits: propose minimal component diff, co-locate styles, keep TypeScript strict, add story/test if repo has them (`*.test.tsx`, `__tests__/`)
   - Run `npm run build` or `tsc --noEmit` mentally — flag type errors, missing deps
8. Write & cite:
   - Update `Projects/<Name>/docs/architecture.md` with React map (toolchain, routes, state, data) + `file:lines`
   - Post concise summary (flavor, entry, 3 key components, run/build cmds) in same Telegram topic, cited

## Outputs
- Primary: KB React map (toolchain, structure, routing, state, data-fetching, styling) + `file:lines`
- Changelog: inspected files, proposed diff, validation
- Next step: run/build command or component patch, isolated to topic

## Related files
- `package.json`
- `vite.config.*` / `next.config.*` / `webpack.config.*`
- `tsconfig.json`
- `src/main.tsx` or `src/index.tsx` or `app/layout.tsx`
- `src/components/**` / `src/pages/**` / `app/**`
- `Skills/nodejs/SKILL.md` (toolchain), `Skills/docker/SKILL.md` (if containerized)

## Notes for Hermes
- Headings: `## Toolchain`, `## Routes`, `## State`, `## Data`, `## Styling` — better chunks.
- Cite `package.json:14` for react version, `vite.config.ts:8` for alias, `src/components/X.tsx:22` for hook usage.
- For Next.js, always note server vs client components (`"use client"` directive).
- Don't invent `npx create-react-app` if `vite` already present — follow repo's own scripts.
