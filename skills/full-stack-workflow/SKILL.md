---
name: full-stack-workflow
description: "Orchestrates the full development lifecycle for frontend + backend + database projects. Load when starting a new full-stack feature, designing a CRUD app, or when the work spans UI, API, and schema. Prevents over-engineering via kill criteria, enforces API contract-first discipline, and provides a definition of done that spans all three layers."
---

# Full-Stack Workflow

> Orchestrates design → plan → implement → review for frontend + backend + DB projects.
> Prevents over-engineering through kill criteria at every layer.
> **Primary Goal:** Ship the minimum working full-stack feature without gold-plating.

---

## The 4-Phase Workflow

Never skip phases. Each phase has explicit exit criteria.

```
Phase 1: DESIGN (system-design + forcing questions)
    ↓ exit: ADR created, out-of-scope defined, kill criteria passed
Phase 2: CONTRACT (API schema + DB schema + frontend types)
    ↓ exit: OpenAPI spec + migration + TypeScript types generated
Phase 3: IMPLEMENT (ponytail + propose-before-write)
    ↓ exit: All layers integrated, definition of done met
Phase 4: REVIEW (code-reviewer + drift check)
    ↓ exit: Complexity thresholds pass, ADR drift clean
```

---

## Phase 1: Design

### 1A. Backend Forcing Questions (Kill Criteria)

Before any backend design, walk these. If a kill criterion trips, **stop**.

| # | Question | Kill Criterion |
|---|---|---|
| Q1 | Read/write ratio + p99 QPS forecast? | No numbers → STOP. Every architecture choice is a guess. |
| Q2 | Tenancy model — single / shared / isolated? | Unknown → default to single-tenant, note as ADR. |
| Q3 | Sync / async / event-driven? | "Event-driven" with team < 20 → STOP. Default to sync. |
| Q4 | Data sensitivity tier — public / internal / PII / PHI / PCI? | Unknown → default to internal, note as ADR. |
| Q5 | Monolith / modular monolith / microservices? | Microservices without team >= 30 + bounded contexts + platform team → STOP. Default to modular monolith. |
| Q6 | RPO + RTO? | Unknown → default RPO 24h, RTO 4h, note as ADR. |
| Q7 | SLO + named error-budget consumer? | No SLO → no reliability work. Default to 99.5% uptime. |

**Load:** `skill_view(name="senior-backend")` → `references/forcing_questions.md`

### 1B. Frontend Forcing Questions (Kill Criteria)

Before any frontend design, walk these.

| # | Question | Kill Criterion |
|---|---|---|
| F1 | How many distinct routes/views? | > 7 views → split into phases, ship core 3 first. |
| F2 | Does it need a state library? | No → useState + context. Yes → justify (Zustand/Redux). |
| F3 | Does it need a data-fetching library? | No → fetch + useEffect. Yes → justify (React Query/SWR). |
| F4 | Does it need SSR/SSG? | No → SPA. Yes → justify (Next.js). |
| F5 | Does it need a component library? | No → hand-rolled + Tailwind. Yes → justify (shadcn/MUI). |
| F6 | Real-time updates (WebSocket/SSE)? | No → polling. Yes → justify. |
| F7 | Offline support / PWA? | No → skip. Yes → justify. |

**Default answers** (when in doubt): useState + context, fetch + useEffect, SPA, hand-rolled + Tailwind, polling, no PWA.

### 1C. DB Forcing Questions (Kill Criteria)

Before any schema design, walk these.

| # | Question | Kill Criterion |
|---|---|---|
| D1 | Expected row count per table? | Unknown → assume < 100k rows, no partitioning. |
| D2 | Read or write heavy? | Unknown → assume read-heavy (100:1). |
| D3 | Need full-text search? | No → skip. Yes → add pg_trgm index, not Elasticsearch. |
| D4 | Need JSON columns? | No → skip. Yes → justify (semi-structured data). |
| D5 | Multi-tenant? | No → skip RLS. Yes → design tenant_id into every table. |
| D6 | Need soft deletes? | No → hard delete. Yes → deleted_at timestamp. |
| D7 | Need audit trail? | No → skip. Yes → created_at + updated_at + created_by. |

**Load:** `skill_view(name="supabase-postgres-best-practices")`

### 1D. System Design Output

Produce a single design document at `<EXECUTION_DIR>/.planning/<slug>/design.md`:

