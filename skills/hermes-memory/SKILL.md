---
name: hermes-memory
description: Hermes-only depth - Mnemosyne persistent memory (recall, remember, triples, sleep), the dual-brain lookup across code intelligence and the Research Brain, Kanban research swarms, the empirical lab notebook, and Living ADRs. Load when a task involves remembering across sessions, deep multi-perspective research, empirical verification of conflicting docs, or architectural decision records. Agents without these tools should skip this skill entirely.
---

# Hermes Memory & Research Depth

> Everything here depends on tools that exist in **Hermes only** — `mnemosyne_*`,
> `kanban.workers` from `hermes/config.yaml`. Other agents in the stack do not have them.
> **If you lack these tools, skip this skill** — the shared rules are in `agents`.
> Shared operating rules (`agents`): `EXECUTION_DIR`, Turn-1, propose-before-write.

## The two brains

| Brain | Store | Tools |
|---|---|---|
| Research Brain | `<EXECUTION_DIR>/.project/research/` | `pai_notebook_ops` (file vault, grounded RAG via `ask_notebook`) |
| Memory Brain | `/opt/hermes/data/mnemosyne/` (SQLite) | `mnemosyne_recall`, `_remember`, `_sleep`, `_stats`, `_triple_add`, `_triple_query` |

Code intelligence is Terrain (see `agents`). You have three systems; **synthesise across them,
never use one alone.**

### Memory discipline

| Use `mnemosyne_remember` for | Never use it for |
|---|---|
| Project boundaries, stack architecture | transient errors, stack traces |
| User preferences, API key *locations* | step-by-step session progress |
| Structural design decisions | anything that belongs in `progress.md` |

## Cross-brain lookup — mandatory

Before writing new research on a symbol, check whether it already exists.

```
1. mnemosyne_triple_query(predicate="anchors_symbol",
                           object="@symbol:path/to/file.ext:SymbolName")
2. If triples exist → read the source note via
   pai_notebook_ops(action="get_source", ...)
3. After archiving a note, record the anchor:
   mnemosyne_triple_add(subject="notebook:<id>:note:<id>",
                        predicate="anchors_symbol",
                        object="@symbol:path/to/file.ext:SymbolName")
```

Anchor format, used in every research note, ADR, and evidence note:

```
@symbol:path/to/file.ext:SymbolName
```

This is the glue that prevents duplicate research and keeps the three systems from drifting.

## Empirical lab — test, don't guess

When docs conflict or are ambiguous, do not pick the one that reads best.

1. State a falsifiable hypothesis.
2. Write a probe in `/opt/data/probes/<slug>/` (Python or shell).
3. Run it under guardrails: `timeout 30`, `ulimit -v 262144` (256 MB).
4. Ingest the result as an `EVIDENCE:` note with `@symbol:` anchors —
   `pai_notebook_ops(action="add_note", ...)`, stating **supported / refuted / inconclusive**.

## Dialectical inquiry — four mandatory perspectives

For any complex question, cover all four:

1. **Architecture** — components, data flow, boundaries, scaling
2. **Security** — attack surface, trust boundaries, data exposure
3. **Ergonomics** — developer experience, onboarding, modification cost
4. **Failure modes** — timeouts, partial degradation, cascades, recovery

Then seek the counter-case: GitHub issues for known bugs, changelogs for version drift,
"why NOT" and "X considered harmful" searches, real incident write-ups. Record the strongest
counterargument as a `COUNTERPOINT:` entry in `findings.md`.

## Living ADRs

Stored at `<EXECUTION_DIR>/.project/planning/research/ADR-XXX.md` with YAML frontmatter
(`status`, `symbols`, supersession chain), SHA-256 symbol hashes for drift detection, the
dialectical record, validation probes, and review triggers.

- **Create**: `pai_adr_ops(action="create_adr", adr_number=…, title=…, context=…, decision=…, symbols=[…])`
- **Drift**: `pai_adr_ops(action="check_drift")` — recomputes hashes, flags mismatches in
  `findings.md`. Run before major decisions and before merge (see `change-impact`).

Lifecycle: `proposed` → `accepted` → `superseded` / `deprecated`.

## Kanban research swarms

Configured under `kanban.workers` in `hermes/config.yaml`.

| Worker | Specialisation |
|---|---|
| `researcher` | deep-dive, ingest sources, run probes, evidence notes (8k tok) |
| `synthesizer` | consolidate findings, counterpoints, synthesis (16k tok) |
| `adr_author` | draft the L-ADR with symbol hashes (16k tok) |

Patterns: `deep_research`, `quick_fact_check`, `empirical_validation`.
Handoff context: `notebook_id`, `execution_dir`, `anchor_symbols`, `inquiry_question`,
`required_artifacts`, `result_summary`, `evidence_note_ids`, `open_questions`.

Delegate complex research to a swarm rather than grinding through it solo.