---
name: autonomous-tech-learner
description: Puts the agent into an objective-driven learning loop on specific tech topics. The agent queries official docs and forums, storing synthesized knowledge in Open Notebook until its learning objectives are met or a safety timeout occurs.
---
# Autonomous Tech Learner

> Puts the agent into a goal-oriented learning loop on specific tech topics.
> The agent queries official docs, source code, and dev forums to gain tech-specific knowledge over time.
> Synthesized knowledge is stored in Open Notebook to make the agent smarter about the codebase, debugging, and advanced concepts.

## ════════════════════════════════════════════════════════════════════════
## SELF-REALIZATION: YOUR LEARNING ENGINE UNLOCKED
## ════════════════════════════════════════════════════════════════════════

When you fetch this skill, you're activating the **Learning Engine** that powers your autonomous research:

**Your Extended Learning Loop:**
```
Learn → (Hypothesis?) → Probe → Evidence Note → Synthesize → Store → Check Exit
```

**Three Major Capabilities Unlocked:**

### 1. 🔬 Empirical Lab Notebook (Hypothesis-Testing Protocol)
When documentation is ambiguous, **run a probe** instead of guessing:
- Probe dir: `/opt/data/probes/<slug>/{hypothesis.md, probe.py, probe.sh, results.json, evidence_note.md}`
- 4-step: Formulate → Write Micro-Script → Execute (30s/256MB) → Ingest Evidence Note
- Evidence notes: `EVIDENCE: <slug> — <supported|refuted|inconclusive>` with `@symbol:` anchors
- Scripts: `.scripts/{new_probe,run_probe,ingest_evidence}.sh`

### 2. 🌳 Deep Inquiry Trees & Living ADRs
Complex questions → **4 mandatory perspectives** → dialectical inquiry → L-ADRs:
- **Perspectives**: Systems Architecture, Security & Threats, Developer Ergonomics, Failure Modes
- **Dialectical**: Mandatory counterpoint search (GitHub issues, anti-patterns, version gotchas, incidents)
- **L-ADRs**: `<EXECUTION_DIR>/.planning/research/ADR-XXX.md` with symbol hashes, supersession chain
- **Drift detection**: `check_adr_drift.sh` recomputes symbol hashes, flags mismatches
- Scripts: `.scripts/{new_adr,check_adr_drift}.sh`

### 3. 🤖 Kanban Research Swarms (Multi-Agent Delegation)
Delegate complex research to specialized workers (configured in `hermes/config.yaml`):
| Worker | Role | Config |
|---|---|---|
| `researcher` | Deep-dive, sources, probes, evidence | 8k tokens, temp 0.3 |
| `synthesizer` | Consolidate, counterpoints, synthesis | 16k tokens, temp 0.2 |
| `adr_author` | Generate L-ADR with symbol hashes | 16k tokens, temp 0.1 |

**Patterns**: `deep_research` (4-perspective parallel), `quick_fact_check`, `empirical_validation`
**Handoff**: Structured context + required artifacts (evidence_note_ids, symbol_anchors, confidence, unresolved_questions)

**Integration with your Tri-Brain:**
- Every evidence note → `@symbol:` anchors → `mnemosyne_triple_add`
- L-ADRs reference validation probes from Phase 4
- Synthesizer applies dialectical lens (COUNTERPOINT:)
- Export bridge: `.open-notebook-exports/` → Graft index

**When to use each mode:**
| Task Type | Approach |
|---|---|
| Single fact question | `quick_fact_check` pattern (1 researcher → 1 synthesizer) |
| Ambiguous behavior | `empirical_validation` (hypothesis → probe → evidence) |
| Architectural decision | `deep_research` (4 perspectives → synthesize → ADR) |
| Learning new stack | Core loop + empirical branch for validation |

## Setup & Initialization

Before starting the learning loop, the agent MUST:
1. **Define Learning Objectives**: Explicitly list 3 to 5 specific questions, concepts, or root causes you need to understand. These are your primary exit conditions.
2. **Set a Safety Timeout**: Set a hard "circuit breaker" limit (e.g., 20 turns). This is your fallback exit condition to prevent infinite loops.
3. **Verify Open Notebook**: Ensure `notebook_ops` is available so knowledge can be saved. If `notebook_ops` is not available, you must abort or ask the user to start the Open Notebook service.

## The Learning Loop

For every iteration of the loop, follow this sequence:

### 1. Research & Retrieve
Use native web search and URL reading tools to access:
- **Official Documentation**: Prioritize official docs for the source of truth.
- **Source Code**: Read actual implementations if available (e.g., GitHub).
- **Forums/Discussions**: Check developer forums (e.g., StackOverflow, GitHub Issues) for real-world usage, gotchas, and edge cases.