```markdown
## Requirements
- Functional: [what it does]
- Non-functional: [latency, throughput, availability]
- Out of Scope: [what we are NOT building]

## Scale Estimates
- RPS: [number]
- Storage: [number]
- Read/write ratio: [number]

## Architecture
- Pattern: [modular monolith default]
- DB: [Postgres default]
- Cache: [none unless QPS > 500]
- Queue: [none unless async justified]

## API Contract
- [OpenAPI spec reference]

## Data Model
- [ERD reference]

## Trade-offs
- [what we sacrificed and why]
```

**Persist:** `pai_adr_ops(action="create_adr")` for each key decision.

---

## Phase 2: Contract

### 2A. API Contract-First

Define the contract before implementing either side.

```yaml
# openapi.yaml — the single source of truth
openapi: 3.0.3
info:
  title: [Feature] API
  version: 1.0.0
paths:
  /[resource]:
    get:
      summary: List [resource]
      parameters:
        - name: limit
          in: query
          schema: { type: integer, default: 20 }
      responses:
        '200':
          content:
            application/json:
              schema:
                type: array
                items: { $ref: '#/components/schemas/[Resource]' }
    post:
      summary: Create [resource]
      requestBody:
        content:
          application/json:
            schema: { $ref: '#/components/schemas/Create[Resource]' }
      responses:
        '201':
          content:
            application/json:
              schema: { $ref: '#/components/schemas/[Resource]' }
components:
  schemas:
    [Resource]:
      type: object
      required: [id, name]
      properties:
        id: { type: string, format: uuid }
        name: { type: string, maxLength: 255 }
        created_at: { type: string, format: date-time }
```

**Generate TypeScript types from OpenAPI:**
```bash
# If openapi-typescript is available
npx openapi-typescript openapi.yaml -o src/types/api.ts
```

### 2B. DB Schema + Migration

Expand-only migrations. Never drop columns in the same release.

```sql
-- migrations/001_initial_schema.sql
CREATE TABLE [resource] (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes (only if justified by query patterns)
CREATE INDEX idx_[resource]_created_at ON [resource](created_at);

-- RLS (only if multi-tenant)
ALTER TABLE [resource] ENABLE ROW LEVEL SECURITY;
```

**Migration discipline:**
- Expand-only: ADD COLUMN, CREATE INDEX — never DROP in same release
- Each migration is reversible (write the down migration)
- Test on a copy of production data before applying
- Zero-downtime: add new column → backfill → switch reads → drop old column (separate releases)

### 2C. Frontend Types

Generate or hand-write types that mirror the API contract:

```typescript
// src/types/[resource].ts
export interface [Resource] {
  id: string;
  name: string;
  createdAt: string;
}

export interface Create[Resource] {
  name: string;
}
```

**Rule:** Frontend types MUST match OpenAPI spec. If they diverge, regenerate.

---

## Phase 3: Implement

### 3A. Implementation Order

```
1. DB migration (expand-only)
2. Backend endpoint (minimal handler + validation)
3. Frontend API client (fetch wrapper)
4. Frontend component (minimal UI)
5. Integration (wire frontend to backend)
```

### 3B. Per-File Simplicity (Ponytail Ladder)

Before writing any file, walk the 7-rung ladder:

```
1. Does this need to exist at all? → YAGNI, skip it
2. Already in this codebase? → Reuse it
3. Stdlib does it? → Use it
4. Native platform feature covers it? → Use it
5. Already-installed dependency solves it? → Use it
6. Can it be one line? → One line
7. Only then: the minimum code that works
```

**Load:** `skill_view(name="ponytail")`

### 3C. Propose-Before-Write

For every file:
1. **Propose** the exact diff or file content to the user
2. **Wait** for explicit confirmation
3. **Write** to `<EXECUTION_DIR>/<file>`

### 3D. Backend Implementation

```typescript
// src/routes/[resource].ts — minimal handler
import { z } from 'zod';

const Create[Resource]Schema = z.object({
  name: z.string().min(1).max(255),
});

export const list[Resource] = async (req: Request, res: Response) => {
  const items = await db.query('SELECT * FROM [resource] ORDER BY created_at DESC LIMIT $1', [20]);
  res.json(items);
};

export const create[Resource] = async (req: Request, res: Response) => {
  const data = Create[Resource]Schema.parse(req.body);
  const item = await db.query('INSERT INTO [resource] (name) VALUES ($1) RETURNING *', [data.name]);
  res.status(201).json(item);
};
```

