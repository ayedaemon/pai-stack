---
name: research
description: Root-level persistent wiki (Karpathy llm-wiki pattern) on the shared research vault. Create, ingest, query, and lint interlinked Markdown knowledge. Use when user mentions wiki, knowledge base, notes, or starts/queries/lints research.
---

# Research — Root-Level Wiki

> Persistent, compounding knowledge base as interlinked Markdown at the vault root.
> Based on Karpathy's LLM Wiki pattern (via `llm-wiki` on hermesskins.io), adapted for pai-stack.

## Wiki Location (env-configurable, same path)

```bash
WIKI="${WIKI_PATH:-$RESEARCH_DIR:-/opt/data/workspace/research}"
```

- In-container `WIKI_PATH == RESEARCH_DIR == /opt/data/workspace/${RESEARCH_SUBDIR:-research}` (`docker-compose.yaml`, `.env.example: RESEARCH_SUBDIR`).
- Host path = `${WORKSPACE_DIR}/${RESEARCH_SUBDIR}` (default `research`). Never use `~/wiki` — unmounted and unindexed.
- Legacy notebook vaults (`<notebook>/{notes/,sources/,notebook.json}`) remain readable alongside the wiki; new knowledge goes in wiki dirs below.

## Architecture: root-level wiki + legacy notebooks

```
research/                        ← $WIKI_PATH == $RESEARCH_DIR
├── SCHEMA.md                    ← conventions, tag taxonomy, domain
├── index.md                     ← sectioned catalog, one-line summaries
├── log.md                       ← chronological action log (append-only, rotate at 500)
├── raw/articles|papers|.../     ← Layer 1: immutable sources (never edit)
├── entities/                    ← Layer 2: people, orgs, products, models
├── concepts/                    ← Layer 2: topics, techniques
├── comparisons/                 ← Layer 2: side-by-side analyses
├── queries/                     ← Layer 2: filed answers worth keeping
├── _archive/                    ← superseded pages (removed from index)
└── <notebook>/notes|sources/    ← legacy vault (read via pai_notebook_ops)
```

Layer 1 raw = immutable. Layer 2 wiki = agent-owned. Layer 3 SCHEMA = rules.

## Orient First (every session touching research)

1. Read `SCHEMA.md` (domain, conventions, tags).
2. Read `index.md` (what exists).
3. Read last 20 lines of `log.md` (recent activity).
4. For 100+ pages, `pai_code_intel(find_code)` / `search` the topic before creating anything.

Skipping this causes duplicates and missed cross-refs.

## Init New Wiki (vault empty)

1. Confirm `$WIKI` resolves (echo path; must be under `/opt/data/workspace`).
2. Ask domain (be specific, e.g. "Aurora Postgres tuning").
3. Write `SCHEMA.md` (template below, customized), `index.md` (section headers, `Total pages: 0`), `log.md` (`create | Wiki initialized`).
4. Suggest first sources.

### SCHEMA.md (adapt to domain)

- Filenames: lowercase, hyphens (`transformer-architecture.md`).
- Every page: YAML frontmatter (`title, created, updated, type: entity|concept|comparison|query|summary, tags, sources`), ≥2 `[[wikilinks]]`, bump `updated` on edit, add to `index.md`, append to `log.md`.
- Tags only from taxonomy (add to SCHEMA first).
- Thresholds: create when entity appears in 2+ sources or is central to one; split at ~200 lines; archive (move to `_archive/`, delink) when superseded.
- Contradictions: keep both claims with dates, set `contested: true` + `contradictions: [slug]`, surface in lint.
- Confidence: `high|medium|low` for opinion-heavy/fast-moving/single-source claims.
- Raw files get `source_url, ingested, sha256` (body hash; skip re-ingest when unchanged, flag drift when changed).

## Ingest (URL, file, paste)

1. Capture raw → `raw/<articles|papers|...>/<slug>.md` with frontmatter. Re-ingest: recompute sha, skip if same, flag drift if different. Never modify `raw/` afterwards.
2. Check existing: `index.md` + `pai_notebook_ops(search)` + `pai_code_intel(find_code)` for mentioned entities.
3. Write/update Layer-2 pages per thresholds. Cross-ref ≥2 `[[wikilinks]]` (both directions). Tags from taxonomy. Append `^[raw/...]` provenance on 3+-source syntheses. Set `confidence` honestly.
4. Update `index.md` (alphabetical, count, date) + append `log.md` (`ingest | Title — files created/updated`).
5. Report files changed. If 10+ pages touched, confirm scope with user first.
6. Hermes glue (mandatory): embed `@symbol:path/to/file.ext:Symbol` anchors for code claims; `mnemosyne_triple_add(subject="notebook:<nb>:note:<id>", predicate="anchors_symbol", object="@symbol:...")`; reverse-lookup via `mnemosyne_triple_query` before creating.

Tool mapping: `add_source_url`/`add_source_file` → raw capture; `add_note` → Layer-2 page body; `search` → duplicate check; `ask_notebook` → grounded draft.

## Query

1. `index.md` → relevant pages (+ `search_files`/code_intel for 100+ pages).
2. Read top-3 pages max (never bulk-read).
3. Synthesize with citations (`[[page]]`, `@symbol:` for code).
4. File back substantial novel synthesis to `queries/` or `comparisons/` (skip trivial lookups).
5. Append `log.md` (`query | question — filed? y/n`).

## Lint (health-check)

Check and report grouped by severity (broken links > orphans > drift > contested > stale > style), then append `log.md` (`lint | N issues`): orphans (0 inbound links), broken `[[links]]`, index completeness (fs vs index), frontmatter validity + taxonomy, stale (`updated` >90d behind newest source), `contested:true` / `contradictions:` / `confidence:low` / single-source-no-confidence, raw `sha256` drift, pages >200 lines, tag sprawl, log rotation (>500 → `log-YYYY.md`).

## Hermes Integration

- Vault is indexed by code intelligence — new pages searchable after `pai_code_intel(check_freshness)`.
- Planning files (`task_plan/findings/progress.md`) stay in `<EXECUTION_DIR>/.planning/`; research conclusions graduate to wiki + Living ADRs (`.planning/research/ADR-XXX.md` via `pai_adr_ops`).
- Probes: `/opt/data/probes/<slug>/` scripts; results ingested as `EVIDENCE:` notes with `@symbol:` anchors.
- Turn 1: load this skill only when research task or `SCHEMA.md` exists; orient reads are SCHEMA + index + log-tail-20 only.

## Pitfalls

- Never edit `raw/`. Never skip orient/index/log updates. No pages for passing mentions. No isolated pages. Frontmatter required. Tags from taxonomy only. Split >200 lines. Rotate log. Contradictions explicit, never silent overwrite.