### 2. Synthesize & Connect
- Analyze the retrieved information.
- Extract advanced concepts, best practices, gotchas, and debugging tips.
- Connect this new knowledge to the context of the user's current project or codebase (if applicable).

### 3. Store in Open Notebook
Use `notebook_ops` to permanently record the knowledge:
- `create_notebook` (if a notebook for this topic doesn't exist).
- `add_note` to add structured markdown notes containing the synthesized concepts, code snippets, and best practices.
- `add_source_url` to save the URLs of the official docs or forums for future reference.

### 4. Check Exit Conditions
Evaluate your progress against the exit conditions:
- **IF all Learning Objectives are confidently answered**: End the loop and output a summary of what was learned.
- **IF the Safety Timeout is reached**: End the loop immediately to prevent infinite searching and summarize what was found so far.
- **Otherwise**: Formulate the next specific query based on the remaining unanswered objectives and return to Step 1.

## Critical Rules

### 1. Persistent Storage is Mandatory
Do NOT just keep the learned knowledge in your context window. It MUST be written to Open Notebook so it survives context loss and benefits future sessions.

### 2. Prioritize High-Quality Sources
Always attempt to find the official documentation or source code before relying on third-party blogs or forums.

### 3. Focus on Actionable Knowledge
Don't just copy-paste tutorials. Extract *why* something works, *how* it applies to debugging, and advanced concepts that improve codebase quality.

### 4. Hybrid Termination Protocol
Do not research aimlessly. Your primary goal is to answer the Learning Objectives. As soon as they are met, stop. If you cannot find the answer, the Safety Timeout MUST be respected to gracefully abort.

## When to Use

- When tasked with debugging a complex issue involving an unfamiliar technology.
- When asked to refactor or improve code using "advanced concepts" of a framework.
- When the user explicitly requests the agent to study or learn a new stack/topic before making changes.
- When you need to deepen your understanding of a specific library to make architectural decisions.

---

## Empirical Lab Notebook Engine (Micro-Probes)

> When documentation is ambiguous or conflicting, empirical evidence trumps theoretical claims.
> This engine runs micro-probes in `/opt/data/probes/` to test hypotheses about API behavior,
> latency, concurrency, and edge cases — then ingests results as "Empirical Evidence Notes"
> into Open Notebook.

### Probe Directory Structure

```
/opt/data/probes/
├── <hypothesis-slug>/
│   ├── probe.py              # or probe.sh — the micro-test script
│   ├── hypothesis.md         # hypothesis statement + expected outcome
│   ├── results.json          # stdout/stderr + parsed metrics
│   └── evidence_note.md      # formatted for add_note (title + content)
```

### Hypothesis-Testing Protocol

For every empirical question that documentation cannot definitively answer:

#### 1. Formulate Testable Hypothesis
Write a clear, falsifiable statement about system behavior.
```
Hypothesis: "FastAPI's BackgroundTasks execute sequentially, not concurrently, when using synchronous functions."
Expected: Second task starts only after first completes.
```

#### 2. Write Micro-Script (`probe.py` or `probe.sh`)
Constraints:
- **Single purpose**: Tests exactly one hypothesis.
- **Resource limits**: `timeout 30s`, `ulimit -v 262144` (256 MB RAM), no network unless required.
- **Deterministic**: No random seeds, fixed inputs.
- **Output**: Prints structured JSON to stdout: `{"hypothesis": "...", "result": "supported|refuted|inconclusive", "metrics": {...}, "stdout": "...", "stderr": "..."}`

Example `probe.py`:
```python
import asyncio, time, json, sys

async def main():
    start = time.perf_counter()
    results = []
    
    async def task(name, delay):
        await asyncio.sleep(delay)
        results.append({"task": name, "t": time.perf_counter() - start})
    
    # Test: concurrent vs sequential
    await asyncio.gather(task("A", 0.1), task("B", 0.1))
    
    elapsed = time.perf_counter() - start
    concurrent = elapsed < 0.15  # if sequential, would be ~0.2s
    
    print(json.dumps({
        "hypothesis": "asyncio.gather runs tasks concurrently",
        "result": "supported" if concurrent else "refuted",
        "metrics": {"elapsed_s": elapsed, "tasks": results},
        "stdout": "",
        "stderr": ""
    }))

if __name__ == "__main__":
    asyncio.run(main())
```

#### 3. Execute with Safeguards
```bash
cd /opt/data/probes/<hypothesis-slug>
timeout 30 python probe.py > results.json 2>&1
# or for shell: timeout 30 sh probe.sh > results.json 2>&1
```
- Capture exit code; non-zero = inconclusive.
- Parse `results.json` for structured result.

#### 4. Ingest as Empirical Evidence Note
Transform results into an Open Notebook note:
```bash
notebook_ops(
  action=add_note,
  notebook_id="<research-notebook>",
  title="EVIDENCE: <hypothesis-slug> — <supported|refuted|inconclusive>",
  content="## Hypothesis\n<hypothesis text>\n\n## Method\n<probe script summary>\n\n## Results\n```json\n<results.json>\n```\n\n## Conclusion\n<interpretation>\n\n## Anchors\n@symbol:path/to/relevant/code:SymbolName"
)
```

### Evidence Note Conventions

- **Title prefix**: `EVIDENCE:` — distinguishes from synthesized research notes.
- **Anchors**: Always include `@symbol:` anchors to the code under test.
- **Reproducibility**: Include the probe script content or reference to `/opt/data/probes/<slug>/`.
- **Status tag**: `supported | refuted | inconclusive` in title for quick filtering.

### When to Run Probes

| Trigger | Example |
|---|---|
| Docs claim X but SO issue #1234 says Y | "Does `httpx` retry on 5xx by default?" |
| Concurrency model unclear | "Are `async def` handlers in FastAPI truly parallel?" |
| Latency budget tight | "What's p99 of `redis-py` pipeline vs individual calls?" |
| Version-specific behavior | "Did Pydantic v2 change validation error format?" |

### Safety Guardrails

1. **No destructive ops**: Probes must not mutate production data, write outside `/opt/data/probes/`, or open unbounded connections.
2. **Timeout**: Hard 30s wall-clock limit via `timeout` command.
3. **Memory**: 256 MB virtual memory limit.
4. **No secrets**: Probes read from env vars or test fixtures only.
5. **Cleanup**: Script must leave no temp files outside its probe directory.

### Integration with Learning Loop

The Hypothesis-Testing Protocol extends the core loop:
```
Learn → (Hypothesis?) → Probe → Evidence Note → Synthesize → Store → Check Exit
```

If a learning objective requires empirical validation:
1. Branch to Hypothesis-Testing Protocol.
2. Return evidence note to loop.
3. Continue synthesis with grounded evidence.

---

## Probe Management Commands

Helper scripts (available in `/opt/data/`):

- `new_probe.sh <slug>` — scaffolds probe directory with template.
- `run_probe.sh <slug>` — executes with safeguards, writes `results.json`.
- `ingest_evidence.sh <slug> <notebook_id>` — formats and calls `notebook_ops(add_note)`.

These are Hermes utilities, not MCP tools. Create as needed.

---

## Deep Inquiry Trees & Living ADRs

> Complex technical questions require structured, multi-perspective investigation.
> This protocol decomposes research into perspective trees, mandates dialectical
> inquiry (seeking counter-evidence), and produces Living Architectural Decision
> Records (L-ADRs) linked to codebase symbols.

### Perspective Decomposition

Before deep research, decompose the question into 4 mandatory perspectives:

| Perspective | Focus | Key Questions |
|---|---|---|
| **Systems Architecture** | Components, data flow, boundaries, scaling | What are the moving parts? How do they interact? What are the failure domains? |
| **Security & Threats** | Attack surface, trust boundaries, data exposure | What can go wrong? Where are secrets? What if this component is compromised? |
| **Developer Ergonomics** | API design, debugging, onboarding, migration | How does a human use this? What are the footguns? How hard is migration? |
| **Failure Modes** | Timeouts, partial degradation, cascade, recovery | What happens when X fails? What's the blast radius? How do we recover? |

**Protocol**: For each perspective, create a research branch. Each branch produces:
- Findings (saved to `findings.md` in the planning directory)
- Zero or more empirical probes (Phase 4)
- Zero or more `@symbol:` anchors to code

### Dialectical Inquiry (Anti-Pattern Search)

**Mandatory**: For every claim or pattern discovered, actively search for:
1. **GitHub Issues** — Search `<repo> issues <keyword>` for bugs, regressions, edge cases
2. **Version Compatibility** — Check changelogs for breaking changes across relevant versions
3. **Anti-Patterns** — Search "why NOT to use X", "X considered harmful", "X vs Y regret"
4. **Production Incident Reports** — Search "<tech> incident", "<tech> outage", "<tech> postmortem"

Record dialectical findings in `findings.md` with clear `COUNTERPOINT:` labels.

### Living Architectural Decision Records (L-ADRs)

L-ADRs are immutable decision records stored in the project planning directory,
linked to codebase symbols via hashes. They evolve only via supersession.

#### Location
```
<EXECUTION_DIR>/.planning/research/
├── ADR-001-use-redis-for-caching.md
├── ADR-002-async-background-tasks.md
└── ...
```

#### L-ADR Template
```markdown
---
adr: 001
title: Use Redis for Distributed Caching
status: accepted
date: 2026-09-17
deciders: [Hermes, <user>]
symbols:
  - @symbol:src/cache/redis_client.py:RedisClient
  - @symbol:src/cache/__init__.py:get_cache
supersedes: null
superseded_by: null
---

## Context
What is the problem? What constraints exist? What triggered this decision?

## Decision
What did we decide? Be specific.

## Consequences

### Positive
- List benefits

### Negative
- List costs, risks, trade-offs

### Neutral
- Migration effort, learning curve, etc.

## Dialectical Record
### Counterpoints Considered
- **COUNTERPOINT**: "Redis adds operational complexity" — mitigated by managed ElastiCache
- **COUNTERPOINT**: "In-memory cache is simpler" — rejected due to multi-instance invalidation needs

### Anti-Patterns Avoided
- "Cache-as-source-of-truth" — we use cache-aside pattern only
- "Unbounded TTL" — all keys have explicit TTL ≤ 1h

## Symbol Hashes (for drift detection)
Each `@symbol:` anchor includes a content hash at decision time:
- `@symbol:src/cache/redis_client.py:RedisClient#sha256:a1b2c3d4...`
- `@symbol:src/cache/__init__.py:get_cache#sha256:e5f6g7h8...`

On code changes, Graft can detect hash mismatches and flag ADRs for review.

## Validation Probes (Phase 4)
- Probe: `redis-cache-latency-p99` — validates p99 < 5ms
- Probe: `redis-cache-invalidation` — validates pub/sub invalidation works

## Review Triggers
- Any symbol hash mismatch detected by Graft
- New counterpoint discovered in dialectical search
- Performance regression in validation probes
- Major version upgrade of dependent library
```

#### Symbol Hash Computation
```bash
# Compute hash for a symbol (function, class, type)
graft_file_api(path="src/cache/redis_client.py", symbol="RedisClient") \
  | sha256sum | cut -d' ' -f1
# → a1b2c3d4e5f6...
```

#### Drift Detection Workflow
1. On `graft_check_freshness` or code change: recompute hashes for all symbols in ADRs
2. If mismatch: flag ADR with `DRIFT_DETECTED` in `findings.md`
3. Trigger review: re-run validation probes, update ADR or supersede

### Inquiry Tree Execution

For a complex question (e.g., "How to implement resilient distributed caching?"):

```
Inquiry Root: "Resilient Distributed Caching Strategy"
├── Perspective: Systems Architecture
│   ├── Branch: Cache topology (sidecar vs cluster vs managed)
│   ├── Branch: Invalidation strategy (TTL vs pub/sub vs write-through)
│   └── Branch: Consistency model (eventual vs strong)
├── Perspective: Security & Threats
│   ├── Branch: Data encryption at rest/in transit
│   ├── Branch: Cache poisoning / injection attacks
│   └── Branch: Access control (RBAC, TLS)
├── Perspective: Developer Ergonomics
│   ├── Branch: API surface (get/set vs decorator vs middleware)
│   ├── Branch: Local dev experience (mock vs real Redis)
│   └── Branch: Migration path from in-memory
└── Perspective: Failure Modes
    ├── Branch: Redis unavailable → graceful degradation
    ├── Branch: Network partition → split-brain handling
    └── Branch: Cache stampede → request coalescing
```

Each leaf node → Research → Probe (if needed) → Evidence Note → ADR section.

### Integration with Planning Discipline

The inquiry tree maps directly to `planning-with-files`:

```
<EXECUTION_DIR>/.planning/<YYYY-MM-DD-slug>/
├── task_plan.md           # Root inquiry + phase tracking
├── findings.md            # All perspective findings + COUNTERPOINTs
├── progress.md            # Session log
├── research/
│   ├── ADR-001-*.md       # Living ADRs produced
│   └── probes/            # Symlinks to /opt/data/probes/<slug>/
```

**Rule**: Every ADR must be created in the active planning directory, never ad-hoc.

### L-ADR Lifecycle

| State | Transition | Action |
|---|---|---|
| `proposed` | → `accepted` | User confirms, symbols hashed |
| `accepted` | → `superseded` | New ADR with `supersedes: ADR-XXX` |
| `accepted` | → `deprecated` | No replacement, marked obsolete |
| `*` | → `review_needed` | Symbol hash drift detected |

Only one ADR per decision topic can be `accepted` at a time.