**Rules:**
- Validation at trust boundary (always)
- No business logic in routes (extract to service layer only if reused)
- Error handling that prevents data loss (always)
- No abstractions for single-use code

### 3E. Frontend Implementation

```typescript
// src/components/[Resource]List.tsx — minimal component
export function [Resource]List() {
  const [items, setItems] = useState<[Resource][]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/[resource]')
      .then(r => r.json())
      .then(setItems)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div>Loading...</div>;

  return (
    <ul>
      {items.map(item => (
        <li key={item.id}>{item.name}</li>
      ))}
    </ul>
  );
}
```

**Rules:**
- No state library unless F2 justified it
- No data-fetching library unless F3 justified it
- No component library unless F5 justified it
- Hand-rolled + Tailwind by default

---

## Phase 4: Review

### 4A. Code Reviewer (Complexity Thresholds)

| Issue | Threshold | Action |
|---|---|---|
| Long function | >50 lines | Split |
| Large file | >500 lines | Split |
| God class | >20 methods | Split |
| Too many params | >5 | Use options object |
| Deep nesting | >4 levels | Extract |
| High complexity | >10 branches | Refactor |

**Load:** `skill_view(name="code-reviewer")`

### 4B. ADR Drift Check

```bash
pai_adr_ops(action="check_drift")
```

If drift detected: update ADR or fix code. Never leave drift unresolved.

### 4C. Full-Stack Definition of Done

A feature is done when ALL of these pass:

| Layer | Criteria |
|---|---|
| **DB** | Migration applied, reversible, indexes justified, RLS if multi-tenant |
| **Backend** | Endpoint returns correct status, validates input, handles errors, matches OpenAPI spec |
| **Frontend** | Component renders, consumes API, handles loading/error states, matches design |
| **Integration** | Frontend successfully calls backend, data flows end-to-end |
| **Tests** | Non-trivial logic has one runnable check |
| **Review** | Complexity thresholds pass, no ADR drift |
| **Scope** | Out-of-scope items were NOT built |

---

## Anti-Over-Engineering Checklist

Before declaring done, verify:

- [ ] No unrequested abstractions (interface with one implementation)
- [ ] No config for values that never change
- [ ] No scaffolding "for later"
- [ ] No dependencies added for what a few lines can do
- [ ] No microservices without team >= 30 + bounded contexts + platform team
- [ ] No event-driven without team >= 20
- [ ] No state library without justification
- [ ] No data-fetching library without justification
- [ ] No SSR/SSG without justification
- [ ] No component library without justification
- [ ] No real-time without justification
- [ ] No PWA without justification
- [ ] No full-text search without justification
- [ ] No JSON columns without justification
- [ ] No partitioning without row count > 1M
- [ ] No cache without QPS > 500
- [ ] No queue without async justification

---

## Integration with Existing Skills

| Phase | Skill | Role |
|---|---|---|
| 1A | `senior-backend` | Backend forcing questions + kill criteria |
| 1B | `react` | Frontend discovery + delegation |
| 1C | `supabase-postgres-best-practices` | DB best practices |
| 1D | `system-design` | Architecture framework |
| 2A | `senior-backend` | API scaffolder |
| 3B | `ponytail` | Simplicity ladder |
| 3D | `nodejs` | Backend authoring |
| 3E | `react` | Frontend authoring |
| 4A | `code-reviewer` | Complexity thresholds |
| 4B | `pai_adr_ops` | Drift detection |
| All | `planning` | .planning/ discipline |
| All | `gitops` | Branch safety |

---

## When to Use This Skill

- New full-stack feature (frontend + backend + DB)
- CRUD app design
- API + UI + schema work
- Any task spanning 2+ layers (UI, API, DB)

**Skip when:**
- Single-layer change (backend-only, frontend-only, DB-only)
- Single-file edit
- One-off lookup

---

## Output

- `.planning/<slug>/design.md` — design document
- `.planning/<slug>/task_plan.md` — implementation plan
- `.planning/<slug>/findings.md` — discoveries
- `.planning/<slug>/progress.md` — session log
- ADRs for key decisions
- OpenAPI spec
- Migration files
- Implementation code
